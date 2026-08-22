from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
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
from verify_bundle import verify_bundle


PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
RESULTS_ROOT = REPO_ROOT / "results"
CANDIDATE_ROOT = RESULTS_ROOT / "candidates"
FROZEN_ROOT = RESULTS_ROOT / "frozen"
REPORT_ALL = REPO_ROOT / "scripts" / "report_all.py"
RUN_MPP = REPO_ROOT / "scripts" / "run_mpp.py"
LOCAL_MPP_CONFIG = REPO_ROOT / "configs" / "e2e" / "local.yaml"
TASK22_SCHEMA = "POI_MPP_FREEZE_BUNDLE_V1"
CLAIM_SCHEMA = "POI_MPP_CLAIM_SUPPORT_MATRIX_V1"
MANUAL_REVIEW_SCHEMA = "POI_MPP_MANUAL_REVIEW_V1"
MANUAL_REVIEW_ABSENT = "manual scientific review record is absent"
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


class CandidateManifest(_FrozenModel):
    schema_version: str
    bundle_kind: str
    run_id: str
    repo_root: str
    report_relative_path: str
    claim_matrix_relative_path: str
    publication_report_relative_path: str
    manual_review_relative_path: str
    completeness: str
    claim_support_overall: str
    blockers: tuple[str, ...]
    required_experiments: tuple[str, ...]
    experiments: dict[str, ExperimentState]
    manual_review: dict[str, Any]
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


def _git_status_fingerprint() -> str:
    completed = _run(("git", "-C", str(REPO_ROOT), "status", "--porcelain"), timeout=30)
    payload = completed.stdout if completed.returncode == 0 else completed.stderr
    return _sha256_bytes(payload.encode("utf-8"))


def _run_id(mode: str) -> str:
    environment = collect_environment(repo_root=REPO_ROOT, lock_path=REPO_ROOT / "requirements.lock")
    material = {
        "schema": TASK22_SCHEMA,
        "mode": mode,
        "approved_schema_hash": approved_schema_hash(),
        "requirements_lock_hash": environment.package_lock_hash,
        "git_revision": environment.code_revision,
        "git_status_fingerprint": _git_status_fingerprint(),
        "script_closure": {
            "reproduce.py": _sha256_bytes(Path(__file__).read_bytes()),
            "verify_bundle.py": _sha256_bytes((REPO_ROOT / "scripts" / "verify_bundle.py").read_bytes()),
            "report_all.py": _sha256_bytes(REPORT_ALL.read_bytes()),
            "run_mpp.py": _sha256_bytes(RUN_MPP.read_bytes()),
        },
    }
    return f"task22-{_sha256_bytes(json.dumps(material, sort_keys=True).encode('utf-8'))[:16]}"


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


def _report_spec(staging_root: Path, *, full_mode: bool) -> dict[str, object]:
    input_root = staging_root / "inputs"
    input_root.mkdir(parents=True, exist_ok=True)
    sources: dict[str, dict[str, str]] = {}
    if full_mode:
        run_config = {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": "task22-e7-live-report",
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
            "run_config_path": str(run_config_path),
            "contracts_root": str(REPO_ROOT / "contracts"),
        }
    return {
        "artifact_root": str(input_root),
        "output_root": str(staging_root / "publication"),
        "sources": sources,
    }


def _build_publication_report(staging_root: Path, *, full_mode: bool) -> tuple[dict[str, str], list[str]]:
    spec_path = _write_json(staging_root / "inputs" / "report_spec.json", _report_spec(staging_root, full_mode=full_mode))
    completed = _run(
        (str(PYTHON), str(REPORT_ALL), "build", "--spec", str(spec_path)),
        timeout=900 if full_mode else 120,
    )
    blockers: list[str] = []
    if completed.returncode != 0:
        blockers.append(f"publication report build failed: {completed.stderr.strip() or completed.stdout.strip()}")
        publication_root = staging_root / "publication"
        publication_root.mkdir(parents=True, exist_ok=True)
        _write_json(publication_root / "artifact_manifest.json", {"schema_version": "TEST_ONLY_NON_EVIDENCE"})
        return {}, blockers

    artifact_map: dict[str, str] = {}
    claim_matrix_path = staging_root / "publication" / "tables" / "claim_matrix.csv"
    if claim_matrix_path.is_file():
        with claim_matrix_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                artifact_map[row.get("artifact_id", "")] = row.get("disposition", "INCONCLUSIVE")
    return artifact_map, blockers


def _task21_blockers(staging_root: Path, *, full_mode: bool) -> tuple[tuple[str, ...], Path | None]:
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


def _claim_rows(experiments: dict[str, ExperimentState]) -> list[ClaimRow]:
    rows: list[ClaimRow] = []
    for claim_id, (experiment_id, required_artifacts) in EXPECTED_CLAIMS.items():
        experiment = experiments[experiment_id]
        present = tuple(sorted(set(experiment.present_artifacts).intersection(required_artifacts)))
        completeness = "COMPLETE" if set(required_artifacts).issubset(set(present)) else "INCOMPLETE"
        disposition = "SUPPORTED" if experiment_id == "E7" and completeness == "COMPLETE" else "INCONCLUSIVE"
        maturity = experiment.origin or "ABSENT"
        rows.append(
            ClaimRow(
                claim_id=claim_id,
                completeness=completeness,
                disposition=disposition,
                required_artifacts=required_artifacts,
                present_artifacts=present,
                paper_language_status="MATCHES_EVIDENCE",
                maturity=maturity,
            )
        )
    return rows


