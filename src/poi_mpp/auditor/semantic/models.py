"""Typed models for deterministic grounded semantic verification."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import EvidenceOrigin


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BOUNDED_DECIMAL = re.compile(r"-?(0|[1-9][0-9]{0,11})(\.[0-9]{1,12})?\Z")


class VerificationMode(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    CONFIRMATORY = "CONFIRMATORY"


class VerificationDecision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class SemanticOutcome(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTORY = "CONTRADICTORY"
    PARTIAL = "PARTIAL"
    AMBIGUOUS = "AMBIGUOUS"
    NUMERICAL_ERROR = "NUMERICAL_ERROR"
    CITATION_ERROR = "CITATION_ERROR"


class EvidenceAnnotationKind(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"


class NumericComparator(StrEnum):
    EQUALS = "EQUALS"
    AT_LEAST = "AT_LEAST"
    AT_MOST = "AT_MOST"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def parse_bounded_decimal(value: str, *, label: str) -> Decimal:
    if not isinstance(value, str) or not _BOUNDED_DECIMAL.fullmatch(value):
        raise ValueError(f"{label} must be a bounded decimal string")
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} must be a bounded decimal string") from error


class EvidenceAnnotation(_FrozenModel):
    claim_id: str
    kind: EvidenceAnnotationKind
    reason: str

    @field_validator("claim_id", "reason")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("annotation fields must not be blank")
        return value


class NumericFact(_FrozenModel):
    claim_id: str
    metric: str
    value: str
    unit: str | None = None

    @field_validator("claim_id", "metric")
    @classmethod
    def reject_blank_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("numeric identifiers must not be blank")
        return value

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        parse_bounded_decimal(value, label="numeric fact value")
        return value

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("unit must not be blank")
        return value


class NumericExpectation(_FrozenModel):
    metric: str
    comparator: NumericComparator
    value: str
    unit: str | None = None

    @field_validator("metric")
    @classmethod
    def reject_blank_metric(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("metric must not be blank")
        return value

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        parse_bounded_decimal(value, label="numeric expectation value")
        return value

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("unit must not be blank")
        return value


class EvidenceRecord(_FrozenModel):
    evidence_id: str
    citation_id: str
    source_family: str
    origin: EvidenceOrigin
    content: str
    content_hash: str
    annotations: tuple[EvidenceAnnotation, ...] = ()
    numeric_facts: tuple[NumericFact, ...] = ()

    @field_validator("evidence_id", "citation_id", "source_family", "content")
    @classmethod
    def reject_blank_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence fields must not be blank")
        return value

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash_shape(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def validate_content_hash(self) -> "EvidenceRecord":
        expected = digest(
            "SEMANTIC_EVIDENCE_CONTENT",
            {
                "citation_id": self.citation_id,
                "content": self.content,
                "source_family": self.source_family,
            },
        )
        if self.content_hash != expected:
            raise ValueError("content_hash must match canonical evidence content")
        return self


class GroundedClaim(_FrozenModel):
    claim_id: str
    text: str
    cited_citation_ids: tuple[str, ...]
    numeric_expectation: NumericExpectation | None = None

    @field_validator("claim_id", "text")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim fields must not be blank")
        return value

    @field_validator("cited_citation_ids")
    @classmethod
    def validate_citations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("claims require at least one citation")
        normalized = tuple(citation.strip() for citation in value)
        if any(not citation for citation in normalized):
            raise ValueError("citation identifiers must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("citation identifiers must be unique per claim")
        return normalized


class ClaimVerificationOutcome(_FrozenModel):
    claim_id: str
    outcome: SemanticOutcome
    decision: VerificationDecision
    citation_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


class GroundedVerificationResult(_FrozenModel):
    schema_version: str = "POI_MPP_GROUNDED_VERIFICATION_V1"
    response_hash: str
    calibration_hash: str
    decision: VerificationDecision
    outcomes: tuple[ClaimVerificationOutcome, ...]
    residual_risks: tuple[str, ...] = ()


class DevelopmentCalibrationExample(_FrozenModel):
    example_id: str
    supported_citations: int = Field(ge=0)
    total_citations: int = Field(gt=0)
    should_accept: bool

    @field_validator("example_id")
    @classmethod
    def reject_blank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("example_id must not be blank")
        return value

    @model_validator(mode="after")
    def validate_supported_count(self) -> "DevelopmentCalibrationExample":
        if self.supported_citations > self.total_citations:
            raise ValueError("supported_citations cannot exceed total_citations")
        return self

    @property
    def support_fraction(self) -> float:
        return self.supported_citations / self.total_citations


class SemanticCalibrationArtifact(_FrozenModel):
    schema_version: str = "POI_MPP_SEMANTIC_CALIBRATION_V1"
    dataset_label: str
    fitted_split: VerificationMode = VerificationMode.DEVELOPMENT
    minimum_support_fraction: float = Field(ge=0.0, le=1.0)
    example_count: int = Field(gt=0)
    content_hash: str

    @field_validator("dataset_label")
    @classmethod
    def reject_blank_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dataset_label must not be blank")
        return value

    @field_validator("content_hash")
    @classmethod
    def validate_hash_shape(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def validate_hash_binding(self) -> "SemanticCalibrationArtifact":
        expected = digest(
            "SEMANTIC_CALIBRATION",
            {
                "dataset_label": self.dataset_label,
                "fitted_split": self.fitted_split.value,
                "minimum_support_fraction": self.minimum_support_fraction,
                "example_count": self.example_count,
            },
        )
        if self.content_hash != expected:
            raise ValueError("content_hash must match canonical calibration content")
        return self

    @classmethod
    def create(
        cls,
        *,
        dataset_label: str,
        minimum_support_fraction: float,
        example_count: int,
    ) -> "SemanticCalibrationArtifact":
        material = {
            "dataset_label": dataset_label,
            "fitted_split": VerificationMode.DEVELOPMENT.value,
            "minimum_support_fraction": minimum_support_fraction,
            "example_count": example_count,
        }
        return cls(
            dataset_label=dataset_label,
            minimum_support_fraction=minimum_support_fraction,
            example_count=example_count,
            content_hash=digest("SEMANTIC_CALIBRATION", material),
        )
