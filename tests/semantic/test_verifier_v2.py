from __future__ import annotations

from datetime import date

import pytest

from poi_mpp.auditor.semantic.authority import (
    IdentityBindingStatus,
    KeyCustodyStatus,
    SemanticAuthorityRecordV1,
    SemanticAuthorityScopeV1,
    TrustIndependenceStatus,
)
from poi_mpp.auditor.semantic.authority_registry import (
    SemanticAuthorityCryptoVerificationV1,
    SemanticAuthorityRegistrySnapshotV1,
)
from poi_mpp.auditor.semantic.models import (
    CalibrationErrorLedgerV1,
    CalibrationLeakageReportV1,
    CalibrationLeakageStatus,
    DevelopmentCalibrationObservationV2,
    EvidenceAnnotation,
    EvidenceAnnotationKind,
    EvidenceRecord,
    GroundedClaim,
    NumericComparator,
    NumericExpectation,
    NumericFact,
    SemanticCalibrationErrorCode,
    SemanticCalibrationErrorFamily,
    SemanticCalibrationFreezeStatus,
    SemanticCalibrationFreezeV2,
    VerificationDecision,
    semantic_calibration_taxonomy_hash,
    semantic_annotation_payload_hash,
    semantic_evidence_content_hash,
)
from poi_mpp.auditor.semantic.policy_v2 import SemanticPolicyV2
from poi_mpp.evidence.claim_spec import (
    ClaimMetricObservation,
    ClaimMetricSpec,
    ClaimDecisionRule,
    ClaimRuleCondition,
    ClaimScope,
    ClaimSpecV2,
    EvidenceMaturity,
    MetricValueSource,
    ThresholdOperator,
)
from poi_mpp.evidence.dataset_manifest_v2 import (
    DatasetAnnotationProvenanceV2,
    DatasetExpectedDecision,
    DatasetExpectedSemanticOutcome,
    DatasetManifestV2,
    DatasetPrivacyStatus,
    DatasetSplitV2,
)
from poi_mpp.evidence.environment_manifest import ExecutionEnvironmentManifestV1
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.protocol.task_envelope import TaskEnvelopeScopeV2, TaskEnvelopeV2
from poi_mpp.protocol.types import TaskClass

from poi_mpp.auditor.semantic.verifier_v2 import (
    SemanticTraceArtifactV1,
    audit_decision_from_verification,
    record_audit_from_verification,
    verify_grounded_v2,
)
from poi_mpp.evidence.canonical import digest
from poi_mpp.protocol.commitment import commit_response
from poi_mpp.protocol.receipt import ActivateReceipt, RecordAudit, RecordDataAvailability
from poi_mpp.protocol.reference_machine import InvalidTransition, transition
from poi_mpp.protocol.types import (
    AuditDecision,
    ModelManifest,
    Receipt,
    ReceiptVerificationMode,
    ReceiptState,
    TaskSpec,
    TransitionContext,
)


def _hash(char: str) -> str:
    return char * 64


def _word(char: str) -> str:
    return f"0x{char * 64}"


def _claim_spec() -> ClaimSpecV2:
    return ClaimSpecV2.model_validate(
        {
            "claim_id": "C3",
            "revision": 2,
            "admissible_wording": "C3-v2 is supported only for the frozen confirmatory scope.",
            "scope": {
                "model_ids": ("phi-mini-1",),
                "task_ids": ("semantic-e3",),
                "environment_ids": ("env-e3-v2",),
                "experiment_ids": ("E3",),
            },
            "evidence_maturity_ceiling": EvidenceMaturity.V4_EXTERNAL.value,
            "allowed_evidence_origins": (EvidenceOrigin.REAL_MODEL_EXECUTION.value,),
            "primary_metrics": (
                {
                    "metric_id": "FAR",
                    "denominator_id": "invalid_items",
                    "minimum_denominator": 2,
                    "confidence_interval_required": True,
                },
                {
                    "metric_id": "FRR",
                    "denominator_id": "valid_items",
                    "minimum_denominator": 2,
                    "confidence_interval_required": True,
                },
                {
                    "metric_id": "COVERAGE",
                    "denominator_id": "all_items",
                    "minimum_denominator": 2,
                    "confidence_interval_required": False,
                },
            ),
            "confidence_interval_method": "WILSON_95",
            "supported_rule": {
                "disposition": "SUPPORTED",
                "reason": "bounded FAR/FRR with useful coverage",
                "conditions": (
                    {
                        "metric_id": "FAR",
                        "source": MetricValueSource.UPPER_CONFIDENCE_BOUND.value,
                        "operator": ThresholdOperator.LE.value,
                        "threshold": 0.25,
                        "minimum_denominator": 2,
                    },
                    {
                        "metric_id": "FRR",
                        "source": MetricValueSource.UPPER_CONFIDENCE_BOUND.value,
                        "operator": ThresholdOperator.LE.value,
                        "threshold": 0.25,
                        "minimum_denominator": 2,
                    },
                    {
                        "metric_id": "COVERAGE",
                        "source": MetricValueSource.POINT_ESTIMATE.value,
                        "operator": ThresholdOperator.GE.value,
                        "threshold": 0.50,
                        "minimum_denominator": 2,
                    },
                ),
            },
            "inconclusive_rule": {
                "disposition": "INCONCLUSIVE",
                "reason": "coverage or precision insufficient",
                "conditions": (
                    {
                        "metric_id": "COVERAGE",
                        "source": MetricValueSource.POINT_ESTIMATE.value,
                        "operator": ThresholdOperator.LT.value,
                        "threshold": 0.50,
                        "minimum_denominator": 2,
                    },
                ),
            },
            "not_supported_rule": {
                "disposition": "NOT_SUPPORTED",
                "reason": "FAR exceeds frozen threshold",
                "conditions": (
                    {
                        "metric_id": "FAR",
                        "source": MetricValueSource.UPPER_CONFIDENCE_BOUND.value,
                        "operator": ThresholdOperator.GT.value,
                        "threshold": 0.25,
                        "minimum_denominator": 2,
                    },
                ),
            },
            "required_artifacts": ("F7", "RAW_E3_EXECUTION", "T4", "T8"),
            "prohibited_generalizations": (
                "C3-v2 establishes general semantic reliability across all models.",
            ),
        }
    )


