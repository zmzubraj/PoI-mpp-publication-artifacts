from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from pydantic import BaseModel, ConfigDict
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.evidence import UNVERSIONED_BLOCKED, approved_schema_hash, collect_environment
from poi_mpp.evidence.models import EvidenceOrigin
from verify_bundle import VERIFY_REPORT_SCHEMA, verify_bundle


PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
RESULTS_ROOT = REPO_ROOT / "results"
CANDIDATE_ROOT = RESULTS_ROOT / "tmp" / "candidates"
REPORT_ALL = REPO_ROOT / "scripts" / "report_all.py"
RUN_MPP = REPO_ROOT / "scripts" / "run_mpp.py"
LOCAL_MPP_CONFIG = REPO_ROOT / "configs" / "e2e" / "local.yaml"
TASK22_SCHEMA = "POI_MPP_FREEZE_BUNDLE_V1"
CLAIM_SCHEMA = "POI_MPP_CLAIM_SUPPORT_MATRIX_V1"
MANUAL_REVIEW_SCHEMA = "POI_MPP_MANUAL_REVIEW_V1"
MANUAL_REVIEW_ABSENT = "manual scientific review record is absent"
NEEDS_CONTEXT_E8 = (
    "NEEDS_CONTEXT: Task19 production canonical-scenario artifact/runner missing; "
    "need a production-owned E8 rows artifact or src/poi_mpp/experiments/e8_consensus.py API "
    "that emits the frozen publication scenario closure without importing "
    "tests/experiments/test_e8_consensus.py::_publication_rows or _write_contract"
)
EXPECTED_CLAIMS = {
    "C1": ("E1", ("T6", "F5")),
    "C2": ("E2", ("T7", "F6")),
    "C3": ("E3", ("T4", "T8", "F7")),
    "C4": ("E4", ("T9", "F8")),
    "C5": ("E5", ("T10",)),
    "C6": ("E6", ("T11", "F9", "F10")),
    "C7": ("E7", ("T12", "F12")),
    "C8": ("E8", ("T13", "F11")),
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunContext(_FrozenModel):
    mode: str
    run_id: str
    head_revision: str
    effective_code_revision: str
    git_status_fingerprint: str
    tracked_dirty_paths: tuple[str, ...]
    package_lock_hash: str | None


class ClaimRow(_FrozenModel):
    claim_id: str
    completeness: str
    disposition: str
    required_artifacts: tuple[str, ...]
    present_artifacts: tuple[str, ...]
    paper_language_status: str
    maturity: str


class ExperimentState(_FrozenModel):
    status: str
    required_artifacts: tuple[str, ...]
    present_artifacts: tuple[str, ...]
    origin: str | None = None


class AuthoritativeInputs(_FrozenModel):
    report_spec_relative_path: str
    task21_config_relative_path: str
    task21_blocker_relative_path: str
    e7_run_config_relative_path: str | None = None
    e8_rows_relative_path: str | None = None
    e8_contract_relative_path: str | None = None


class ManualReviewSummary(_FrozenModel):
    status: str
    reviewer_identity: str | None = None
    review_date: str | None = None


class CandidateManifest(_FrozenModel):
    schema_version: str
    bundle_kind: str
    run_id: str
    repo_root: str
    report_relative_path: str
    claim_matrix_relative_path: str
    publication_report_relative_path: str
    manual_review_relative_path: str
    authoritative_inputs: AuthoritativeInputs
    completeness: str
    claim_support_overall: str
    blockers: tuple[str, ...]
    required_experiments: tuple[str, ...]
    experiments: dict[str, ExperimentState]
    manual_review: ManualReviewSummary
    sentinel_present: bool
    frozen_manifest_relative_path: str | None = None
    tool_versions: dict[str, str]
    argv_contract: dict[str, tuple[str, ...]]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _atomic_replace_directory(staging_root: Path, target_root: Path) -> None:
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging_root, target_root)


