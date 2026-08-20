"""E3 confirmatory semantic-evaluation harness with fail-closed authority checks."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.auditor.semantic.models import SemanticCalibrationArtifact, SemanticOutcome, VerificationDecision
from poi_mpp.datasets.manifests import DatasetManifest, DatasetSplit, assert_confirmatory_isolation
from poi_mpp.evidence import EvidenceOrigin, ProvenanceBundle, RunConfig
from poi_mpp.reporting.e3 import E3MetricPolicy, E3Summary, semantic_metrics


PUBLICATION_EVIDENCE_AUTHORIZED = "PUBLICATION_EVIDENCE_AUTHORIZED"
E3_CONFIRMATORY_SCOPE = "E3_CONFIRMATORY_PUBLICATION_V1"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ErrorClass(StrEnum):
    FALSE_ACCEPT = "FALSE_ACCEPT"
    FALSE_REJECT = "FALSE_REJECT"
    ABSTAIN = "ABSTAIN"
    OUTCOME_MISMATCH = "OUTCOME_MISMATCH"


class PublicationEligibilityError(ValueError):
    """Raised when a confirmatory E3 run lacks publication authority."""

    def __init__(self, reasons: Sequence[str]):
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__("; ".join(self.reasons) if self.reasons else "publication eligibility failed")


class E3SemanticRow(_FrozenModel):
    schema_version: str = "POI_MPP_E3_ROW_V1"
    run_id: str
    experiment_id: str
    case_id: str
    split: DatasetSplit
    origin: EvidenceOrigin
    frozen_reference_valid: bool
    frozen_reference_outcome: SemanticOutcome
    verifier_decision: VerificationDecision
    verifier_outcome: SemanticOutcome | None = None
    abstained: bool
    subgroup: str
    verifier_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    calibration_hash: str
    source_record_id: str
    source_content_hash: str
    source_origin: EvidenceOrigin
    annotation_record_id: str
    annotation_hash: str
    annotation_origin: EvidenceOrigin
    evaluator_id: str
    evaluator_hash: str
    evaluator_origin: EvidenceOrigin
    evaluator_independence_basis: str

    @field_validator(
        "run_id",
        "experiment_id",
        "case_id",
        "subgroup",
        "source_record_id",
        "annotation_record_id",
        "evaluator_id",
        "evaluator_independence_basis",
    )
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("E3 text fields must not be blank")
        return value

    @field_validator(
        "calibration_hash",
        "source_content_hash",
        "annotation_hash",
        "evaluator_hash",
    )
    @classmethod
    def require_hash_shape(cls, value: str) -> str:
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("E3 hash fields must be lowercase SHA-256 hex digests")
        return value

    @model_validator(mode="after")
    def validate_decision_contract(self) -> "E3SemanticRow":
        if self.abstained != (self.verifier_decision is VerificationDecision.ABSTAIN):
            raise ValueError("abstained must equal whether verifier_decision is ABSTAIN")
        if self.verifier_decision is VerificationDecision.ABSTAIN:
            if self.verifier_outcome is not None:
                raise ValueError("abstained rows cannot carry verifier_outcome")
            if self.verifier_confidence is not None:
                raise ValueError("abstained rows cannot carry verifier_confidence")
        else:
            if self.verifier_outcome is None:
                raise ValueError("non-abstained rows require verifier_outcome")
            if self.verifier_confidence is None:
                raise ValueError("non-abstained rows require verifier_confidence")
        return self


class E3EvaluatorAuthority(_FrozenModel):
    evaluator_id: str
    evaluator_hash: str
    origin: EvidenceOrigin
    independence_basis: str
    verified: bool

    @field_validator("evaluator_id", "independence_basis")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evaluator authority fields must not be blank")
        return value

    @field_validator("evaluator_hash")
    @classmethod
    def require_hash_shape(cls, value: str) -> str:
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("evaluator_hash must be a lowercase SHA-256 hex digest")
        return value


class E3DevelopmentDataset(_FrozenModel):
    dataset_id: str
    manifest: DatasetManifest
    calibration: SemanticCalibrationArtifact

    @field_validator("dataset_id")
    @classmethod
    def require_nonblank_dataset_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dataset_id must not be blank")
        return value


class E3ConfirmatoryDataset(_FrozenModel):
    dataset_id: str
    origin: EvidenceOrigin
    manifest: DatasetManifest
    license_id: str | None = None
    privacy_status: str | None = None
    annotation_protocol_id: str | None = None

    @field_validator("dataset_id", "license_id", "privacy_status", "annotation_protocol_id")
    @classmethod
    def reject_blank_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional dataset metadata must not be blank when supplied")
        return value


class E3AnnotationProvenance(_FrozenModel):
    source_record_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    source_origins: tuple[EvidenceOrigin, ...]
    annotation_record_ids: tuple[str, ...]
    annotation_hashes: tuple[str, ...]
    annotation_origins: tuple[EvidenceOrigin, ...]
    evaluator_ids: tuple[str, ...]
    evaluator_hashes: tuple[str, ...]
    evaluator_origins: tuple[EvidenceOrigin, ...]
    evaluator_independence_bases: tuple[str, ...]


class E3ErrorLedgerEntry(_FrozenModel):
    case_id: str
    subgroup: str
    error_class: ErrorClass
    frozen_reference_valid: bool
    frozen_reference_outcome: SemanticOutcome
    verifier_decision: VerificationDecision
    verifier_outcome: SemanticOutcome | None = None

    @field_validator("case_id", "subgroup")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("error ledger fields must not be blank")
        return value


class E3ConfirmatoryConfig(_FrozenModel):
    run_config: RunConfig
    publication_scope: str
    development_dataset: E3DevelopmentDataset
    dataset: E3ConfirmatoryDataset
    evaluators: tuple[E3EvaluatorAuthority, ...]
    policy: E3MetricPolicy = E3MetricPolicy()
    provenance_bundle: ProvenanceBundle | None = None

    @field_validator("publication_scope")
    @classmethod
    def require_nonblank_publication_scope(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("publication_scope must not be blank")
        return value

    @model_validator(mode="after")
    def validate_static_contract(self) -> "E3ConfirmatoryConfig":
        if self.run_config.experiment_id != "E3":
            raise ValueError("run_config.experiment_id must equal E3")
        if self.development_dataset.calibration.fitted_split.value != "DEVELOPMENT":
            raise ValueError("calibration must be fitted on the DEVELOPMENT split")
        return self


class E3ConfirmatoryResult(_FrozenModel):
    summary: E3Summary
    annotation_provenance: E3AnnotationProvenance
    error_ledger: tuple[E3ErrorLedgerEntry, ...]


def _annotation_provenance(rows: Sequence[E3SemanticRow]) -> E3AnnotationProvenance:
    return E3AnnotationProvenance(
        source_record_ids=tuple(sorted({row.source_record_id for row in rows})),
        source_hashes=tuple(sorted({row.source_content_hash for row in rows})),
        source_origins=tuple(sorted({row.source_origin for row in rows}, key=lambda item: item.value)),
        annotation_record_ids=tuple(sorted({row.annotation_record_id for row in rows})),
        annotation_hashes=tuple(sorted({row.annotation_hash for row in rows})),
        annotation_origins=tuple(sorted({row.annotation_origin for row in rows}, key=lambda item: item.value)),
        evaluator_ids=tuple(sorted({row.evaluator_id for row in rows})),
        evaluator_hashes=tuple(sorted({row.evaluator_hash for row in rows})),
        evaluator_origins=tuple(sorted({row.evaluator_origin for row in rows}, key=lambda item: item.value)),
        evaluator_independence_bases=tuple(sorted({row.evaluator_independence_basis for row in rows})),
    )


def _error_ledger(rows: Sequence[E3SemanticRow]) -> tuple[E3ErrorLedgerEntry, ...]:
    entries: list[E3ErrorLedgerEntry] = []
    for row in rows:
        if row.verifier_decision is VerificationDecision.ABSTAIN:
            error_class = ErrorClass.ABSTAIN
        elif row.verifier_decision is VerificationDecision.ACCEPT and not row.frozen_reference_valid:
            error_class = ErrorClass.FALSE_ACCEPT
        elif row.verifier_decision is VerificationDecision.REJECT and row.frozen_reference_valid:
            error_class = ErrorClass.FALSE_REJECT
        elif row.verifier_outcome != row.frozen_reference_outcome:
            error_class = ErrorClass.OUTCOME_MISMATCH
        else:
            continue
        entries.append(
            E3ErrorLedgerEntry(
                case_id=row.case_id,
                subgroup=row.subgroup,
                error_class=error_class,
                frozen_reference_valid=row.frozen_reference_valid,
                frozen_reference_outcome=row.frozen_reference_outcome,
                verifier_decision=row.verifier_decision,
                verifier_outcome=row.verifier_outcome,
            )
        )
    return tuple(entries)


def _publication_reasons(
    *,
    config: E3ConfirmatoryConfig,
    rows: Sequence[E3SemanticRow],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if config.run_config.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        reasons.append(
            f"run_config.authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
        )
    if config.publication_scope != E3_CONFIRMATORY_SCOPE:
        reasons.append(
            f"publication_scope must equal {E3_CONFIRMATORY_SCOPE}"
        )
    if config.dataset.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
        reasons.append("synthetic non-evidence cannot run the E3 confirmatory publication path")
    if config.dataset.manifest.split is not DatasetSplit.CONFIRMATORY:
        reasons.append("confirmatory dataset manifest must use the CONFIRMATORY split")
    if config.development_dataset.manifest.split is not DatasetSplit.DEVELOPMENT:
        reasons.append("development dataset manifest must use the DEVELOPMENT split")
    try:
        assert_confirmatory_isolation(
            config.development_dataset.manifest,
            config.dataset.manifest,
        )
    except ValueError as error:
        reasons.append(str(error))
    if config.dataset.license_id is None:
        reasons.append("frozen confirmatory dataset manifest requires a non-synthetic license_id")
    if config.dataset.privacy_status is None:
        reasons.append("frozen confirmatory dataset manifest requires privacy_status")
    if config.dataset.annotation_protocol_id is None:
        reasons.append("frozen confirmatory dataset manifest requires annotation_protocol_id")
    if not config.evaluators:
        reasons.append("verified evaluator identities are required")
    else:
        allowed_evaluator_ids = {evaluator.evaluator_id for evaluator in config.evaluators if evaluator.verified}
        if not allowed_evaluator_ids:
            reasons.append("verified evaluator identities are required")
        for evaluator in config.evaluators:
            if not evaluator.verified:
                reasons.append(f"evaluator {evaluator.evaluator_id} is not independently verified")
            if evaluator.independence_basis.strip() == "":
                reasons.append(f"evaluator {evaluator.evaluator_id} is missing independence_basis")
        for row in rows:
            if row.evaluator_id not in allowed_evaluator_ids:
                reasons.append(f"row {row.case_id} evaluator_id is not in the verified evaluator registry")
    if config.provenance_bundle is None:
        reasons.append("frozen config and verified provenance bundle are required")
    else:
        if config.provenance_bundle.config.model_dump(mode="json") != config.run_config.model_dump(mode="json"):
            reasons.append("provenance bundle config must exactly match run_config")
        if config.provenance_bundle.manifest.run_id != config.run_config.run_id:
            reasons.append("provenance manifest run_id must equal run_config.run_id")
        if config.provenance_bundle.manifest.experiment_id != config.run_config.experiment_id:
            reasons.append("provenance manifest experiment_id must equal run_config.experiment_id")
        if config.provenance_bundle.manifest.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
            reasons.append(
                f"provenance manifest authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
            )
    if not rows:
        reasons.append("confirmatory semantic rows are required")
    expected_evaluator_ids = {evaluator.evaluator_id for evaluator in config.evaluators}
    for row in rows:
        if row.split is not DatasetSplit.CONFIRMATORY:
            reasons.append(f"row {row.case_id} must use the CONFIRMATORY split")
        if row.origin is not config.dataset.origin:
            reasons.append(f"row {row.case_id} origin must equal config.dataset.origin")
        if row.calibration_hash != config.development_dataset.calibration.content_hash:
            reasons.append(f"row {row.case_id} calibration_hash must equal the frozen development calibration")
        if row.evaluator_id not in expected_evaluator_ids:
            reasons.append(f"row {row.case_id} evaluator_id is unknown to the confirmatory config")
        if row.annotation_origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
            reasons.append(f"row {row.case_id} annotation provenance is synthetic")
        if row.source_origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
            reasons.append(f"row {row.case_id} source provenance is synthetic")
    return tuple(dict.fromkeys(reasons))


def run_confirmatory_semantic(
    *,
    config: E3ConfirmatoryConfig,
    rows: Sequence[E3SemanticRow] | Sequence[object],
) -> E3ConfirmatoryResult:
    canonical_rows = tuple(E3SemanticRow.model_validate(row) for row in rows)
    reasons = _publication_reasons(config=config, rows=canonical_rows)
    if reasons:
        raise PublicationEligibilityError(reasons)
    return E3ConfirmatoryResult(
        summary=semantic_metrics(canonical_rows, policy=config.policy),
        annotation_provenance=_annotation_provenance(canonical_rows),
        error_ledger=_error_ledger(canonical_rows),
    )