def _dataset_manifest(evidence: tuple[EvidenceRecord, ...]) -> DatasetManifestV2:
    records = []
    for index, evidence_record in enumerate(evidence, start=1):
        annotation_hash = semantic_annotation_payload_hash(
            evidence_id=evidence_record.evidence_id,
            citation_id=evidence_record.citation_id,
            source_family=evidence_record.source_family,
            annotations=evidence_record.annotations,
            numeric_facts=evidence_record.numeric_facts,
        )
        records.append(
            {
                "record_id": evidence_record.evidence_id,
                "item_path": f"items/{evidence_record.evidence_id}.json",
                "label_path": f"labels/{evidence_record.evidence_id}.json",
                "item_hash": evidence_record.content_hash,
                "label_hash": annotation_hash,
                "content_hash": evidence_record.content_hash,
                "split": DatasetSplitV2.CONFIRMATORY.value,
                "license_id": "CC-BY-4.0",
                "privacy_status": DatasetPrivacyStatus.AUTHORIZED_PUBLIC.value,
                "expected_decision": DatasetExpectedDecision.ACCEPT.value,
                "expected_semantic_outcome": DatasetExpectedSemanticOutcome.SUPPORTED_GROUNDS.value,
                "error_family": "frozen-case",
                "subgroup": "baseline",
                "difficulty": "medium",
                "deduplication_group": f"g{index}",
                "annotation": {
                    "annotation_scope": "semantic-e3",
                    "annotation_hash": annotation_hash,
                    "agreement_fraction": 1.0,
                },
                "evidence_origin": evidence_record.origin.value,
            }
        )
    return DatasetManifestV2.model_validate(
        {
            "dataset_id": "e3-confirmatory-v2",
            "split": DatasetSplitV2.CONFIRMATORY.value,
            "records": tuple(records),
        }
    )


def _environment_manifest() -> ExecutionEnvironmentManifestV1:
    return ExecutionEnvironmentManifestV1.model_validate(
        {
            "environment_id": "env-e3-v2",
            "model": {
                "model_id": "phi-mini-1",
                "model_revision": "a" * 40,
                "model_weights_hash": _hash("9"),
                "tokenizer_id": "phi-mini-1-tokenizer",
                "tokenizer_revision": "b" * 40,
                "tokenizer_hash": _hash("a"),
                "parameter_count_billions": 3.0,
            },
            "runtime": {
                "python_version": "3.12.4",
                "framework_name": "transformers",
                "framework_version": "4.45.0",
                "dependency_lock_hash": _hash("b"),
                "environment_sbom_digest": _hash("c"),
            },
            "hardware": {
                "accelerator_label": "MPS",
                "accelerator_count": 1,
                "driver_version": "local",
            },
            "deterministic": {
                "global_seed": 7,
                "inference_seed": 7,
                "local_files_only": True,
                "hash_check_enforced": True,
            },
            "generation": {
                "do_sample": False,
                "temperature": 0.0,
                "top_p": 1.0,
                "max_new_tokens": 256,
            },
            "script_hashes": {
                "runner": _hash("d"),
                "artifact_exporter": _hash("e"),
            },
            "config_hashes": {
                "experiment_protocol": _hash("f"),
                "generation_config": _hash("0"),
            },
        }
    )


def _authority_record(
    claim_spec: ClaimSpecV2,
    dataset_manifest: DatasetManifestV2,
    environment_manifest: ExecutionEnvironmentManifestV1,
    *,
    decision: str = "APPROVED",
    allowed_metric_ids: tuple[str, ...] | None = None,
    allowed_artifact_ids: tuple[str, ...] | None = None,
    identity_status: IdentityBindingStatus = IdentityBindingStatus.VERIFIED_ACCOUNTABLE_IDENTITY,
    independence_status: TrustIndependenceStatus = TrustIndependenceStatus.VERIFIED_OUT_OF_BAND,
    key_custody_status: KeyCustodyStatus = KeyCustodyStatus.VERIFIED_OUT_OF_BAND,
    unresolved_checks: tuple[str, ...] = (),
    semantic_policy_hash: str = "3" * 64,
) -> SemanticAuthorityRecordV1:
    return SemanticAuthorityRecordV1.model_validate(
        {
            "authority_id": "AUTHORITY_E3_V2",
            "key_id": "ssh-ed25519:authority-e3-v2",
            "accountable_identity_reference": "orcid:0000-0001-2345-6789",
            "registry_revision": 11,
            "registry_snapshot_hash": _hash("1"),
            "signature_namespace": "file",
            "signature_reference": "POI_E3_EXTERNAL/signatures/e3-v2.sig",
            "detached_signature_sha256": _hash("2"),
            "decision": decision,
            "valid_from": "2026-08-20",
            "valid_until": "2026-08-31",
            "revocation_state": "ACTIVE",
            "scope": {
                "experiment_id": "E3",
                "claim_id": claim_spec.claim_id,
                "claim_spec_hash": claim_spec.claim_spec_hash(),
                "dataset_manifest_hash": dataset_manifest.dataset_manifest_hash(),
                "semantic_policy_hash": semantic_policy_hash,
                "runtime_environment_hash": environment_manifest.environment_manifest_hash(),
                "evidence_origin": EvidenceOrigin.REAL_MODEL_EXECUTION.value,
                "use_mode": "CONFIRMATORY_PUBLICATION",
                "allowed_metric_ids": allowed_metric_ids or ("COVERAGE", "FAR", "FRR"),
                "allowed_artifact_ids": allowed_artifact_ids or ("F7", "RAW_E3_EXECUTION", "T4", "T8"),
            },
            "identity_binding_status": identity_status,
            "independence_status": independence_status,
            "key_custody_status": key_custody_status,
            "independence_basis": "different institution, no authorship overlap",
            "unresolved_out_of_band_checks": unresolved_checks,
        }
    )