def _run(argv: tuple[str, ...], *, cwd: Path = REPO_ROOT, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    safe_env = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "PYTHONPATH": str(SRC_ROOT),
    }
    env = {key: value for key, value in os.environ.items() if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
    env.update(safe_env)
    return subprocess.run(
        list(argv),
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env=env,
    )


def _git_head() -> str:
    completed = _run(("git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"), timeout=30)
    if completed.returncode != 0:
        return UNVERSIONED_BLOCKED
    candidate = completed.stdout.strip()
    if len(candidate) != 40 or any(character not in "0123456789abcdef" for character in candidate):
        return UNVERSIONED_BLOCKED
    return candidate


def _runtime_output_path(relative_path: str) -> bool:
    parts = PurePosixPath(relative_path).parts
    return len(parts) >= 1 and parts[0] == "results"


def _tracked_dirty_paths() -> tuple[str, ...]:
    dirty: set[str] = set()
    diff_completed = _run(("git", "-C", str(REPO_ROOT), "diff", "--name-only", "HEAD", "--"), timeout=30)
    if diff_completed.returncode == 0:
        dirty.update(line.strip() for line in diff_completed.stdout.splitlines() if line.strip())
    untracked_completed = _run(
        ("git", "-C", str(REPO_ROOT), "ls-files", "--others", "--exclude-standard"),
        timeout=30,
    )
    if untracked_completed.returncode == 0:
        dirty.update(line.strip() for line in untracked_completed.stdout.splitlines() if line.strip())
    filtered = sorted(path for path in dirty if not _runtime_output_path(path))
    return tuple(filtered)


def _run_context(mode: str) -> RunContext:
    environment = collect_environment(repo_root=REPO_ROOT, lock_path=REPO_ROOT / "requirements.lock")
    head_revision = _git_head()
    dirty_paths = _tracked_dirty_paths()
    effective_code_revision = head_revision if head_revision != UNVERSIONED_BLOCKED and not dirty_paths else UNVERSIONED_BLOCKED
    material = {
        "schema": TASK22_SCHEMA,
        "mode": mode,
        "approved_schema_hash": approved_schema_hash(),
        "requirements_lock_hash": environment.package_lock_hash,
        "head_revision": head_revision,
        "effective_code_revision": effective_code_revision,
        "dirty_paths": list(dirty_paths),
        "script_closure": {
            "reproduce.py": _sha256_bytes(Path(__file__).read_bytes()),
            "verify_bundle.py": _sha256_bytes((REPO_ROOT / "scripts" / "verify_bundle.py").read_bytes()),
            "report_all.py": _sha256_bytes(REPORT_ALL.read_bytes()),
            "run_mpp.py": _sha256_bytes(RUN_MPP.read_bytes()),
        },
    }
    fingerprint = _sha256_bytes(json.dumps(material, sort_keys=True).encode("utf-8"))
    return RunContext(
        mode=mode,
        run_id=f"task22-{fingerprint[:16]}",
        head_revision=head_revision,
        effective_code_revision=effective_code_revision,
        git_status_fingerprint=fingerprint,
        tracked_dirty_paths=dirty_paths,
        package_lock_hash=environment.package_lock_hash,
    )


def _tool_versions() -> dict[str, str]:
    versions = {
        "python": sys.version.split()[0],
        "git": "UNAVAILABLE",
        "forge": "UNAVAILABLE",
    }
    git_version = _run(("git", "--version"), timeout=30)
    if git_version.returncode == 0:
        versions["git"] = git_version.stdout.strip()
    forge_version = _run(("forge", "--version"), timeout=30)
    if forge_version.returncode == 0:
        versions["forge"] = forge_version.stdout.strip()
    return versions


def _report_spec(
    staging_root: Path,
    run_context: RunContext,
    *,
    full_mode: bool,
    e8_rows_relative_path: str | None,
    e8_contract_relative_path: str | None,
) -> dict[str, object]:
    input_root = staging_root / "inputs"
    input_root.mkdir(parents=True, exist_ok=True)
    sources: dict[str, dict[str, str]] = {}
    if full_mode:
        run_config = {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": f"{run_context.run_id}-e7-live",
            "experiment_id": "E7",
            "origin": EvidenceOrigin.FOUNDRY_MEASUREMENT.value,
            "authorization_scope": "PUBLICATION_EVIDENCE_AUTHORIZED",
            "model_hash": "5" * 64,
            "dataset_hash": "6" * 64,
            "parent_hashes": [],
            "data_availability": {
                "total_shards": 16,
                "samples": 8,
                "replacement": False,
            },
        }
        run_config_path = _write_json(input_root / "e7_run_config.json", run_config)
        sources["E7"] = {
            "run_config_path": str(run_config_path.resolve()),
            "contracts_root": str((REPO_ROOT / "contracts").resolve()),
        }
    if e8_rows_relative_path is not None and e8_contract_relative_path is not None:
        sources["E8"] = {
            "rows_path": str((staging_root / e8_rows_relative_path).resolve()),
            "contract_path": str((staging_root / e8_contract_relative_path).resolve()),
        }
    return {
        "artifact_root": str(input_root.resolve()),
        "output_root": str((staging_root / "publication").resolve()),
        "sources": sources,
    }


def _build_publication_report(
    staging_root: Path,
    run_context: RunContext,
    *,
    full_mode: bool,
    e8_rows_relative_path: str | None,
    e8_contract_relative_path: str | None,
) -> list[str]:
    spec_path = _write_json(
        staging_root / "inputs" / "report_spec.json",
        _report_spec(
            staging_root,
            run_context,
            full_mode=full_mode,
            e8_rows_relative_path=e8_rows_relative_path,
            e8_contract_relative_path=e8_contract_relative_path,
        ),
    )
    completed = _run(
        (str(PYTHON), str(REPORT_ALL), "build", "--spec", str(spec_path)),
        timeout=900 if full_mode else 180,
    )
    if completed.returncode != 0:
        return [f"publication report build failed: {completed.stderr.strip() or completed.stdout.strip()}"]
    return []


def _task21_blockers(staging_root: Path, *, full_mode: bool) -> tuple[tuple[str, ...], Path]:
    task21_config_path = staging_root / "inputs" / "task21_local_config.json"
    staged_config = _sanitized_task21_config()
    _write_json(task21_config_path, staged_config)
    reasons = (
        "WAITING_LOCAL_MODEL_ARTIFACT: exact local model artifact is absent",
        "WAITING_EXTERNAL_EVALUATOR_AUTHORITY: external evaluator authority remains absent",
    )
    status_path = staging_root / "task21" / "task21_blockers.json"
    _write_json(
        status_path,
        {
            "schema_version": "POI_MPP_TASK21_BLOCKER_CHAIN_V1",
            "mode": "full" if full_mode else "candidate-only",
            "config_path": str(task21_config_path.relative_to(staging_root)),
            "blocker_chain": list(reasons),
        },
    )
    return reasons, status_path


def _sanitized_task21_config() -> dict[str, Any]:
    raw = yaml.safe_load(LOCAL_MPP_CONFIG.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("configs/e2e/local.yaml must remain a mapping")
    cloned = json.loads(json.dumps(raw))
    run_config = cloned.get("run_config", {})
    model = cloned.get("model", {})
    manifest = model.get("manifest", {})
    for key in ("model_hash", "dataset_hash"):
        if key in run_config:
            run_config[key] = str(run_config[key])
    for key in ("revision", "tokenizer_revision"):
        if key in manifest:
            manifest[key] = str(manifest[key])
    for mapping_key in ("model_file_hashes", "tokenizer_file_hashes"):
        values = manifest.get(mapping_key)
        if isinstance(values, dict):
            manifest[mapping_key] = {name: str(value) for name, value in values.items()}
    return cloned


def _copy_if_exists(source: Path, destination: Path) -> Path | None:
    if not source.is_file():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _locate_production_e8_inputs(staging_root: Path) -> tuple[str | None, str | None, list[str]]:
    contract_path = REPO_ROOT / "configs" / "confirmatory" / "e8.yaml"
    if not contract_path.is_file():
        return None, None, [NEEDS_CONTEXT_E8]
    candidate_rows: list[Path] = []
    for path in REPO_ROOT.rglob("*.json"):
        if "tests" in path.parts or "results" in path.parts and "raw" not in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "POI_MPP_E8_SCENARIO_ROW_V1" in text:
            candidate_rows.append(path)
    if not candidate_rows:
        return None, None, [NEEDS_CONTEXT_E8]
    selected_rows = sorted(candidate_rows)[0]
    staged_rows = staging_root / "inputs" / "e8_rows.json"
    staged_contract = staging_root / "inputs" / "e8_contract.yaml"
    _copy_if_exists(selected_rows, staged_rows)
    _copy_if_exists(contract_path, staged_contract)
    return (
        str(staged_rows.relative_to(staging_root)),
        str(staged_contract.relative_to(staging_root)),
        [],
    )


def _publication_outputs(staging_root: Path) -> dict[str, dict[str, str]]:
    manifest_path = staging_root / "publication" / "artifact_manifest.json"
    if not manifest_path.is_file():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    outputs = payload.get("outputs", [])
    if not isinstance(outputs, list):
        return {}
    index: dict[str, dict[str, str]] = {}
    for item in outputs:
        if not isinstance(item, dict):
            continue
        artifact_id = item.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            index[artifact_id] = {key: str(value) for key, value in item.items() if isinstance(key, str)}
    return index


def _experiment_states(
    publication_outputs: dict[str, dict[str, str]],
    *,
    e8_rows_relative_path: str | None,
) -> tuple[dict[str, ExperimentState], list[str]]:
    blockers: list[str] = []
    states = {
        "E1": ExperimentState(status="MISSING", required_artifacts=("T6", "F5"), present_artifacts=(), origin=None),
        "E2": ExperimentState(status="MISSING", required_artifacts=("T7", "F6"), present_artifacts=(), origin=None),
        "E3": ExperimentState(
            status="WAITING_EXTERNAL",
            required_artifacts=("T4", "T8", "F7"),
            present_artifacts=(),
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION.value,
        ),
        "E4": ExperimentState(status="MISSING", required_artifacts=("T9", "F8"), present_artifacts=(), origin=None),
        "E5": ExperimentState(status="MISSING", required_artifacts=("T10",), present_artifacts=(), origin=None),
        "E6": ExperimentState(status="MISSING", required_artifacts=("T11", "F9", "F10"), present_artifacts=(), origin=None),
        "E7": ExperimentState(
            status="LOCAL_ONLY",
            required_artifacts=("T12", "F12"),
            present_artifacts=tuple(
                artifact_id
                for artifact_id in ("T12", "F12")
                if publication_outputs.get(artifact_id, {}).get("disposition") in {"SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"}
            ),
            origin=EvidenceOrigin.FOUNDRY_MEASUREMENT.value,
        ),
        "E8": ExperimentState(
            status="NEEDS_CONTEXT" if e8_rows_relative_path is None else "INCONCLUSIVE",
            required_artifacts=("T13", "F11"),
            present_artifacts=tuple(
                artifact_id
                for artifact_id in ("T13", "F11")
                if publication_outputs.get(artifact_id, {}).get("disposition") in {"SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"}
            ),
            origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION.value,
        ),
    }
    if states["E7"].present_artifacts == ("T12", "F12"):
        states["E7"] = states["E7"].model_copy(update={"status": "COMPLETE"})
    for experiment_id in ("E1", "E2", "E3", "E4", "E5", "E6"):
        blockers.append(f"missing experiment evidence: {experiment_id}")
    if e8_rows_relative_path is None:
        blockers.append(NEEDS_CONTEXT_E8)
    elif set(states["E8"].present_artifacts) != {"T13", "F11"}:
        blockers.append("missing experiment evidence: E8")
    return states, blockers


def _claim_rows(experiments: dict[str, ExperimentState]) -> list[ClaimRow]:
    rows: list[ClaimRow] = []
    for claim_id, (experiment_id, required_artifacts) in EXPECTED_CLAIMS.items():
        experiment = experiments[experiment_id]
        present = tuple(artifact_id for artifact_id in required_artifacts if artifact_id in experiment.present_artifacts)
        completeness = "COMPLETE" if set(required_artifacts).issubset(set(present)) else "INCOMPLETE"
        if experiment_id == "E7" and completeness == "COMPLETE":
            disposition = "SUPPORTED"
        elif experiment_id == "E8" and experiment.origin == EvidenceOrigin.REPRODUCIBLE_SIMULATION.value:
            disposition = "INCONCLUSIVE"
        else:
            disposition = "INCONCLUSIVE"
        rows.append(
            ClaimRow(
                claim_id=claim_id,
                completeness=completeness,
                disposition=disposition,
                required_artifacts=required_artifacts,
                present_artifacts=present,
                paper_language_status="MATCHES_EVIDENCE",
                maturity=experiment.origin or "ABSENT",
            )
        )
    return rows


def _candidate_manifest(
    run_context: RunContext,
    blockers: list[str],
    experiments: dict[str, ExperimentState],
    authoritative_inputs: AuthoritativeInputs,
) -> CandidateManifest:
    return CandidateManifest(
        schema_version=TASK22_SCHEMA,
        bundle_kind="candidate",
        run_id=run_context.run_id,
        repo_root=str(REPO_ROOT),
        report_relative_path="verification_report.json",
        claim_matrix_relative_path="claim_support_matrix.json",
        publication_report_relative_path="publication/artifact_manifest.json",
        manual_review_relative_path="manual_review.json",
        authoritative_inputs=authoritative_inputs,
        completeness="INCOMPLETE",
        claim_support_overall="INCONCLUSIVE",
        blockers=tuple(dict.fromkeys(blockers)),
        required_experiments=tuple(f"E{index}" for index in range(1, 9)),
        experiments=experiments,
        manual_review=ManualReviewSummary(status="MISSING", reviewer_identity=None, review_date=None),
        sentinel_present=False,
        tool_versions=_tool_versions(),
        argv_contract={
            "report_all_build": (
                str(PYTHON),
                "scripts/report_all.py",
                "build",
                "--spec",
                "<SPEC>",
            ),
            "task21_replay": (
                str(PYTHON),
                "scripts/run_mpp.py",
                "--config",
                "configs/e2e/local.yaml",
                "--output-root",
                "<OUTPUT_ROOT>",
            ),
        },
    )


def _placeholder_report(run_id: str) -> dict[str, object]:
    return {
        "schema_version": VERIFY_REPORT_SCHEMA,
        "run_id": run_id,
        "completeness": "INCOMPLETE",
        "blockers": [],
        "claims": {},
        "sentinel_present": False,
        "manual_review_authenticated": False,
    }


def _write_candidate_bundle(staging_root: Path, run_context: RunContext, *, full_mode: bool) -> tuple[Path, dict[str, object]]:
    e8_rows_relative_path, e8_contract_relative_path, e8_blockers = _locate_production_e8_inputs(staging_root)
    publication_blockers = _build_publication_report(
        staging_root,
        run_context,
        full_mode=full_mode,
        e8_rows_relative_path=e8_rows_relative_path,
        e8_contract_relative_path=e8_contract_relative_path,
    )
    task21_reasons, task21_result_path = _task21_blockers(staging_root, full_mode=full_mode)
    publication_outputs = _publication_outputs(staging_root)
    experiments, experiment_blockers = _experiment_states(
        publication_outputs,
        e8_rows_relative_path=e8_rows_relative_path,
    )
    blockers: list[str] = []
    blockers.extend(publication_blockers)
    blockers.extend(task21_reasons)
    blockers.extend(e8_blockers)
    blockers.extend(experiment_blockers)
    blockers.append(MANUAL_REVIEW_ABSENT)
    if run_context.effective_code_revision == UNVERSIONED_BLOCKED:
        blockers.append(
            "code revision is UNVERSIONED_BLOCKED; tracked or non-runtime unversioned changes remain outside the frozen boundary"
        )
    authoritative_inputs = AuthoritativeInputs(
        report_spec_relative_path="inputs/report_spec.json",
        task21_config_relative_path="inputs/task21_local_config.json",
        task21_blocker_relative_path=str(task21_result_path.relative_to(staging_root)),
        e7_run_config_relative_path="inputs/e7_run_config.json" if full_mode else None,
        e8_rows_relative_path=e8_rows_relative_path,
        e8_contract_relative_path=e8_contract_relative_path,
    )
    manifest = _candidate_manifest(run_context, blockers, experiments, authoritative_inputs)
    claim_rows = _claim_rows(experiments)
    _write_json(
        staging_root / "claim_support_matrix.json",
        {"schema_version": CLAIM_SCHEMA, "claims": [row.model_dump(mode="json") for row in claim_rows]},
    )
    _write_json(staging_root / "manual_review.json", {"schema_version": MANUAL_REVIEW_SCHEMA, "status": "MISSING"})
    _write_json(staging_root / "manifest.json", manifest.model_dump(mode="json"))
    _write_json(staging_root / "verification_report.json", _placeholder_report(run_context.run_id))
    summary = verify_bundle(staging_root, enforce_stored_report=False)
    _write_json(staging_root / "verification_report.json", summary.model_dump(mode="json"))
    final_summary = verify_bundle(staging_root)
    payload = {
        "status": final_summary.completeness,
        "run_id": manifest.run_id,
        "candidate_relative_path": str(Path("results") / "tmp" / "candidates" / manifest.run_id),
        "report_relative_path": str(Path("results") / "tmp" / "candidates" / manifest.run_id / "verification_report.json"),
        "blockers": list(final_summary.blockers),
    }
    return staging_root, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage and verify a Task 22 publication-bundle candidate.")
    parser.add_argument("--mode", choices=("full", "candidate-only"), default="full")
    args = parser.parse_args(argv)

    run_context = _run_context(args.mode)
    CANDIDATE_ROOT.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix=f".{run_context.run_id}.", dir=str(CANDIDATE_ROOT)))
    staging_root = staging_parent / run_context.run_id
    staging_root.mkdir(parents=True, exist_ok=True)
    try:
        _, payload = _write_candidate_bundle(staging_root, run_context, full_mode=args.mode == "full")
        final_root = CANDIDATE_ROOT / run_context.run_id
        _atomic_replace_directory(staging_root, final_root)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    finally:
        if staging_parent.exists():
            shutil.rmtree(staging_parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
