"""Registry-backed semantic authority records for publication-scoped execution."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

from poi_mpp.evidence.canonical import canonical_bytes as _canonical_bytes
from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import EvidenceOrigin


SEMANTIC_AUTHORITY_RECORD_V1_SCHEMA = "POI_MPP_SEMANTIC_AUTHORITY_RECORD_V1"
SEMANTIC_AUTHORITY_RECORD_V1_DOMAIN = "SEMANTIC_AUTHORITY_RECORD_V1"

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CLAIM_ID = re.compile(r"C[1-9][0-9]*\Z")
_EXPERIMENT_ID = re.compile(r"E[1-9][0-9]*\Z")
_METRIC_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_ARTIFACT_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}\Z")


class _FrozenAuthorityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticAuthorityDecision(StrEnum):
    APPROVED = "APPROVED"
    LIMITED_SCOPE = "LIMITED_SCOPE"


class SemanticAuthorityRevocationState(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class SemanticAuthorityUseMode(StrEnum):
    DEVELOPMENT_ONLY = "DEVELOPMENT_ONLY"
    CONFIRMATORY_PUBLICATION = "CONFIRMATORY_PUBLICATION"


class IdentityBindingStatus(StrEnum):
    VERIFIED_ACCOUNTABLE_IDENTITY = "VERIFIED_ACCOUNTABLE_IDENTITY"
    UNVERIFIED_OUT_OF_BAND = "UNVERIFIED_OUT_OF_BAND"


class TrustIndependenceStatus(StrEnum):
    VERIFIED_OUT_OF_BAND = "VERIFIED_OUT_OF_BAND"
    UNVERIFIED_OUT_OF_BAND = "UNVERIFIED_OUT_OF_BAND"


class KeyCustodyStatus(StrEnum):
    VERIFIED_OUT_OF_BAND = "VERIFIED_OUT_OF_BAND"
    UNVERIFIED_OUT_OF_BAND = "UNVERIFIED_OUT_OF_BAND"


def _normalized_nonblank(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _normalized_pattern(value: Any, *, field_name: str, pattern: re.Pattern[str]) -> str:
    normalized = _normalized_nonblank(value, field_name=field_name)
    if pattern.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} has an invalid format")
    return normalized


def _normalized_hash(value: Any, *, field_name: str) -> str:
    normalized = _normalized_nonblank(value, field_name=field_name)
    if _SHA256.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return normalized


def _normalized_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an exact integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _normalized_unique_strings(
    values: Any,
    *,
    field_name: str,
    pattern: re.Pattern[str],
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a sequence")
    normalized = tuple(
        _normalized_pattern(item, field_name=field_name, pattern=pattern)
        for item in values
    )
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


class SemanticAuthorityScopeV1(_FrozenAuthorityModel):
    experiment_id: str
    claim_id: str
    claim_spec_hash: str
    dataset_manifest_hash: str
    semantic_policy_hash: str
    runtime_environment_hash: str
    evidence_origin: EvidenceOrigin
    use_mode: SemanticAuthorityUseMode
    allowed_metric_ids: tuple[str, ...]
    allowed_artifact_ids: tuple[str, ...]

    @field_validator("experiment_id", mode="before")
    @classmethod
    def normalize_experiment_id(cls, value: Any) -> str:
        return _normalized_pattern(value, field_name="experiment_id", pattern=_EXPERIMENT_ID)

    @field_validator("claim_id", mode="before")
    @classmethod
    def normalize_claim_id(cls, value: Any) -> str:
        return _normalized_pattern(value, field_name="claim_id", pattern=_CLAIM_ID)

    @field_validator(
        "claim_spec_hash",
        "dataset_manifest_hash",
        "semantic_policy_hash",
        "runtime_environment_hash",
        mode="before",
    )
    @classmethod
    def normalize_hashes(cls, value: Any, info: ValidationInfo) -> str:
        return _normalized_hash(value, field_name=info.field_name)

    @field_validator("allowed_metric_ids", mode="before")
    @classmethod
    def normalize_metric_ids(cls, value: Any) -> tuple[str, ...]:
        return _normalized_unique_strings(value, field_name="allowed_metric_ids", pattern=_METRIC_ID)

    @field_validator("allowed_artifact_ids", mode="before")
    @classmethod
    def normalize_artifact_ids(cls, value: Any) -> tuple[str, ...]:
        return _normalized_unique_strings(value, field_name="allowed_artifact_ids", pattern=_ARTIFACT_ID)

    @model_validator(mode="after")
    def validate_evidence_origin_contract(self) -> "SemanticAuthorityScopeV1":
        if self.evidence_origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
            raise ValueError("evidence_origin must not be SYNTHETIC_NON_EVIDENCE")
        if (
            self.use_mode is SemanticAuthorityUseMode.CONFIRMATORY_PUBLICATION
            and self.evidence_origin is not EvidenceOrigin.REAL_MODEL_EXECUTION
        ):
            raise ValueError(
                "evidence_origin must be REAL_MODEL_EXECUTION for CONFIRMATORY_PUBLICATION"
            )
        return self


class SemanticAuthorityRecordV1(_FrozenAuthorityModel):
    schema_version: Literal[SEMANTIC_AUTHORITY_RECORD_V1_SCHEMA] = (
        SEMANTIC_AUTHORITY_RECORD_V1_SCHEMA
    )
    authority_id: str
    key_id: str
    accountable_identity_reference: str
    registry_revision: int
    registry_snapshot_hash: str
    signature_namespace: str
    signature_reference: str
    detached_signature_sha256: str
    decision: SemanticAuthorityDecision
    valid_from: date
    valid_until: date
    revocation_state: SemanticAuthorityRevocationState
    scope: SemanticAuthorityScopeV1
    identity_binding_status: IdentityBindingStatus
    independence_status: TrustIndependenceStatus
    key_custody_status: KeyCustodyStatus
    independence_basis: str
    unresolved_out_of_band_checks: tuple[str, ...] = ()

    @field_validator(
        "authority_id",
        "key_id",
        "accountable_identity_reference",
        "signature_namespace",
        "signature_reference",
        mode="before",
    )
    @classmethod
    def normalize_tokens(cls, value: Any, info: ValidationInfo) -> str:
        return _normalized_pattern(value, field_name=info.field_name, pattern=_SAFE_TOKEN)

    @field_validator("independence_basis", mode="before")
    @classmethod
    def normalize_independence_basis(cls, value: Any) -> str:
        return _normalized_nonblank(value, field_name="independence_basis")

    @field_validator("registry_revision", mode="before")
    @classmethod
    def normalize_registry_revision(cls, value: Any) -> int:
        return _normalized_positive_int(value, field_name="registry_revision")

    @field_validator("registry_snapshot_hash", "detached_signature_sha256", mode="before")
    @classmethod
    def normalize_record_hashes(cls, value: Any, info: ValidationInfo) -> str:
        return _normalized_hash(value, field_name=info.field_name)

    @field_validator("unresolved_out_of_band_checks", mode="before")
    @classmethod
    def normalize_unresolved_checks(cls, value: Any) -> tuple[str, ...]:
        if value in (None, ()):
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("unresolved_out_of_band_checks must be a sequence")
        normalized = tuple(
            _normalized_nonblank(item, field_name="unresolved_out_of_band_checks")
            for item in value
        )
        if len(set(normalized)) != len(normalized):
            raise ValueError("unresolved_out_of_band_checks must not contain duplicates")
        return tuple(sorted(normalized))

    @model_validator(mode="after")
    def validate_temporal_and_trust_contract(self) -> "SemanticAuthorityRecordV1":
        if self.valid_until < self.valid_from:
            raise ValueError("valid_until must not precede valid_from")
        if (
            self.identity_binding_status
            is IdentityBindingStatus.VERIFIED_ACCOUNTABLE_IDENTITY
            and self.independence_status is TrustIndependenceStatus.VERIFIED_OUT_OF_BAND
            and self.key_custody_status is KeyCustodyStatus.VERIFIED_OUT_OF_BAND
            and self.unresolved_out_of_band_checks
        ):
            raise ValueError(
                "unresolved_out_of_band_checks must be empty when all out-of-band statuses are verified"
            )
        return self

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(SEMANTIC_AUTHORITY_RECORD_V1_DOMAIN, self.canonical_payload())

    @property
    def record_digest(self) -> str:
        return digest(SEMANTIC_AUTHORITY_RECORD_V1_DOMAIN, self.canonical_payload())

    def scope_gate_reasons(self, *, on_date: date | None = None) -> tuple[str, ...]:
        inspection_date = on_date or date.today()
        reasons: list[str] = []
        if self.revocation_state is SemanticAuthorityRevocationState.REVOKED:
            reasons.append("authority record is revoked")
        if inspection_date < self.valid_from:
            reasons.append("authority record is not yet valid")
        if inspection_date > self.valid_until:
            reasons.append("authority record is expired")
        if self.scope.evidence_origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
            reasons.append("authority scope binds synthetic non-evidence")
        if (
            self.scope.use_mode is SemanticAuthorityUseMode.CONFIRMATORY_PUBLICATION
            and self.scope.evidence_origin is not EvidenceOrigin.REAL_MODEL_EXECUTION
        ):
            reasons.append(
                "confirmatory publication authority requires REAL_MODEL_EXECUTION evidence_origin"
            )
        return tuple(dict.fromkeys(reasons))

    def out_of_band_review_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.identity_binding_status is not IdentityBindingStatus.VERIFIED_ACCOUNTABLE_IDENTITY:
            reasons.append("accountable identity remains unverified out of band")
        if self.independence_status is not TrustIndependenceStatus.VERIFIED_OUT_OF_BAND:
            reasons.append("independence remains unverified out of band")
        if self.key_custody_status is not KeyCustodyStatus.VERIFIED_OUT_OF_BAND:
            reasons.append("private-key custody remains unverified out of band")
        reasons.extend(
            f"unresolved out-of-band check: {item}"
            for item in self.unresolved_out_of_band_checks
        )
        return tuple(dict.fromkeys(reasons))

    def publication_eligibility_gate_reasons(
        self,
        *,
        cryptographic_validity_verified: bool,
        requested_metric_ids: tuple[str, ...],
        requested_artifact_ids: tuple[str, ...],
        on_date: date | None = None,
    ) -> tuple[str, ...]:
        reasons = [
            *self.scope_gate_reasons(on_date=on_date),
            *self.out_of_band_review_reasons(),
        ]
        if cryptographic_validity_verified is not True:
            reasons.append(
                "detached signature validity remains unverified by the canonical external verifier"
            )
        requested_metrics = set(requested_metric_ids)
        requested_artifacts = set(requested_artifact_ids)
        if not requested_metrics:
            reasons.append("requested metric scope must not be empty")
        if not requested_artifacts:
            reasons.append("requested artifact scope must not be empty")
        unexpected_metrics = sorted(
            requested_metrics.difference(self.scope.allowed_metric_ids)
        )
        unexpected_artifacts = sorted(
            requested_artifacts.difference(self.scope.allowed_artifact_ids)
        )
        if unexpected_metrics:
            reasons.append(
                "requested metric scope exceeds signed authority: "
                + ", ".join(unexpected_metrics)
            )
        if unexpected_artifacts:
            reasons.append(
                "requested artifact scope exceeds signed authority: "
                + ", ".join(unexpected_artifacts)
            )
        if self.decision is SemanticAuthorityDecision.LIMITED_SCOPE:
            if requested_metrics != set(self.scope.allowed_metric_ids):
                reasons.append(
                    "LIMITED_SCOPE requires exact signed metric scope equality"
                )
            if requested_artifacts != set(self.scope.allowed_artifact_ids):
                reasons.append(
                    "LIMITED_SCOPE requires exact signed artifact scope equality"
                )
        return tuple(dict.fromkeys(reasons))

    def is_publication_eligible(
        self,
        *,
        cryptographic_validity_verified: bool,
        requested_metric_ids: tuple[str, ...],
        requested_artifact_ids: tuple[str, ...],
        on_date: date | None = None,
    ) -> bool:
        """Return local eligibility only; this is not submission or scientific readiness."""

        return not self.publication_eligibility_gate_reasons(
            cryptographic_validity_verified=cryptographic_validity_verified,
            requested_metric_ids=requested_metric_ids,
            requested_artifact_ids=requested_artifact_ids,
            on_date=on_date,
        )