def _bind_authority_registry(
    record: SemanticAuthorityRecordV1,
) -> tuple[
    SemanticAuthorityRecordV1,
    SemanticAuthorityRegistrySnapshotV1,
    SemanticAuthorityCryptoVerificationV1,
]:
    snapshot_hash = SemanticAuthorityRegistrySnapshotV1.preview_snapshot_hash(
        registry_revision=record.registry_revision,
        authority_records=(record,),
    )
    bound_record = SemanticAuthorityRecordV1.model_validate(
        {
            **record.model_dump(mode="python"),
            "registry_snapshot_hash": snapshot_hash,
        }
    )
    snapshot = SemanticAuthorityRegistrySnapshotV1.model_validate(
        {
            "registry_revision": bound_record.registry_revision,
            "authority_records": (bound_record,),
        }
    )
    crypto = SemanticAuthorityCryptoVerificationV1.model_validate(
        {
            "authority_id": bound_record.authority_id,
            "key_id": bound_record.key_id,
            "record_digest": bound_record.record_digest,
            "registry_revision": snapshot.registry_revision,
            "registry_snapshot_hash": snapshot.snapshot_hash,
            "cryptographic_validity_verified": True,
            "verification_receipt": {
                "verifier_id": "canonical-external-authority-verifier-v1",
                "verification_method": "OPENSSH_DETACHED_SIGNATURE",
                "verified_on": "2026-08-24",
                "authority_record_digest": bound_record.record_digest,
                "key_id": bound_record.key_id,
                "authority_record_sha256": _hash("7"),
                "detached_signature_sha256": bound_record.detached_signature_sha256,
                "allowed_signers_sha256": _hash("8"),
                "verifier_output_sha256": _hash("9"),
            },
        }
    )
    return bound_record, snapshot, crypto


def _semantic_policy(
    *,
    claim_spec: ClaimSpecV2,
    dataset_manifest: DatasetManifestV2,
    environment_manifest: ExecutionEnvironmentManifestV1,
    registry_snapshot_hash: str,
    calibration_freeze: SemanticCalibrationFreezeV2,
    calibration_error_ledger: CalibrationErrorLedgerV1,
    confirmatory_leakage_report: CalibrationLeakageReportV1,
) -> SemanticPolicyV2:
    return SemanticPolicyV2.model_validate(
        {
            "claim_spec_hash": claim_spec.claim_spec_hash(),
            "dataset_manifest_hash": dataset_manifest.dataset_manifest_hash(),
            "authority_registry_snapshot_hash": registry_snapshot_hash,
            "model_manifest_hash": _hash("4"),
            "runtime_environment_hash": environment_manifest.environment_manifest_hash(),
            "task_payload_hash": _hash("b"),
            "prompt_template_hash": _hash("5"),
            "calibration_hash": calibration_freeze.content_hash,
            "calibration_error_ledger_hash": calibration_error_ledger.content_hash,
            "confirmatory_leakage_report_hash": confirmatory_leakage_report.content_hash,
            "mode": "CONFIRMATORY",
            "calibration_split": "DEVELOPMENT",
            "support_threshold": calibration_freeze.support_threshold,
            "reject_threshold": calibration_freeze.reject_threshold,
            "minimum_calibrated_confidence": calibration_freeze.minimum_calibrated_confidence,
            "freeze_locked": True,
            "require_output_trace_agreement": True,
            "allowed_evidence_origins": ("REAL_MODEL_EXECUTION",),
            "allowed_metric_ids": tuple(
                metric.metric_id for metric in claim_spec.primary_metrics
            ),
            "required_artifact_ids": claim_spec.required_artifacts,
            "accept_outcomes": ("SUPPORTED",),
            "reject_outcomes": (
                "CONTRADICTORY",
                "UNSUPPORTED",
                "NUMERICAL_ERROR",
                "CITATION_ERROR",
            ),
            "abstain_outcomes": ("PARTIAL", "AMBIGUOUS"),
        }
    )


def _task_envelope(
    claim_spec: ClaimSpecV2,
    dataset_manifest: DatasetManifestV2,
    environment_manifest: ExecutionEnvironmentManifestV1,
    authority_record: SemanticAuthorityRecordV1,
    *,
    claim_hash: str | None = None,
    dataset_hash: str | None = None,
    runtime_hash: str | None = None,
    policy_hash: str | None = None,
    registry_hash: str | None = None,
    model_hash: str | None = None,
    origin: str = "REAL_MODEL_EXECUTION",
) -> TaskEnvelopeV2:
    return TaskEnvelopeV2.model_validate(
        {
            "claim_spec_hash": _word("a") if claim_hash is None else f"0x{claim_hash}",
            "task_payload_hash": _word("b"),
            "semantic_policy_hash": _word("3") if policy_hash is None else f"0x{policy_hash}",
            "dataset_manifest_hash": _word("c") if dataset_hash is None else f"0x{dataset_hash}",
            "authority_registry_snapshot_hash": _word("1") if registry_hash is None else f"0x{registry_hash}",
            "model_manifest_hash": _word("4") if model_hash is None else f"0x{model_hash}",
            "runtime_environment_hash": _word("d") if runtime_hash is None else f"0x{runtime_hash}",
            "evidence_origin_policy_hash": _word("e"),
            "experiment_protocol_hash": _word("f"),
            "epoch": 7,
            "expiry": 500,
            "scope": TaskEnvelopeScopeV2(
                publication_scope="E3_CONFIRMATORY_PUBLICATION_V2",
                authorization_scope="PUBLICATION_EVIDENCE_AUTHORIZED",
                evidence_origin=origin,
                task_class=TaskClass.CONSENSUS,
            ),
        }
    ).model_copy(
        update={
            "claim_spec_hash": f"0x{claim_spec.claim_spec_hash()}" if claim_hash is None else f"0x{claim_hash}",
            "dataset_manifest_hash": f"0x{dataset_manifest.dataset_manifest_hash()}" if dataset_hash is None else f"0x{dataset_hash}",
            "runtime_environment_hash": f"0x{environment_manifest.environment_manifest_hash()}" if runtime_hash is None else f"0x{runtime_hash}",
            "semantic_policy_hash": f"0x{authority_record.scope.semantic_policy_hash}" if policy_hash is None else f"0x{policy_hash}",
            "authority_registry_snapshot_hash": f"0x{authority_record.registry_snapshot_hash}" if registry_hash is None else f"0x{registry_hash}",
            "model_manifest_hash": f"0x{_hash('4')}" if model_hash is None else f"0x{model_hash}",
        }
    )


