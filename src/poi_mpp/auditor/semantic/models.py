"""Typed models for deterministic grounded semantic verification."""

from __future__ import annotations

from contextvars import ContextVar
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import ArtifactRecord, ArtifactStage, EvidenceOrigin, RunManifest


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BOUNDED_DECIMAL = re.compile(r"-?(0|[1-9][0-9]{0,11})(\.[0-9]{1,12})?\Z")
_TRUSTED_TERMINAL_STAGES = frozenset({ArtifactStage.FROZEN, ArtifactStage.PUBLICATION_ELIGIBLE})
_TRUSTED_EVIDENCE_ORIGINS = frozenset(
    {
        EvidenceOrigin.REAL_MODEL_EXECUTION,
        EvidenceOrigin.FOUNDRY_MEASUREMENT,
        EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    }
)
_TRUSTED_SEMANTIC_SENTINEL = object()
_trusted_semantic_binding: ContextVar[dict[str, Any] | None] = ContextVar(
    "poi_mpp_trusted_semantic_binding", default=None
)


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


class SemanticLabelAuthority(StrEnum):
    UNTRUSTED_CALLER = "UNTRUSTED_CALLER"
    TRUSTED_GROUNDED_ANNOTATOR = "TRUSTED_GROUNDED_ANNOTATOR"


