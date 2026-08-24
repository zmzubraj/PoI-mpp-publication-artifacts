from __future__ import annotations

import argparse
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
from poi_mpp.experiments.e8_consensus import default_e8_publication_plan_path, load_and_run_e8_publication
from poi_mpp.orchestration.run_mpp import _verify_local_model_artifact, load_local_mpp_config
from poi_mpp.reporting.manifest import PublicationReportManifestModel, validate_existing_manifest
from verify_bundle import VERIFY_REPORT_SCHEMA, verify_bundle


PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
RESULTS_ROOT = REPO_ROOT / "results"
CANDIDATE_ROOT = RESULTS_ROOT / "tmp" / "candidates"
REPORT_ALL = REPO_ROOT / "scripts" / "report_all.py"
RUN_MPP = REPO_ROOT / "scripts" / "run_mpp.py"
LOCAL_MPP_CONFIG = REPO_ROOT / "configs" / "e2e" / "local.yaml"
PUBLICATION_REPORT_SPEC = REPO_ROOT / "configs" / "publication_report.json"
EXTERNAL_REVIEW_HANDOFF_MANIFEST = (
    REPO_ROOT
    / "docs"
    / "paper_artifacts"
    / "final"
    / "external_review"
    / "EXTERNAL_REVIEW_HANDOFF_MANIFEST.json"
)
TASK22_SCHEMA = "POI_MPP_FREEZE_BUNDLE_V1"
CLAIM_SCHEMA = "POI_MPP_CLAIM_SUPPORT_MATRIX_V1"
MANUAL_REVIEW_SCHEMA = "POI_MPP_MANUAL_REVIEW_V1"
MANUAL_REVIEW_ABSENT = "manual scientific review record is absent"
BUNDLE_STATE_CANDIDATE = "CANDIDATE_VERIFIED"
ALLOWED_CLAIM_DISPOSITIONS = {"SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"}
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
EXPERIMENT_TO_CLAIM = {experiment_id: claim_id for claim_id, (experiment_id, _) in EXPECTED_CLAIMS.items()}
EXPERIMENT_REQUIRED_ARTIFACTS = {
    experiment_id: required_artifacts for _, (experiment_id, required_artifacts) in EXPECTED_CLAIMS.items()
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
    review_handoff_manifest_relative_path: str


class ManualReviewSummary(_FrozenModel):
    status: str
    reviewer_identity: str | None = None
    review_date: str | None = None


class CandidateManifest(_FrozenModel):
    schema_version: str
    bundle_kind: str
    bundle_state: str
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


def _artifact_root_relative(bundle_relative_path: str) -> str:
    canonical = _canonical_bundle_relative_path(bundle_relative_path)
    parts = PurePosixPath(canonical).parts
    if not parts or parts[0] != "inputs":
        raise ValueError(f"artifact-root relative path must live under inputs/: {bundle_relative_path}")
    relative = PurePosixPath(*parts[1:])
    if not relative.parts:
        raise ValueError(f"artifact-root relative path must target a file under inputs/: {bundle_relative_path}")
    return relative.as_posix()


def _canonical_bundle_relative_path(value: str) -> str:
    canonical = str(PurePosixPath(value))
    if canonical != value or canonical.startswith("/") or any(part in {"", ".", ".."} for part in PurePosixPath(value).parts):
        raise ValueError(f"bundle relative path must already be canonical: {value}")
    return canonical


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
    raw = json.loads(PUBLICATION_REPORT_SPEC.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), dict):
        raise ValueError("configs/publication_report.json must remain a JSON object with a sources mapping")
    for experiment_id, source_payload in raw["sources"].items():
        if not isinstance(source_payload, dict):
            raise ValueError(f"publication_report source for {experiment_id} must be a mapping")
        staged_source: dict[str, str] = {}
        for key, value in source_payload.items():
            if key == "timeout_seconds":
                staged_source[key] = str(int(value))
                continue
            if key == "contracts_root":
                contracts_root = Path(value)
                if not contracts_root.is_absolute():
                    contracts_root = (REPO_ROOT / contracts_root).resolve()
                staged_source[key] = str(contracts_root)
                continue
            if (
                experiment_id == "E8"
                and key == "rows_path"
                and e8_rows_relative_path is not None
            ):
                staged_source[key] = _artifact_root_relative(e8_rows_relative_path)
                continue
            if (
                experiment_id == "E8"
                and key == "contract_path"
                and e8_contract_relative_path is not None
            ):
                staged_source[key] = _artifact_root_relative(e8_contract_relative_path)
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"publication_report source {experiment_id}.{key} must be a non-blank string")
            source_path = Path(value)
            if not source_path.is_absolute():
                source_path = (REPO_ROOT / source_path).resolve()
            if not source_path.is_file():
                raise ValueError(f"publication_report source {experiment_id}.{key} is missing: {source_path}")
            staged_relative = PurePosixPath(value)
            if experiment_id == "E7" and key == "run_config_path":
                staged_relative = PurePosixPath("e7_run_config.yaml")
            staged_path = input_root / staged_relative
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, staged_path)
            staged_source[key] = _artifact_root_relative(str(staged_path.relative_to(staging_root)))
        sources[experiment_id] = staged_source
    if e8_rows_relative_path is not None and e8_contract_relative_path is not None:
        if full_mode:
            sources.setdefault("E8", {})
            sources["E8"]["rows_path"] = _artifact_root_relative(e8_rows_relative_path)
            sources["E8"]["contract_path"] = _artifact_root_relative(e8_contract_relative_path)
        else:
            sources["E8"] = {
                "rows_path": _artifact_root_relative(e8_rows_relative_path),
                "contract_path": _artifact_root_relative(e8_contract_relative_path),
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
    portable_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    portable_spec["artifact_root"] = "inputs"
    portable_spec["output_root"] = "publication"
    _write_json(spec_path, portable_spec)
    return []


def _task21_blockers(staging_root: Path, *, full_mode: bool) -> tuple[tuple[str, ...], Path]:
    task21_config_path = staging_root / "inputs" / "task21_local_config.json"
    staged_config = _sanitized_task21_config()
    _write_json(task21_config_path, staged_config)
    blocker, reasons = _verify_local_model_artifact(load_local_mpp_config(task21_config_path))
    status_path = staging_root / "task21" / "task21_blockers.json"
    _write_json(
        status_path,
        {
            "schema_version": "POI_MPP_TASK21_BLOCKER_CHAIN_V1",
            "mode": "full" if full_mode else "candidate-only",
            "config_path": str(task21_config_path.relative_to(staging_root)),
            "blocker": blocker.value,
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
    semantic = cloned.get("semantic", {})
    schema_path = semantic.get("confirmatory_schema_path")
    if isinstance(schema_path, str) and not Path(schema_path).is_absolute():
        semantic["confirmatory_schema_path"] = str((LOCAL_MPP_CONFIG.parent / schema_path).resolve())
    return cloned


def _copy_if_exists(source: Path, destination: Path) -> Path | None:
    if not source.is_file():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _stage_e8_publication_inputs(staging_root: Path) -> tuple[str, str]:
    staged_rows = staging_root / "inputs" / "e8_publication_artifact.json"
    staged_contract = staging_root / "inputs" / "configs" / "confirmatory" / "e8.yaml"
    load_and_run_e8_publication(default_e8_publication_plan_path(), output_path=staged_rows)
    copied_contract = _copy_if_exists(REPO_ROOT / "configs" / "confirmatory" / "e8.yaml", staged_contract)
    if copied_contract is None:
        raise FileNotFoundError("configs/confirmatory/e8.yaml is missing")
    return (
        str(staged_rows.relative_to(staging_root)),
        str(staged_contract.relative_to(staging_root)),
    )


def _stage_external_review_handoff(staging_root: Path) -> str:
    selection = json.loads(EXTERNAL_REVIEW_HANDOFF_MANIFEST.read_text(encoding="utf-8"))
    if selection.get("schema_version") != "POI_MPP_EXTERNAL_REVIEW_HANDOFF_V1":
        raise ValueError("external review handoff selection has an unsupported schema")
    if selection.get("status") != "UNSIGNED_REVIEW_INPUT_ONLY":
        raise ValueError("external review handoff selection must remain unsigned review input only")
    selected_entries = selection.get("review_inputs")
    if not isinstance(selected_entries, list) or not selected_entries:
        raise ValueError("external review handoff selection must contain review inputs")

    staged_entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for selected in selected_entries:
        if not isinstance(selected, dict) or not isinstance(selected.get("path"), str):
            raise ValueError("external review handoff selection entries must contain a path")
        relative_path = selected["path"]
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or str(pure) != relative_path or any(part in {"", ".", ".."} for part in pure.parts):
            raise ValueError(f"unsafe external review handoff path: {relative_path}")
        if relative_path in seen:
            raise ValueError(f"duplicate external review handoff path: {relative_path}")
        seen.add(relative_path)
        source = staging_root.joinpath(*pure.parts) if pure.parts[0] == "publication" else REPO_ROOT.joinpath(*pure.parts)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"external review handoff input is missing or unsafe: {relative_path}")
        data = source.read_bytes()
        destination = staging_root / "review_handoff" / "inputs" / pure
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        staged_entries.append(
            {
                "path": relative_path,
                "role": str(selected.get("role", "REVIEW_INPUT")),
                "sha256": _sha256_bytes(data),
                "size_bytes": len(data),
            }
        )

    publication_manifest = staging_root / "publication" / "artifact_manifest.json"
    payload: dict[str, object] = {
        "schema_version": "POI_MPP_EXTERNAL_REVIEW_HANDOFF_V1",
        "status": "UNSIGNED_REVIEW_INPUT_ONLY",
        "canonical_publication_manifest_sha256": _sha256_bytes(publication_manifest.read_bytes()),
        "review_input_count": len(staged_entries),
        "review_inputs": staged_entries,
        "external_gates": {
            "e3_semantic_evaluator_authority": "WAITING_EXTERNAL",
            "independent_domain_expert_review": "WAITING_EXTERNAL",
            "publication_freeze_sentinel": "BLOCKED_UNTIL_EXTERNAL_GATES_CLOSE",
        },
        "authority_boundary": (
            "This manifest binds review inputs only; it does not create evaluator authority, "
            "independent review, a signature, or publication readiness."
        ),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["self_digest"] = _sha256_bytes(canonical)
    relative_manifest = "review_handoff/EXTERNAL_REVIEW_HANDOFF_MANIFEST.json"
    _write_json(staging_root / relative_manifest, payload)
    return relative_manifest


def _validated_publication_artifacts(
    staging_root: Path,
) -> tuple[PublicationReportManifestModel | None, tuple[dict[str, object], ...], tuple[dict[str, object], ...], list[str]]:
    publication_root = staging_root / "publication"
    manifest_path = publication_root / "artifact_manifest.json"
    claim_matrix_path = publication_root / "tables" / "claim_matrix.json"
    omissions_path = publication_root / "tables" / "omissions.json"
    if not manifest_path.is_file():
        return None, (), (), ["publication report manifest is absent"]
    try:
        validate_existing_manifest(publication_root)
        manifest = PublicationReportManifestModel.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    except Exception as error:
        return None, (), (), [f"publication report validation failed: {error}"]
    try:
        claim_matrix_payload = json.loads(claim_matrix_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        return manifest, (), (), [f"publication claim matrix is unavailable: {error}"]
    try:
        omissions_payload = json.loads(omissions_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        return manifest, (), (), [f"publication omission ledger is unavailable: {error}"]
    if not isinstance(claim_matrix_payload, list):
        return manifest, (), (), ["publication claim matrix must remain a JSON list"]
    if not isinstance(omissions_payload, list):
        return manifest, (), (), ["publication omission ledger must remain a JSON list"]
    claim_rows: tuple[dict[str, object], ...] = tuple(
        row for row in claim_matrix_payload if isinstance(row, dict) and isinstance(row.get("experiment_id"), str)
    )
    omission_rows: tuple[dict[str, object], ...] = tuple(
        row for row in omissions_payload if isinstance(row, dict) and isinstance(row.get("experiment_id"), str)
    )
    return manifest, claim_rows, omission_rows, []


def _experiment_states(
    publication_manifest: PublicationReportManifestModel | None,
    publication_claim_rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, ExperimentState], list[str]]:
    claim_by_experiment = {
        str(row["experiment_id"]): row
        for row in publication_claim_rows
        if str(row.get("experiment_id")) in EXPERIMENT_REQUIRED_ARTIFACTS
    }
    output_artifacts: dict[str, set[str]] = {experiment_id: set() for experiment_id in EXPERIMENT_REQUIRED_ARTIFACTS}
    if publication_manifest is not None:
        for output in publication_manifest.outputs:
            if output.experiment_id not in output_artifacts:
                continue
            if output.omission_reason is not None:
                continue
            if output.artifact_id in EXPERIMENT_REQUIRED_ARTIFACTS[output.experiment_id]:
                output_artifacts[output.experiment_id].add(output.artifact_id)
    blockers: list[str] = []
    states: dict[str, ExperimentState] = {}
    for experiment_id, required_artifacts in EXPERIMENT_REQUIRED_ARTIFACTS.items():
        publication_row = claim_by_experiment.get(experiment_id, {})
        present_artifacts = tuple(
            artifact_id for artifact_id in required_artifacts if artifact_id in output_artifacts.get(experiment_id, set())
        )
        disposition = str(publication_row.get("disposition", "MISSING"))
        status = "COMPLETE" if set(present_artifacts) == set(required_artifacts) else disposition
        if status not in {"COMPLETE", "MISSING", "WAITING_EXTERNAL", "INCOMPLETE"}:
            status = "INCOMPLETE" if present_artifacts else "MISSING"
        origin = publication_row.get("origin")
        states[experiment_id] = ExperimentState(
            status=status,
            required_artifacts=required_artifacts,
            present_artifacts=present_artifacts,
            origin=str(origin) if isinstance(origin, str) and origin else None,
        )
        if set(present_artifacts) != set(required_artifacts):
            blockers.append(f"missing experiment evidence: {experiment_id}")
    return states, blockers


def _claim_rows(experiments: dict[str, ExperimentState], publication_claim_rows: tuple[dict[str, object], ...]) -> list[ClaimRow]:
    claim_rows_by_experiment = {
        str(row["experiment_id"]): row
        for row in publication_claim_rows
        if str(row.get("experiment_id")) in EXPERIMENT_REQUIRED_ARTIFACTS
    }
    rows: list[ClaimRow] = []
    for claim_id, (experiment_id, required_artifacts) in EXPECTED_CLAIMS.items():
        experiment = experiments[experiment_id]
        publication_row = claim_rows_by_experiment.get(experiment_id, {})
        present = tuple(artifact_id for artifact_id in required_artifacts if artifact_id in experiment.present_artifacts)
        completeness = "COMPLETE" if set(required_artifacts).issubset(set(present)) else "INCOMPLETE"
        disposition = str(publication_row.get("disposition", "INCONCLUSIVE"))
        if disposition not in ALLOWED_CLAIM_DISPOSITIONS or completeness != "COMPLETE":
            disposition = "INCONCLUSIVE"
        rows.append(
            ClaimRow(
                claim_id=claim_id,
                completeness=completeness,
                disposition=disposition,
                required_artifacts=required_artifacts,
                present_artifacts=present,
                paper_language_status="MATCHES_EVIDENCE",
                maturity=str(publication_row.get("maturity", experiment.origin or "ABSENT")),
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
        bundle_state=BUNDLE_STATE_CANDIDATE,
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
        "bundle_state": BUNDLE_STATE_CANDIDATE,
    }


def _write_candidate_bundle(staging_root: Path, run_context: RunContext, *, full_mode: bool) -> tuple[Path, dict[str, object]]:
    e8_rows_relative_path, e8_contract_relative_path = _stage_e8_publication_inputs(staging_root)
    publication_blockers = _build_publication_report(
        staging_root,
        run_context,
        full_mode=full_mode,
        e8_rows_relative_path=e8_rows_relative_path,
        e8_contract_relative_path=e8_contract_relative_path,
    )
    publication_manifest, publication_claim_rows, _, publication_validation_blockers = _validated_publication_artifacts(staging_root)
    review_handoff_manifest_relative_path = _stage_external_review_handoff(staging_root)
    task21_reasons, task21_result_path = _task21_blockers(staging_root, full_mode=full_mode)
    experiments, experiment_blockers = _experiment_states(
        publication_manifest,
        publication_claim_rows,
    )
    blockers: list[str] = []
    blockers.extend(publication_blockers)
    blockers.extend(publication_validation_blockers)
    blockers.extend(task21_reasons)
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
        e7_run_config_relative_path="inputs/e7_run_config.yaml" if "E7" in experiments else None,
        e8_rows_relative_path=e8_rows_relative_path,
        e8_contract_relative_path=e8_contract_relative_path,
        review_handoff_manifest_relative_path=review_handoff_manifest_relative_path,
    )
    manifest = _candidate_manifest(run_context, blockers, experiments, authoritative_inputs)
    claim_rows = _claim_rows(experiments, publication_claim_rows)
    _write_json(
        staging_root / "claim_support_matrix.json",
        {"schema_version": CLAIM_SCHEMA, "claims": [row.model_dump(mode="json") for row in claim_rows]},
    )
    _write_json(staging_root / "manual_review.json", {"schema_version": MANUAL_REVIEW_SCHEMA, "status": "MISSING"})
    _write_json(staging_root / "manifest.json", manifest.model_dump(mode="json"))
    _write_json(staging_root / "verification_report.json", _placeholder_report(run_context.run_id))
    summary = verify_bundle(staging_root, enforce_stored_report=False)
    _write_json(staging_root / "verification_report.json", summary.model_dump(mode="json"))
    payload = {
        "status": summary.completeness,
        "run_id": manifest.run_id,
        "candidate_relative_path": str(Path("results") / "tmp" / "candidates" / manifest.run_id),
        "report_relative_path": str(Path("results") / "tmp" / "candidates" / manifest.run_id / "verification_report.json"),
        "blockers": list(summary.blockers),
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
