"""V2 publication-scoped grounded semantic verification."""

from __future__ import annotations

from datetime import date
from typing import Sequence

from pydantic import BaseModel, ConfigDict, field_validator

from poi_mpp.auditor.semantic.authority import SemanticAuthorityRecordV1
from poi_mpp.auditor.semantic.authority_registry import (
    SemanticAuthorityCryptoVerificationV1,
    SemanticAuthorityRegistrySnapshotV1,
)
from poi_mpp.auditor.semantic.models import (
    EvidenceAnnotationKind,
    EvidenceRecord,
    GroundedClaim,
    NumericExpectation,
    SemanticCalibrationArtifact,
    SemanticOutcome,
    VerificationDecision,
    parse_bounded_decimal,
    semantic_annotation_payload_hash,
)
from poi_mpp.auditor.semantic.policy_v2 import SemanticPolicyV2
from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.claim_spec import ClaimDisposition, ClaimMetricObservation, ClaimSpecV2
from poi_mpp.evidence.dataset_manifest_v2 import DatasetManifestV2
from poi_mpp.evidence.environment_manifest import ExecutionEnvironmentManifestV1
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.protocol.receipt import RecordAudit
from poi_mpp.protocol.task_envelope import TaskEnvelopeV2
from poi_mpp.protocol.types import (
    AuditDecision,
    ModelManifest,
    ResponseCommitment,
    TaskSpec,
    model_commitment_hash,
    task_commitment_hash,
)


SEMANTIC_TRACE_ARTIFACT_V1_DOMAIN = "POI_MPP_SEMANTIC_TRACE_ARTIFACT_V1"
GROUNDED_VERIFICATION_RESULT_V2_DOMAIN = "POI_MPP_GROUNDED_VERIFICATION_RESULT_V2"


