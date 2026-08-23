from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.evidence.config import load_run_config
from poi_mpp.experiments.e7_evm import E7Bundle, default_measurement_contract
from poi_mpp.experiments.e8_consensus import (
    default_e8_publication_plan_path,
    load_e8_confirmatory_contract,
    load_e8_publication_artifact,
)
from poi_mpp.reporting.e7 import collect_and_summarize_e7_publication
from poi_mpp.reporting.load import PublicationEligibilityError
from poi_mpp.reporting.manifest import PublicationReportManifestModel, validate_existing_manifest


class BundleVerificationError(ValueError):
    def __init__(self, reasons: str | list[str] | tuple[str, ...]):
        if isinstance(reasons, str):
            reasons = [reasons]
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__("; ".join(self.reasons))


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


TASK22_SCHEMA = "POI_MPP_FREEZE_BUNDLE_V1"
CLAIM_SCHEMA = "POI_MPP_CLAIM_SUPPORT_MATRIX_V1"
MANUAL_REVIEW_SCHEMA = "POI_MPP_MANUAL_REVIEW_V1"
VERIFY_REPORT_SCHEMA = "POI_MPP_FREEZE_VERIFICATION_REPORT_V1"
PUBLICATION_SCHEMA = "POI_MPP_PUBLICATION_REPORT_MANIFEST_V4"
SENTINEL_SCHEMA = "POI_MPP_FREEZE_SENTINEL_V1"
SENTINEL = "MPP_ARTIFACT_COMPLETE"
TEST_ONLY_SCHEMA = "TEST_ONLY_NON_EVIDENCE"
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
CURRENT_DATE = date(2026, 8, 23)
REVIEW_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BUNDLE_STATE_CANDIDATE = "CANDIDATE_VERIFIED"
BUNDLE_STATE_FROZEN = "FROZEN_VERIFIED"
VERIFICATION_MODE_NORMAL = "normal"
VERIFICATION_MODE_PRE_SENTINEL_FROZEN = "pre_sentinel_frozen"
QUALIFYING_REVIEW_BASIS = "INDEPENDENT_DOMAIN_EXPERT_REVIEW"
NONQUALIFYING_REVIEW_BASIS = "ACCOUNTABLE_NON_INDEPENDENT_REVIEW"
ALLOWED_REVIEW_BASES = {QUALIFYING_REVIEW_BASIS, NONQUALIFYING_REVIEW_BASIS}
EXPECTED_EXPERIMENTS = tuple(f"E{index}" for index in range(1, 9))
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
EXPECTED_CLAIM_ORDER = tuple(EXPECTED_CLAIMS)
REQUIRED_MANUAL_REVIEW_HASH_KEYS = (
    "claim_support_matrix.json",
    "publication/artifact_manifest.json",
)


class ManualReviewChecks(_FrozenModel):
    denominator: bool = False
    interval: bool = False
    negative_results: bool = False
    simulation_labeling: bool = False
    editability: bool = False
    accessibility: bool = False
    claim_language: bool = False


class ManualReviewRecord(_FrozenModel):
    schema_version: str
    status: str
    reviewer_identity: str | None = None
    review_basis: str | None = None
    review_date: str | None = None
    expertise_scope: str | None = None
    independence_basis: str | None = None
    reviewed_run_id: str | None = None
    reviewed_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    checks: ManualReviewChecks | None = None

    @field_validator("schema_version")
    @classmethod
    def _validate_schema(cls, value: str) -> str:
        if value != MANUAL_REVIEW_SCHEMA:
            raise ValueError(f"schema_version must equal {MANUAL_REVIEW_SCHEMA}")
        return value


class ManualReviewSummary(_FrozenModel):
    status: str
    reviewer_identity: str | None = None
    review_date: str | None = None


class ClaimSupportRow(_FrozenModel):
    claim_id: str
    completeness: str
    disposition: str
    required_artifacts: tuple[str, ...]
    present_artifacts: tuple[str, ...]
    paper_language_status: str
    maturity: str

    @field_validator("claim_id", "completeness", "disposition", "paper_language_status", "maturity")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("field must not be blank")
        return value


