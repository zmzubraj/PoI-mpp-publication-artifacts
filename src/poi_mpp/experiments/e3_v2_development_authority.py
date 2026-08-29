"""Canonical request and verification contract for E3-v2 development authority.

This module is development-only. It validates the sealed 120--150 item bundle,
builds and re-derives one deterministic request, enforces APPROVED and
LIMITED_SCOPE decisions, and delegates detached-signature verification to the
canonical trust primitive in ``scripts/verify_e3_authority.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_TRUST_VERIFIER = REPO_ROOT / "scripts" / "verify_e3_authority.py"
REQUEST_SCHEMA_VERSION = "POI_MPP_E3_V2_DEVELOPMENT_AUTHORITY_REQUEST_V1"
RECORD_SCHEMA_VERSION = "POI_MPP_E3_V2_DEVELOPMENT_AUTHORITY_RECORD_V1"
REQUEST_STATUS = "UNSIGNED_PRE_EXECUTION_DEVELOPMENT_SCOPE_REQUEST"
SIGNATURE_NAMESPACE = "poi-e3-v2-development"
MAX_AUTHORITY_AGE_DAYS = 30
DEVELOPMENT_METRIC_SCOPE = ("ABSTAIN", "FAR", "FRR", "calibration", "coverage")
DEVELOPMENT_ARTIFACT_SCOPE = ("RAW_E3_EXECUTION",)
DEVELOPMENT_SUPPORT_RULE: dict[str, Any] = {
    "rule_id": "C3_V2_WILSON_SUPPORT_DEVELOPMENT_V1",
    "wilson_z_value": "1.959963984540054",
    "far_wilson_upper_bound_max": "0.25",
    "frr_wilson_upper_bound_max": "0.25",
    "coverage_min": "0.50",
    "development_composition": {
        "ACCEPT": 50,
        "REJECT": 50,
        "ABSTAIN_MIN": 20,
        "ABSTAIN_MAX": 50,
        "total_min": 120,
        "total_max": 150,
    },
}
REQUEST_INPUTS = (
    "scripts/build_e3_v2_development_authority_request.py",
    "scripts/fit_e3_v2_development_calibration.py",
    "scripts/run_e3_v2_development_model.py",
    "scripts/verify_e3_authority.py",
    "src/poi_mpp/experiments/e3_development.py",
    "src/poi_mpp/experiments/e3_v2_development_authority.py",
    "src/poi_mpp/worker/development_observation_exporter.py",
)


class DevelopmentAuthorityError(ValueError):
    """Raised when development authority validation fails closed."""


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


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    probe = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise DevelopmentAuthorityError(f"{label} may not be a symlink")


def _external_path(path: Path | str, *, label: str, directory: bool = False) -> Path:
    original = Path(path)
    _assert_no_symlink_components(original, label=label)
    try:
        resolved = original.resolve(strict=True)
    except FileNotFoundError as error:
        raise DevelopmentAuthorityError(f"{label} is missing") from error
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise DevelopmentAuthorityError(f"{label} must live outside the repository")
    valid = resolved.is_dir() if directory else resolved.is_file()
    if not valid or (not directory and resolved.stat().st_size == 0):
        kind = "directory" if directory else "non-empty file"
        raise DevelopmentAuthorityError(f"{label} must be a {kind}")
    return resolved


def _read_canonical_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DevelopmentAuthorityError(f"{label} must be valid JSON") from error
    if not isinstance(payload, dict):
        raise DevelopmentAuthorityError(f"{label} must be a JSON object")
    if raw != canonical_json_bytes(payload):
        raise DevelopmentAuthorityError(f"{label} must use canonical JSON serialization")
    return payload, raw


def build_requested_scope() -> dict[str, Any]:
    return {
        "experiment_id": "E3",
        "experiment_generation": "E3_V2",
        "claim_id": "C3",
        "claim_generation": "C3_V2",
        "task_class": "GROUNDED_SEMANTIC_ASSURANCE_DEVELOPMENT",
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "metric_scope": list(DEVELOPMENT_METRIC_SCOPE),
        "artifact_scope": list(DEVELOPMENT_ARTIFACT_SCOPE),
        "scope_scope": "DEVELOPMENT",
        "support_rule": DEVELOPMENT_SUPPORT_RULE,
    }


def _validated_repo_input(relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise DevelopmentAuthorityError(f"unsafe request input path: {relative_path}")
    candidate = REPO_ROOT.joinpath(*pure.parts)
    _assert_no_symlink_components(candidate, label=relative_path)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except (FileNotFoundError, ValueError) as error:
        raise DevelopmentAuthorityError(f"request input is missing: {relative_path}") from error
    if not resolved.is_file():
        raise DevelopmentAuthorityError(f"request input is not a file: {relative_path}")
    return resolved


def build_development_authority_request_manifest(bundle_root: Path | str) -> dict[str, Any]:
    """Derive the exact unsigned development request from validated materials."""

    resolved_bundle = _external_path(bundle_root, label="development bundle root", directory=True)
    from poi_mpp.experiments.e3_development import (
        validate_e3_phase3_development_bundle_materials,
    )

    try:
        materials = validate_e3_phase3_development_bundle_materials(
            bundle_root=resolved_bundle
        )
    except (ValueError, OSError) as error:
        raise DevelopmentAuthorityError(str(error)) from error
    policy_keys = (
        "claim_spec_hash",
        "prompt_template_hash",
        "output_schema_hash",
        "contradiction_policy_hash",
        "error_recovery_policy_hash",
        "error_taxonomy_review_hash",
    )
    policy_bindings = {
        key: materials.policy_input_file_hashes[key] for key in policy_keys
    }
    bound_materials = {
        "development_bundle_manifest_sha256": materials.bundle_manifest_sha256,
        "development_dataset_manifest_hash": materials.dataset_manifest.dataset_manifest_hash(),
        "development_model_manifest_hash": materials.policy_input_file_hashes[
            "model_manifest_hash"
        ],
        "development_decode_policy_hash": materials.policy_input_file_hashes[
            "deterministic_decode_policy_hash"
        ],
        "development_environment_manifest_hash": materials.policy_input_file_hashes[
            "runtime_environment_hash"
        ],
        "development_policy_inputs_digest": _sha256(
            canonical_json_bytes(policy_bindings)
        ),
    }
    request_inputs = []
    for relative_path in sorted(REQUEST_INPUTS):
        artifact = _validated_repo_input(relative_path)
        raw = artifact.read_bytes()
        request_inputs.append(
            {"path": relative_path, "sha256": _sha256(raw), "size_bytes": len(raw)}
        )
    requested_scope = build_requested_scope()
    payload: dict[str, Any] = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "status": REQUEST_STATUS,
        "requested_scope": requested_scope,
        "requested_scope_digest": _sha256(canonical_json_bytes(requested_scope)),
        "bound_materials": bound_materials,
        "bound_materials_digest": _sha256(canonical_json_bytes(bound_materials)),
        "bound_documents": {"development_bundle_root": resolved_bundle.as_posix()},
        "request_input_count": len(request_inputs),
        "request_inputs": request_inputs,
        "allowed_authority_decisions": ["APPROVED", "LIMITED_SCOPE"],
        "result_attestation_status": "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION",
        "authority_boundary": (
            "Unsigned request for the 120-150-item E3-v2 development phase only; "
            "it grants no authority and cannot authorize confirmatory execution."
        ),
    }
    payload["self_digest"] = _sha256(canonical_json_bytes(payload))
    return payload


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ReviewedRequest(_FrozenModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    self_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class _AuthorizedScope(_FrozenModel):
    experiment_id: Literal["E3"]
    experiment_generation: Literal["E3_V2"]
    claim_id: Literal["C3"]
    claim_generation: Literal["C3_V2"]
    task_class: Literal["GROUNDED_SEMANTIC_ASSURANCE_DEVELOPMENT"]
    evidence_origin: Literal["REAL_MODEL_EXECUTION"]
    metric_scope: tuple[str, ...]
    artifact_scope: tuple[str, ...]
    scope_scope: Literal["DEVELOPMENT"]
    development_composition: dict[str, int]
    request_scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("metric_scope", "artifact_scope")
    @classmethod
    def _unique_nonempty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("scope must be non-empty and unique")
        return value


class _AuthorityRecord(_FrozenModel):
    schema_version: Literal["POI_MPP_E3_V2_DEVELOPMENT_AUTHORITY_RECORD_V1"]
    record_type: Literal["DEVELOPMENT_PRE_EXECUTION_SCOPE_AUTHORIZATION"]
    authority_identity: str = Field(min_length=1)
    authority_basis: str = Field(min_length=1)
    expertise_scope: str = Field(min_length=1)
    authorized_scope: _AuthorizedScope
    bound_materials: dict[str, str]
    reviewed_request_manifest: _ReviewedRequest
    decision: Literal["APPROVED", "LIMITED_SCOPE"]
    decision_notes: str = Field(min_length=1)
    authorization_date: str
    result_attestation_status: Literal["NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION"]
    external_signature_required: Literal[True]
    signature_reference: str = Field(min_length=1)
    allowed_signers_reference: str = Field(min_length=1)

    @field_validator(
        "authority_identity", "authority_basis", "expertise_scope", "decision_notes",
        "signature_reference", "allowed_signers_reference",
    )
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value

    @field_validator("authorization_date")
    @classmethod
    def _iso_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("authorization_date must use YYYY-MM-DD") from error
        if parsed.isoformat() != value:
            raise ValueError("authorization_date must use YYYY-MM-DD")
        return value


@dataclass(frozen=True)
class VerifiedDevelopmentAuthorityGrant:
    experiment_id: str
    claim_id: str
    evidence_origin: str
    decision: str
    authority_identity: str
    metric_scope: tuple[str, ...]
    artifact_scope: tuple[str, ...]
    request_scope_digest: str
    authority_record_sha256: str
    request_manifest_sha256: str
    request_manifest_self_digest: str
    development_bundle_manifest_sha256: str
    development_dataset_manifest_hash: str
    development_model_manifest_hash: str
    development_decode_policy_hash: str
    development_environment_manifest_hash: str
    development_policy_inputs_digest: str
    allowed_signers_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        frame = inspect.currentframe()
        authorized = False
        for _ in range(3):
            frame = None if frame is None else frame.f_back
            if frame is not None and frame.f_code.co_name == "verify_development_authority":
                authorized = Path(frame.f_code.co_filename).resolve() == Path(__file__).resolve()
                break
        if not authorized:
            raise DevelopmentAuthorityError(
                "verified development authority grants may only be created by the canonical verifier"
            )


def _load_canonical_trust_verifier():
    module_name = "_poi_mpp_canonical_e3_external_trust"
    module = sys.modules.get(module_name)
    if module is None:
        spec = importlib.util.spec_from_file_location(module_name, CANONICAL_TRUST_VERIFIER)
        if spec is None or spec.loader is None:
            raise DevelopmentAuthorityError("canonical authority verifier is unavailable")
        module = importlib.util.module_from_spec(spec)
        scripts_root = str(CANONICAL_TRUST_VERIFIER.parent)
        inserted = scripts_root not in sys.path
        if inserted:
            sys.path.insert(0, scripts_root)
        try:
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        finally:
            if inserted:
                sys.path.pop(0)
    verifier = getattr(module, "verify_external_detached_signature", None)
    if verifier is None:
        raise DevelopmentAuthorityError("canonical external trust primitive is unavailable")
    return verifier


def verify_development_authority(
    *, request_manifest_path: Path | str, authority_record_path: Path | str,
    allowed_signers_path: Path | str, signature_path: Path | str,
) -> VerifiedDevelopmentAuthorityGrant:
    request_path = _external_path(request_manifest_path, label="development request manifest")
    record_path = _external_path(authority_record_path, label="development authority record")
    request, request_bytes = _read_canonical_json(request_path, label="development request manifest")
    bound_documents = request.get("bound_documents")
    if not isinstance(bound_documents, dict) or not isinstance(
        bound_documents.get("development_bundle_root"), str
    ):
        raise DevelopmentAuthorityError("development request is missing bound bundle root")
    expected = build_development_authority_request_manifest(
        bound_documents["development_bundle_root"]
    )
    if request != expected:
        if request.get("requested_scope_digest") != expected["requested_scope_digest"]:
            raise DevelopmentAuthorityError("requested scope digest mismatch")
        raise DevelopmentAuthorityError("development request manifest is stale, tampered, or non-canonical")
    record_payload, record_bytes = _read_canonical_json(record_path, label="development authority record")
    try:
        record = _AuthorityRecord.model_validate(record_payload)
    except ValidationError as error:
        raise DevelopmentAuthorityError(f"development authority record validation failed: {error}") from error
    reviewed = record.reviewed_request_manifest
    if reviewed.path not in {request_path.name, request_path.as_posix()}:
        raise DevelopmentAuthorityError("reviewed request manifest path mismatch")
    if reviewed.sha256 != _sha256(request_bytes):
        raise DevelopmentAuthorityError("request manifest sha256 mismatch")
    if reviewed.self_digest != request["self_digest"]:
        raise DevelopmentAuthorityError("request manifest self_digest mismatch")
    requested = request["requested_scope"]
    scope = record.authorized_scope
    if scope.request_scope_digest != request["requested_scope_digest"]:
        raise DevelopmentAuthorityError("requested scope digest mismatch")
    fixed_fields = (
        "experiment_id", "experiment_generation", "claim_id", "claim_generation",
        "task_class", "evidence_origin", "scope_scope",
    )
    if any(getattr(scope, field) != requested[field] for field in fixed_fields):
        raise DevelopmentAuthorityError("authority scope does not match development request")
    if scope.development_composition != DEVELOPMENT_SUPPORT_RULE["development_composition"]:
        raise DevelopmentAuthorityError("authority development composition is not frozen")
    if record.bound_materials != request["bound_materials"]:
        raise DevelopmentAuthorityError("authority bound materials do not echo the request")
    requested_metrics = set(requested["metric_scope"])
    requested_artifacts = set(requested["artifact_scope"])
    metrics = set(scope.metric_scope)
    artifacts = set(scope.artifact_scope)
    if record.decision == "APPROVED":
        if metrics != requested_metrics or artifacts != requested_artifacts:
            raise DevelopmentAuthorityError("APPROVED scope must exactly match the request")
    else:
        if not metrics.issubset(requested_metrics) or not artifacts.issubset(requested_artifacts):
            raise DevelopmentAuthorityError("LIMITED_SCOPE must be a request subset")
        if metrics == requested_metrics and artifacts == requested_artifacts:
            raise DevelopmentAuthorityError("LIMITED_SCOPE must be a strict narrowing")
        if "RAW_E3_EXECUTION" not in artifacts:
            raise DevelopmentAuthorityError("LIMITED_SCOPE must include RAW_E3_EXECUTION")
    authorization_date = date.fromisoformat(record.authorization_date)
    age = (date.today() - authorization_date).days
    if age < 0 or age > MAX_AUTHORITY_AGE_DAYS:
        raise DevelopmentAuthorityError("development authority record is stale")
    try:
        transcript = _load_canonical_trust_verifier()(
            record_bytes=record_bytes,
            authority_identity=record.authority_identity,
            allowed_signers_path=Path(allowed_signers_path),
            signature_path=Path(signature_path),
            namespace=SIGNATURE_NAMESPACE,
        )
    except Exception as error:
        raise DevelopmentAuthorityError(str(error)) from error
    bindings = request["bound_materials"]
    return VerifiedDevelopmentAuthorityGrant(
        experiment_id=scope.experiment_id, claim_id=scope.claim_id,
        evidence_origin=scope.evidence_origin, decision=record.decision,
        authority_identity=record.authority_identity, metric_scope=scope.metric_scope,
        artifact_scope=scope.artifact_scope, request_scope_digest=scope.request_scope_digest,
        authority_record_sha256=_sha256(record_bytes), request_manifest_sha256=_sha256(request_bytes),
        request_manifest_self_digest=request["self_digest"],
        development_bundle_manifest_sha256=bindings["development_bundle_manifest_sha256"],
        development_dataset_manifest_hash=bindings["development_dataset_manifest_hash"],
        development_model_manifest_hash=bindings["development_model_manifest_hash"],
        development_decode_policy_hash=bindings["development_decode_policy_hash"],
        development_environment_manifest_hash=bindings["development_environment_manifest_hash"],
        development_policy_inputs_digest=bindings["development_policy_inputs_digest"],
        allowed_signers_sha256=transcript.allowed_signers_sha256,
        signature_sha256=transcript.signature_sha256,
    )
