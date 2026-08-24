"""E3 semantic evaluation with strict manifest closure and fail-closed authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
import hashlib
import inspect
from pathlib import Path
from typing import Literal
import weakref

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import yaml

from poi_mpp.auditor.semantic.models import SemanticCalibrationArtifact, SemanticOutcome, VerificationDecision
from poi_mpp.datasets.manifests import DatasetManifest, DatasetRecord, DatasetSplit, assert_confirmatory_isolation
from poi_mpp.evidence import ArtifactStage, EvidenceOrigin, ProvenanceBundle, RunConfig, provenance_bundle_from_json
from poi_mpp.evidence.validation import ArtifactValidationError
from poi_mpp.reporting.e3 import E3MetricPolicy, E3Summary, semantic_metrics


PUBLICATION_EVIDENCE_AUTHORIZED = "PUBLICATION_EVIDENCE_AUTHORIZED"
E3_CONFIRMATORY_SCOPE = "E3_CONFIRMATORY_PUBLICATION_V1"
WAITING_EXTERNAL_EVALUATOR_AUTHORITY = "WAITING_EXTERNAL_EVALUATOR_AUTHORITY"
_PLUMBING_INDEPENDENCE_BASIS = "SYNTHETIC_NON_EVIDENCE_PLUMBING_ONLY"
E3_CLAIM_ID = "C3"
E3_TASK_CLASS = "GROUNDED_SEMANTIC_ASSURANCE"
E3_METRIC_SCOPE = ("ABSTAIN", "FAR", "FRR", "calibration", "coverage")
E3_ARTIFACT_SCOPE = ("F7", "RAW_E3_EXECUTION", "T4", "T8")
_CANONICAL_AUTHORITY_VERIFIER = (
    Path(__file__).resolve().parents[3] / "scripts" / "verify_e3_authority.py"
)


def _authority_grant_contract():
    issued: weakref.WeakSet[VerifiedE3AuthorityGrant] = weakref.WeakSet()

    class VerifiedE3AuthorityGrant:
        """Process-local capability emitted after canonical external verification.

        The constructor guard is defense in depth against accidental/lookalike
        grants, not a hostile same-process Python security boundary. Detached
        SSH verification in ``scripts/verify_e3_authority.py`` is the trust
        boundary used by the production CLI.
        """

        __slots__ = (
            "_experiment_id",
            "_claim_id",
            "_task_class",
            "_evidence_origin",
            "_metric_scope",
            "_artifact_scope",
            "_privacy_scope",
            "_request_scope_digest",
            "_authority_record_sha256",
            "_decision",
            "_authority_identity",
            "_request_manifest_sha256",
            "_request_manifest_self_digest",
            "_result_attestation_status",
            "_locked",
            "__weakref__",
        )

        def __init__(
            self,
            *,
            experiment_id: str,
            claim_id: str,
            task_class: str,
            evidence_origin: str,
            metric_scope: Sequence[str],
            artifact_scope: Sequence[str],
            privacy_scope: str,
            request_scope_digest: str,
            authority_record_sha256: str,
            decision: str,
            authority_identity: str,
            request_manifest_sha256: str = "",
            request_manifest_self_digest: str = "",
            result_attestation_status: str = "",
            _verification_transcript: object | None = None,
        ) -> None:
            caller = inspect.currentframe().f_back
            caller_locals = caller.f_locals if caller is not None else {}
            completed = caller_locals.get("completed")
            transcript_bytes = getattr(_verification_transcript, "record_bytes", None)
            canonical_call = (
                caller is not None
                and caller.f_code.co_name == "verify_authority"
                and Path(caller.f_code.co_filename).resolve() == _CANONICAL_AUTHORITY_VERIFIER
                and caller_locals.get("verification_transcript") is _verification_transcript
                and getattr(completed, "returncode", None) == 0
                and isinstance(transcript_bytes, bytes)
                and transcript_bytes == caller_locals.get("record_bytes")
                and hashlib.sha256(transcript_bytes).hexdigest() == authority_record_sha256
            )
            if not canonical_call:
                raise TypeError(
                    "VerifiedE3AuthorityGrant: only verify_authority may produce a verified grant"
                )
            values = {
                "_experiment_id": experiment_id,
                "_claim_id": claim_id,
                "_task_class": task_class,
                "_evidence_origin": evidence_origin,
                "_metric_scope": tuple(metric_scope),
                "_artifact_scope": tuple(artifact_scope),
                "_privacy_scope": privacy_scope,
                "_request_scope_digest": request_scope_digest,
                "_authority_record_sha256": authority_record_sha256,
                "_decision": decision,
                "_authority_identity": authority_identity,
                "_request_manifest_sha256": request_manifest_sha256,
                "_request_manifest_self_digest": request_manifest_self_digest,
                "_result_attestation_status": result_attestation_status,
                "_locked": True,
            }
            for name, value in values.items():
                object.__setattr__(self, name, value)
            issued.add(self)

        def __setattr__(self, name: str, value: object) -> None:
            if getattr(self, "_locked", False):
                raise AttributeError("VerifiedE3AuthorityGrant is read-only")
            object.__setattr__(self, name, value)

        @property
        def experiment_id(self) -> str:
            return self._experiment_id

        @property
        def claim_id(self) -> str:
            return self._claim_id

        @property
        def task_class(self) -> str:
            return self._task_class

        @property
        def evidence_origin(self) -> str:
            return self._evidence_origin

        @property
        def metric_scope(self) -> tuple[str, ...]:
            return self._metric_scope

        @property
        def artifact_scope(self) -> tuple[str, ...]:
            return self._artifact_scope

        @property
        def privacy_scope(self) -> str:
            return self._privacy_scope

        @property
        def request_scope_digest(self) -> str:
            return self._request_scope_digest

        @property
        def authority_record_sha256(self) -> str:
            return self._authority_record_sha256

        @property
        def decision(self) -> str:
            return self._decision

        @property
        def authority_identity(self) -> str:
            return self._authority_identity

        @property
        def verification_summary(self) -> dict[str, str]:
            return {
                "schema_version": "POI_MPP_E3_AUTHORITY_VERIFICATION_V1",
                "status": "VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY",
                "experiment_id": self.experiment_id,
                "claim_id": self.claim_id,
                "decision": self.decision,
                "authority_identity": self.authority_identity,
                "request_manifest_sha256": self._request_manifest_sha256,
                "request_manifest_self_digest": self._request_manifest_self_digest,
                "result_attestation_status": self._result_attestation_status,
                "authority_record_sha256": self.authority_record_sha256,
                "authority_boundary": (
                    "Signature verification authenticates pre-execution E3 scope authorization only; "
                    "it does not attest to any E3 result or publication claim."
                ),
            }

        def __getitem__(self, key: str) -> str:
            """Narrow compatibility for the post-execution verifier's decision lookup."""
            if key != "decision":
                raise KeyError(key)
            return self.decision

    def is_authentic(value: object) -> bool:
        return isinstance(value, VerifiedE3AuthorityGrant) and value in issued

    return VerifiedE3AuthorityGrant, is_authentic