def _grounded_claim(*citation_ids: str, numeric_expectation: NumericExpectation | None = None) -> GroundedClaim:
    return GroundedClaim(
        claim_id="grounded-1",
        text="Grounded semantic claim",
        cited_citation_ids=citation_ids,
        numeric_expectation=numeric_expectation,
    )


def _record(
    citation_id: str,
    *,
    origin: EvidenceOrigin = EvidenceOrigin.REAL_MODEL_EXECUTION,
    annotations: tuple[EvidenceAnnotation, ...] = (),
    numeric_facts: tuple[NumericFact, ...] = (),
) -> EvidenceRecord:
    content = f"evidence::{citation_id}"
    return EvidenceRecord.model_validate(
        {
            "evidence_id": f"evidence-{citation_id}",
            "citation_id": citation_id,
            "source_family": "paper-a",
            "origin": origin,
            "content": content,
            "content_hash": semantic_evidence_content_hash(
                citation_id=citation_id,
                content=content,
                source_family="paper-a",
            ),
            "annotations": annotations,
            "numeric_facts": numeric_facts,
        }
    )


def _leakage_report(
    dataset_manifest: DatasetManifestV2,
    *,
    status: CalibrationLeakageStatus = CalibrationLeakageStatus.NOT_YET_ASSESSABLE,
    confirmatory_manifest_hash: str | None = None,
) -> CalibrationLeakageReportV1:
    payload: dict[str, object] = {
        "development_manifest_hash": _hash("8"),
        "confirmatory_manifest_hash": confirmatory_manifest_hash,
        "record_overlap_count": 0,
        "content_overlap_count": 0,
        "item_overlap_count": 0,
        "label_overlap_count": 0,
        "dedup_overlap_count": 0,
        "source_overlap_count": 0,
        "source_family_overlap_count": 0,
        "near_duplicate_overlap_count": 0,
        "status": status.value,
    }
    return CalibrationLeakageReportV1.model_validate(payload)


def _confirmatory_leakage_report(
    dataset_manifest: DatasetManifestV2,
    *,
    status: CalibrationLeakageStatus = CalibrationLeakageStatus.CLEAR,
    confirmatory_manifest_hash: str | None = None,
) -> CalibrationLeakageReportV1:
    development_payload = _leakage_report(
        dataset_manifest,
        status=CalibrationLeakageStatus.NOT_YET_ASSESSABLE,
    ).model_dump(mode="python")
    development_payload.pop("content_hash", None)
    return CalibrationLeakageReportV1.model_validate(
        {
            **development_payload,
            "confirmatory_manifest_hash": (
                dataset_manifest.dataset_manifest_hash()
                if confirmatory_manifest_hash is None
                else confirmatory_manifest_hash
            ),
            "status": status.value,
            "record_overlap_count": 1 if status is CalibrationLeakageStatus.BLOCKED else 0,
        }
    )


def _calibration_error_ledger(
    development_manifest_hash: str,
    *,
    origin: EvidenceOrigin = EvidenceOrigin.REAL_MODEL_EXECUTION,
) -> CalibrationErrorLedgerV1:
    return CalibrationErrorLedgerV1.model_validate(
        {
            "dataset_manifest_hash": development_manifest_hash,
            "rows": (
                DevelopmentCalibrationObservationV2(
                    record_id="dev-row-1",
                    expected_decision=VerificationDecision.ACCEPT,
                    observed_decision=VerificationDecision.ACCEPT,
                    support_fraction=0.90,
                    calibrated_confidence=0.90,
                    error_code=SemanticCalibrationErrorCode.CORRECT_ACCEPT,
                    error_family=SemanticCalibrationErrorFamily.DECISION,
                    attack_family="BASELINE",
                    subgroup="all",
                    difficulty="standard",
                    origin=origin,
                ),
            ),
        }
    )


def _calibration_freeze(
    claim_spec: ClaimSpecV2,
    environment_manifest: ExecutionEnvironmentManifestV1,
    development_leakage_report: CalibrationLeakageReportV1,
    calibration_error_ledger: CalibrationErrorLedgerV1,
    *,
    support_threshold: float = 0.75,
    reject_threshold: float = 0.25,
    minimum_calibrated_confidence: float = 0.60,
) -> SemanticCalibrationFreezeV2:
    return SemanticCalibrationFreezeV2.model_validate(
        {
            "status": SemanticCalibrationFreezeStatus.FROZEN_DEVELOPMENT_ONLY.value,
            "development_dataset_manifest_hash": development_leakage_report.development_manifest_hash,
            "claim_spec_hash": claim_spec.claim_spec_hash(),
            "prompt_template_hash": _hash("5"),
            "model_manifest_hash": _hash("4"),
            "runtime_environment_hash": environment_manifest.environment_manifest_hash(),
            "output_schema_hash": _hash("1"),
            "contradiction_policy_hash": _hash("2"),
            "error_recovery_policy_hash": _hash("3"),
            "accept_example_count": 50,
            "reject_example_count": 50,
            "abstain_example_count": 20,
            "error_taxonomy_version": "POI_MPP_SEMANTIC_CALIBRATION_ERROR_TAXONOMY_V1",
            "error_taxonomy_hash": semantic_calibration_taxonomy_hash(),
            "support_threshold": support_threshold,
            "reject_threshold": reject_threshold,
            "minimum_calibrated_confidence": minimum_calibrated_confidence,
            "selection_rule_id": "TRI_STATE_ACCURACY_FAIL_CLOSED_V1",
            "example_count": 120,
            "error_ledger_hash": calibration_error_ledger.content_hash,
            "leakage_report_hash": development_leakage_report.content_hash,
        }
    )


def _calibrated_confidence() -> float:
    return 0.90