class _FrozenVerifierModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticTraceArtifactV1(_FrozenVerifierModel):
    schema_version: str = "POI_MPP_SEMANTIC_TRACE_ARTIFACT_V1"
    task_root: str
    response_hash: str
    semantic_policy_hash: str
    dataset_manifest_hash: str
    authority_record_digest: str
    decision: VerificationDecision

    @field_validator(
        "response_hash",
        "semantic_policy_hash",
        "dataset_manifest_hash",
        "authority_record_digest",
    )
    @classmethod
    def require_digest(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("semantic trace hashes must be lowercase 32-byte hex digests")
        return normalized

    @field_validator("task_root")
    @classmethod
    def require_task_root(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("0x") or len(normalized) != 66:
            raise ValueError("task_root must be a 0x-prefixed 32-byte hex word")
        if any(char not in "0123456789abcdef" for char in normalized[2:]):
            raise ValueError("task_root must be lowercase hexadecimal")
        return normalized

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    @property
    def trace_root(self) -> str:
        return digest(SEMANTIC_TRACE_ARTIFACT_V1_DOMAIN, self.canonical_payload())

    @classmethod
    def create(
        cls,
        *,
        task_root: str,
        response_hash: str,
        semantic_policy_hash: str,
        dataset_manifest_hash: str,
        authority_record_digest: str,
        decision: VerificationDecision,
    ) -> "SemanticTraceArtifactV1":
        return cls(
            task_root=task_root,
            response_hash=response_hash,
            semantic_policy_hash=semantic_policy_hash,
            dataset_manifest_hash=dataset_manifest_hash,
            authority_record_digest=authority_record_digest,
            decision=decision,
        )


class ClaimVerificationOutcomeV2(_FrozenVerifierModel):
    claim_id: str
    outcome: SemanticOutcome
    decision: VerificationDecision
    support_fraction: float
    citation_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


class GroundedVerificationResultV2(_FrozenVerifierModel):
    schema_version: str = "POI_MPP_GROUNDED_VERIFICATION_V2"
    response_hash: str
    task_root: str
    response_commitment_hash: str
    claim_spec_hash: str
    dataset_manifest_hash: str
    environment_manifest_hash: str
    authority_record_digest: str
    authority_crypto_verification_digest: str
    authority_verification_receipt_digest: str
    claim_disposition: ClaimDisposition
    decision: VerificationDecision
    outcomes: tuple[ClaimVerificationOutcomeV2, ...]
    integrity_reasons: tuple[str, ...] = ()
    residual_risks: tuple[str, ...] = ()

    @field_validator(
        "authority_crypto_verification_digest",
        "authority_verification_receipt_digest",
    )
    @classmethod
    def _require_digest(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("verification digests must be lowercase SHA-256 hex")
        return normalized

    @field_validator("response_commitment_hash")
    @classmethod
    def _require_word_hash(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("0x") or len(normalized) != 66:
            raise ValueError("response_commitment_hash must be a 0x-prefixed word")
        if any(char not in "0123456789abcdef" for char in normalized[2:]):
            raise ValueError("response_commitment_hash must be lowercase hexadecimal")
        return normalized

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    @property
    def result_digest(self) -> str:
        return digest(GROUNDED_VERIFICATION_RESULT_V2_DOMAIN, self.canonical_payload())


def audit_decision_from_verification(
    result: GroundedVerificationResultV2,
) -> AuditDecision:
    """Map the frozen semantic result into the protocol receipt gate."""

    return {
        VerificationDecision.ACCEPT: AuditDecision.ACCEPT,
        VerificationDecision.REJECT: AuditDecision.REJECT,
        VerificationDecision.ABSTAIN: AuditDecision.ABSTAIN,
    }[result.decision]


def record_audit_from_verification(
    result: GroundedVerificationResultV2,
) -> RecordAudit:
    """Preserve semantic lineage when entering the protocol receipt machine."""

    return RecordAudit(
        decision=audit_decision_from_verification(result),
        verification_result_digest=f"0x{result.result_digest}",
        semantic_task_root=result.task_root,
        semantic_response_hash=f"0x{result.response_hash}",
        semantic_commitment_hash=result.response_commitment_hash,
    )


def _word_hex_to_digest(value: str) -> str:
    return value[2:] if value.startswith("0x") else value


def _ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _compare_numeric_expectation(
    expectation: NumericExpectation,
    records: Sequence[EvidenceRecord],
    claim_id: str,
) -> tuple[bool, tuple[str, ...]]:
    matching_values = []
    units = set()
    for record in records:
        for fact in record.numeric_facts:
            if fact.claim_id != claim_id or fact.metric != expectation.metric:
                continue
            matching_values.append(parse_bounded_decimal(fact.value, label="numeric fact value"))
            if fact.unit is not None:
                units.add(fact.unit)
    if not matching_values:
        return False, ("missing numeric fact for expected metric",)
    if len(units) > 1:
        return False, ("numeric units disagree across cited evidence",)
    expected = parse_bounded_decimal(expectation.value, label="numeric expectation value")
    if expectation.unit is not None and units and expectation.unit not in units:
        return False, ("numeric unit mismatch for expected metric",)
    passed = {
        "EQUALS": all(value == expected for value in matching_values),
        "AT_LEAST": all(value >= expected for value in matching_values),
        "AT_MOST": all(value <= expected for value in matching_values),
    }[expectation.comparator.value]
    if passed:
        return True, ()
    return False, ("numeric expectation mismatch",)


def _evaluate_claim(
    claim: GroundedClaim,
    evidence_index: dict[str, list[EvidenceRecord]],
    calibration: SemanticCalibrationArtifact,
) -> ClaimVerificationOutcomeV2:
    missing = [citation_id for citation_id in claim.cited_citation_ids if citation_id not in evidence_index]
    duplicate = [
        citation_id
        for citation_id in claim.cited_citation_ids
        if len(evidence_index.get(citation_id, ())) != 1
    ]
    if missing or duplicate:
        reasons = tuple(
            [f"missing citation: {citation_id}" for citation_id in missing]
            + [f"duplicate citation: {citation_id}" for citation_id in duplicate]
        )
        return ClaimVerificationOutcomeV2(
            claim_id=claim.claim_id,
            outcome=SemanticOutcome.CITATION_ERROR,
            decision=VerificationDecision.REJECT,
            support_fraction=0.0,
            citation_ids=claim.cited_citation_ids,
            reasons=reasons,
        )

    records = tuple(evidence_index[citation_id][0] for citation_id in claim.cited_citation_ids)
    supported_citations: list[str] = []
    contradiction_reasons: list[str] = []
    evidence_ids: list[str] = []
    for record in records:
        evidence_ids.append(record.evidence_id)
        claim_annotations = tuple(
            annotation for annotation in record.annotations if annotation.claim_id == claim.claim_id
        )
        if any(item.kind is EvidenceAnnotationKind.CONTRADICTS for item in claim_annotations):
            contradiction_reasons.append(f"citation {record.citation_id} contradicts the claim")
        if any(item.kind is EvidenceAnnotationKind.SUPPORTS for item in claim_annotations):
            supported_citations.append(record.citation_id)

    if contradiction_reasons:
        return ClaimVerificationOutcomeV2(
            claim_id=claim.claim_id,
            outcome=SemanticOutcome.CONTRADICTORY,
            decision=VerificationDecision.REJECT,
            support_fraction=0.0,
            citation_ids=claim.cited_citation_ids,
            evidence_ids=tuple(evidence_ids),
            reasons=tuple(contradiction_reasons),
        )

    support_fraction = len(supported_citations) / len(claim.cited_citation_ids)
    if len(supported_citations) == 0:
        return ClaimVerificationOutcomeV2(
            claim_id=claim.claim_id,
            outcome=SemanticOutcome.UNSUPPORTED,
            decision=VerificationDecision.REJECT,
            support_fraction=support_fraction,
            citation_ids=claim.cited_citation_ids,
            evidence_ids=tuple(evidence_ids),
            reasons=("no cited evidence explicitly supports the claim",),
        )

    if claim.numeric_expectation is not None:
        numeric_ok, numeric_reasons = _compare_numeric_expectation(
            claim.numeric_expectation,
            records,
            claim.claim_id,
        )
        if not numeric_ok:
            return ClaimVerificationOutcomeV2(
                claim_id=claim.claim_id,
                outcome=SemanticOutcome.NUMERICAL_ERROR,
                decision=VerificationDecision.REJECT,
                support_fraction=support_fraction,
                citation_ids=claim.cited_citation_ids,
                evidence_ids=tuple(evidence_ids),
                reasons=numeric_reasons,
            )

    if support_fraction < calibration.minimum_support_fraction or len(supported_citations) != len(
        claim.cited_citation_ids
    ):
        return ClaimVerificationOutcomeV2(
            claim_id=claim.claim_id,
            outcome=SemanticOutcome.PARTIAL,
            decision=VerificationDecision.ABSTAIN,
            support_fraction=support_fraction,
            citation_ids=claim.cited_citation_ids,
            evidence_ids=tuple(evidence_ids),
            reasons=("support is incomplete for the cited evidence set",),
        )

    return ClaimVerificationOutcomeV2(
        claim_id=claim.claim_id,
        outcome=SemanticOutcome.SUPPORTED,
        decision=VerificationDecision.ACCEPT,
        support_fraction=support_fraction,
        citation_ids=claim.cited_citation_ids,
        evidence_ids=tuple(evidence_ids),
        reasons=(),
    )


def _integrity_reasons(
    *,
    claim_spec: ClaimSpecV2,
    dataset_manifest: DatasetManifestV2,
    environment_manifest: ExecutionEnvironmentManifestV1,
    authority_record: SemanticAuthorityRecordV1,
    task_envelope: TaskEnvelopeV2,
    evidence: Sequence[EvidenceRecord],
    calibration: SemanticCalibrationArtifact,
    model_manifest_hash: str,
    registry_snapshot: SemanticAuthorityRegistrySnapshotV1,
    semantic_policy: SemanticPolicyV2,
    prompt_template_hash: str,
    authority_crypto_verification: SemanticAuthorityCryptoVerificationV1,
    trace_artifact: SemanticTraceArtifactV1,
    protocol_task: TaskSpec,
    protocol_model: ModelManifest,
    response_commitment: ResponseCommitment,
    response: str,
    on_date: date | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    claim_spec_hash = claim_spec.claim_spec_hash()
    dataset_hash = dataset_manifest.dataset_manifest_hash()
    environment_hash = environment_manifest.environment_manifest_hash()
    semantic_policy_hash = semantic_policy.policy_hash()
    response_hash = digest("SEMANTIC_RESPONSE", response)

    if task_envelope.claim_spec_hash != f"0x{claim_spec_hash}":
        reasons.append("task envelope claim_spec_hash mismatch")
    if task_envelope.dataset_manifest_hash != f"0x{dataset_hash}":
        reasons.append("task envelope dataset_manifest_hash mismatch")
    if task_envelope.runtime_environment_hash != f"0x{environment_hash}":
        reasons.append("task envelope runtime_environment_hash mismatch")
    if task_envelope.semantic_policy_hash != f"0x{semantic_policy_hash}":
        reasons.append("task envelope semantic_policy_hash mismatch")
    if task_envelope.authority_registry_snapshot_hash != f"0x{registry_snapshot.snapshot_hash}":
        reasons.append("task envelope authority_registry_snapshot_hash mismatch")
    if task_envelope.model_manifest_hash != f"0x{model_manifest_hash}":
        reasons.append("task envelope model_manifest_hash mismatch")
    if task_envelope.scope.evidence_origin != EvidenceOrigin.REAL_MODEL_EXECUTION.value:
        reasons.append("task envelope evidence_origin must remain REAL_MODEL_EXECUTION")

    if trace_artifact.task_root != task_envelope.task_root:
        reasons.append("semantic trace task_root mismatch")
    if trace_artifact.response_hash != response_hash:
        reasons.append("semantic trace response_hash mismatch")
    if trace_artifact.semantic_policy_hash != semantic_policy_hash:
        reasons.append("semantic trace policy hash mismatch")
    if trace_artifact.dataset_manifest_hash != dataset_hash:
        reasons.append("semantic trace dataset hash mismatch")
    if trace_artifact.authority_record_digest != authority_record.record_digest:
        reasons.append("semantic trace authority record digest mismatch")
    if protocol_task.task_root != task_envelope.task_root:
        reasons.append("protocol task_root does not match task envelope")
    if protocol_task.task_id != response_commitment.task_id:
        reasons.append("response commitment task_id mismatch")
    if protocol_task.worker_id != response_commitment.worker_id:
        reasons.append("response commitment worker_id mismatch")
    if protocol_task.task_class is not response_commitment.task_class:
        reasons.append("response commitment task_class mismatch")
    if protocol_task.epoch != response_commitment.task_epoch:
        reasons.append("response commitment task epoch mismatch")
    if response_commitment.response_hash != f"0x{response_hash}":
        reasons.append("response commitment response_hash mismatch")
    if response_commitment.trace_root != f"0x{trace_artifact.trace_root}":
        reasons.append("response commitment trace_root mismatch")
    if response_commitment.task_commitment != task_commitment_hash(protocol_task):
        reasons.append("response commitment task_commitment mismatch")
    if response_commitment.model_commitment != model_commitment_hash(protocol_model):
        reasons.append("response commitment model_commitment mismatch")
    if protocol_model.model_manifest_hash != f"0x{model_manifest_hash}":
        reasons.append("protocol model_manifest_hash mismatch")

    if authority_record.scope.claim_id != claim_spec.claim_id:
        reasons.append("authority claim_id mismatch")
    if authority_record.scope.claim_spec_hash != claim_spec_hash:
        reasons.append("authority claim_spec_hash mismatch")
    if authority_record.scope.dataset_manifest_hash != dataset_hash:
        reasons.append("authority dataset_manifest_hash mismatch")
    if authority_record.scope.runtime_environment_hash != environment_hash:
        reasons.append("authority runtime_environment_hash mismatch")
    if authority_record.scope.semantic_policy_hash != semantic_policy_hash:
        reasons.append("authority semantic_policy_hash mismatch")
    if authority_record.registry_snapshot_hash != registry_snapshot.snapshot_hash:
        reasons.append("authority registry_snapshot_hash mismatch")
    reasons.extend(
        registry_snapshot.cryptographic_binding_reasons(
            record=authority_record,
            cryptographic_verification=authority_crypto_verification,
        )
    )
    if authority_record.scope.evidence_origin is not EvidenceOrigin.REAL_MODEL_EXECUTION:
        reasons.append("authority evidence_origin must remain REAL_MODEL_EXECUTION")
    if environment_manifest.model.model_id not in claim_spec.scope.model_ids:
        reasons.append("environment model_id falls outside claim scope")
    if environment_manifest.environment_id not in claim_spec.scope.environment_ids:
        reasons.append("environment_id falls outside claim scope")
    if authority_record.scope.experiment_id not in claim_spec.scope.experiment_ids:
        reasons.append("authority experiment_id falls outside claim scope")
    if authority_record.scope.claim_id != claim_spec.claim_id:
        reasons.append("claim scope mismatch")

    frozen_bindings = {
        "claim_spec_hash": claim_spec_hash,
        "dataset_manifest_hash": dataset_hash,
        "authority_registry_snapshot_hash": registry_snapshot.snapshot_hash,
        "model_manifest_hash": model_manifest_hash,
        "runtime_environment_hash": environment_hash,
        "task_payload_hash": _word_hex_to_digest(task_envelope.task_payload_hash),
        "prompt_template_hash": prompt_template_hash,
        "calibration_hash": calibration.content_hash,
    }
    try:
        semantic_policy.assert_frozen_inputs(frozen_bindings)
    except ValueError as error:
        reasons.append(f"semantic policy binding failure: {error}")
    claim_metric_ids = {metric.metric_id for metric in claim_spec.primary_metrics}
    if set(semantic_policy.allowed_metric_ids) != claim_metric_ids:
        reasons.append("semantic policy metric scope does not equal claim metric scope")
    if set(semantic_policy.required_artifact_ids) != set(claim_spec.required_artifacts):
        reasons.append("semantic policy artifact scope does not equal claim artifact scope")

    reasons.extend(
        authority_record.publication_eligibility_gate_reasons(
            cryptographic_validity_verified=(
                authority_crypto_verification.cryptographic_validity_verified
            ),
            requested_metric_ids=tuple(metric.metric_id for metric in claim_spec.primary_metrics),
            requested_artifact_ids=claim_spec.required_artifacts,
            on_date=on_date,
        )
    )
    for record in evidence:
        dataset_records = {
            dataset_record.record_id: dataset_record
            for dataset_record in dataset_manifest.records
        }
        dataset_record = dataset_records.get(record.evidence_id)
        if dataset_record is None:
            reasons.append(
                f"evidence record is absent from the frozen dataset manifest: {record.evidence_id}"
            )
        else:
            if dataset_record.content_hash != record.content_hash:
                reasons.append(
                    f"dataset content_hash mismatch for evidence: {record.evidence_id}"
                )
            if dataset_record.evidence_origin is not record.origin:
                reasons.append(
                    f"dataset evidence_origin mismatch for evidence: {record.evidence_id}"
                )
            annotation_hash = semantic_annotation_payload_hash(
                evidence_id=record.evidence_id,
                citation_id=record.citation_id,
                source_family=record.source_family,
                annotations=record.annotations,
                numeric_facts=record.numeric_facts,
            )
            if dataset_record.annotation.annotation_hash != annotation_hash:
                reasons.append(
                    f"dataset annotation hash mismatch for evidence: {record.evidence_id}"
                )
        if record.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
            reasons.append("synthetic evidence cannot satisfy publication verification")
        elif record.origin is not EvidenceOrigin.REAL_MODEL_EXECUTION:
            reasons.append(f"unsupported evidence origin: {record.origin.value}")
        elif record.origin not in claim_spec.allowed_evidence_origins:
            reasons.append(f"claim spec does not allow evidence origin: {record.origin.value}")

    return _ordered_unique(reasons)


def _safe_claim_adjudication(
    *,
    claim_spec: ClaimSpecV2,
    metrics: dict[str, ClaimMetricObservation],
    origin: EvidenceOrigin,
    statement: str,
) -> tuple[ClaimDisposition, str | None]:
    """Keep malformed publication claims fail-closed and machine-readable."""

    try:
        return (
            claim_spec.adjudicate(
                metrics=metrics,
                origin=origin,
                statement=statement,
            ),
            None,
        )
    except ValueError as error:
        return ClaimDisposition.INCONCLUSIVE, f"claim adjudication failure: {error}"


def verify_grounded_v2(
    *,
    response: str,
    trace_artifact: SemanticTraceArtifactV1,
    protocol_task: TaskSpec,
    protocol_model: ModelManifest,
    response_commitment: ResponseCommitment,
    claims: Sequence[GroundedClaim],
    evidence: Sequence[EvidenceRecord],
    calibration: SemanticCalibrationArtifact,
    claim_spec: ClaimSpecV2,
    dataset_manifest: DatasetManifestV2,
    environment_manifest: ExecutionEnvironmentManifestV1,
    authority_record: SemanticAuthorityRecordV1,
    task_envelope: TaskEnvelopeV2,
    metrics: dict[str, ClaimMetricObservation],
    model_manifest_hash: str,
    registry_snapshot: SemanticAuthorityRegistrySnapshotV1,
    semantic_policy: SemanticPolicyV2,
    prompt_template_hash: str,
    statement: str,
    authority_crypto_verification: SemanticAuthorityCryptoVerificationV1,
    on_date: date | None = None,
) -> GroundedVerificationResultV2:
    """Run the V2 publication-scoped verifier without duplicating trust logic."""

    integrity_reasons = _integrity_reasons(
        claim_spec=claim_spec,
        dataset_manifest=dataset_manifest,
        environment_manifest=environment_manifest,
        authority_record=authority_record,
        task_envelope=task_envelope,
        evidence=evidence,
        calibration=calibration,
        model_manifest_hash=model_manifest_hash,
        registry_snapshot=registry_snapshot,
        semantic_policy=semantic_policy,
        prompt_template_hash=prompt_template_hash,
        authority_crypto_verification=authority_crypto_verification,
        trace_artifact=trace_artifact,
        protocol_task=protocol_task,
        protocol_model=protocol_model,
        response_commitment=response_commitment,
        response=response,
        on_date=on_date,
    )
    integrity_reason_list = list(integrity_reasons)
    if not claims:
        integrity_reason_list.append("verify_grounded_v2 requires at least one claim")
    if not evidence:
        integrity_reason_list.append(
            "verify_grounded_v2 requires at least one evidence record"
        )

    claim_disposition, adjudication_failure = _safe_claim_adjudication(
        claim_spec=claim_spec,
        metrics=metrics,
        origin=authority_record.scope.evidence_origin,
        statement=statement,
    )
    if adjudication_failure is not None:
        integrity_reason_list.append(adjudication_failure)
    integrity_reasons = _ordered_unique(integrity_reason_list)

    evidence_index: dict[str, list[EvidenceRecord]] = {}
    for record in evidence:
        evidence_index.setdefault(record.citation_id, []).append(record)
    outcomes = tuple(_evaluate_claim(claim, evidence_index, calibration) for claim in claims)

    if integrity_reasons:
        return GroundedVerificationResultV2(
            response_hash=digest("SEMANTIC_RESPONSE", response),
            task_root=task_envelope.task_root,
            response_commitment_hash=response_commitment.commitment_hash,
            claim_spec_hash=claim_spec.claim_spec_hash(),
            dataset_manifest_hash=dataset_manifest.dataset_manifest_hash(),
            environment_manifest_hash=environment_manifest.environment_manifest_hash(),
            authority_record_digest=authority_record.record_digest,
            authority_crypto_verification_digest=(
                authority_crypto_verification.verification_digest
            ),
            authority_verification_receipt_digest=(
                authority_crypto_verification.verification_receipt.receipt_digest
            ),
            claim_disposition=claim_disposition,
            decision=VerificationDecision.REJECT,
            outcomes=outcomes,
            integrity_reasons=integrity_reasons,
            residual_risks=(),
        )

    if any(outcome.decision is VerificationDecision.REJECT for outcome in outcomes):
        computed_decision = VerificationDecision.REJECT
    elif all(outcome.decision is VerificationDecision.ACCEPT for outcome in outcomes):
        computed_decision = VerificationDecision.ACCEPT
    else:
        computed_decision = VerificationDecision.ABSTAIN

    residual_risks: list[str] = []
    if claim_disposition is ClaimDisposition.NOT_SUPPORTED:
        computed_decision = VerificationDecision.REJECT
        residual_risks.append("claim metrics adjudicate to NOT_SUPPORTED under the frozen claim specification")
    elif claim_disposition is ClaimDisposition.INCONCLUSIVE and computed_decision is VerificationDecision.ACCEPT:
        computed_decision = VerificationDecision.ABSTAIN
        residual_risks.append("claim metrics remain inconclusive under the frozen claim specification")

    if trace_artifact.decision is not computed_decision:
        residual_risks.append("output/trace disagreement detected")
        computed_decision = VerificationDecision.REJECT

    return GroundedVerificationResultV2(
        response_hash=digest("SEMANTIC_RESPONSE", response),
        task_root=task_envelope.task_root,
        response_commitment_hash=response_commitment.commitment_hash,
        claim_spec_hash=claim_spec.claim_spec_hash(),
        dataset_manifest_hash=dataset_manifest.dataset_manifest_hash(),
        environment_manifest_hash=environment_manifest.environment_manifest_hash(),
        authority_record_digest=authority_record.record_digest,
        authority_crypto_verification_digest=(
            authority_crypto_verification.verification_digest
        ),
        authority_verification_receipt_digest=(
            authority_crypto_verification.verification_receipt.receipt_digest
        ),
        claim_disposition=claim_disposition,
        decision=computed_decision,
        outcomes=outcomes,
        integrity_reasons=(),
        residual_risks=_ordered_unique(
            list(residual_risks) + [reason for outcome in outcomes for reason in outcome.reasons]
        ),
    )