VerifiedE3AuthorityGrant, _grant_is_authentic = _authority_grant_contract()


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ErrorClass(StrEnum):
    FALSE_ACCEPT = "FALSE_ACCEPT"
    FALSE_REJECT = "FALSE_REJECT"
    ABSTAIN = "ABSTAIN"
    OUTCOME_MISMATCH = "OUTCOME_MISMATCH"


class E3EvaluationContractError(ValueError):
    """Raised when a row/config contract breaks before metrics are computed."""

    def __init__(self, reasons: Sequence[str]):
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__("; ".join(self.reasons) if self.reasons else "E3 evaluation contract failed")


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


class E3DeclaredEvaluator(_FrozenModel):
    evaluator_id: str
    evaluator_hash: str
    origin: EvidenceOrigin
    independence_basis: str

    @field_validator("evaluator_id", "independence_basis")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("declared evaluator fields must not be blank")
        return value

    @field_validator("evaluator_hash")
    @classmethod
    def require_hash_shape(cls, value: str) -> str:
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("evaluator_hash must be a lowercase SHA-256 hex digest")
        return value


class E3SyntheticPlumbingEvaluator(E3DeclaredEvaluator):
    @model_validator(mode="after")
    def validate_synthetic_origin(self) -> "E3SyntheticPlumbingEvaluator":
        if self.origin is not EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
            raise ValueError("synthetic plumbing evaluators must use SYNTHETIC_NON_EVIDENCE origin")
        if self.independence_basis != _PLUMBING_INDEPENDENCE_BASIS:
            raise ValueError(
                f"synthetic plumbing evaluators must use independence_basis {_PLUMBING_INDEPENDENCE_BASIS}"
            )
        return self