def _pending_receipt(
    *,
    semantic_task_root: str | None = None,
    semantic_response_hash: str | None = None,
    commitment_hash: str | None = None,
) -> Receipt:
    return Receipt(
        receipt_id=1,
        task_id=1,
        worker_id="0x0000000000000000000000000000000000002001",
        commitment_hash=commitment_hash or "0x" + "11" * 32,
        audit_id="0x" + "22" * 32,
        state=ReceiptState.PENDING,
        epoch_issued=7,
        challenge_deadline=129,
        nullifier="0x" + "66" * 32,
        audit_decision=None,
        audit_accepted=False,
        da_decision=None,
        data_availability_passed=False,
        activated_epoch=None,
        challenge_reason=None,
        slash_reason=None,
        semantic_task_root=semantic_task_root,
        semantic_response_hash=semantic_response_hash,
        audit_verification_result_digest=None,
        verification_mode=(
            ReceiptVerificationMode.SEMANTIC_PUBLICATION
            if semantic_task_root is not None
            else ReceiptVerificationMode.LEGACY_PROTOCOL
        ),
    )


def _mature_context() -> TransitionContext:
    return TransitionContext(
        current_height=129,
        current_epoch=8,
        used_nullifiers=frozenset(),
    )


def _supported_metrics() -> dict[str, ClaimMetricObservation]:
    return {
        "FAR": ClaimMetricObservation(metric_id="FAR", point_estimate=0.10, denominator=20, confidence_interval=(0.02, 0.20)),
        "FRR": ClaimMetricObservation(metric_id="FRR", point_estimate=0.10, denominator=20, confidence_interval=(0.02, 0.20)),
        "COVERAGE": ClaimMetricObservation(metric_id="COVERAGE", point_estimate=0.875, denominator=40),
    }


def _bind_trace(
    kwargs: dict[str, object],
    decision: VerificationDecision,
    *,
    calibrated_confidence: float | None = None,
) -> None:
    confidence = _calibrated_confidence() if calibrated_confidence is None else calibrated_confidence
    response_hash = digest("SEMANTIC_RESPONSE", kwargs["response"])
    trace_artifact = SemanticTraceArtifactV1.create(
        task_root=kwargs["task_envelope"].task_root,
        response_hash=response_hash,
        semantic_policy_hash=kwargs["semantic_policy"].policy_hash(),
        dataset_manifest_hash=kwargs["dataset_manifest"].dataset_manifest_hash(),
        authority_record_digest=kwargs["authority_record"].record_digest,
        decision=decision,
        calibrated_confidence=confidence,
    )
    protocol_task = TaskSpec(
        task_id=1,
        task_root=kwargs["task_envelope"].task_root,
        worker_id="0x0000000000000000000000000000000000002001",
        task_class=TaskClass.CONSENSUS,
        active=True,
        registered=True,
        credit_budget=90,
        epoch=7,
        deadline=500,
        commitment_height=120,
        commitment_finality_depth=5,
        challenge_window_blocks=9,
        audit_domain_size=16,
    )
    model = ModelManifest(
        model_root=_word("b"),
        runtime_root=_word("c"),
        model_manifest_hash=f"0x{kwargs['model_manifest_hash']}",
        assurance_class=1,
    )
    response_commitment = commit_response(
        task=protocol_task,
        model=model,
        response_hash=f"0x{response_hash}",
        trace_root=f"0x{trace_artifact.trace_root}",
        evidence_root=_word("d"),
        artifact_root=_word("e"),
        nonce=bytes.fromhex("55" * 32),
    )
    kwargs["trace_artifact"] = trace_artifact
    kwargs["protocol_task"] = protocol_task
    kwargs["protocol_model"] = model
    kwargs["response_commitment"] = response_commitment


def _base_kwargs():
    claim_spec = _claim_spec()
    evidence = (
        _record(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="grounded-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="verifiable support",
                ),
            ),
            numeric_facts=(
                NumericFact(
                    claim_id="grounded-1",
                    metric="accuracy",
                    value="0.99",
                    unit="ratio",
                ),
            ),
        ),
    )
    dataset_manifest = _dataset_manifest(evidence)
    environment_manifest = _environment_manifest()
    development_leakage_report = _leakage_report(dataset_manifest)
    calibration_error_ledger = _calibration_error_ledger(
        development_leakage_report.development_manifest_hash
    )
    confirmatory_leakage_report = _confirmatory_leakage_report(dataset_manifest)
    calibration_freeze = _calibration_freeze(
        claim_spec,
        environment_manifest,
        development_leakage_report,
        calibration_error_ledger,
    )
    preliminary_authority = _authority_record(
        claim_spec,
        dataset_manifest,
        environment_manifest,
    )
    registry_snapshot_hash = SemanticAuthorityRegistrySnapshotV1.preview_snapshot_hash(
        registry_revision=preliminary_authority.registry_revision,
        authority_records=(preliminary_authority,),
    )
    semantic_policy = _semantic_policy(
        claim_spec=claim_spec,
        dataset_manifest=dataset_manifest,
        environment_manifest=environment_manifest,
        registry_snapshot_hash=registry_snapshot_hash,
        calibration_freeze=calibration_freeze,
        calibration_error_ledger=calibration_error_ledger,
        confirmatory_leakage_report=confirmatory_leakage_report,
    )
    authority_record, registry_snapshot, authority_crypto = _bind_authority_registry(
        _authority_record(
            claim_spec,
            dataset_manifest,
            environment_manifest,
            semantic_policy_hash=semantic_policy.policy_hash(),
        )
    )
    kwargs = {
        "claim_spec": claim_spec,
        "dataset_manifest": dataset_manifest,
        "environment_manifest": environment_manifest,
        "authority_record": authority_record,
        "task_envelope": _task_envelope(claim_spec, dataset_manifest, environment_manifest, authority_record),
        "claims": (
            _grounded_claim(
                "cite-1",
                numeric_expectation=NumericExpectation(
                    metric="accuracy",
                    comparator=NumericComparator.AT_LEAST,
                    value="0.95",
                    unit="ratio",
                ),
            ),
        ),
        "evidence": evidence,
        "calibration_freeze": calibration_freeze,
        "development_leakage_report": development_leakage_report,
        "calibration_error_ledger": calibration_error_ledger,
        "confirmatory_leakage_report": confirmatory_leakage_report,
        "metrics": _supported_metrics(),
        "model_manifest_hash": _hash("4"),
        "registry_snapshot": registry_snapshot,
        "semantic_policy": semantic_policy,
        "prompt_template_hash": _hash("5"),
        "statement": claim_spec.admissible_wording,
        "response": "semantic-response",
        "authority_crypto_verification": authority_crypto,
        "on_date": date(2026, 8, 24),
    }
    _bind_trace(kwargs, VerificationDecision.ACCEPT)
    return kwargs


