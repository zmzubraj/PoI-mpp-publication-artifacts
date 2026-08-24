"""Typed models for deterministic grounded semantic verification."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum
import math
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.dataset_manifest_v2 import DatasetManifestRecordV2
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
        normalized["label_authority"] = SemanticLabelAuthority.UNTRUSTED_CALLER
        normalized["trusted_artifact_id"] = None
        normalized["trusted_provenance_hash"] = None
        normalized["trusted_annotation_hash"] = None
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
        return self

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False) -> "EvidenceRecord":
        if not update:
            return super().model_copy(deep=deep)
        merged = self.model_dump(mode="python")
        merged.update(update)
        return type(self).model_validate(merged)

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> "EvidenceRecord":
        raise TypeError("EvidenceRecord.model_construct is disabled; use model_validate")


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
SEMANTIC_CALIBRATION_ERROR_TAXONOMY_VERSION = "POI_MPP_SEMANTIC_CALIBRATION_ERROR_TAXONOMY_V1"
SEMANTIC_CALIBRATION_SELECTION_RULE_V2 = "TRI_STATE_ACCURACY_FAIL_CLOSED_V1"


class SemanticCalibrationErrorFamily(StrEnum):
    DECISION = "DECISION"
    GROUNDING = "GROUNDING"
    NUMERIC = "NUMERIC"
    AUTHORITY = "AUTHORITY"
    PROVENANCE = "PROVENANCE"
    DATASET = "DATASET"
    FREEZE_BINDING = "FREEZE_BINDING"


class SemanticCalibrationErrorCode(StrEnum):
    CORRECT_ACCEPT = "CORRECT_ACCEPT"
    CORRECT_REJECT = "CORRECT_REJECT"
    FALSE_ACCEPT = "FALSE_ACCEPT"
    FALSE_REJECT = "FALSE_REJECT"
    CORRECT_ABSTAIN = "CORRECT_ABSTAIN"
    INCORRECT_ABSTAIN = "INCORRECT_ABSTAIN"
    OUTCOME_MISMATCH = "OUTCOME_MISMATCH"
    CITATION_ERROR = "CITATION_ERROR"
    CONTRADICTION_MISS = "CONTRADICTION_MISS"
    NUMERIC_CHECK_FAILURE = "NUMERIC_CHECK_FAILURE"
    AUTHORITY_SCOPE_FAILURE = "AUTHORITY_SCOPE_FAILURE"
    PROVENANCE_FAILURE = "PROVENANCE_FAILURE"
    DATASET_LEAKAGE = "DATASET_LEAKAGE"
    FREEZE_BINDING_FAILURE = "FREEZE_BINDING_FAILURE"


_ERROR_FAMILY_BY_CODE = {
    SemanticCalibrationErrorCode.CORRECT_ACCEPT: SemanticCalibrationErrorFamily.DECISION,
    SemanticCalibrationErrorCode.CORRECT_REJECT: SemanticCalibrationErrorFamily.DECISION,
    SemanticCalibrationErrorCode.FALSE_ACCEPT: SemanticCalibrationErrorFamily.DECISION,
    SemanticCalibrationErrorCode.FALSE_REJECT: SemanticCalibrationErrorFamily.DECISION,
    SemanticCalibrationErrorCode.CORRECT_ABSTAIN: SemanticCalibrationErrorFamily.DECISION,
    SemanticCalibrationErrorCode.INCORRECT_ABSTAIN: SemanticCalibrationErrorFamily.DECISION,
    SemanticCalibrationErrorCode.OUTCOME_MISMATCH: SemanticCalibrationErrorFamily.DECISION,
    SemanticCalibrationErrorCode.CITATION_ERROR: SemanticCalibrationErrorFamily.GROUNDING,
    SemanticCalibrationErrorCode.CONTRADICTION_MISS: SemanticCalibrationErrorFamily.GROUNDING,
    SemanticCalibrationErrorCode.NUMERIC_CHECK_FAILURE: SemanticCalibrationErrorFamily.NUMERIC,
    SemanticCalibrationErrorCode.AUTHORITY_SCOPE_FAILURE: SemanticCalibrationErrorFamily.AUTHORITY,
    SemanticCalibrationErrorCode.PROVENANCE_FAILURE: SemanticCalibrationErrorFamily.PROVENANCE,
    SemanticCalibrationErrorCode.DATASET_LEAKAGE: SemanticCalibrationErrorFamily.DATASET,
    SemanticCalibrationErrorCode.FREEZE_BINDING_FAILURE: SemanticCalibrationErrorFamily.FREEZE_BINDING,
}


def semantic_calibration_taxonomy_hash(
    version: str = SEMANTIC_CALIBRATION_ERROR_TAXONOMY_VERSION,
) -> str:
    return digest(
        "SEMANTIC_CALIBRATION_ERROR_TAXONOMY",
        {
            "version": version,
            "codes": [
                {"code": code.value, "family": family.value}
                for code, family in sorted(_ERROR_FAMILY_BY_CODE.items(), key=lambda item: item[0].value)
            ],
        },
    )


def development_calibration_record_binding_hash(
    record: DatasetManifestRecordV2,
) -> str:
    return digest(
        "DEVELOPMENT_CALIBRATION_DATASET_RECORD_BINDING_V1",
        {
            "record_id": record.record_id,
            "item_hash": record.item_hash,
            "label_hash": record.label_hash,
            "content_hash": record.content_hash,
            "deduplication_group": record.deduplication_group,
            "subgroup": record.subgroup,
            "difficulty": record.difficulty,
            "error_family": record.error_family,
            "annotation_hash": record.annotation.annotation_hash,
            "expected_decision": record.expected_decision.value,
            "evidence_origin": record.evidence_origin.value,
        },
    )


def _normalize_nonblank_token(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value.strip()


def _normalize_probability(value: float | int, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be a finite real number")
    if normalized < 0.0 or normalized > 1.0:
        raise ValueError(f"{field_name} must lie within [0, 1]")
    return normalized


def _validate_sha256(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


class DevelopmentCalibrationObservationV2(_FrozenModel):
    record_id: str
    expected_decision: VerificationDecision
    observed_decision: VerificationDecision
    support_fraction: float
    calibrated_confidence: float
    error_code: SemanticCalibrationErrorCode
    error_family: SemanticCalibrationErrorFamily
    attack_family: str = "BASELINE"
    subgroup: str
    difficulty: str
    origin: EvidenceOrigin | None = None
    dataset_record_binding_hash: str | None = None

    @field_validator("record_id", "attack_family", "subgroup", "difficulty")
    @classmethod
    def reject_blank_tokens(cls, value: str, info) -> str:
        return _normalize_nonblank_token(value, field_name=info.field_name)

    @field_validator("dataset_record_binding_hash", mode="before")
    @classmethod
    def validate_optional_record_binding_hash(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        return _validate_sha256(value, field_name="dataset_record_binding_hash")

    @field_validator("support_fraction", "calibrated_confidence", mode="before")
    @classmethod
    def normalize_probabilities(cls, value: float | int, info) -> float:
        return _normalize_probability(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_taxonomy_binding(self) -> "DevelopmentCalibrationObservationV2":
        expected_family = _ERROR_FAMILY_BY_CODE[self.error_code]
        if self.error_family is not expected_family:
            raise ValueError("error_family does not match the canonical taxonomy")
        decision_bindings = {
            SemanticCalibrationErrorCode.CORRECT_ACCEPT: (
                VerificationDecision.ACCEPT,
                VerificationDecision.ACCEPT,
            ),
            SemanticCalibrationErrorCode.CORRECT_REJECT: (
                VerificationDecision.REJECT,
                VerificationDecision.REJECT,
            ),
            SemanticCalibrationErrorCode.FALSE_REJECT: (
                VerificationDecision.ACCEPT,
                VerificationDecision.REJECT,
            ),
            SemanticCalibrationErrorCode.CORRECT_ABSTAIN: (
                VerificationDecision.ABSTAIN,
                VerificationDecision.ABSTAIN,
            ),
        }
        exact_binding = decision_bindings.get(self.error_code)
        if exact_binding is not None and (
            self.expected_decision,
            self.observed_decision,
        ) != exact_binding:
            raise ValueError("error_code is inconsistent with expected and observed decisions")
        if self.error_code is SemanticCalibrationErrorCode.FALSE_ACCEPT and not (
            self.observed_decision is VerificationDecision.ACCEPT
            and self.expected_decision is not VerificationDecision.ACCEPT
        ):
            raise ValueError("error_code is inconsistent with expected and observed decisions")
        if self.error_code is SemanticCalibrationErrorCode.INCORRECT_ABSTAIN and not (
            self.observed_decision is VerificationDecision.ABSTAIN
            and self.expected_decision is not VerificationDecision.ABSTAIN
        ):
            raise ValueError("error_code is inconsistent with expected and observed decisions")
        return self

    def canonical_sort_key(self) -> tuple[str, ...]:
        return (
            self.record_id,
            self.expected_decision.value,
            self.observed_decision.value,
            self.error_code.value,
            self.error_family.value,
            self.attack_family,
            self.subgroup,
            self.difficulty,
            "" if self.origin is None else self.origin.value,
            "" if self.dataset_record_binding_hash is None else self.dataset_record_binding_hash,
        )


class CalibrationErrorLedgerV1(_FrozenModel):
    schema_version: str = "POI_MPP_SEMANTIC_CALIBRATION_ERROR_LEDGER_V1"
    dataset_manifest_hash: str
    taxonomy_version: str = SEMANTIC_CALIBRATION_ERROR_TAXONOMY_VERSION
    taxonomy_hash: str | None = None
    rows: tuple[DevelopmentCalibrationObservationV2, ...]
    content_hash: str | None = None

    @field_validator("dataset_manifest_hash", mode="before")
    @classmethod
    def validate_dataset_manifest_hash(cls, value: str) -> str:
        return _validate_sha256(value, field_name="dataset_manifest_hash")

    @field_validator("taxonomy_version")
    @classmethod
    def validate_taxonomy_version(cls, value: str) -> str:
        if value != SEMANTIC_CALIBRATION_ERROR_TAXONOMY_VERSION:
            raise ValueError("taxonomy_version must match the canonical V1 taxonomy")
        return value

    @field_validator("taxonomy_hash", "content_hash", mode="before")
    @classmethod
    def validate_optional_hashes(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _validate_sha256(value, field_name=info.field_name)

    @field_validator("rows", mode="before")
    @classmethod
    def normalize_rows(
        cls,
        value: tuple[DevelopmentCalibrationObservationV2, ...] | list[DevelopmentCalibrationObservationV2],
    ) -> tuple[DevelopmentCalibrationObservationV2, ...]:
        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError("rows must be a non-empty sequence")
        normalized = []
        for item in value:
            normalized.append(
                item
                if isinstance(item, DevelopmentCalibrationObservationV2)
                else DevelopmentCalibrationObservationV2.model_validate(item)
            )
        record_ids = [row.record_id for row in normalized]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("duplicate record_id in calibration error ledger")
        return tuple(sorted(normalized, key=lambda row: row.canonical_sort_key()))

    @model_validator(mode="after")
    def bind_hashes(self) -> "CalibrationErrorLedgerV1":
        expected_taxonomy_hash = semantic_calibration_taxonomy_hash(self.taxonomy_version)
        if self.taxonomy_hash is None:
            object.__setattr__(self, "taxonomy_hash", expected_taxonomy_hash)
        elif self.taxonomy_hash != expected_taxonomy_hash:
            raise ValueError("taxonomy_hash must match the canonical taxonomy content")

        expected_content_hash = digest(
            "SEMANTIC_CALIBRATION_ERROR_LEDGER",
            {
                "dataset_manifest_hash": self.dataset_manifest_hash,
                "taxonomy_version": self.taxonomy_version,
                "taxonomy_hash": expected_taxonomy_hash,
                "rows": [row.model_dump(mode="json") for row in self.rows],
            },
        )
        if self.content_hash is None:
            object.__setattr__(self, "content_hash", expected_content_hash)
        elif self.content_hash != expected_content_hash:
            raise ValueError("content_hash must match canonical calibration ledger content")
        return self


class CalibrationLeakageStatus(StrEnum):
    NOT_YET_ASSESSABLE = "NOT_YET_ASSESSABLE"
    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"


class CalibrationLeakageReportV1(_FrozenModel):
    schema_version: str = "POI_MPP_SEMANTIC_CALIBRATION_LEAKAGE_REPORT_V1"
    development_manifest_hash: str
    confirmatory_manifest_hash: str | None = None
    record_overlap_count: int = Field(ge=0)
    content_overlap_count: int = Field(ge=0)
    item_overlap_count: int = Field(ge=0)
    label_overlap_count: int = Field(ge=0)
    dedup_overlap_count: int = Field(ge=0)
    source_overlap_count: int = Field(ge=0)
    source_family_overlap_count: int = Field(ge=0)
    near_duplicate_overlap_count: int = Field(ge=0)
    status: CalibrationLeakageStatus
    content_hash: str | None = None

    @field_validator("development_manifest_hash", "confirmatory_manifest_hash", mode="before")
    @classmethod
    def validate_hash_bindings(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _validate_sha256(value, field_name=info.field_name)

    @field_validator("content_hash", mode="before")
    @classmethod
    def validate_content_hash_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_sha256(value, field_name="content_hash")

    @model_validator(mode="after")
    def validate_status_contract(self) -> "CalibrationLeakageReportV1":
        overlap_counts = (
            self.record_overlap_count,
            self.content_overlap_count,
            self.item_overlap_count,
            self.label_overlap_count,
            self.dedup_overlap_count,
            self.source_overlap_count,
            self.source_family_overlap_count,
            self.near_duplicate_overlap_count,
        )
        total_overlap = sum(overlap_counts)
        if self.status is CalibrationLeakageStatus.CLEAR:
            if self.confirmatory_manifest_hash is None:
                raise ValueError("CLEAR leakage status requires a confirmatory manifest hash")
            if total_overlap != 0:
                raise ValueError("CLEAR leakage status requires zero overlap counts")
        if (
            self.confirmatory_manifest_hash is not None
            and self.status is CalibrationLeakageStatus.NOT_YET_ASSESSABLE
        ):
            raise ValueError("confirmatory leakage assessment cannot remain NOT_YET_ASSESSABLE")
        if self.status is CalibrationLeakageStatus.BLOCKED and total_overlap == 0:
            raise ValueError("BLOCKED leakage status requires a concrete overlap or unresolved leak")

        expected = digest(
            "SEMANTIC_CALIBRATION_LEAKAGE_REPORT",
            {
                "development_manifest_hash": self.development_manifest_hash,
                "confirmatory_manifest_hash": self.confirmatory_manifest_hash,
                "record_overlap_count": self.record_overlap_count,
                "content_overlap_count": self.content_overlap_count,
                "item_overlap_count": self.item_overlap_count,
                "label_overlap_count": self.label_overlap_count,
                "dedup_overlap_count": self.dedup_overlap_count,
                "source_overlap_count": self.source_overlap_count,
                "source_family_overlap_count": self.source_family_overlap_count,
                "near_duplicate_overlap_count": self.near_duplicate_overlap_count,
                "status": self.status.value,
            },
        )
        if self.content_hash is None:
            object.__setattr__(self, "content_hash", expected)
        elif self.content_hash != expected:
            raise ValueError("content_hash must match canonical leakage report content")
        return self


class SemanticCalibrationFreezeStatus(StrEnum):
    READY_FOR_DATA = "READY_FOR_DATA"
    FROZEN_DEVELOPMENT_ONLY = "FROZEN_DEVELOPMENT_ONLY"
    BLOCKED = "BLOCKED"


class SemanticCalibrationFreezeV2(_FrozenModel):
    schema_version: str = "POI_MPP_SEMANTIC_CALIBRATION_FREEZE_V2"
    status: SemanticCalibrationFreezeStatus
    development_dataset_manifest_hash: str
    claim_spec_hash: str
    prompt_template_hash: str
    model_manifest_hash: str
    runtime_environment_hash: str
    output_schema_hash: str
    contradiction_policy_hash: str
    error_recovery_policy_hash: str
    accept_example_count: int = Field(ge=0)
    reject_example_count: int = Field(ge=0)
    abstain_example_count: int = Field(ge=0)
    error_taxonomy_version: str
    error_taxonomy_hash: str
    support_threshold: float
    reject_threshold: float
    minimum_calibrated_confidence: float
    selection_rule_id: str
    example_count: int = Field(ge=0)
    error_ledger_hash: str
    leakage_report_hash: str
    content_hash: str | None = None

    @field_validator(
        "development_dataset_manifest_hash",
        "claim_spec_hash",
        "prompt_template_hash",
        "model_manifest_hash",
        "runtime_environment_hash",
        "output_schema_hash",
        "contradiction_policy_hash",
        "error_recovery_policy_hash",
        "error_taxonomy_hash",
        "error_ledger_hash",
        "leakage_report_hash",
        "content_hash",
        mode="before",
    )
    @classmethod
    def validate_hash_fields(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _validate_sha256(value, field_name=info.field_name)

    @field_validator("error_taxonomy_version")
    @classmethod
    def validate_error_taxonomy_version(cls, value: str) -> str:
        if value != SEMANTIC_CALIBRATION_ERROR_TAXONOMY_VERSION:
            raise ValueError("error_taxonomy_version must match the canonical V1 taxonomy")
        return value

    @field_validator("selection_rule_id")
    @classmethod
    def validate_selection_rule_id(cls, value: str) -> str:
        normalized = _normalize_nonblank_token(value, field_name="selection_rule_id")
        if normalized != SEMANTIC_CALIBRATION_SELECTION_RULE_V2:
            raise ValueError(
                "selection_rule_id must equal the canonical calibration selection rule"
            )
        return normalized

    @field_validator(
        "support_threshold",
        "reject_threshold",
        "minimum_calibrated_confidence",
        mode="before",
    )
    @classmethod
    def validate_probabilities(cls, value: float | int, info) -> float:
        return _normalize_probability(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_freeze_contract(self) -> "SemanticCalibrationFreezeV2":
        expected_taxonomy_hash = semantic_calibration_taxonomy_hash(self.error_taxonomy_version)
        if self.error_taxonomy_hash != expected_taxonomy_hash:
            raise ValueError("error_taxonomy_hash must match the canonical taxonomy content")
        if self.reject_threshold > self.support_threshold:
            raise ValueError("reject_threshold must not exceed support_threshold")
        if self.status is SemanticCalibrationFreezeStatus.FROZEN_DEVELOPMENT_ONLY:
            if self.example_count < 120 or self.example_count > 150:
                raise ValueError("frozen development calibration requires 120-150 examples")
            if self.accept_example_count != 50:
                raise ValueError("frozen development calibration requires exactly 50 ACCEPT examples")
            if self.reject_example_count != 50:
                raise ValueError("frozen development calibration requires exactly 50 REJECT examples")
            if self.abstain_example_count < 20 or self.abstain_example_count > 50:
                raise ValueError("frozen development calibration requires 20-50 ABSTAIN examples")
            if (
                self.accept_example_count
                + self.reject_example_count
                + self.abstain_example_count
            ) != self.example_count:
                raise ValueError("example_count must equal the frozen calibration composition total")

        expected = digest(
            "SEMANTIC_CALIBRATION_FREEZE_V2",
            {
                "status": self.status.value,
                "development_dataset_manifest_hash": self.development_dataset_manifest_hash,
                "claim_spec_hash": self.claim_spec_hash,
                "prompt_template_hash": self.prompt_template_hash,
                "model_manifest_hash": self.model_manifest_hash,
                "runtime_environment_hash": self.runtime_environment_hash,
                "output_schema_hash": self.output_schema_hash,
                "contradiction_policy_hash": self.contradiction_policy_hash,
                "error_recovery_policy_hash": self.error_recovery_policy_hash,
                "accept_example_count": self.accept_example_count,
                "reject_example_count": self.reject_example_count,
                "abstain_example_count": self.abstain_example_count,
                "error_taxonomy_version": self.error_taxonomy_version,
                "error_taxonomy_hash": self.error_taxonomy_hash,
                "support_threshold": self.support_threshold,
                "reject_threshold": self.reject_threshold,
                "minimum_calibrated_confidence": self.minimum_calibrated_confidence,
                "selection_rule_id": self.selection_rule_id,
                "example_count": self.example_count,
                "error_ledger_hash": self.error_ledger_hash,
                "leakage_report_hash": self.leakage_report_hash,
            },
        )
        if self.content_hash is None:
            object.__setattr__(self, "content_hash", expected)
        elif self.content_hash != expected:
            raise ValueError("content_hash must match canonical calibration freeze content")
        return self


class DevelopmentCalibrationFitResultV2(_FrozenModel):
    freeze: SemanticCalibrationFreezeV2
    error_ledger: CalibrationErrorLedgerV1
    leakage_report: CalibrationLeakageReportV1
    exact_accuracy: float = Field(ge=0.0, le=1.0)
    false_accept_rate: float = Field(ge=0.0, le=1.0)
    false_reject_rate: float = Field(ge=0.0, le=1.0)
    coverage: float = Field(ge=0.0, le=1.0)


class DevelopmentCalibrationThresholdSelectionV2(_FrozenModel):
    """Mechanics-only threshold selection with no publication-freeze authority."""

    support_threshold: float = Field(ge=0.0, le=1.0)
    reject_threshold: float = Field(ge=0.0, le=1.0)
    minimum_calibrated_confidence: float = Field(ge=0.0, le=1.0)
    exact_accuracy: float = Field(ge=0.0, le=1.0)
    false_accept_rate: float = Field(ge=0.0, le=1.0)
    false_reject_rate: float = Field(ge=0.0, le=1.0)
    coverage: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "DevelopmentCalibrationThresholdSelectionV2":
        if self.reject_threshold > self.support_threshold:
            raise ValueError("reject_threshold must not exceed support_threshold")
        return self