def _candidate_manifest(
    run_id: str,
    blockers: list[str],
    experiments: dict[str, ExperimentState],
) -> CandidateManifest:
    return CandidateManifest(
        schema_version=TASK22_SCHEMA,
        bundle_kind="candidate",
        run_id=run_id,
        repo_root=str(REPO_ROOT),
        report_relative_path="verification_report.json",
        claim_matrix_relative_path="claim_support_matrix.json",
        publication_report_relative_path="publication/artifact_manifest.json",
        manual_review_relative_path="manual_review.json",
        completeness="INCOMPLETE",
        claim_support_overall="INCONCLUSIVE",
        blockers=tuple(dict.fromkeys(blockers)),
        required_experiments=tuple(f"E{index}" for index in range(1, 9)),
        experiments=experiments,
        manual_review={"status": "MISSING", "reviewer_identity": None},
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


def _write_candidate_bundle(staging_root: Path, *, full_mode: bool) -> tuple[Path, dict[str, object]]:
    environment = collect_environment(repo_root=REPO_ROOT, lock_path=REPO_ROOT / "requirements.lock")
    publication_dispositions, blockers = _build_publication_report(staging_root, full_mode=full_mode)
    task21_reasons, task21_result_path = _task21_blockers(staging_root, full_mode=full_mode)
    blockers.extend(task21_reasons)
    blockers.append(MANUAL_REVIEW_ABSENT)
    if environment.code_revision == UNVERSIONED_BLOCKED:
        blockers.append("code revision is UNVERSIONED_BLOCKED; dirty or unversioned evidence cannot freeze")
    for experiment_id in ("E1", "E2", "E3", "E4", "E5", "E6", "E8"):
        blockers.append(f"missing experiment evidence: {experiment_id}")

    present_e7 = tuple(
        artifact_id
        for artifact_id in ("T12", "F12")
        if (staging_root / "publication" / ("tables" if artifact_id.startswith("T") else "figures")).exists()
    )
    experiments = {
        "E1": ExperimentState(status="MISSING", required_artifacts=("T6", "F5"), present_artifacts=(), origin=None),
        "E2": ExperimentState(status="MISSING", required_artifacts=("T7", "F6"), present_artifacts=(), origin=None),
        "E3": ExperimentState(status="WAITING_EXTERNAL", required_artifacts=("T4", "T8", "F7"), present_artifacts=(), origin=EvidenceOrigin.REAL_MODEL_EXECUTION.value),
        "E4": ExperimentState(status="MISSING", required_artifacts=("T9", "F8"), present_artifacts=(), origin=None),
        "E5": ExperimentState(status="MISSING", required_artifacts=("T10",), present_artifacts=(), origin=None),
        "E6": ExperimentState(status="MISSING", required_artifacts=("T11", "F9", "F10"), present_artifacts=(), origin=None),
        "E7": ExperimentState(
            status="COMPLETE" if publication_dispositions else "LOCAL_ONLY",
            required_artifacts=("T12", "F12"),
            present_artifacts=tuple(
                artifact_id
                for artifact_id in ("T12", "F12")
                if (
                    artifact_id.startswith("T")
                    and (staging_root / "publication" / "tables" / "T12_evm_boundedness.csv").is_file()
                )
                or (
                    artifact_id.startswith("F")
                    and (staging_root / "publication" / "figures" / "F12_evm_gas_state_scaling.svg").is_file()
                )
            ),
            origin=EvidenceOrigin.FOUNDRY_MEASUREMENT.value,
        ),
        "E8": ExperimentState(
            status="INCONCLUSIVE",
            required_artifacts=("T13", "F11"),
            present_artifacts=(),
            origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION.value,
        ),
    }
    manifest = _candidate_manifest(_run_id("full" if full_mode else "candidate-only"), blockers, experiments)
    claim_rows = _claim_rows(experiments)
    _write_json(staging_root / "claim_support_matrix.json", {"schema_version": CLAIM_SCHEMA, "claims": [row.model_dump(mode="json") for row in claim_rows]})
    _write_json(staging_root / "manual_review.json", {"schema_version": MANUAL_REVIEW_SCHEMA, "status": "MISSING"})
    _write_json(staging_root / "manifest.json", manifest.model_dump(mode="json"))
    summary = verify_bundle(staging_root)
    _write_json(staging_root / "verification_report.json", summary.model_dump(mode="json"))
    payload = {
        "status": "INCOMPLETE",
        "run_id": manifest.run_id,
        "candidate_relative_path": str(Path("results") / "candidates" / manifest.run_id),
        "report_relative_path": str(Path("results") / "candidates" / manifest.run_id / "verification_report.json"),
        "blockers": list(summary.blockers),
    }
    if task21_result_path is not None:
        payload["task21_result_relative_path"] = str(task21_result_path.relative_to(staging_root))
    return staging_root, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage and verify a Task 22 publication-bundle candidate.")
    parser.add_argument("--mode", choices=("full", "candidate-only"), default="full")
    args = parser.parse_args(argv)

    run_id = _run_id(args.mode)
    CANDIDATE_ROOT.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=str(CANDIDATE_ROOT)))
    staging_root = staging_parent / run_id
    staging_root.mkdir(parents=True, exist_ok=True)
    try:
        _, payload = _write_candidate_bundle(staging_root, full_mode=args.mode == "full")
        final_root = CANDIDATE_ROOT / run_id
        _atomic_replace_directory(staging_root, final_root)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    finally:
        if staging_parent.exists():
            shutil.rmtree(staging_parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