def _rebind_dataset(kwargs: dict[str, object]) -> None:
    evidence = tuple(kwargs["evidence"])
    dataset_manifest = _dataset_manifest(evidence)
    development_leakage_report = _leakage_report(dataset_manifest)
    calibration_error_ledger = _calibration_error_ledger(
        development_leakage_report.development_manifest_hash
    )
    confirmatory_leakage_report = _confirmatory_leakage_report(dataset_manifest)
    calibration_freeze = _calibration_freeze(
        kwargs["claim_spec"],
        kwargs["environment_manifest"],
        development_leakage_report,
        calibration_error_ledger,
        support_threshold=kwargs["calibration_freeze"].support_threshold,
        reject_threshold=kwargs["calibration_freeze"].reject_threshold,
        minimum_calibrated_confidence=kwargs["calibration_freeze"].minimum_calibrated_confidence,
    )
    preliminary_authority = _authority_record(
        kwargs["claim_spec"],
        dataset_manifest,
        kwargs["environment_manifest"],
    )
    registry_snapshot_hash = SemanticAuthorityRegistrySnapshotV1.preview_snapshot_hash(
        registry_revision=preliminary_authority.registry_revision,
        authority_records=(preliminary_authority,),
    )
    semantic_policy = _semantic_policy(
        claim_spec=kwargs["claim_spec"],
        dataset_manifest=dataset_manifest,
        environment_manifest=kwargs["environment_manifest"],
        registry_snapshot_hash=registry_snapshot_hash,
        calibration_freeze=calibration_freeze,
        calibration_error_ledger=calibration_error_ledger,
        confirmatory_leakage_report=confirmatory_leakage_report,
    )
    authority_record, registry_snapshot, authority_crypto = _bind_authority_registry(
        _authority_record(
            kwargs["claim_spec"],
            dataset_manifest,
            kwargs["environment_manifest"],
            semantic_policy_hash=semantic_policy.policy_hash(),
        )
    )
    kwargs["dataset_manifest"] = dataset_manifest
    kwargs["development_leakage_report"] = development_leakage_report
    kwargs["confirmatory_leakage_report"] = confirmatory_leakage_report
    kwargs["calibration_error_ledger"] = calibration_error_ledger
    kwargs["calibration_freeze"] = calibration_freeze
    kwargs["authority_record"] = authority_record
    kwargs["registry_snapshot"] = registry_snapshot
    kwargs["authority_crypto_verification"] = authority_crypto
    kwargs["semantic_policy"] = semantic_policy
    kwargs["task_envelope"] = _task_envelope(
        kwargs["claim_spec"],
        dataset_manifest,
        kwargs["environment_manifest"],
        authority_record,
    )
    prior_decision = kwargs["trace_artifact"].decision
    _bind_trace(
        kwargs,
        prior_decision,
        calibrated_confidence=kwargs["trace_artifact"].calibrated_confidence,
    )


def _replace_authority(
    kwargs: dict[str, object],
    raw_record: SemanticAuthorityRecordV1,
) -> None:
    authority_record, registry_snapshot, authority_crypto = _bind_authority_registry(
        raw_record
    )
    kwargs["authority_record"] = authority_record
    kwargs["registry_snapshot"] = registry_snapshot
    kwargs["authority_crypto_verification"] = authority_crypto
    kwargs["task_envelope"] = _task_envelope(
        kwargs["claim_spec"],
        kwargs["dataset_manifest"],
        kwargs["environment_manifest"],
        authority_record,
    )
    prior_decision = kwargs["trace_artifact"].decision
    _bind_trace(
        kwargs,
        prior_decision,
        calibrated_confidence=kwargs["trace_artifact"].calibrated_confidence,
    )


def test_verify_grounded_v2_accepts_when_all_publication_gates_and_support_pass():
    result = verify_grounded_v2(**_base_kwargs())

    assert result.decision is VerificationDecision.ACCEPT
    assert result.claim_disposition.value == "SUPPORTED"
    assert result.outcomes[0].outcome.value == "SUPPORTED"


def test_verify_grounded_v2_rejects_contradicted_evidence():
    kwargs = _base_kwargs()
    _bind_trace(kwargs, VerificationDecision.REJECT)
    kwargs["evidence"] = (
        _record(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="grounded-1",
                    kind=EvidenceAnnotationKind.CONTRADICTS,
                    reason="direct contradiction",
                ),
            ),
        ),
    )
    _rebind_dataset(kwargs)

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert result.outcomes[0].outcome.value == "CONTRADICTORY"


def test_verify_grounded_v2_rejects_numeric_expectation_mismatch():
    kwargs = _base_kwargs()
    _bind_trace(kwargs, VerificationDecision.REJECT)
    kwargs["evidence"] = (
        _record(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="grounded-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="support",
                ),
            ),
            numeric_facts=(
                NumericFact(
                    claim_id="grounded-1",
                    metric="accuracy",
                    value="0.80",
                    unit="ratio",
                ),
            ),
        ),
    )
    _rebind_dataset(kwargs)

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert result.outcomes[0].outcome.value == "NUMERICAL_ERROR"


def test_verify_grounded_v2_abstains_for_partial_support_below_threshold():
    kwargs = _base_kwargs()
    _bind_trace(kwargs, VerificationDecision.ABSTAIN)
    kwargs["claims"] = (_grounded_claim("cite-1", "cite-2"),)
    kwargs["evidence"] = (
        _record(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="grounded-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="partial support",
                ),
            ),
        ),
        _record("cite-2"),
    )
    _rebind_dataset(kwargs)

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.ABSTAIN
    assert result.outcomes[0].outcome.value == "PARTIAL"