class E3ManifestClosure(_FrozenModel):
    case_manifest: DatasetManifest
    source_manifest: DatasetManifest
    annotation_manifest: DatasetManifest


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


class E3ConfirmatorySchema(_FrozenModel):
    schema_version: str = "POI_MPP_E3_CONFIRMATORY_SCOPE_V1"
    publication_scope: str
    required_run_origin: EvidenceOrigin
    required_run_authorization_scope: str
    required_calibration_split: DatasetSplit
    required_confirmatory_manifest_split: DatasetSplit
    forbidden_confirmatory_origins: tuple[EvidenceOrigin, ...]
    required_confirmatory_metadata: tuple[str, ...]
    required_evaluator_fields: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_contract(self) -> "E3ConfirmatorySchema":
        if self.schema_version != "POI_MPP_E3_CONFIRMATORY_SCOPE_V1":
            raise ValueError("schema_version must equal POI_MPP_E3_CONFIRMATORY_SCOPE_V1")
        if self.publication_scope != E3_CONFIRMATORY_SCOPE:
            raise ValueError(f"publication_scope must equal {E3_CONFIRMATORY_SCOPE}")
        if self.required_run_origin is not EvidenceOrigin.REAL_MODEL_EXECUTION:
            raise ValueError("required_run_origin must equal REAL_MODEL_EXECUTION")
        if self.required_run_authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
            raise ValueError(
                f"required_run_authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
            )
        if self.required_calibration_split is not DatasetSplit.DEVELOPMENT:
            raise ValueError("required_calibration_split must equal DEVELOPMENT")
        if self.required_confirmatory_manifest_split is not DatasetSplit.CONFIRMATORY:
            raise ValueError("required_confirmatory_manifest_split must equal CONFIRMATORY")
        if EvidenceOrigin.SYNTHETIC_NON_EVIDENCE not in self.forbidden_confirmatory_origins:
            raise ValueError("forbidden_confirmatory_origins must include SYNTHETIC_NON_EVIDENCE")
        if tuple(self.required_confirmatory_metadata) != (
            "license_id",
            "privacy_status",
            "annotation_protocol_id",
        ):
            raise ValueError(
                "required_confirmatory_metadata must equal license_id, privacy_status, annotation_protocol_id"
            )
        if tuple(self.required_evaluator_fields) != (
            "evaluator_id",
            "evaluator_hash",
            "independence_basis",
        ):
            raise ValueError(
                "required_evaluator_fields must equal evaluator_id, evaluator_hash, independence_basis"
            )
        return self


def default_e3_confirmatory_schema() -> E3ConfirmatorySchema:
    return E3ConfirmatorySchema(
        publication_scope=E3_CONFIRMATORY_SCOPE,
        required_run_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        required_run_authorization_scope=PUBLICATION_EVIDENCE_AUTHORIZED,
        required_calibration_split=DatasetSplit.DEVELOPMENT,
        required_confirmatory_manifest_split=DatasetSplit.CONFIRMATORY,
        forbidden_confirmatory_origins=(EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,),
        required_confirmatory_metadata=("license_id", "privacy_status", "annotation_protocol_id"),
        required_evaluator_fields=("evaluator_id", "evaluator_hash", "independence_basis"),
        notes=(),
    )


