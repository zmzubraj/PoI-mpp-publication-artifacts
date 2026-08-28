"""Typed E3-v2 authority scope contracts.

Defines the frozen C3-v2 request scope, the V2 authority request manifest
builder, and the V2 authority record model.  The request manifest binds:

- the frozen C3-v2 Wilson support rule,
- the six development bundle bindings (from the development bundle report),
- the confirmatory freeze material lineage (from the lineage report),
- the semantic calibration freeze content hash,
- the tracked repository input files.

The manifest is unsigned request material: it grants no authority, contains no
evaluator identity or decision, and cannot attest to any future result.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date as _date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from poi_mpp.auditor.semantic.models import (
    SemanticCalibrationFreezeStatus,
    SemanticCalibrationFreezeV2,
)


REPO_ROOT = Path(__file__).resolve().parents[3]

E3_V2_REQUEST_SCHEMA_VERSION = "POI_MPP_E3_AUTHORITY_REQUEST_V2"
E3_V2_AUTHORITY_RECORD_SCHEMA_VERSION = "POI_MPP_E3_AUTHORITY_RECORD_V3"
E3_V2_REQUEST_STATUS = "UNSIGNED_PRE_EXECUTION_SCOPE_REQUEST"
E3_V2_EXPERIMENT_GENERATION = "E3_V2"
E3_V2_CLAIM_GENERATION = "C3_V2"
E3_V2_TASK_CLASS = "GROUNDED_SEMANTIC_ASSURANCE"
E3_V2_METRIC_SCOPE = ("ABSTAIN", "FAR", "FRR", "calibration", "coverage")
E3_V2_ARTIFACT_SCOPE = ("F7", "RAW_E3_EXECUTION", "T4", "T8")
E3_V2_EVIDENCE_ORIGIN = "REAL_MODEL_EXECUTION"
E3_V2_SUPPORT_RULE_ID = "C3_V2_WILSON_SUPPORT_V1"
E3_V2_RESULT_ATTESTATION_STATUS = "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION"
E3_V2_ALLOWED_AUTHORITY_DECISIONS = ("APPROVED", "LIMITED_SCOPE")
DEVELOPMENT_REPORT_SCHEMA_VERSION = "POI_MPP_E3_V2_DEVELOPMENT_BUNDLE_REPORT_V1"
DEVELOPMENT_REPORT_STATUS = "MATERIALS_VALIDATED_WAITING_AUTHORITY"
CONFIRMATORY_LINEAGE_SCHEMA_VERSION = "POI_MPP_E3_V2_CONFIRMATORY_FREEZE_LINEAGE_V1"
CONFIRMATORY_LINEAGE_STATUS = "WAITING_EXTERNAL"

E3_V2_SUPPORT_RULE: dict[str, Any] = {
    "rule_id": E3_V2_SUPPORT_RULE_ID,
    "wilson_z_value": "1.959963984540054",
    "far_wilson_upper_bound_max": "0.25",
    "frr_wilson_upper_bound_max": "0.25",
    "coverage_min": "0.50",
    "confirmatory_composition": {"ACCEPT": 200, "REJECT": 200, "ABSTAIN": 100, "total": 500},
}

REQUEST_INPUTS = (
    "Makefile",
    "configs/confirmatory/e3.schema.yaml",
    "docs/EXPERIMENT_PLAN.md",
    "docs/EXPERIMENT_ARTIFACT_MATRIX.md",
    "docs/MAIN_RESULTS_TARGETS.md",
    "docs/PAPER_ARTIFACT_MAP.md",
    "docs/paper_artifacts/final/external_review/E3_SEMANTIC_EVALUATOR_AUTHORITY_REQUEST_CHECKLIST.md",
    "docs/paper_artifacts/final/external_review/e3_result_attestation_record.schema.json",
    "docs/paper_artifacts/final/external_review/semantic_evaluator_authority_record.schema.json",
    "docs/paper_artifacts/final/manuscript/POI_SUBMISSION_MANUSCRIPT.md",
    "docs/paper_artifacts/final/tables/T4_experiment_design_and_current_status.md",
    "docs/paper_artifacts/final/tables/T7_limitations_and_nonclaims.md",
    "publication/artifact_manifest.json",
    "publication/tables/claim_matrix.json",
    "publication/tables/omissions.json",
    "scripts/build_e3_v2_attestation_draft.py",
    "scripts/build_e3_v2_authority_request.py",
    "scripts/build_e3_v2_development_bundle.py",
    "scripts/freeze_e3_v2_confirmatory_dataset.py",
    "scripts/import_verified_e3_v2_result.py",
    "scripts/run_e3_v2_real_model.py",
    "scripts/verify_e3_v2_authority.py",
    "src/poi_mpp/auditor/semantic/models.py",
    "src/poi_mpp/evidence/canonical.py",
    "src/poi_mpp/evidence/dataset_manifest_v2.py",
    "src/poi_mpp/evidence/environment_manifest.py",
    "src/poi_mpp/experiments/e3_confirmatory_freeze.py",
    "src/poi_mpp/experiments/e3_development.py",
    "src/poi_mpp/experiments/e3_semantic.py",
    "src/poi_mpp/experiments/e3_v2_authority.py",
    "src/poi_mpp/experiments/e3_v2_scope.py",
    "src/poi_mpp/reporting/e3.py",
    "src/poi_mpp/worker/deterministic_decode.py",
    "src/poi_mpp/worker/model_manifest.py",
)

_DEVELOPMENT_BINDING_KEYS = (
    "development_bundle_manifest_sha256",
    "development_dataset_manifest_hash",
    "development_model_manifest_hash",
    "development_decode_policy_hash",
    "development_environment_manifest_hash",
    "development_policy_inputs_digest",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class E3V2ScopeError(ValueError):
    """Raised when E3-v2 authority scope contracts fail closed validation."""


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_requested_scope() -> dict[str, Any]:
    """Return the frozen C3-v2 requested scope as a plain canonical dict."""

    return {
        "experiment_id": "E3",
        "experiment_generation": E3_V2_EXPERIMENT_GENERATION,
        "claim_id": "C3",
        "claim_generation": E3_V2_CLAIM_GENERATION,
        "task_class": E3_V2_TASK_CLASS,
        "metric_scope": list(E3_V2_METRIC_SCOPE),
        "artifact_scope": list(E3_V2_ARTIFACT_SCOPE),
        "evidence_origin": E3_V2_EVIDENCE_ORIGIN,
        "support_rule": deepcopy(E3_V2_SUPPORT_RULE),
    }


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    probe = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise E3V2ScopeError(f"{label} may not be a symlink")


def _require_external_file(path: Path | str, *, label: str) -> Path:
    _assert_no_symlink_components(Path(path), label=label)
    try:
        resolved = Path(path).resolve(strict=True)
    except FileNotFoundError as error:
        raise E3V2ScopeError(f"{label} is missing") from error
    if not resolved.is_file():
        raise E3V2ScopeError(f"{label} must be a file")
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise E3V2ScopeError(f"{label} must live outside the repository")


def _read_canonical_json(path: Path, *, label: str) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise E3V2ScopeError(f"{label} must be valid JSON") from error
    if not isinstance(payload, dict):
        raise E3V2ScopeError(f"{label} must be a JSON object")
    if raw != canonical_json_bytes(payload):
        raise E3V2ScopeError(f"{label} must use canonical JSON serialization")
    return payload


def _require_self_digest(payload: dict[str, Any], *, label: str) -> None:
    provided = payload.get("self_digest")
    if not isinstance(provided, str) or not _SHA256_RE.match(provided):
        raise E3V2ScopeError(f"{label} self_digest must be a lowercase SHA-256 digest")
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    if _sha256(canonical_json_bytes(unsigned)) != provided:
        raise E3V2ScopeError(f"{label} self_digest mismatch")


def load_development_report(path: Path | str) -> dict[str, Any]:
    resolved = _require_external_file(path, label="development bundle report")
    payload = _read_canonical_json(resolved, label="development bundle report")
    if payload.get("schema_version") != DEVELOPMENT_REPORT_SCHEMA_VERSION:
        raise E3V2ScopeError(
            f"development bundle report has unexpected schema_version: {payload.get('schema_version')!r}"
        )
    if payload.get("status") != DEVELOPMENT_REPORT_STATUS:
        raise E3V2ScopeError("development bundle report must be MATERIALS_VALIDATED_WAITING_AUTHORITY")
    _require_self_digest(payload, label="development bundle report")
    for key in _DEVELOPMENT_BINDING_KEYS:
        value = payload.get(key)
        if not isinstance(value, str) or not _SHA256_RE.match(value):
            raise E3V2ScopeError(f"development report is missing binding: {key}")
    return payload


def load_confirmatory_lineage(path: Path | str) -> dict[str, Any]:
    resolved = _require_external_file(path, label="confirmatory freeze lineage report")
    payload = _read_canonical_json(resolved, label="confirmatory freeze lineage report")
    if payload.get("schema_version") != CONFIRMATORY_LINEAGE_SCHEMA_VERSION:
        raise E3V2ScopeError(
            f"confirmatory lineage report has unexpected schema_version: {payload.get('schema_version')!r}"
        )
    if payload.get("status") != CONFIRMATORY_LINEAGE_STATUS:
        raise E3V2ScopeError("confirmatory lineage report must remain WAITING_EXTERNAL")
    _require_self_digest(payload, label="confirmatory freeze lineage report")
    lineage = payload.get("material_lineage_hash")
    if not isinstance(lineage, str) or not _SHA256_RE.match(lineage):
        raise E3V2ScopeError("confirmatory lineage report is missing material_lineage_hash")
    nested = payload.get("lineage")
    if not isinstance(nested, dict):
        raise E3V2ScopeError("confirmatory lineage report is missing lineage bindings")
    for key in ("dataset_manifest_hash", "development_manifest_hash"):
        value = nested.get(key)
        if not isinstance(value, str) or not _SHA256_RE.match(value):
            raise E3V2ScopeError(f"confirmatory lineage report is missing lineage binding: {key}")
    return payload


def load_calibration_freeze(path: Path | str) -> SemanticCalibrationFreezeV2:
    resolved = _require_external_file(path, label="semantic calibration freeze")
    payload = _read_canonical_json(resolved, label="semantic calibration freeze")
    try:
        freeze = SemanticCalibrationFreezeV2.model_validate(payload)
    except ValidationError as error:
        raise E3V2ScopeError(f"semantic calibration freeze validation failed: {error}") from error
    if freeze.status is not SemanticCalibrationFreezeStatus.FROZEN_DEVELOPMENT_ONLY:
        raise E3V2ScopeError("semantic calibration freeze must be FROZEN_DEVELOPMENT_ONLY")
    return freeze


def build_bound_materials(
    *,
    development_report: dict[str, Any],
    confirmatory_lineage: dict[str, Any],
    calibration_freeze: SemanticCalibrationFreezeV2,
) -> dict[str, Any]:
    """Lift and cross-check every material binding the authority record must echo."""

    if calibration_freeze.development_dataset_manifest_hash != development_report[
        "development_dataset_manifest_hash"
    ]:
        raise E3V2ScopeError(
            "calibration freeze is not bound to the development bundle dataset manifest"
        )
    if calibration_freeze.runtime_environment_hash != development_report[
        "development_environment_manifest_hash"
    ]:
        raise E3V2ScopeError(
            "calibration freeze is not bound to the development bundle runtime environment"
        )
    lineage = confirmatory_lineage["lineage"]
    return {
        "development_bundle_manifest_sha256": development_report["development_bundle_manifest_sha256"],
        "development_dataset_manifest_hash": development_report["development_dataset_manifest_hash"],
        "development_model_manifest_hash": development_report["development_model_manifest_hash"],
        "development_decode_policy_hash": development_report["development_decode_policy_hash"],
        "development_environment_manifest_hash": development_report[
            "development_environment_manifest_hash"
        ],
        "development_policy_inputs_digest": development_report["development_policy_inputs_digest"],
        "confirmatory_freeze_material_lineage_hash": confirmatory_lineage["material_lineage_hash"],
        "confirmatory_dataset_manifest_hash": lineage["dataset_manifest_hash"],
        "confirmatory_development_manifest_hash": lineage["development_manifest_hash"],
        "calibration_freeze_content_hash": calibration_freeze.content_hash,
    }


def _validated_repo_file(relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise E3V2ScopeError(f"unsafe E3-v2 request input path: {relative_path}")
    candidate = REPO_ROOT.joinpath(*pure.parts)
    if candidate.is_symlink():
        raise E3V2ScopeError(f"E3-v2 request input may not be a symlink: {relative_path}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except (FileNotFoundError, ValueError) as error:
        raise E3V2ScopeError(
            f"E3-v2 request input is missing or escapes repository root: {relative_path}"
        ) from error
    if not resolved.is_file():
        raise E3V2ScopeError(f"E3-v2 request input is not a file: {relative_path}")
    return resolved


def build_manifest(
    *,
    development_report_path: Path | str,
    confirmatory_lineage_path: Path | str,
    calibration_freeze_path: Path | str,
) -> dict[str, Any]:
    """Build the deterministic unsigned E3-v2 pre-execution authority request."""

    resolved_report = _require_external_file(development_report_path, label="development bundle report")
    resolved_lineage = _require_external_file(
        confirmatory_lineage_path, label="confirmatory freeze lineage report"
    )
    resolved_freeze = _require_external_file(calibration_freeze_path, label="semantic calibration freeze")
    development_report = load_development_report(development_report_path)
    confirmatory_lineage = load_confirmatory_lineage(confirmatory_lineage_path)
    calibration_freeze = load_calibration_freeze(calibration_freeze_path)
    bound_materials = build_bound_materials(
        development_report=development_report,
        confirmatory_lineage=confirmatory_lineage,
        calibration_freeze=calibration_freeze,
    )
    requested_scope = build_requested_scope()

    entries: list[dict[str, Any]] = []
    for relative_path in sorted(REQUEST_INPUTS):
        artifact = _validated_repo_file(relative_path)
        payload = artifact.read_bytes()
        entries.append(
            {
                "path": relative_path,
                "sha256": _sha256(payload),
                "size_bytes": len(payload),
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": E3_V2_REQUEST_SCHEMA_VERSION,
        "status": E3_V2_REQUEST_STATUS,
        "requested_scope": requested_scope,
        "requested_scope_digest": _sha256(canonical_json_bytes(requested_scope)),
        "bound_materials": bound_materials,
        "bound_materials_digest": _sha256(canonical_json_bytes(bound_materials)),
        "bound_documents": {
            "development_report": resolved_report.as_posix(),
            "confirmatory_lineage": resolved_lineage.as_posix(),
            "calibration_freeze": resolved_freeze.as_posix(),
        },
        "request_input_count": len(entries),
        "request_inputs": entries,
        "allowed_authority_decisions": list(E3_V2_ALLOWED_AUTHORITY_DECISIONS),
        "result_attestation_status": E3_V2_RESULT_ATTESTATION_STATUS,
        "authority_boundary": (
            "This unsigned manifest requests external pre-execution scope authorization for the "
            "E3-v2 confirmatory experiment only. It grants no authority and contains no evaluator "
            "identity, decision, signature, or future-run result."
        ),
        "post_execution_boundary": (
            "Generated E3-v2 evidence can only be bound by a separate post-execution result "
            "attestation created after authorized execution; this request cannot attest to "
            "future artifacts, and the C3-v2 disposition is decided solely by the frozen "
            "Wilson-bound support rule recorded in requested_scope.support_rule."
        ),
    }
    manifest["self_digest"] = _sha256(canonical_json_bytes(manifest))
    return manifest


def validate_request_manifest_structure(payload: dict[str, Any]) -> None:
    """Fail closed unless the manifest is internally consistent with the frozen scope."""

    if payload.get("schema_version") != E3_V2_REQUEST_SCHEMA_VERSION:
        raise E3V2ScopeError("request manifest must use POI_MPP_E3_AUTHORITY_REQUEST_V2")
    if payload.get("status") != E3_V2_REQUEST_STATUS:
        raise E3V2ScopeError("request manifest must remain UNSIGNED_PRE_EXECUTION_SCOPE_REQUEST")
    if payload.get("requested_scope") != build_requested_scope():
        raise E3V2ScopeError("requested scope must equal the frozen C3-v2 scope")
    expected_scope_digest = _sha256(canonical_json_bytes(build_requested_scope()))
    if payload.get("requested_scope_digest") != expected_scope_digest:
        raise E3V2ScopeError("requested_scope_digest does not match the frozen C3-v2 scope")
    bound_materials = payload.get("bound_materials")
    if not isinstance(bound_materials, dict):
        raise E3V2ScopeError("request manifest is missing bound_materials")
    for key, value in bound_materials.items():
        if not isinstance(value, str) or not _SHA256_RE.match(value):
            raise E3V2ScopeError(f"bound material is not a SHA-256 digest: {key}")
    if payload.get("bound_materials_digest") != _sha256(canonical_json_bytes(bound_materials)):
        raise E3V2ScopeError("bound_materials_digest does not match bound_materials")
    bound_documents = payload.get("bound_documents")
    if not isinstance(bound_documents, dict) or set(bound_documents) != {
        "development_report",
        "confirmatory_lineage",
        "calibration_freeze",
    }:
        raise E3V2ScopeError("request manifest must bind exactly the three E3-v2 documents")
    for key, value in bound_documents.items():
        if not isinstance(value, str) or not value.strip():
            raise E3V2ScopeError(f"bound document path must not be blank: {key}")
        if not PurePosixPath(value).is_absolute():
            raise E3V2ScopeError(f"bound document path must be absolute: {key}")
    if payload.get("allowed_authority_decisions") != list(E3_V2_ALLOWED_AUTHORITY_DECISIONS):
        raise E3V2ScopeError("allowed_authority_decisions must remain APPROVED and LIMITED_SCOPE")
    if payload.get("result_attestation_status") != E3_V2_RESULT_ATTESTATION_STATUS:
        raise E3V2ScopeError("request manifest cannot include result attestation")
    for key in ("authority_boundary", "post_execution_boundary"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise E3V2ScopeError(f"request manifest boundary text is missing: {key}")
    _require_self_digest(payload, label="request manifest")


def validate_request_inputs_current(payload: dict[str, Any]) -> None:
    """Fail closed unless the bound repository inputs still match the working tree."""

    entries = payload.get("request_inputs")
    if not isinstance(entries, list) or not entries:
        raise E3V2ScopeError("request manifest is missing request_inputs")
    if payload.get("request_input_count") != len(entries):
        raise E3V2ScopeError("request_input_count does not match request_inputs")
    paths = [entry.get("path") for entry in entries]
    if paths != sorted(REQUEST_INPUTS):
        raise E3V2ScopeError("request_inputs must bind the canonical E3-v2 input selection")
    for entry in entries:
        relative_path = entry.get("path")
        artifact = _validated_repo_file(str(relative_path))
        raw = artifact.read_bytes()
        if entry.get("sha256") != _sha256(raw):
            raise E3V2ScopeError(f"request input is stale: {relative_path}")
        if entry.get("size_bytes") != len(raw):
            raise E3V2ScopeError(f"request input size is stale: {relative_path}")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_nonblank(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be blank")
    return value.strip()


class E3V2SupportRule(_FrozenModel):
    rule_id: str
    wilson_z_value: str
    far_wilson_upper_bound_max: str
    frr_wilson_upper_bound_max: str
    coverage_min: str
    confirmatory_composition: dict[str, int]

    @field_validator("rule_id")
    @classmethod
    def _validate_rule_id(cls, value: str) -> str:
        if value != E3_V2_SUPPORT_RULE_ID:
            raise ValueError("support rule must be the frozen C3-v2 Wilson support rule")
        return value

    @field_validator("confirmatory_composition")
    @classmethod
    def _validate_composition(cls, value: dict[str, int]) -> dict[str, int]:
        if value != E3_V2_SUPPORT_RULE["confirmatory_composition"]:
            raise ValueError("confirmatory composition must remain 200/200/100 of 500")
        return value


class E3V2AuthorizedScope(_FrozenModel):
    experiment_id: Literal["E3"]
    experiment_generation: Literal["E3_V2"]
    claim_id: Literal["C3"]
    claim_generation: Literal["C3_V2"]
    task_class: Literal["GROUNDED_SEMANTIC_ASSURANCE"]
    evidence_origin: Literal["REAL_MODEL_EXECUTION"]
    metric_scope: tuple[str, ...]
    artifact_scope: tuple[str, ...]
    privacy_scope: str
    request_scope_digest: str
    support_rule: E3V2SupportRule

    @field_validator("metric_scope")
    @classmethod
    def _validate_metric_scope(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(metric not in E3_V2_METRIC_SCOPE for metric in value):
            raise ValueError("metric_scope must be a non-empty subset of the E3 metric scope")
        return value

    @field_validator("artifact_scope")
    @classmethod
    def _validate_artifact_scope(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(artifact not in E3_V2_ARTIFACT_SCOPE for artifact in value):
            raise ValueError("artifact_scope must be a non-empty subset of the E3 artifact scope")
        return value

    @field_validator("privacy_scope")
    @classmethod
    def _validate_privacy_scope(cls, value: str) -> str:
        return _require_nonblank(value, label="privacy_scope")

    @field_validator("request_scope_digest")
    @classmethod
    def _validate_request_scope_digest(cls, value: str) -> str:
        return _require_sha256(value, label="request_scope_digest")


class E3V2BoundMaterials(_FrozenModel):
    development_bundle_manifest_sha256: str
    development_dataset_manifest_hash: str
    development_model_manifest_hash: str
    development_decode_policy_hash: str
    development_environment_manifest_hash: str
    development_policy_inputs_digest: str
    confirmatory_freeze_material_lineage_hash: str
    confirmatory_dataset_manifest_hash: str
    confirmatory_development_manifest_hash: str
    calibration_freeze_content_hash: str

    @field_validator(
        "development_bundle_manifest_sha256",
        "development_dataset_manifest_hash",
        "development_model_manifest_hash",
        "development_decode_policy_hash",
        "development_environment_manifest_hash",
        "development_policy_inputs_digest",
        "confirmatory_freeze_material_lineage_hash",
        "confirmatory_dataset_manifest_hash",
        "confirmatory_development_manifest_hash",
        "calibration_freeze_content_hash",
    )
    @classmethod
    def _validate_digests(cls, value: str, info) -> str:
        return _require_sha256(value, label=info.field_name)


class E3V2ReviewedRequestManifest(_FrozenModel):
    path: str
    sha256: str
    self_digest: str

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _require_nonblank(value, label="reviewed_request_manifest.path")

    @field_validator("sha256", "self_digest")
    @classmethod
    def _validate_digests(cls, value: str, info) -> str:
        return _require_sha256(value, label=info.field_name)


class E3V2AuthorityRecord(_FrozenModel):
    schema_version: Literal["POI_MPP_E3_AUTHORITY_RECORD_V3"]
    record_type: Literal["PRE_EXECUTION_SCOPE_AUTHORIZATION"]
    authority_identity: str
    authority_basis: str
    expertise_scope: str
    authorized_scope: E3V2AuthorizedScope
    bound_materials: E3V2BoundMaterials
    reviewed_request_manifest: E3V2ReviewedRequestManifest
    decision: Literal["APPROVED", "LIMITED_SCOPE"]
    decision_notes: str
    authorization_date: str
    result_attestation_status: Literal["NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION"]
    external_signature_required: Literal[True] = True
    signature_reference: str
    allowed_signers_reference: str

    @field_validator("authority_identity", "authority_basis", "expertise_scope", "decision_notes")
    @classmethod
    def _validate_nonblank(cls, value: str, info) -> str:
        return _require_nonblank(value, label=info.field_name)

    @field_validator("authorization_date")
    @classmethod
    def _validate_authorization_date(cls, value: str) -> str:
        if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
            raise ValueError("authorization_date must be a strict ISO date")
        try:
            _date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("authorization_date must be a valid ISO date") from error
        return value

    @field_validator("signature_reference", "allowed_signers_reference")
    @classmethod
    def _validate_external_references(cls, value: str, info) -> str:
        normalized = _require_nonblank(value, label=info.field_name)
        if not normalized.startswith("external://"):
            raise ValueError(f"{info.field_name} must reference material outside the repository")
        return normalized


def parse_authority_record(payload: dict[str, Any]) -> E3V2AuthorityRecord:
    try:
        return E3V2AuthorityRecord.model_validate(payload)
    except ValidationError as error:
        raise E3V2ScopeError(f"authority record validation failed: {error}") from error