def test_verify_grounded_v2_rejects_hash_binding_drift():
    kwargs = _base_kwargs()
    kwargs["task_envelope"] = _task_envelope(
        kwargs["claim_spec"],
        kwargs["dataset_manifest"],
        kwargs["environment_manifest"],
        kwargs["authority_record"],
        claim_hash=_hash("f"),
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "claim_spec_hash" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_non_real_or_synthetic_evidence():
    kwargs = _base_kwargs()
    kwargs["evidence"] = (
        _record(
            "cite-1",
            origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
            annotations=(
                EvidenceAnnotation(
                    claim_id="grounded-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="synthetic support",
                ),
            ),
        ),
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "synthetic" in " ".join(result.integrity_reasons).lower()


def test_verify_grounded_v2_rejects_when_authority_is_not_publication_eligible():
    kwargs = _base_kwargs()
    _replace_authority(
        kwargs,
        _authority_record(
            kwargs["claim_spec"],
            kwargs["dataset_manifest"],
            kwargs["environment_manifest"],
            identity_status=IdentityBindingStatus.UNVERIFIED_OUT_OF_BAND,
            independence_status=TrustIndependenceStatus.UNVERIFIED_OUT_OF_BAND,
            key_custody_status=KeyCustodyStatus.UNVERIFIED_OUT_OF_BAND,
            unresolved_checks=("identity pending",),
            semantic_policy_hash=kwargs["semantic_policy"].policy_hash(),
        ),
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "identity" in " ".join(result.integrity_reasons).lower()


def test_verify_grounded_v2_rejects_limited_scope_mismatch():
    kwargs = _base_kwargs()
    _replace_authority(
        kwargs,
        _authority_record(
            kwargs["claim_spec"],
            kwargs["dataset_manifest"],
            kwargs["environment_manifest"],
            decision="LIMITED_SCOPE",
            allowed_metric_ids=("FAR",),
            allowed_artifact_ids=("T8",),
            semantic_policy_hash=kwargs["semantic_policy"].policy_hash(),
        ),
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "exact signed metric scope" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_output_trace_disagreement():
    kwargs = _base_kwargs()
    _bind_trace(kwargs, VerificationDecision.REJECT)

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "output decision and trace decision must agree" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_trace_artifact_not_bound_by_commitment():
    kwargs = _base_kwargs()
    kwargs["trace_artifact"] = kwargs["trace_artifact"].model_copy(
        update={"decision": VerificationDecision.REJECT}
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "trace_root mismatch" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_response_commitment_from_different_task_root():
    kwargs = _base_kwargs()
    wrong_task = kwargs["protocol_task"].model_copy(update={"task_root": _word("9")})
    kwargs["response_commitment"] = commit_response(
        task=wrong_task,
        model=kwargs["protocol_model"],
        response_hash=f"0x{kwargs['trace_artifact'].response_hash}",
        trace_root=f"0x{kwargs['trace_artifact'].trace_root}",
        evidence_root=_word("d"),
        artifact_root=_word("e"),
        nonce=bytes.fromhex("55" * 32),
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "task_commitment mismatch" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_unbound_caller_supplied_annotations():
    kwargs = _base_kwargs()
    kwargs["evidence"] = (
        _record(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="grounded-1",
                    kind=EvidenceAnnotationKind.CONTRADICTS,
                    reason="unbound caller mutation",
                ),
            ),
        ),
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "annotation hash mismatch" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_prompt_policy_binding_drift():
    kwargs = _base_kwargs()
    kwargs["prompt_template_hash"] = _hash("6")

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "semantic policy binding failure" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_abstains_when_confidence_is_below_frozen_threshold():
    kwargs = _base_kwargs()
    _bind_trace(
        kwargs,
        VerificationDecision.ABSTAIN,
        calibrated_confidence=0.50,
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.ABSTAIN
    assert result.integrity_reasons == ()


def test_verify_grounded_v2_rejects_threshold_drift_between_policy_and_freeze():
    kwargs = _base_kwargs()
    kwargs["semantic_policy"] = _semantic_policy(
        claim_spec=kwargs["claim_spec"],
        dataset_manifest=kwargs["dataset_manifest"],
        environment_manifest=kwargs["environment_manifest"],
        registry_snapshot_hash=kwargs["registry_snapshot"].snapshot_hash,
        calibration_freeze=kwargs["calibration_freeze"].model_copy(
            update={"support_threshold": 0.80}
        ),
        calibration_error_ledger=kwargs["calibration_error_ledger"],
        confirmatory_leakage_report=kwargs["confirmatory_leakage_report"],
    )
    _replace_authority(
        kwargs,
        _authority_record(
            kwargs["claim_spec"],
            kwargs["dataset_manifest"],
            kwargs["environment_manifest"],
            semantic_policy_hash=kwargs["semantic_policy"].policy_hash(),
        ),
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "calibration freeze binding failure" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_non_clear_leakage_report():
    kwargs = _base_kwargs()
    kwargs["confirmatory_leakage_report"] = _confirmatory_leakage_report(
        kwargs["dataset_manifest"],
        status=CalibrationLeakageStatus.BLOCKED,
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "leakage report status must be CLEAR" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_confirmatory_manifest_hash_mismatch():
    kwargs = _base_kwargs()
    kwargs["confirmatory_leakage_report"] = _confirmatory_leakage_report(
        kwargs["dataset_manifest"],
        confirmatory_manifest_hash=_hash("f"),
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "confirmatory manifest hash mismatch" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_freeze_hash_drift():
    kwargs = _base_kwargs()
    kwargs["calibration_freeze"] = kwargs["calibration_freeze"].model_copy(
        update={"leakage_report_hash": _hash("f")}
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "freeze leakage_report_hash mismatch" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_error_ledger_hash_drift():
    kwargs = _base_kwargs()
    kwargs["calibration_freeze"] = kwargs["calibration_freeze"].model_copy(
        update={"error_ledger_hash": _hash("f")}
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "freeze error_ledger_hash mismatch" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_non_real_error_ledger_rows():
    kwargs = _base_kwargs()
    kwargs["calibration_error_ledger"] = _calibration_error_ledger(
        kwargs["development_leakage_report"].development_manifest_hash,
        origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    )
    kwargs["semantic_policy"] = _semantic_policy(
        claim_spec=kwargs["claim_spec"],
        dataset_manifest=kwargs["dataset_manifest"],
        environment_manifest=kwargs["environment_manifest"],
        registry_snapshot_hash=kwargs["registry_snapshot"].snapshot_hash,
        calibration_freeze=kwargs["calibration_freeze"],
        calibration_error_ledger=kwargs["calibration_error_ledger"],
        confirmatory_leakage_report=kwargs["confirmatory_leakage_report"],
    )
    _replace_authority(
        kwargs,
        _authority_record(
            kwargs["claim_spec"],
            kwargs["dataset_manifest"],
            kwargs["environment_manifest"],
            semantic_policy_hash=kwargs["semantic_policy"].policy_hash(),
        ),
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "error ledger rows must remain REAL_MODEL_EXECUTION" in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_rejects_trace_confidence_tampering():
    kwargs = _base_kwargs()
    kwargs["trace_artifact"] = kwargs["trace_artifact"].model_copy(
        update={"calibrated_confidence": 0.10}
    )

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert "trace_root mismatch" in " ".join(result.integrity_reasons)


@pytest.mark.parametrize(
    ("field", "expected_reason"),
    (
        ("claims", "requires at least one claim"),
        ("evidence", "requires at least one evidence record"),
    ),
)
def test_verify_grounded_v2_rejects_empty_scientific_inputs(field, expected_reason):
    kwargs = _base_kwargs()
    kwargs[field] = ()

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert expected_reason in " ".join(result.integrity_reasons)


def test_verify_grounded_v2_returns_structured_reject_for_invalid_claim_wording():
    kwargs = _base_kwargs()
    kwargs["statement"] = "A broader unsupported semantic reliability claim."

    result = verify_grounded_v2(**kwargs)

    assert result.decision is VerificationDecision.REJECT
    assert result.claim_disposition.value == "INCONCLUSIVE"
    assert "claim adjudication failure" in " ".join(result.integrity_reasons)


def test_semantic_v2_receipt_gate_activates_only_after_accept_and_da():
    result = verify_grounded_v2(**_base_kwargs())
    receipt = _pending_receipt(
        semantic_task_root=result.task_root,
        semantic_response_hash=result.response_hash,
        commitment_hash=result.response_commitment_hash,
    )
    mature_context = _mature_context()

    audited = transition(
        receipt,
        record_audit_from_verification(result),
        mature_context,
        semantic_verification_result=result,
    )
    available = transition(
        audited,
        RecordDataAvailability(available=True),
        mature_context,
    )
    active = transition(available, ActivateReceipt(), mature_context)

    assert active.state is ReceiptState.ACTIVE
    assert active.audit_verification_result_digest == f"0x{result.result_digest}"


def test_semantic_v2_receipt_gate_rejects_trace_mismatch_and_prevents_activation():
    kwargs = _base_kwargs()
    _bind_trace(kwargs, VerificationDecision.REJECT)
    result = verify_grounded_v2(**kwargs)
    receipt = _pending_receipt(
        semantic_task_root=result.task_root,
        semantic_response_hash=result.response_hash,
        commitment_hash=result.response_commitment_hash,
    )
    mature_context = _mature_context()

    rejected = transition(
        receipt,
        record_audit_from_verification(result),
        mature_context,
        semantic_verification_result=result,
    )

    assert rejected.state is ReceiptState.REJECTED
    with pytest.raises(InvalidTransition):
        transition(rejected, ActivateReceipt(), mature_context)


def test_semantic_v2_audit_result_cannot_replay_onto_unrelated_receipt():
    result = verify_grounded_v2(**_base_kwargs())
    unrelated = _pending_receipt(
        semantic_task_root=_word("9"),
        semantic_response_hash=result.response_hash,
        commitment_hash=result.response_commitment_hash,
    )

    with pytest.raises(InvalidTransition, match="task_root"):
        transition(
            unrelated,
            record_audit_from_verification(result),
            _mature_context(),
            semantic_verification_result=result,
        )


def test_semantic_v2_audit_result_cannot_replay_onto_other_commitment():
    result = verify_grounded_v2(**_base_kwargs())
    unrelated = _pending_receipt(
        semantic_task_root=result.task_root,
        semantic_response_hash=result.response_hash,
        commitment_hash=_word("9"),
    )

    with pytest.raises(InvalidTransition, match="commitment_hash"):
        transition(
            unrelated,
            record_audit_from_verification(result),
            _mature_context(),
            semantic_verification_result=result,
        )


def test_forged_semantic_record_audit_without_result_object_is_rejected():
    result = verify_grounded_v2(**_base_kwargs())
    receipt = _pending_receipt(
        semantic_task_root=result.task_root,
        semantic_response_hash=result.response_hash,
        commitment_hash=result.response_commitment_hash,
    )
    forged = RecordAudit(
        decision=AuditDecision.ACCEPT,
        verification_result_digest=_word("9"),
        semantic_task_root=result.task_root,
        semantic_response_hash=f"0x{result.response_hash}",
        semantic_commitment_hash=result.response_commitment_hash,
    )

    with pytest.raises(InvalidTransition, match="verification result is required"):
        transition(receipt, forged, _mature_context())


def test_semantic_publication_receipt_cannot_be_issued_without_bindings():
    payload = _pending_receipt().model_dump(mode="python")
    payload["verification_mode"] = ReceiptVerificationMode.SEMANTIC_PUBLICATION

    with pytest.raises(ValueError, match="semantic publication receipts require"):
        Receipt.model_validate(payload)


def test_not_supported_semantic_result_is_rejected_and_never_activates():
    kwargs = _base_kwargs()
    kwargs["metrics"] = {
        **kwargs["metrics"],
        "FAR": ClaimMetricObservation(
            metric_id="FAR",
            point_estimate=0.50,
            denominator=20,
            confidence_interval=(0.30, 0.70),
        ),
    }
    _bind_trace(kwargs, VerificationDecision.ACCEPT)
    result = verify_grounded_v2(**kwargs)
    receipt = _pending_receipt(
        semantic_task_root=result.task_root,
        semantic_response_hash=result.response_hash,
        commitment_hash=result.response_commitment_hash,
    )

    rejected = transition(
        receipt,
        record_audit_from_verification(result),
        _mature_context(),
        semantic_verification_result=result,
    )

    assert result.claim_disposition.value == "NOT_SUPPORTED"
    assert rejected.state is ReceiptState.REJECTED
    with pytest.raises(InvalidTransition):
        transition(rejected, ActivateReceipt(), _mature_context())