def load_e3_confirmatory_schema(path: str | Path) -> E3ConfirmatorySchema:
    schema_path = Path(path)
    try:
        raw = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"unable to load E3 confirmatory schema: {schema_path}") from error
    if not isinstance(raw, Mapping):
        raise ValueError("E3 confirmatory schema must be a mapping")
    return E3ConfirmatorySchema.model_validate(dict(raw))


class E3SyntheticPlumbingConfig(_FrozenModel):
    run_config: RunConfig
    development_dataset: E3DevelopmentDataset
    manifests: E3ManifestClosure
    evaluators: tuple[E3SyntheticPlumbingEvaluator, ...]
    policy: E3MetricPolicy = E3MetricPolicy()

    @model_validator(mode="after")
    def validate_contract(self) -> "E3SyntheticPlumbingConfig":
        if self.run_config.experiment_id != "E3":
            raise ValueError("run_config.experiment_id must equal E3")
        if self.run_config.origin is not EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
            raise ValueError("synthetic plumbing run_config.origin must equal SYNTHETIC_NON_EVIDENCE")
        if self.development_dataset.calibration.fitted_split.value != "DEVELOPMENT":
            raise ValueError("calibration must be fitted on the DEVELOPMENT split")
        return self


class E3ConfirmatoryConfig(_FrozenModel):
    run_config: RunConfig
    schema_contract: E3ConfirmatorySchema = default_e3_confirmatory_schema()
    publication_scope: str
    claim_id: Literal["C3"] = E3_CLAIM_ID
    task_class: Literal["GROUNDED_SEMANTIC_ASSURANCE"] = E3_TASK_CLASS
    metric_scope: tuple[Literal["FAR", "FRR", "ABSTAIN", "coverage", "calibration"], ...] = E3_METRIC_SCOPE
    artifact_scope: tuple[Literal["T4", "T8", "F7", "RAW_E3_EXECUTION"], ...] = E3_ARTIFACT_SCOPE
    authority_privacy_scope: str
    authority_request_scope_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    pre_execution_authority_record_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    development_dataset: E3DevelopmentDataset
    manifests: E3ManifestClosure
    evaluators: tuple[E3DeclaredEvaluator, ...]
    license_id: str
    privacy_status: str
    annotation_protocol_id: str
    provenance_bundle: ProvenanceBundle | None = None
    policy: E3MetricPolicy = E3MetricPolicy()

    @field_validator(
        "publication_scope",
        "license_id",
        "privacy_status",
        "annotation_protocol_id",
        "authority_privacy_scope",
    )
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("confirmatory metadata must not be blank")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> "E3ConfirmatoryConfig":
        if self.run_config.experiment_id != "E3":
            raise ValueError("run_config.experiment_id must equal E3")
        if self.development_dataset.calibration.fitted_split.value != self.schema_contract.required_calibration_split.value:
            raise ValueError("calibration must be fitted on the DEVELOPMENT split")
        if self.publication_scope != self.schema_contract.publication_scope:
            raise ValueError(f"publication_scope must equal {self.schema_contract.publication_scope}")
        if not self.metric_scope or len(self.metric_scope) != len(set(self.metric_scope)):
            raise ValueError("metric_scope must be non-empty and unique")
        if not self.artifact_scope or len(self.artifact_scope) != len(set(self.artifact_scope)):
            raise ValueError("artifact_scope must be non-empty and unique")
        return self


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


class E3ConfirmatoryResult(_FrozenModel):
    evaluated_rows: tuple[E3SemanticRow, ...]
    summary: E3Summary
    annotation_provenance: E3AnnotationProvenance
    error_ledger: tuple[E3ErrorLedgerEntry, ...]


class E3SyntheticPlumbingResult(_FrozenModel):
    origin: EvidenceOrigin = EvidenceOrigin.SYNTHETIC_NON_EVIDENCE
    stage: ArtifactStage = ArtifactStage.SEMANTICALLY_VALID
    summary: E3Summary
    annotation_provenance: E3AnnotationProvenance
    error_ledger: tuple[E3ErrorLedgerEntry, ...]


