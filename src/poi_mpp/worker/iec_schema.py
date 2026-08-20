"""Intelligence Evidence Capsule schema."""

from __future__ import annotations

from pydantic import ValidationInfo, field_validator, model_validator

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.worker.model_manifest import _FrozenWorkerModel, validate_public_json


class EvidenceItem(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_IEC_EVIDENCE_ITEM_V1"
    evidence_id: str
    artifact_label: str
    content: str
    keywords: tuple[str, ...]
    origin: EvidenceOrigin
    confidence: float | None = None

    @field_validator("evidence_id", "artifact_label", "content")
    @classmethod
    def require_safe_text(cls, value: str, info: ValidationInfo) -> str:
        normalized = validate_public_json(value, field_name=info.field_name)
        assert isinstance(normalized, str)
        return normalized

    @field_validator("keywords")
    @classmethod
    def require_keywords(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("keywords must not be empty")
        normalized = validate_public_json(list(value), field_name="keywords")
        assert isinstance(normalized, list)
        return tuple(item for item in normalized if isinstance(item, str))

    @field_validator("confidence")
    @classmethod
    def require_finite_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return value
        normalized = validate_public_json(value, field_name="confidence")
        assert isinstance(normalized, float)
        return normalized


class ClaimNode(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_IEC_CLAIM_NODE_V1"
    claim_id: str
    text: str
    evidence_ids: tuple[str, ...]

    @field_validator("claim_id", "text")
    @classmethod
    def require_safe_text(cls, value: str, info: ValidationInfo) -> str:
        normalized = validate_public_json(value, field_name=info.field_name)
        assert isinstance(normalized, str)
        return normalized

    @field_validator("evidence_ids")
    @classmethod
    def require_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = validate_public_json(list(value), field_name="evidence_ids")
        assert isinstance(normalized, list)
        return tuple(item for item in normalized if isinstance(item, str))


class IntelligenceEvidenceCapsule(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_IEC_V1"
    response_hash: str
    claims: tuple[ClaimNode, ...]
    evidence_items: tuple[EvidenceItem, ...]
    task_requirements: tuple[str, ...] = ()
    evidence_root: str

    @field_validator("task_requirements")
    @classmethod
    def require_requirements(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = validate_public_json(list(value), field_name="task_requirements")
        assert isinstance(normalized, list)
        return tuple(item for item in normalized if isinstance(item, str))

    @model_validator(mode="after")
    def require_closed_evidence_graph(self) -> "IntelligenceEvidenceCapsule":
        evidence_ids = {item.evidence_id for item in self.evidence_items}
        if len(evidence_ids) != len(self.evidence_items):
            raise ValueError("evidence_items must have unique evidence_id values")
        for claim in self.claims:
            if not set(claim.evidence_ids).issubset(evidence_ids):
                raise ValueError("claim references unknown evidence_id")
        return self