class NumericComparator(StrEnum):
    EQUALS = "EQUALS"
    AT_LEAST = "AT_LEAST"
    AT_MOST = "AT_MOST"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def normalize_source_family(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("source_family must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not normalized:
        raise ValueError("source_family must not be blank")
    return normalized


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


def semantic_evidence_content_hash(
    *,
    citation_id: str,
    content: str,
    source_family: str,
) -> str:
    return digest(
        "SEMANTIC_EVIDENCE_CONTENT",
        {
            "citation_id": citation_id,
            "content": content,
            "source_family": normalize_source_family(source_family),
        },
    )


def semantic_annotation_payload_hash(
    *,
    evidence_id: str,
    citation_id: str,
    source_family: str,
    annotations: tuple["EvidenceAnnotation", ...],
    numeric_facts: tuple["NumericFact", ...],
) -> str:
    return digest(
        "TRUSTED_GROUNDED_LABEL_PAYLOAD",
        {
            "evidence_id": evidence_id,
            "citation_id": citation_id,
            "source_family": normalize_source_family(source_family),
            "annotations": [item.model_dump(mode="json") for item in annotations],
            "numeric_facts": [item.model_dump(mode="json") for item in numeric_facts],
        },
    )


def _semantic_provenance_hash(provenance: RunManifest) -> str:
    return digest("TRUSTED_GROUNDED_PROVENANCE", provenance.model_dump(mode="json"))


class EvidenceRecord(_FrozenModel):
    evidence_id: str
    citation_id: str
    source_family: str
    origin: EvidenceOrigin
    label_authority: SemanticLabelAuthority = SemanticLabelAuthority.UNTRUSTED_CALLER
    trusted_artifact_id: str | None = None
    trusted_provenance_hash: str | None = None
    trusted_annotation_hash: str | None = None
    content: str
    content_hash: str
    annotations: tuple[EvidenceAnnotation, ...] = ()
    numeric_facts: tuple[NumericFact, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def apply_trust_boundary(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if isinstance(normalized.get("source_family"), str):
            normalized["source_family"] = normalize_source_family(normalized["source_family"])
        binding = _trusted_semantic_binding.get()
        if binding is None or binding.get("capability") is not _TRUSTED_SEMANTIC_SENTINEL:
            normalized["label_authority"] = SemanticLabelAuthority.UNTRUSTED_CALLER
            normalized["trusted_artifact_id"] = None
            normalized["trusted_provenance_hash"] = None
            normalized["trusted_annotation_hash"] = None
            return normalized
        normalized["label_authority"] = SemanticLabelAuthority.TRUSTED_GROUNDED_ANNOTATOR
        normalized["trusted_artifact_id"] = binding["artifact"].artifact_id
        normalized["trusted_provenance_hash"] = _semantic_provenance_hash(binding["provenance"])
        normalized["trusted_annotation_hash"] = binding["annotation_hash"]
        return normalized

    @field_validator("evidence_id", "citation_id", "content")
    @classmethod
    def reject_blank_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence fields must not be blank")
        return value

    @field_validator("source_family")
    @classmethod
    def normalize_source_family_value(cls, value: str) -> str:
        return normalize_source_family(value)

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash_shape(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("trusted_provenance_hash", "trusted_annotation_hash")
    @classmethod
    def validate_optional_hashes(cls, value: str | None, info) -> str | None:
        if value is not None and not _SHA256.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def validate_content_hash(self) -> "EvidenceRecord":
        expected = semantic_evidence_content_hash(
            citation_id=self.citation_id,
            content=self.content,
            source_family=self.source_family,
        )
        if self.content_hash != expected:
            raise ValueError("content_hash must match canonical evidence content")
        if self.label_authority is SemanticLabelAuthority.TRUSTED_GROUNDED_ANNOTATOR:
            binding = _trusted_semantic_binding.get()
            if binding is None or binding.get("capability") is not _TRUSTED_SEMANTIC_SENTINEL:
                raise ValueError("trusted semantic labels require an internal issuance context")
            expected_annotation_hash = semantic_annotation_payload_hash(
                evidence_id=self.evidence_id,
                citation_id=self.citation_id,
                source_family=self.source_family,
                annotations=self.annotations,
                numeric_facts=self.numeric_facts,
            )
            if self.trusted_annotation_hash != expected_annotation_hash:
                raise ValueError("trusted_annotation_hash must bind the issued label payload")
            if self.trusted_artifact_id != binding["artifact"].artifact_id:
                raise ValueError("trusted_artifact_id must match the issued artifact")
            expected_provenance_hash = _semantic_provenance_hash(binding["provenance"])
            if self.trusted_provenance_hash != expected_provenance_hash:
                raise ValueError("trusted_provenance_hash must match the issued provenance")
        return self

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False) -> "EvidenceRecord":
        if not update:
            return super().model_copy(deep=deep)
        merged = self.model_dump(mode="python")
        merged.update(update)
        return type(self).model_validate(merged)


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


def _trusted_semantic_issue_binding(
    *,
    artifact: ArtifactRecord,
    provenance: RunManifest,
    evidence_id: str,
    citation_id: str,
    source_family: str,
    content: str,
    annotations: tuple[EvidenceAnnotation, ...],
    numeric_facts: tuple[NumericFact, ...],
) -> dict[str, Any]:
    normalized_source_family = normalize_source_family(source_family)
    if artifact.stage not in _TRUSTED_TERMINAL_STAGES:
        raise ValueError("trusted semantic issuance requires a terminal artifact stage")
    if artifact.origin not in _TRUSTED_EVIDENCE_ORIGINS:
        raise ValueError("trusted semantic issuance requires a non-synthetic publication evidence origin")
    if provenance.origin != artifact.origin:
        raise ValueError("trusted semantic issuance requires matching artifact/provenance origins")
    if provenance.run_id != artifact.run_id or provenance.experiment_id != artifact.experiment_id:
        raise ValueError("trusted semantic issuance requires matching artifact/provenance identity")
    expected_content_hash = semantic_evidence_content_hash(
        citation_id=citation_id,
        content=content,
        source_family=normalized_source_family,
    )
    if artifact.content_hash != expected_content_hash:
        raise ValueError("trusted semantic issuance requires artifact content_hash to match evidence content")
    annotation_hash = semantic_annotation_payload_hash(
        evidence_id=evidence_id,
        citation_id=citation_id,
        source_family=normalized_source_family,
        annotations=annotations,
        numeric_facts=numeric_facts,
    )
    if annotation_hash not in artifact.parent_hashes:
        raise ValueError("trusted semantic issuance requires artifact parent_hashes to bind the label payload")
    return {
        "capability": _TRUSTED_SEMANTIC_SENTINEL,
        "artifact": artifact,
        "provenance": provenance,
        "annotation_hash": annotation_hash,
    }


def _issue_trusted_evidence(
    *,
    artifact: ArtifactRecord,
    provenance: RunManifest,
    evidence_id: str,
    citation_id: str,
    source_family: str,
    content: str,
    annotations: tuple[EvidenceAnnotation, ...] = (),
    numeric_facts: tuple[NumericFact, ...] = (),
) -> EvidenceRecord:
    """Issue a trusted semantic record via a module-private evidence-kernel binding."""

    binding = _trusted_semantic_issue_binding(
        artifact=artifact,
        provenance=provenance,
        evidence_id=evidence_id,
        citation_id=citation_id,
        source_family=source_family,
        content=content,
        annotations=annotations,
        numeric_facts=numeric_facts,
    )
    token = _trusted_semantic_binding.set(binding)
    try:
        return EvidenceRecord(
            evidence_id=evidence_id,
            citation_id=citation_id,
            source_family=source_family,
            origin=artifact.origin,
            content=content,
            content_hash=artifact.content_hash or "",
            annotations=annotations,
            numeric_facts=numeric_facts,
        )
    finally:
        _trusted_semantic_binding.reset(token)