def _revalidate_config(config: object, expected_type: type[_FrozenModel]) -> _FrozenModel:
    if isinstance(config, expected_type):
        payload = config.model_dump(mode="json")
    elif isinstance(config, BaseModel):
        payload = config.model_dump(mode="json")
    elif isinstance(config, Mapping):
        payload = dict(config)
    else:
        raise TypeError(f"config must be a {expected_type.__name__} or equivalent mapping")
    return expected_type.model_validate(payload)


def _revalidate_row(row: object) -> E3SemanticRow:
    if isinstance(row, BaseModel):
        payload = row.model_dump(mode="json")
    elif isinstance(row, Mapping):
        payload = dict(row)
    else:
        payload = row
    return E3SemanticRow.model_validate(payload)


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


def _record_map(
    manifest: DatasetManifest,
    *,
    label: str,
) -> dict[str, DatasetRecord]:
    records = {record.record_id: record for record in manifest.records}
    if len(records) != len(manifest.records):
        raise E3EvaluationContractError((f"{label} must not contain duplicate record_id values",))
    return records


def _shared_closure_reasons(
    *,
    run_config: RunConfig,
    manifests: E3ManifestClosure,
    evaluators: Sequence[E3DeclaredEvaluator],
    calibration: SemanticCalibrationArtifact,
    rows: Sequence[E3SemanticRow],
    expected_split: DatasetSplit,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if manifests.case_manifest.split is not expected_split:
        reasons.append(f"case manifest must use the {expected_split.value} split")
    if manifests.source_manifest.split is not expected_split:
        reasons.append(f"source manifest must use the {expected_split.value} split")
    if manifests.annotation_manifest.split is not expected_split:
        reasons.append(f"annotation manifest must use the {expected_split.value} split")
    if not rows:
        reasons.append("semantic rows are required")
        return tuple(reasons)
    if len({row.case_id for row in rows}) != len(rows):
        reasons.append("row case_id values must be unique")
    if len({row.source_record_id for row in rows}) != len(rows):
        reasons.append("row source_record_id values must be one-to-one")
    if len({row.annotation_record_id for row in rows}) != len(rows):
        reasons.append("row annotation_record_id values must be one-to-one")
    if len({row.evaluator_id for row in rows}) > len(evaluators):
        reasons.append("row evaluator_id values exceed the frozen evaluator registry closure")
    case_records = _record_map(manifests.case_manifest, label="case manifest")
    source_records = _record_map(manifests.source_manifest, label="source manifest")
    annotation_records = _record_map(manifests.annotation_manifest, label="annotation manifest")
    declared_evaluators = {evaluator.evaluator_id: evaluator for evaluator in evaluators}

    if {row.case_id for row in rows} != set(case_records):
        reasons.append("case manifest closure must exactly match row case_id values")
    if {row.source_record_id for row in rows} != set(source_records):
        reasons.append("source manifest closure must exactly match row source_record_id values")
    if {row.annotation_record_id for row in rows} != set(annotation_records):
        reasons.append("annotation manifest closure must exactly match row annotation_record_id values")

    for row in rows:
        if row.run_id != run_config.run_id:
            reasons.append(f"row {row.case_id} run_id must equal run_config.run_id")
        if row.experiment_id != run_config.experiment_id:
            reasons.append(f"row {row.case_id} experiment_id must equal run_config.experiment_id")
        if row.split is not expected_split:
            reasons.append(f"row {row.case_id} must use the {expected_split.value} split")
        if row.calibration_hash != calibration.content_hash:
            reasons.append(
                f"row {row.case_id} calibration_hash must equal the frozen development calibration"
            )
        case_record = case_records.get(row.case_id)
        if case_record is None:
            reasons.append(f"row {row.case_id} is outside the case manifest closure")
        elif row.origin is not case_record.origin:
            reasons.append(f"row {row.case_id} origin must match the case manifest origin")
        source_record = source_records.get(row.source_record_id)
        if source_record is None:
            reasons.append(f"row {row.case_id} source manifest is missing {row.source_record_id}")
        else:
            if row.source_content_hash != source_record.content_hash:
                reasons.append(f"row {row.case_id} source manifest hash does not match")
            if row.source_origin is not source_record.origin:
                reasons.append(f"row {row.case_id} source manifest origin does not match")
        annotation_record = annotation_records.get(row.annotation_record_id)
        if annotation_record is None:
            reasons.append(f"row {row.case_id} annotation manifest is missing {row.annotation_record_id}")
        else:
            if row.annotation_hash != annotation_record.content_hash:
                reasons.append(f"row {row.case_id} annotation manifest hash does not match")
            if row.annotation_origin is not annotation_record.origin:
                reasons.append(f"row {row.case_id} annotation manifest origin does not match")
        evaluator = declared_evaluators.get(row.evaluator_id)
        if evaluator is None:
            reasons.append(f"row {row.case_id} evaluator_id is outside the frozen evaluator registry")
        else:
            if row.evaluator_hash != evaluator.evaluator_hash:
                reasons.append(f"row {row.case_id} evaluator registry hash does not match")
            if row.evaluator_origin is not evaluator.origin:
                reasons.append(f"row {row.case_id} evaluator registry origin does not match")
            if row.evaluator_independence_basis != evaluator.independence_basis:
                reasons.append(f"row {row.case_id} evaluator registry independence_basis does not match")
    return tuple(dict.fromkeys(reasons))


def _confirmatory_reasons(
    *,
    config: E3ConfirmatoryConfig,
    rows: Sequence[E3SemanticRow],
) -> tuple[str, ...]:
    if config.provenance_bundle is None:
        return ("verified provenance bundle is required before confirmatory authority evaluation",)
    try:
        verified_bundle = provenance_bundle_from_json(
            {
                "config": config.provenance_bundle.config.model_dump(mode="json"),
                "environment": config.provenance_bundle.environment.model_dump(mode="json"),
                "manifest": config.provenance_bundle.manifest.model_dump(mode="json"),
            }
        )
    except ArtifactValidationError as error:
        return error.reasons
    provenance_reasons: list[str] = []
    if verified_bundle.config.model_dump(mode="json") != config.run_config.model_dump(mode="json"):
        provenance_reasons.append("provenance bundle config must exactly match run_config")
    if verified_bundle.manifest.run_id != config.run_config.run_id:
        provenance_reasons.append("provenance manifest run_id must equal run_config.run_id")
    if verified_bundle.manifest.experiment_id != config.run_config.experiment_id:
        provenance_reasons.append("provenance manifest experiment_id must equal run_config.experiment_id")
    if verified_bundle.manifest.origin is not config.run_config.origin:
        provenance_reasons.append("provenance manifest origin must equal run_config.origin")
    if provenance_reasons:
        return tuple(dict.fromkeys(provenance_reasons))
    reasons = list(
        _shared_closure_reasons(
            run_config=config.run_config,
            manifests=config.manifests,
            evaluators=config.evaluators,
            calibration=config.development_dataset.calibration,
            rows=rows,
            expected_split=config.schema_contract.required_confirmatory_manifest_split,
        )
    )
    if config.run_config.origin is not config.schema_contract.required_run_origin:
        reasons.append("run_config.origin must equal REAL_MODEL_EXECUTION")
    if config.run_config.authorization_scope != config.schema_contract.required_run_authorization_scope:
        reasons.append(
            f"run_config.authorization_scope must equal {config.schema_contract.required_run_authorization_scope}"
        )
    if config.publication_scope != config.schema_contract.publication_scope:
        reasons.append(f"publication_scope must equal {config.schema_contract.publication_scope}")
    try:
        assert_confirmatory_isolation(config.development_dataset.manifest, config.manifests.case_manifest)
    except ValueError as error:
        reasons.append(str(error))
    if config.license_id.strip() == "":
        reasons.append("license_id must not be blank")
    if config.privacy_status.strip() == "":
        reasons.append("privacy_status must not be blank")
    if config.annotation_protocol_id.strip() == "":
        reasons.append("annotation_protocol_id must not be blank")
    forbidden_origins = set(config.schema_contract.forbidden_confirmatory_origins)
    if config.run_config.origin in forbidden_origins:
        reasons.append("run_config.origin is forbidden for confirmatory publication")
    for manifest in (
        config.manifests.case_manifest,
        config.manifests.source_manifest,
        config.manifests.annotation_manifest,
    ):
        for record in manifest.records:
            if record.origin in forbidden_origins:
                reasons.append("confirmatory manifests cannot contain forbidden synthetic origins")
    return tuple(dict.fromkeys(reasons))


def run_synthetic_plumbing_semantic(
    *,
    config: E3SyntheticPlumbingConfig,
    rows: Sequence[E3SemanticRow] | Sequence[object],
) -> E3SyntheticPlumbingResult:
    canonical_config = _revalidate_config(config, E3SyntheticPlumbingConfig)
    canonical_rows = tuple(_revalidate_row(row) for row in rows)
    reasons = _shared_closure_reasons(
        run_config=canonical_config.run_config,
        manifests=canonical_config.manifests,
        evaluators=canonical_config.evaluators,
        calibration=canonical_config.development_dataset.calibration,
        rows=canonical_rows,
        expected_split=DatasetSplit.PLUMBING,
    )
    if reasons:
        raise E3EvaluationContractError(reasons)
    return E3SyntheticPlumbingResult(
        summary=semantic_metrics(canonical_rows, policy=canonical_config.policy),
        annotation_provenance=_annotation_provenance(canonical_rows),
        error_ledger=_error_ledger(canonical_rows),
    )


def run_confirmatory_semantic(
    *,
    config: E3ConfirmatoryConfig,
    rows: Sequence[E3SemanticRow] | Sequence[object],
    authority_grant: VerifiedE3AuthorityGrant | object | None = None,
) -> E3ConfirmatoryResult:
    canonical_config = _revalidate_config(config, E3ConfirmatoryConfig)
    canonical_rows = tuple(_revalidate_row(row) for row in rows)
    reasons = _confirmatory_reasons(config=canonical_config, rows=canonical_rows)
    if reasons:
        raise PublicationEligibilityError(reasons)
    if not _grant_is_authentic(authority_grant):
        boundary = (
            WAITING_EXTERNAL_EVALUATOR_AUTHORITY
            if authority_grant is None
            else "a genuine VerifiedE3AuthorityGrant from verify_authority is required"
        )
        raise PublicationEligibilityError((boundary,))
    assert isinstance(authority_grant, VerifiedE3AuthorityGrant)
    authority_reasons: list[str] = []
    if authority_grant.experiment_id != canonical_config.run_config.experiment_id:
        authority_reasons.append("authority experiment_id must exactly match config experiment_id E3")
    if authority_grant.claim_id != canonical_config.claim_id:
        authority_reasons.append("authority claim_id must exactly match config claim_id C3")
    if authority_grant.task_class != canonical_config.task_class:
        authority_reasons.append("authority task_class must exactly match config task_class")
    if authority_grant.evidence_origin != canonical_config.run_config.origin.value:
        authority_reasons.append("authority evidence_origin must exactly match REAL_MODEL_EXECUTION config origin")
    if authority_grant.metric_scope != canonical_config.metric_scope:
        authority_reasons.append("metric_scope must exactly match verified authority grant")
    if authority_grant.artifact_scope != canonical_config.artifact_scope:
        authority_reasons.append("artifact_scope must exactly match verified authority grant")
    if authority_grant.privacy_scope != canonical_config.authority_privacy_scope:
        authority_reasons.append("privacy_scope must exactly match verified authority grant")
    if authority_grant.request_scope_digest != canonical_config.authority_request_scope_digest:
        authority_reasons.append("request_scope_digest must exactly match verified authority grant")
    if (
        authority_grant.authority_record_sha256
        != canonical_config.pre_execution_authority_record_sha256
    ):
        authority_reasons.append(
            "pre_execution_authority_record_sha256 must exactly match verified authority grant"
        )
    if authority_reasons:
        raise PublicationEligibilityError(authority_reasons)
    return E3ConfirmatoryResult(
        evaluated_rows=canonical_rows,
        summary=semantic_metrics(canonical_rows, policy=canonical_config.policy),
        annotation_provenance=_annotation_provenance(canonical_rows),
        error_ledger=_error_ledger(canonical_rows),
    )