class ClaimSupportMatrix(_FrozenModel):
    schema_version: str
    claims: tuple[ClaimSupportRow, ...]

    @field_validator("schema_version")
    @classmethod
    def _validate_schema(cls, value: str) -> str:
        if value != CLAIM_SCHEMA:
            raise ValueError(f"schema_version must equal {CLAIM_SCHEMA}")
        return value

    @model_validator(mode="after")
    def _unique_claims(self) -> "ClaimSupportMatrix":
        claim_ids = [row.claim_id for row in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("duplicate claim ids are forbidden")
        return self


class ExperimentEntry(_FrozenModel):
    status: str
    required_artifacts: tuple[str, ...] = ()
    present_artifacts: tuple[str, ...] = ()
    origin: str | None = None


class AuthoritativeInputs(_FrozenModel):
    report_spec_relative_path: str
    task21_config_relative_path: str
    task21_blocker_relative_path: str
    e7_run_config_relative_path: str | None = None
    e8_rows_relative_path: str | None = None
    e8_contract_relative_path: str | None = None

    @field_validator(
        "report_spec_relative_path",
        "task21_config_relative_path",
        "task21_blocker_relative_path",
        "e7_run_config_relative_path",
        "e8_rows_relative_path",
        "e8_contract_relative_path",
        mode="before",
    )
    @classmethod
    def _validate_relative_path(cls, value: object) -> object:
        if value is None:
            return None
        return _canonical_relative_path(value)


class BundleManifest(_FrozenModel):
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
    experiments: dict[str, ExperimentEntry]
    manual_review: ManualReviewSummary
    sentinel_present: bool
    frozen_manifest_relative_path: str | None = None
    tool_versions: dict[str, str] = Field(default_factory=dict)
    argv_contract: dict[str, tuple[str, ...]]

    @field_validator("schema_version")
    @classmethod
    def _validate_schema(cls, value: str) -> str:
        if value != TASK22_SCHEMA:
            raise ValueError(f"schema_version must equal {TASK22_SCHEMA}")
        return value

    @field_validator("bundle_kind")
    @classmethod
    def _validate_bundle_kind(cls, value: str) -> str:
        if value not in {"candidate", "frozen"}:
            raise ValueError("bundle_kind must equal candidate or frozen")
        return value

    @field_validator("bundle_state")
    @classmethod
    def _validate_bundle_state(cls, value: str) -> str:
        if value not in {BUNDLE_STATE_CANDIDATE, BUNDLE_STATE_FROZEN}:
            raise ValueError(f"bundle_state must equal {BUNDLE_STATE_CANDIDATE} or {BUNDLE_STATE_FROZEN}")
        return value

    @field_validator(
        "report_relative_path",
        "claim_matrix_relative_path",
        "publication_report_relative_path",
        "manual_review_relative_path",
        "frozen_manifest_relative_path",
        mode="before",
    )
    @classmethod
    def _validate_manifest_relative_paths(cls, value: object) -> object:
        if value is None:
            return None
        return _canonical_relative_path(value)

    @model_validator(mode="after")
    def _validate_experiments(self) -> "BundleManifest":
        if self.required_experiments != EXPECTED_EXPERIMENTS:
            raise ValueError("required_experiments must exactly equal E1..E8 in order")
        if tuple(self.experiments) != EXPECTED_EXPERIMENTS:
            raise ValueError("experiment records must exactly equal E1..E8 in order")
        expected_state = BUNDLE_STATE_CANDIDATE if self.bundle_kind == "candidate" else BUNDLE_STATE_FROZEN
        if self.bundle_state != expected_state:
            raise ValueError("bundle_kind and bundle_state must agree")
        return self


class VerificationSummary(_FrozenModel):
    schema_version: str = VERIFY_REPORT_SCHEMA
    run_id: str
    completeness: str
    blockers: tuple[str, ...]
    claims: dict[str, str]
    sentinel_present: bool
    manual_review_authenticated: bool = False
    bundle_state: str

    @field_validator("schema_version")
    @classmethod
    def _validate_schema(cls, value: str) -> str:
        if value != VERIFY_REPORT_SCHEMA:
            raise ValueError(f"schema_version must equal {VERIFY_REPORT_SCHEMA}")
        return value

    @field_validator("bundle_state")
    @classmethod
    def _validate_bundle_state(cls, value: str) -> str:
        if value not in {BUNDLE_STATE_CANDIDATE, BUNDLE_STATE_FROZEN}:
            raise ValueError(f"bundle_state must equal {BUNDLE_STATE_CANDIDATE} or {BUNDLE_STATE_FROZEN}")
        return value


class SentinelRecord(_FrozenModel):
    schema_version: str
    run_id: str
    bundle_state: str
    manifest_sha256: str
    verification_report_sha256: str

    @field_validator("schema_version")
    @classmethod
    def _validate_schema(cls, value: str) -> str:
        if value != SENTINEL_SCHEMA:
            raise ValueError(f"schema_version must equal {SENTINEL_SCHEMA}")
        return value

    @field_validator("bundle_state")
    @classmethod
    def _validate_bundle_state(cls, value: str) -> str:
        if value != BUNDLE_STATE_FROZEN:
            raise ValueError(f"bundle_state must equal {BUNDLE_STATE_FROZEN}")
        return value


class LoadedBundle(_FrozenModel):
    root: str
    manifest: BundleManifest
    claim_matrix: ClaimSupportMatrix
    manual_review_record: ManualReviewRecord
    stored_report: VerificationSummary
    publication_manifest_json: dict[str, Any]
    publication_manifest_model: PublicationReportManifestModel | None = None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("relative path must not be blank")
    if value.startswith("/") or "\\" in value:
        raise ValueError("relative path must be a canonical POSIX relative path")
    normalized = str(PurePosixPath(value))
    if normalized != value:
        raise ValueError("relative path must already be normalized")
    parts = PurePosixPath(value).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("relative path must not contain '.', '..', or empty parts")
    return value


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_write_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
        return _sha256_bytes(data)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def _assert_no_symlink_components(path: Path, *, stop_at: Path | None = None, require_directory: bool = False) -> None:
    current = path
    while True:
        try:
            metadata = os.lstat(current)
        except OSError as error:
            raise BundleVerificationError(f"unable to stat path component: {current}") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise BundleVerificationError(f"symlinked path component is forbidden: {current}")
        if require_directory and current == path and not stat.S_ISDIR(metadata.st_mode):
            raise BundleVerificationError(f"bundle root must be a directory: {current}")
        if stop_at is not None and current == stop_at:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent


def _safe_root(bundle_root: Path) -> Path:
    _assert_no_symlink_components(bundle_root, require_directory=True)
    return bundle_root.resolve(strict=True)


def _safe_read_bytes(path: Path, *, root: Path) -> bytes:
    _assert_no_symlink_components(path.parent, stop_at=root, require_directory=True)
    try:
        file_descriptor = os.open(str(path), os.O_RDONLY | NOFOLLOW)
    except OSError as error:
        raise BundleVerificationError(f"unable to open file without following symlinks: {path}") from error
    try:
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise BundleVerificationError(f"path is not a regular file: {path}")
        if metadata.st_nlink != 1:
            raise BundleVerificationError(f"hardlinked output/input file is forbidden: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(file_descriptor)


def _safe_read_json(path: Path, *, root: Path) -> dict[str, Any]:
    try:
        return json.loads(_safe_read_bytes(path, root=root).decode("utf-8"))
    except json.JSONDecodeError as error:
        raise BundleVerificationError(f"invalid JSON: {path}") from error


def _resolve_relative(root: Path, relative_path: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        path.relative_to(root)
    except ValueError as error:
        raise BundleVerificationError(f"path escapes bundle root: {relative_path}") from error
    return path


def _enumerate_files(root: Path) -> set[str]:
    files: set[str] = set()
    _assert_no_symlink_components(root, require_directory=True)
    for current_root, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current_root)
        for directory_name in list(directory_names):
            directory_path = current_path / directory_name
            metadata = os.lstat(directory_path)
            if stat.S_ISLNK(metadata.st_mode):
                raise BundleVerificationError(f"symlinked output directory is forbidden: {directory_path}")
            if not stat.S_ISDIR(metadata.st_mode):
                raise BundleVerificationError(f"non-directory bundle component is forbidden: {directory_path}")
        for file_name in file_names:
            file_path = current_path / file_name
            _safe_read_bytes(file_path, root=root)
            files.add(str(file_path.relative_to(root).as_posix()))
    return files


def _contains_test_only(payload: object) -> bool:
    if payload == TEST_ONLY_SCHEMA:
        return True
    if isinstance(payload, dict):
        return any(_contains_test_only(key) or _contains_test_only(value) for key, value in payload.items())
    if isinstance(payload, (list, tuple)):
        return any(_contains_test_only(item) for item in payload)
    return False


def _load_bundle(bundle_root: Path, *, allow_test_only: bool) -> LoadedBundle:
    resolved_root = _safe_root(bundle_root)
    manifest_json = _safe_read_json(resolved_root / "manifest.json", root=resolved_root)
    claim_matrix_json = _safe_read_json(resolved_root / "claim_support_matrix.json", root=resolved_root)
    manual_review_json = _safe_read_json(resolved_root / "manual_review.json", root=resolved_root)
    report_json = _safe_read_json(resolved_root / "verification_report.json", root=resolved_root)
    publication_manifest_json = _safe_read_json(resolved_root / "publication" / "artifact_manifest.json", root=resolved_root)
    if not allow_test_only:
        for payload in (manifest_json, claim_matrix_json, manual_review_json, report_json, publication_manifest_json):
            if _contains_test_only(payload):
                raise BundleVerificationError("TEST_ONLY_NON_EVIDENCE records are forbidden in production verification")
    manifest = BundleManifest.model_validate(manifest_json)
    claim_matrix = ClaimSupportMatrix.model_validate(
        _safe_read_json(_resolve_relative(resolved_root, manifest.claim_matrix_relative_path), root=resolved_root)
    )
    manual_review_record = ManualReviewRecord.model_validate(
        _safe_read_json(_resolve_relative(resolved_root, manifest.manual_review_relative_path), root=resolved_root)
    )
    stored_report = VerificationSummary.model_validate(
        _safe_read_json(_resolve_relative(resolved_root, manifest.report_relative_path), root=resolved_root)
    )
    publication_manifest_model: PublicationReportManifestModel | None = None
    if allow_test_only and publication_manifest_json.get("schema_version") == TEST_ONLY_SCHEMA:
        publication_manifest_model = None
    else:
        if publication_manifest_json.get("schema_version") != PUBLICATION_SCHEMA:
            raise BundleVerificationError(f"publication report manifest schema_version must equal {PUBLICATION_SCHEMA}")
        try:
            validate_existing_manifest(_resolve_relative(resolved_root, "publication"))
            publication_manifest_model = PublicationReportManifestModel.model_validate(publication_manifest_json)
        except (PublicationEligibilityError, ValidationError) as error:
            reasons = error.reasons if isinstance(error, PublicationEligibilityError) else (str(error),)
            raise BundleVerificationError(list(reasons)) from error
    return LoadedBundle(
        root=str(resolved_root),
        manifest=manifest,
        claim_matrix=claim_matrix,
        manual_review_record=manual_review_record,
        stored_report=stored_report,
        publication_manifest_json=publication_manifest_json,
        publication_manifest_model=publication_manifest_model,
    )


def _publication_expected_files(bundle: LoadedBundle) -> set[str]:
    publication_root = PurePosixPath(bundle.manifest.publication_report_relative_path).parent
    publication_root_text = str(publication_root)
    if publication_root_text == ".":
        raise BundleVerificationError("publication report manifest must live under a dedicated publication directory")
    if bundle.publication_manifest_model is None:
        return {str(publication_root / "artifact_manifest.json")}
    return {str(publication_root / "artifact_manifest.json")} | {
        str(publication_root / PurePosixPath(item.relative_path)) for item in bundle.publication_manifest_model.outputs
    }


def _report_spec_expected_files(bundle: LoadedBundle) -> set[str]:
    report_spec_path = _resolve_relative(Path(bundle.root), bundle.manifest.authoritative_inputs.report_spec_relative_path)
    payload = _safe_read_json(report_spec_path, root=Path(bundle.root))
    artifact_root = payload.get("artifact_root")
    sources = payload.get("sources")
    if not isinstance(artifact_root, str) or not isinstance(sources, dict):
        return set()
    try:
        artifact_root_path = Path(artifact_root).resolve(strict=True)
    except FileNotFoundError as error:
        raise BundleVerificationError(f"report_spec artifact_root is missing: {artifact_root}") from error
    bundle_root = Path(bundle.root)
    expected: set[str] = set()
    for source_payload in sources.values():
        if not isinstance(source_payload, dict):
            raise BundleVerificationError("report_spec sources must be objects")
        for key, value in source_payload.items():
            if key in {"contracts_root", "timeout_seconds"} or not isinstance(value, str):
                continue
            candidate = artifact_root_path.joinpath(*PurePosixPath(value).parts).resolve(strict=True)
            try:
                relative = candidate.relative_to(bundle_root)
            except ValueError:
                continue
            if candidate.is_file():
                expected.add(relative.as_posix())
    return expected


def _validate_bundle_closure(bundle: LoadedBundle, *, verification_mode: str) -> tuple[str, ...]:
    expected = {
        "manifest.json",
        bundle.manifest.report_relative_path,
        bundle.manifest.claim_matrix_relative_path,
        bundle.manifest.publication_report_relative_path,
        bundle.manifest.manual_review_relative_path,
        bundle.manifest.authoritative_inputs.report_spec_relative_path,
        bundle.manifest.authoritative_inputs.task21_config_relative_path,
        bundle.manifest.authoritative_inputs.task21_blocker_relative_path,
    }
    for optional_path in (
        bundle.manifest.authoritative_inputs.e7_run_config_relative_path,
        bundle.manifest.authoritative_inputs.e8_rows_relative_path,
        bundle.manifest.authoritative_inputs.e8_contract_relative_path,
        bundle.manifest.frozen_manifest_relative_path,
    ):
        if optional_path is not None:
            expected.add(optional_path)
    expected |= _publication_expected_files(bundle)
    expected |= _report_spec_expected_files(bundle)
    if bundle.manifest.bundle_state == BUNDLE_STATE_FROZEN and verification_mode == VERIFICATION_MODE_NORMAL:
        expected.add(SENTINEL)
    actual = _enumerate_files(Path(bundle.root))
    if actual != expected:
        missing = sorted(expected - actual)
        extras = sorted(actual - expected)
        reasons: list[str] = []
        if missing:
            reasons.append(f"bundle closure missing files: {', '.join(missing)}")
        if extras:
            reasons.append(f"bundle closure has unexpected files: {', '.join(extras)}")
        return tuple(reasons)
    return ()


def _validate_experiments(bundle: LoadedBundle) -> tuple[str, ...]:
    reasons: list[str] = []
    for claim_id, (experiment_id, required_artifacts) in EXPECTED_CLAIMS.items():
        experiment = bundle.manifest.experiments[experiment_id]
        if experiment.required_artifacts != required_artifacts:
            reasons.append(f"{experiment_id} required_artifacts do not match the frozen claim map")
        unknown_present = sorted(set(experiment.present_artifacts) - set(required_artifacts))
        if unknown_present:
            reasons.append(f"{experiment_id} declares unknown present_artifacts: {', '.join(unknown_present)}")
        claim_row = next(row for row in bundle.claim_matrix.claims if row.claim_id == claim_id)
        expected_present = tuple(
            artifact_id for artifact_id in required_artifacts if artifact_id in experiment.present_artifacts
        )
        if claim_row.required_artifacts != required_artifacts:
            reasons.append(f"{claim_id} required_artifacts do not match the frozen claim map")
        if claim_row.present_artifacts != expected_present:
            reasons.append(f"{claim_id} present_artifacts contradict {experiment_id}")
    return tuple(dict.fromkeys(reasons))


def _sentinel_effective_presence(bundle: LoadedBundle, *, verification_mode: str) -> bool:
    actual_present = (_resolve_relative(Path(bundle.root), SENTINEL)).exists()
    if verification_mode == VERIFICATION_MODE_PRE_SENTINEL_FROZEN and bundle.manifest.bundle_state == BUNDLE_STATE_FROZEN:
        return True
    return actual_present


def _validate_sentinel_state(bundle: LoadedBundle, *, verification_mode: str) -> tuple[str, ...]:
    reasons: list[str] = []
    actual_present = (_resolve_relative(Path(bundle.root), SENTINEL)).exists()
    if bundle.manifest.bundle_state == BUNDLE_STATE_CANDIDATE:
        if actual_present:
            reasons.append("candidate bundles must not contain the completion sentinel")
        if bundle.manifest.sentinel_present:
            reasons.append("candidate bundles must record sentinel_present as false")
        if bundle.stored_report.sentinel_present:
            reasons.append("candidate verification reports must record sentinel_present as false")
        return tuple(reasons)
    if bundle.manifest.sentinel_present is not True:
        reasons.append("frozen bundles must record sentinel_present as true in manifest.json")
    if bundle.stored_report.sentinel_present is not True:
        reasons.append("frozen bundles must record sentinel_present as true in verification_report.json")
    if verification_mode == VERIFICATION_MODE_PRE_SENTINEL_FROZEN:
        if actual_present:
            reasons.append("pre-sentinel frozen verification requires the sentinel to be absent")
        return tuple(reasons)
    if not actual_present:
        reasons.append("frozen bundles require the completion sentinel")
    return tuple(reasons)


def _validate_sentinel_payload(bundle: LoadedBundle, *, verification_mode: str) -> tuple[str, ...]:
    if bundle.manifest.bundle_state != BUNDLE_STATE_FROZEN or verification_mode != VERIFICATION_MODE_NORMAL:
        return ()
    sentinel_path = _resolve_relative(Path(bundle.root), SENTINEL)
    if not sentinel_path.exists():
        return ()
    try:
        payload = SentinelRecord.model_validate(_safe_read_json(sentinel_path, root=Path(bundle.root)))
    except (BundleVerificationError, ValidationError) as error:
        return (str(error),)
    reasons: list[str] = []
    if payload.run_id != bundle.manifest.run_id:
        reasons.append("sentinel run_id does not match manifest.json")
    if payload.manifest_sha256 != _digest_for_relative_path(Path(bundle.root), "manifest.json"):
        reasons.append("sentinel manifest_sha256 does not match manifest.json")
    if payload.verification_report_sha256 != _digest_for_relative_path(Path(bundle.root), bundle.manifest.report_relative_path):
        reasons.append("sentinel verification_report_sha256 does not match verification_report.json")
    return tuple(dict.fromkeys(reasons))


def _parse_review_date(value: str) -> date:
    if not REVIEW_DATE_PATTERN.fullmatch(value):
        raise ValueError("manual review review_date must use strict ISO YYYY-MM-DD format")
    parsed = date.fromisoformat(value)
    if parsed > CURRENT_DATE:
        raise ValueError(f"manual review review_date must not be in the future relative to {CURRENT_DATE.isoformat()}")
    return parsed


def _structural_reasons(bundle: LoadedBundle, *, verification_mode: str) -> tuple[str, ...]:
    reasons: list[str] = []
    reasons.extend(_validate_bundle_closure(bundle, verification_mode=verification_mode))
    reasons.extend(bundle.manifest.blockers)
    claim_order = tuple(row.claim_id for row in bundle.claim_matrix.claims)
    if claim_order != EXPECTED_CLAIM_ORDER:
        reasons.append("claim rows must exactly equal C1..C8 in order")
    reasons.extend(_validate_experiments(bundle))
    for row in bundle.claim_matrix.claims:
        if row.completeness != "COMPLETE":
            reasons.append(f"{row.claim_id} is {row.completeness}")
        missing_artifacts = sorted(set(row.required_artifacts) - set(row.present_artifacts))
        if missing_artifacts:
            reasons.append(f"{row.claim_id} missing artifacts: {', '.join(missing_artifacts)}")
        if row.paper_language_status != "MATCHES_EVIDENCE":
            reasons.append(f"{row.claim_id} paper language does not match evidence")
    if bundle.manifest.manual_review.status != bundle.manual_review_record.status:
        reasons.append("manifest manual_review summary contradicts manual_review.json")
    if bundle.manifest.manual_review.reviewer_identity != bundle.manual_review_record.reviewer_identity:
        reasons.append("manifest manual_review reviewer_identity contradicts manual_review.json")
    if bundle.manifest.manual_review.review_date != bundle.manual_review_record.review_date:
        reasons.append("manifest manual_review review_date contradicts manual_review.json")
    if bundle.stored_report.bundle_state != bundle.manifest.bundle_state:
        reasons.append("verification report bundle_state contradicts manifest.json")
    for experiment_id, experiment in sorted(bundle.manifest.experiments.items()):
        if experiment.origin == "SYNTHETIC_NON_EVIDENCE":
            reasons.append(f"{experiment_id} synthetic substitution is forbidden")
    reasons.extend(_validate_sentinel_state(bundle, verification_mode=verification_mode))
    reasons.extend(_validate_sentinel_payload(bundle, verification_mode=verification_mode))
    return tuple(dict.fromkeys(reasons))


def _claims_map(bundle: LoadedBundle) -> dict[str, str]:
    return {row.claim_id: row.disposition for row in bundle.claim_matrix.claims}


def verify_bundle_structure(
    bundle_root: Path,
    *,
    enforce_stored_report: bool = False,
    verification_mode: str = VERIFICATION_MODE_NORMAL,
) -> VerificationSummary:
    bundle = _load_bundle(bundle_root, allow_test_only=True)
    reasons = list(_structural_reasons(bundle, verification_mode=verification_mode))
    sentinel_present = _sentinel_effective_presence(bundle, verification_mode=verification_mode)
    completeness = "COMPLETE" if not reasons and bundle.manifest.completeness == "COMPLETE" else "INCOMPLETE"
    if completeness != "COMPLETE" and (_resolve_relative(Path(bundle.root), SENTINEL)).exists():
        reasons.append("sentinel present before verification completed")
        completeness = "INCOMPLETE"
    summary = VerificationSummary(
        run_id=bundle.manifest.run_id,
        completeness=completeness,
        blockers=tuple(dict.fromkeys(reasons)),
        claims=_claims_map(bundle),
        sentinel_present=sentinel_present,
        manual_review_authenticated=bundle.manual_review_record.status == "COMPLETE",
        bundle_state=bundle.manifest.bundle_state,
    )
    if enforce_stored_report and bundle.stored_report.model_dump(mode="json") != summary.model_dump(mode="json"):
        summary = summary.model_copy(
            update={
                "completeness": "INCOMPLETE",
                "blockers": tuple(
                    dict.fromkeys((*summary.blockers, "verification report does not match the recomputed structural summary"))
                ),
            }
        )
    return summary


def _assert_external_file(path: Path, *, bundle_root: Path, label: str) -> Path:
    candidate = Path(path)
    try:
        candidate.relative_to(bundle_root)
    except ValueError:
        pass
    else:
        raise BundleVerificationError(f"{label} must live outside the bundle root")
    _assert_no_symlink_components(candidate.parent, require_directory=True)
    data = _safe_read_bytes(candidate, root=candidate.parent)
    if not data:
        raise BundleVerificationError(f"{label} must not be empty: {candidate}")
    return candidate.resolve(strict=True)


def _digest_for_relative_path(bundle_root: Path, relative_path: str) -> str:
    return _sha256_bytes(_safe_read_bytes(_resolve_relative(bundle_root, relative_path), root=bundle_root))


def _validate_manual_review(
    bundle: LoadedBundle,
    *,
    allowed_signers_path: Path | None,
    signature_path: Path | None,
) -> tuple[tuple[str, ...], bool]:
    record = bundle.manual_review_record
    if record.status != "COMPLETE":
        return (("manual scientific review record is absent",), False)
    reasons: list[str] = []
    if not record.reviewer_identity:
        reasons.append("manual review requires reviewer_identity")
    if not record.review_basis:
        reasons.append("manual review requires review_basis")
    elif record.review_basis not in ALLOWED_REVIEW_BASES:
        reasons.append(
            "manual review review_basis must be one of "
            + ", ".join(sorted(ALLOWED_REVIEW_BASES))
        )
    if not record.review_date:
        reasons.append("manual review requires review_date")
    else:
        try:
            _parse_review_date(record.review_date)
        except ValueError as error:
            reasons.append(str(error))
    if not record.expertise_scope or not record.expertise_scope.strip():
        reasons.append("manual review requires expertise_scope")
    if record.review_basis == QUALIFYING_REVIEW_BASIS and (
        not record.independence_basis or not record.independence_basis.strip()
    ):
        reasons.append("manual review requires independence_basis for INDEPENDENT_DOMAIN_EXPERT_REVIEW")
    if not record.reviewed_run_id:
        reasons.append("manual review requires reviewed_run_id")
    elif record.reviewed_run_id != bundle.manifest.run_id:
        reasons.append("manual review reviewed_run_id does not match manifest.json run_id")
    if record.checks is None:
        reasons.append("manual review requires explicit checks")
    else:
        for key, passed in record.checks.model_dump(mode="json").items():
            if not passed:
                reasons.append(f"manual review check failed: {key}")
    bundle_root = Path(bundle.root)
    observed_hashes = {
        "manifest.json": _digest_for_relative_path(bundle_root, "manifest.json"),
        "claim_support_matrix.json": _digest_for_relative_path(bundle_root, bundle.manifest.claim_matrix_relative_path),
        "publication/artifact_manifest.json": _digest_for_relative_path(
            bundle_root, bundle.manifest.publication_report_relative_path
        ),
        "verification_report.json": _digest_for_relative_path(bundle_root, bundle.manifest.report_relative_path),
    }
    for key in REQUIRED_MANUAL_REVIEW_HASH_KEYS:
        expected = record.reviewed_artifact_hashes.get(key)
        if expected is None:
            reasons.append(f"manual review requires reviewed_artifact_hashes[{key}]")
            continue
        if expected != observed_hashes[key]:
            reasons.append(f"manual review artifact hash mismatch for {key}")
    if allowed_signers_path is None or signature_path is None:
        reasons.append("manual scientific review signature is absent")
        return (tuple(dict.fromkeys(reasons)), False)
    if record.reviewer_identity is None:
        return (tuple(dict.fromkeys(reasons)), False)
    try:
        verified_allowed = _assert_external_file(
            allowed_signers_path, bundle_root=bundle_root, label="manual review allowed signers file"
        )
        verified_signature = _assert_external_file(
            signature_path, bundle_root=bundle_root, label="manual review detached signature"
        )
        manual_review_path = _resolve_relative(bundle_root, bundle.manifest.manual_review_relative_path)
        signed_bytes = _safe_read_bytes(manual_review_path, root=bundle_root)
        completed = subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "verify",
                "-f",
                str(verified_allowed),
                "-I",
                record.reviewer_identity,
                "-n",
                "file",
                "-s",
                str(verified_signature),
            ],
            input=signed_bytes,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            reasons.append(
                "manual scientific review signature verification failed: "
                + ((completed.stderr or completed.stdout).decode("utf-8", errors="replace").strip() or "unknown failure")
            )
            return (tuple(dict.fromkeys(reasons)), False)
    except (BundleVerificationError, OSError) as error:
        reasons.append(str(error))
        return (tuple(dict.fromkeys(reasons)), False)
    if record.review_basis != QUALIFYING_REVIEW_BASIS:
        reasons.append("manual review basis is explicitly non-independent and cannot satisfy the production freeze gate")
        return (tuple(dict.fromkeys(reasons)), False)
    return (tuple(dict.fromkeys(reasons)), not reasons)


def _revalidate_e7(bundle: LoadedBundle) -> tuple[str, ...]:
    if bundle.publication_manifest_model is None:
        return ("production publication manifest is required for E7 authority replay",)
    raw_entry = next(
        (item for item in bundle.publication_manifest_model.outputs if item.artifact_id == "RAW_E7_LIVE_BUNDLE"),
        None,
    )
    if raw_entry is None:
        return ("E7 publication bundle is missing RAW_E7_LIVE_BUNDLE",)
    run_config_relative_path = bundle.manifest.authoritative_inputs.e7_run_config_relative_path
    if run_config_relative_path is None:
        return ("E7 live authority replay requires authoritative_inputs.e7_run_config_relative_path",)
    bundle_root = Path(bundle.root)
    run_config = load_run_config(_resolve_relative(bundle_root, run_config_relative_path))
    candidate_raw_path = _resolve_relative(
        bundle_root,
        str(PurePosixPath(bundle.manifest.publication_report_relative_path).parent / PurePosixPath(raw_entry.relative_path)),
    )
    candidate_bundle = E7Bundle.model_validate(_safe_read_json(candidate_raw_path, root=bundle_root))
    reasons: list[str] = []
    with tempfile.TemporaryDirectory(prefix="task22-e7-revalidate-") as temp_dir:
        fresh_output = Path(temp_dir) / "E7_live_bundle.json"
        result = collect_and_summarize_e7_publication(
            contracts_root=REPO_ROOT / "contracts",
            run_config=run_config,
            bundle_output_path=fresh_output,
            contract=default_measurement_contract(),
            timeout=120,
        )
        if tuple(row.model_dump(mode="json") for row in candidate_bundle.rows) != tuple(
            row.model_dump(mode="json") for row in result.bundle.rows
        ):
            reasons.append("E7 stored raw bundle does not match a fresh live-authority replay")
        if candidate_bundle.run_config_snapshot.model_dump(mode="json") != result.bundle.run_config_snapshot.model_dump(
            mode="json"
        ):
            reasons.append("E7 stored run_config snapshot does not match a fresh live-authority replay")
        if candidate_bundle.raw_report_hash != result.bundle.raw_report_hash:
            reasons.append("E7 stored raw report hash does not match a fresh live-authority replay")
        if raw_entry.run_id != result.bundle.run_config_snapshot.run_id:
            reasons.append("E7 publication raw output run_id does not match the fresh replay")
        if raw_entry.config_hash != result.bundle.run_config_hash:
            reasons.append("E7 publication raw output config_hash does not match the fresh replay")
        if raw_entry.source_closure_hash != result.parity_verification.source_closure_hash:
            reasons.append("E7 publication raw output source_closure_hash does not match the fresh replay")
        expected_source_hashes = (
            result.bundle.raw_report_hash,
            result.bundle.run_config_hash,
            result.parity_verification.source_closure_hash,
            result.parity_verification.protocol_vectors_hash,
            result.parity_verification.protocol_witness_hash,
        )
        if raw_entry.source_hashes != expected_source_hashes:
            reasons.append("E7 publication raw output source_hashes do not match the fresh replay")
    return tuple(dict.fromkeys(reasons))


def _revalidate_e8(bundle: LoadedBundle) -> tuple[str, ...]:
    rows_relative_path = bundle.manifest.authoritative_inputs.e8_rows_relative_path
    contract_relative_path = bundle.manifest.authoritative_inputs.e8_contract_relative_path
    e8_outputs_present = any(
        item.artifact_id in {"T13", "F11"} for item in (bundle.publication_manifest_model.outputs if bundle.publication_manifest_model else ())
    )
    if rows_relative_path is None or contract_relative_path is None:
        if e8_outputs_present or bundle.manifest.experiments["E8"].present_artifacts:
            return ("E8 publication replay requires authoritative_inputs.e8_rows_relative_path and e8_contract_relative_path",)
        return ()
    bundle_root = Path(bundle.root)
    try:
        artifact = load_e8_publication_artifact(
            _resolve_relative(bundle_root, rows_relative_path),
            plan_path=default_e8_publication_plan_path(),
        )
        staged_contract = load_e8_confirmatory_contract(_resolve_relative(bundle_root, contract_relative_path))
        current_contract = load_e8_confirmatory_contract(REPO_ROOT / "configs" / "confirmatory" / "e8.yaml")
    except (ValueError, ValidationError) as error:
        raise BundleVerificationError(str(error)) from error
    reasons: list[str] = []
    if staged_contract.model_dump(mode="json") != artifact.contract_snapshot.model_dump(mode="json"):
        reasons.append("E8 staged contract does not match the publication artifact contract snapshot")
    if staged_contract.model_dump(mode="json") != current_contract.model_dump(mode="json"):
        reasons.append("E8 staged contract does not match configs/confirmatory/e8.yaml")
    if bundle.claim_matrix.claims[-1].disposition != artifact.claim_disposition:
        reasons.append("C8 disposition does not match the E8 authoritative replay summary")
    rows_input_sha = _digest_for_relative_path(bundle_root, rows_relative_path)
    contract_input_sha = _digest_for_relative_path(bundle_root, contract_relative_path)
    e8_outputs = [
        item
        for item in (bundle.publication_manifest_model.outputs if bundle.publication_manifest_model else ())
        if item.artifact_id in {"T13", "F11"}
    ]
    observed_artifact_ids = {item.artifact_id for item in e8_outputs}
    if observed_artifact_ids != {"T13", "F11"}:
        reasons.append("validated publication manifest must expose both T13 and F11 outputs for E8")
    for output in e8_outputs:
        if output.experiment_id != "E8":
            reasons.append(f"{output.artifact_id} output is not bound to experiment E8")
        if output.origin != artifact.origin.value:
            reasons.append(f"{output.artifact_id} output origin does not match the authoritative E8 artifact")
        if output.disposition != artifact.claim_disposition:
            reasons.append(f"{output.artifact_id} output disposition does not match the authoritative E8 artifact")
        if output.run_id != artifact.run_id:
            reasons.append(f"{output.artifact_id} output run_id does not match the authoritative E8 artifact")
        if output.config_hash != artifact.run_config_hash:
            reasons.append(f"{output.artifact_id} output config_hash does not match the authoritative E8 artifact")
        if output.source_hashes != (rows_input_sha, contract_input_sha):
            reasons.append(f"{output.artifact_id} output source_hashes do not match the authoritative E8 inputs")
    e8_inputs = [
        item for item in (bundle.publication_manifest_model.inputs if bundle.publication_manifest_model else ()) if item.experiment_id == "E8"
    ]
    if len(e8_inputs) != 2:
        reasons.append("validated publication manifest must expose exactly two E8 inputs")
    input_by_role = {item.input_role: item for item in e8_inputs}
    rows_input = input_by_role.get("rows")
    contract_input = input_by_role.get("confirmatory_contract")
    if rows_input is None:
        reasons.append("validated publication manifest is missing the E8 rows input record")
    else:
        if rows_input.sha256 != rows_input_sha:
            reasons.append("E8 rows input sha256 does not match the bundled publication artifact")
        if rows_input.origin != artifact.origin.value:
            reasons.append("E8 rows input origin does not match the authoritative E8 artifact")
        if rows_input.disposition != artifact.claim_disposition:
            reasons.append("E8 rows input disposition does not match the authoritative E8 artifact")
        if rows_input.run_id != artifact.run_id:
            reasons.append("E8 rows input run_id does not match the authoritative E8 artifact")
        if rows_input.config_hash != artifact.run_config_hash:
            reasons.append("E8 rows input config_hash does not match the authoritative E8 artifact")
    if contract_input is None:
        reasons.append("validated publication manifest is missing the E8 confirmatory_contract input record")
    else:
        if contract_input.sha256 != contract_input_sha:
            reasons.append("E8 contract input sha256 does not match the bundled contract file")
        if contract_input.origin != artifact.origin.value:
            reasons.append("E8 contract input origin does not match the authoritative E8 artifact")
        if contract_input.disposition != artifact.claim_disposition:
            reasons.append("E8 contract input disposition does not match the authoritative E8 artifact")
        if contract_input.run_id != artifact.run_id:
            reasons.append("E8 contract input run_id does not match the authoritative E8 artifact")
        if contract_input.config_hash != artifact.run_config_hash:
            reasons.append("E8 contract input config_hash does not match the authoritative E8 artifact")
    return tuple(dict.fromkeys(reasons))


def verify_bundle(
    bundle_root: Path,
    *,
    manual_review_allowed_signers: Path | None = None,
    manual_review_signature: Path | None = None,
    enforce_stored_report: bool = True,
    verification_mode: str = VERIFICATION_MODE_NORMAL,
) -> VerificationSummary:
    bundle = _load_bundle(bundle_root, allow_test_only=False)
    reasons: list[str] = list(_structural_reasons(bundle, verification_mode=verification_mode))
    manual_review_reasons, manual_review_authenticated = _validate_manual_review(
        bundle,
        allowed_signers_path=manual_review_allowed_signers,
        signature_path=manual_review_signature,
    )
    reasons.extend(manual_review_reasons)
    reasons.extend(_revalidate_e7(bundle))
    reasons.extend(_revalidate_e8(bundle))
    sentinel_present = _sentinel_effective_presence(bundle, verification_mode=verification_mode)
    completeness = "COMPLETE" if not reasons and bundle.manifest.completeness == "COMPLETE" else "INCOMPLETE"
    if completeness != "COMPLETE" and (_resolve_relative(Path(bundle.root), SENTINEL)).exists():
        reasons.append("sentinel present before verification completed")
        completeness = "INCOMPLETE"
    summary = VerificationSummary(
        run_id=bundle.manifest.run_id,
        completeness=completeness,
        blockers=tuple(dict.fromkeys(reasons)),
        claims=_claims_map(bundle),
        sentinel_present=sentinel_present,
        manual_review_authenticated=manual_review_authenticated,
        bundle_state=bundle.manifest.bundle_state,
    )
    if enforce_stored_report and bundle.stored_report.model_dump(mode="json") != summary.model_dump(mode="json"):
        summary = summary.model_copy(
            update={
                "completeness": "INCOMPLETE",
                "blockers": tuple(
                    dict.fromkeys((*summary.blockers, "verification report does not match the recomputed authoritative summary"))
                ),
            }
        )
    return summary


def _copy_bundle(source_root: Path, target_root: Path) -> None:
    shutil.copytree(source_root, target_root)


def _sentinel_payload(bundle_root: Path, summary: VerificationSummary) -> bytes:
    payload = {
        "schema_version": SENTINEL_SCHEMA,
        "run_id": summary.run_id,
        "bundle_state": summary.bundle_state,
        "manifest_sha256": _digest_for_relative_path(bundle_root, "manifest.json"),
        "verification_report_sha256": _digest_for_relative_path(bundle_root, "verification_report.json"),
    }
    return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _atomic_write_json(path: Path, payload: object) -> None:
    _atomic_write_bytes(path, (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8"))


def _rewrite_frozen_bundle_state(
    bundle_root: Path,
    source_summary: VerificationSummary,
    *,
    manual_review_allowed_signers: Path | None,
    manual_review_signature: Path | None,
) -> VerificationSummary:
    root = _safe_root(bundle_root)
    manifest_path = root / "manifest.json"
    report_path = root / "verification_report.json"
    manifest_payload = _safe_read_json(manifest_path, root=root)
    report_payload = _safe_read_json(report_path, root=root)
    manifest_payload["bundle_kind"] = "frozen"
    manifest_payload["bundle_state"] = BUNDLE_STATE_FROZEN
    manifest_payload["sentinel_present"] = True
    report_payload.update(
        {
            "schema_version": VERIFY_REPORT_SCHEMA,
            "run_id": source_summary.run_id,
            "completeness": source_summary.completeness,
            "blockers": list(source_summary.blockers),
            "claims": source_summary.claims,
            "sentinel_present": True,
            "manual_review_authenticated": source_summary.manual_review_authenticated,
            "bundle_state": BUNDLE_STATE_FROZEN,
        }
    )
    _atomic_write_json(manifest_path, manifest_payload)
    _atomic_write_json(report_path, report_payload)
    pre_summary = verify_bundle(
        root,
        manual_review_allowed_signers=manual_review_allowed_signers,
        manual_review_signature=manual_review_signature,
        enforce_stored_report=False,
        verification_mode=VERIFICATION_MODE_PRE_SENTINEL_FROZEN,
    )
    if pre_summary.completeness != "COMPLETE":
        raise BundleVerificationError(pre_summary.blockers)
    _atomic_write_json(report_path, pre_summary.model_dump(mode="json"))
    return verify_bundle(
        root,
        manual_review_allowed_signers=manual_review_allowed_signers,
        manual_review_signature=manual_review_signature,
        enforce_stored_report=True,
        verification_mode=VERIFICATION_MODE_PRE_SENTINEL_FROZEN,
    )


def promote_bundle(
    bundle_root: Path,
    frozen_root: Path,
    *,
    manual_review_allowed_signers: Path | None = None,
    manual_review_signature: Path | None = None,
    simulate_failure: bool = False,
) -> Path:
    source_root = _safe_root(bundle_root)
    summary = verify_bundle(
        source_root,
        manual_review_allowed_signers=manual_review_allowed_signers,
        manual_review_signature=manual_review_signature,
        verification_mode=VERIFICATION_MODE_NORMAL,
    )
    if summary.completeness != "COMPLETE":
        raise BundleVerificationError(summary.blockers)
    if summary.bundle_state != BUNDLE_STATE_CANDIDATE:
        raise BundleVerificationError("promotion requires a candidate bundle in CANDIDATE_VERIFIED state")
    frozen_root = frozen_root.resolve()
    frozen_root.mkdir(parents=True, exist_ok=True)
    target_root = frozen_root / summary.run_id
    if target_root.exists():
        raise BundleVerificationError(f"frozen target already exists: {target_root}")
    staging_parent = Path(tempfile.mkdtemp(prefix=f".{summary.run_id}.", dir=str(frozen_root)))
    staging_root = staging_parent / summary.run_id
    replaced_target = False
    try:
        _copy_bundle(source_root, staging_root)
        copied_summary = _rewrite_frozen_bundle_state(
            staging_root,
            summary,
            manual_review_allowed_signers=manual_review_allowed_signers,
            manual_review_signature=manual_review_signature,
        )
        copied_summary = verify_bundle(
            staging_root,
            manual_review_allowed_signers=manual_review_allowed_signers,
            manual_review_signature=manual_review_signature,
            verification_mode=VERIFICATION_MODE_PRE_SENTINEL_FROZEN,
        )
        if copied_summary.completeness != "COMPLETE":
            raise BundleVerificationError(copied_summary.blockers)
        if simulate_failure:
            raise BundleVerificationError("simulated promotion failure")
        os.replace(staging_root, target_root)
        replaced_target = True
        destination_summary = verify_bundle(
            target_root,
            manual_review_allowed_signers=manual_review_allowed_signers,
            manual_review_signature=manual_review_signature,
            verification_mode=VERIFICATION_MODE_PRE_SENTINEL_FROZEN,
        )
        if destination_summary.completeness != "COMPLETE":
            raise BundleVerificationError(destination_summary.blockers)
        _atomic_write_bytes(target_root / SENTINEL, _sentinel_payload(target_root, destination_summary))
        _fsync_directory(target_root)
        frozen_summary = verify_bundle(
            target_root,
            manual_review_allowed_signers=manual_review_allowed_signers,
            manual_review_signature=manual_review_signature,
            verification_mode=VERIFICATION_MODE_NORMAL,
        )
        if frozen_summary.completeness != "COMPLETE":
            raise BundleVerificationError(frozen_summary.blockers)
        return target_root
    except Exception:
        if replaced_target and target_root.exists():
            shutil.rmtree(target_root, ignore_errors=True)
        raise
    finally:
        if staging_parent.exists():
            shutil.rmtree(staging_parent, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify or promote a Task 22 publication bundle candidate.")
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--promote-to-frozen", action="store_true")
    parser.add_argument("--frozen-root")
    parser.add_argument("--simulate-promotion-failure", action="store_true")
    parser.add_argument("--manual-review-allowed-signers")
    parser.add_argument("--manual-review-signature")
    args = parser.parse_args(argv)
    try:
        bundle_root = Path(args.bundle_root)
        allowed_signers = Path(args.manual_review_allowed_signers) if args.manual_review_allowed_signers else None
        signature = Path(args.manual_review_signature) if args.manual_review_signature else None
        summary = verify_bundle(
            bundle_root,
            manual_review_allowed_signers=allowed_signers,
            manual_review_signature=signature,
        )
        payload: dict[str, object] = summary.model_dump(mode="json")
        if args.promote_to_frozen:
            if not args.frozen_root:
                raise BundleVerificationError("--frozen-root is required when promoting")
            target_root = promote_bundle(
                bundle_root,
                Path(args.frozen_root),
                manual_review_allowed_signers=allowed_signers,
                manual_review_signature=signature,
                simulate_failure=args.simulate_promotion_failure,
            )
            summary = verify_bundle(
                target_root,
                manual_review_allowed_signers=allowed_signers,
                manual_review_signature=signature,
                verification_mode=VERIFICATION_MODE_NORMAL,
            )
            payload = summary.model_dump(mode="json")
            payload["frozen_root"] = str(target_root)
        _print_json(payload)
        return 0 if summary.completeness == "COMPLETE" and not summary.blockers else 1
    except (BundleVerificationError, ValidationError) as error:
        reasons = error.reasons if isinstance(error, BundleVerificationError) else (str(error),)
        _print_json(
            {
                "schema_version": VERIFY_REPORT_SCHEMA,
                "completeness": "INCOMPLETE",
                "blockers": list(reasons),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
