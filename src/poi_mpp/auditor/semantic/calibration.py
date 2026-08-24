"""Development-only calibration for deterministic semantic verification."""

from __future__ import annotations

from collections.abc import Iterable

from poi_mpp.auditor.semantic.models import (
    CalibrationErrorLedgerV1,
    CalibrationLeakageReportV1,
    CalibrationLeakageStatus,
    DevelopmentCalibrationExample,
    DevelopmentCalibrationFitResultV2,
    DevelopmentCalibrationObservationV2,
    DevelopmentCalibrationThresholdSelectionV2,
    SEMANTIC_CALIBRATION_ERROR_TAXONOMY_VERSION,
    SEMANTIC_CALIBRATION_SELECTION_RULE_V2,
    SemanticCalibrationArtifact,
    SemanticCalibrationFreezeStatus,
    SemanticCalibrationFreezeV2,
    VerificationDecision,
    development_calibration_record_binding_hash,
)
from poi_mpp.evidence.dataset_manifest_v2 import DatasetManifestV2, DatasetSplitV2
from poi_mpp.evidence.models import EvidenceOrigin


def fit_development_calibration(
    examples: tuple[DevelopmentCalibrationExample, ...] | list[DevelopmentCalibrationExample],
    *,
    dataset_label: str = "development",
) -> SemanticCalibrationArtifact:
    """Fit a fail-closed support threshold on development examples only."""

    frozen_examples = tuple(examples)
    if not frozen_examples:
        raise ValueError("development calibration requires at least one example")

    candidate_thresholds = sorted(
        {example.support_fraction for example in frozen_examples} | {1.0}
    )
    best_threshold: float | None = None
    best_accuracy = -1
    for threshold in candidate_thresholds:
        accuracy = sum(
            (example.support_fraction >= threshold) == example.should_accept
            for example in frozen_examples
        )
        if accuracy > best_accuracy or (
            accuracy == best_accuracy and (best_threshold is None or threshold > best_threshold)
        ):
            best_threshold = threshold
            best_accuracy = accuracy

    assert best_threshold is not None
    return SemanticCalibrationArtifact.create(
        dataset_label=dataset_label,
        minimum_support_fraction=float(best_threshold),
        example_count=len(frozen_examples),
    )


def _validate_observation_set(
    observations: tuple[DevelopmentCalibrationObservationV2, ...]
    | list[DevelopmentCalibrationObservationV2],
) -> tuple[DevelopmentCalibrationObservationV2, ...]:
    frozen = tuple(observations)
    if not frozen:
        raise ValueError("development calibration v2 requires at least one observation")
    seen: set[str] = set()
    accept_count = 0
    reject_count = 0
    abstain_count = 0
    for row in frozen:
        if row.record_id in seen:
            raise ValueError(f"duplicate record_id: {row.record_id}")
        seen.add(row.record_id)
        if row.origin is None:
            raise ValueError("development observations require explicit provenance")
        if row.expected_decision is VerificationDecision.ACCEPT:
            accept_count += 1
        elif row.expected_decision is VerificationDecision.REJECT:
            reject_count += 1
        else:
            abstain_count += 1
    if accept_count != 50:
        raise ValueError("development calibration v2 requires exactly 50 ACCEPT observations")
    if reject_count != 50:
        raise ValueError("development calibration v2 requires exactly 50 REJECT observations")
    if abstain_count < 20 or abstain_count > 50:
        raise ValueError("development calibration v2 requires 20-50 ABSTAIN observations")
    if len(frozen) < 120 or len(frozen) > 150:
        raise ValueError("development calibration v2 requires 120-150 observations")
    return frozen


def _freeze_observations(
    observations: tuple[DevelopmentCalibrationObservationV2, ...]
    | list[DevelopmentCalibrationObservationV2],
) -> tuple[DevelopmentCalibrationObservationV2, ...]:
    frozen = _validate_observation_set(observations)
    if any(row.origin is not EvidenceOrigin.REAL_MODEL_EXECUTION for row in frozen):
        raise ValueError(
            "frozen development calibration requires REAL_MODEL_EXECUTION observations"
    )
    return frozen


def _validate_dataset_membership(
    observations: tuple[DevelopmentCalibrationObservationV2, ...],
    *,
    development_dataset_manifest: DatasetManifestV2,
) -> str:
    if development_dataset_manifest.split is not DatasetSplitV2.DEVELOPMENT:
        raise ValueError("Phase-3 calibration requires a DEVELOPMENT dataset manifest")
    manifest_hash = development_dataset_manifest.dataset_manifest_hash()
    record_index = {
        record.record_id: record
        for record in development_dataset_manifest.records
    }
    for row in observations:
        if row.dataset_record_binding_hash is None:
            raise ValueError(
                f"dataset_record_binding_hash is required for frozen observation: {row.record_id}"
            )
        record = record_index.get(row.record_id)
        if record is None:
            raise ValueError(
                f"development observation is absent from the authoritative dataset manifest: {row.record_id}"
            )
        expected_binding_hash = development_calibration_record_binding_hash(record)
        if row.dataset_record_binding_hash != expected_binding_hash:
            raise ValueError(
                f"dataset record binding hash mismatch for development observation: {row.record_id}"
            )
        if row.origin is not record.evidence_origin:
            raise ValueError(
                f"development observation provenance does not match the authoritative dataset manifest: {row.record_id}"
            )
        if row.expected_decision.value != record.expected_decision.value:
            raise ValueError(
                f"development observation expected decision does not match the authoritative dataset manifest: {row.record_id}"
            )
        if row.attack_family != record.error_family:
            raise ValueError(
                f"development observation attack_family does not match the authoritative dataset manifest: {row.record_id}"
            )
        if row.subgroup != record.subgroup:
            raise ValueError(
                f"development observation subgroup does not match the authoritative dataset manifest: {row.record_id}"
            )
        if row.difficulty != record.difficulty:
            raise ValueError(
                f"development observation difficulty does not match the authoritative dataset manifest: {row.record_id}"
            )
    return manifest_hash


def _prediction(
    *,
    support_fraction: float,
    calibrated_confidence: float,
    support_threshold: float,
    reject_threshold: float,
    minimum_calibrated_confidence: float,
) -> VerificationDecision:
    if support_fraction <= reject_threshold:
        return VerificationDecision.REJECT
    if (
        support_fraction >= support_threshold
        and calibrated_confidence >= minimum_calibrated_confidence
    ):
        return VerificationDecision.ACCEPT
    return VerificationDecision.ABSTAIN


def _candidate_values(
    rows: Iterable[DevelopmentCalibrationObservationV2],
) -> tuple[list[float], list[float]]:
    support_values = {0.0, 1.0}
    confidence_values = {0.0, 1.0}
    for row in rows:
        support_values.add(row.support_fraction)
        confidence_values.add(row.calibrated_confidence)
    return sorted(support_values), sorted(confidence_values)


def select_development_calibration_thresholds_v2(
    observations: tuple[DevelopmentCalibrationObservationV2, ...]
    | list[DevelopmentCalibrationObservationV2],
) -> DevelopmentCalibrationThresholdSelectionV2:
    """Select thresholds without creating a publication-eligible freeze.

    This mechanics-only boundary may consume ``SYNTHETIC_NON_EVIDENCE``
    plumbing fixtures. The publication freeze boundary below separately
    requires real-model observations.
    """

    frozen = _validate_observation_set(observations)
    support_values, confidence_values = _candidate_values(frozen)
    best_score: tuple[float, float, float, float, float, float, float] | None = None
    best_thresholds: tuple[float, float, float] | None = None
    best_metrics: tuple[float, float, float, float] | None = None
    non_accept_total = sum(
        1 for row in frozen if row.expected_decision is not VerificationDecision.ACCEPT
    )
    accept_total = sum(
        1 for row in frozen if row.expected_decision is VerificationDecision.ACCEPT
    )

    for support_threshold in support_values:
        for reject_threshold in support_values:
            if reject_threshold > support_threshold:
                continue
            for minimum_confidence in confidence_values:
                correct = 0
                false_accepts = 0
                false_rejects = 0
                non_abstain = 0
                for row in frozen:
                    predicted = _prediction(
                        support_fraction=row.support_fraction,
                        calibrated_confidence=row.calibrated_confidence,
                        support_threshold=support_threshold,
                        reject_threshold=reject_threshold,
                        minimum_calibrated_confidence=minimum_confidence,
                    )
                    if predicted is row.expected_decision:
                        correct += 1
                    if predicted is not VerificationDecision.ABSTAIN:
                        non_abstain += 1
                    if (
                        predicted is VerificationDecision.ACCEPT
                        and row.expected_decision is not VerificationDecision.ACCEPT
                    ):
                        false_accepts += 1
                    if (
                        predicted is VerificationDecision.REJECT
                        and row.expected_decision is VerificationDecision.ACCEPT
                    ):
                        false_rejects += 1

                accuracy = correct / len(frozen)
                false_accept_rate = false_accepts / non_accept_total if non_accept_total else 0.0
                false_reject_rate = false_rejects / accept_total if accept_total else 0.0
                coverage = non_abstain / len(frozen)
                score = (
                    accuracy,
                    -false_accept_rate,
                    -false_reject_rate,
                    coverage,
                    support_threshold,
                    -reject_threshold,
                    minimum_confidence,
                )
                if best_score is None or score > best_score:
                    best_score = score
                    best_thresholds = (support_threshold, reject_threshold, minimum_confidence)
                    best_metrics = (
                        accuracy,
                        false_accept_rate,
                        false_reject_rate,
                        coverage,
                    )

    assert best_thresholds is not None
    assert best_metrics is not None
    return DevelopmentCalibrationThresholdSelectionV2(
        support_threshold=best_thresholds[0],
        reject_threshold=best_thresholds[1],
        minimum_calibrated_confidence=best_thresholds[2],
        exact_accuracy=best_metrics[0],
        false_accept_rate=best_metrics[1],
        false_reject_rate=best_metrics[2],
        coverage=best_metrics[3],
    )


def fit_development_calibration_v2(
    observations: tuple[DevelopmentCalibrationObservationV2, ...]
    | list[DevelopmentCalibrationObservationV2],
    *,
    development_dataset_manifest: DatasetManifestV2,
    claim_spec_hash: str,
    prompt_template_hash: str,
    model_manifest_hash: str,
    runtime_environment_hash: str,
    output_schema_hash: str,
    contradiction_policy_hash: str,
    error_recovery_policy_hash: str,
    leakage_report: CalibrationLeakageReportV1,
) -> DevelopmentCalibrationFitResultV2:
    """Freeze a development-only V2 calibration bundle from real executions.

    This fit is deterministic and scoped only to observed development-set
    behavior. It does not claim transport, statistical calibration, or
    confirmatory validity.
    """

    frozen = _freeze_observations(observations)
    development_dataset_manifest_hash = _validate_dataset_membership(
        frozen,
        development_dataset_manifest=development_dataset_manifest,
    )
    if leakage_report.development_manifest_hash != development_dataset_manifest_hash:
        raise ValueError("leakage report development manifest hash does not match the calibration input")
    if (
        leakage_report.status is not CalibrationLeakageStatus.NOT_YET_ASSESSABLE
        or leakage_report.confirmatory_manifest_hash is not None
    ):
        raise ValueError(
            "Phase-3 calibration requires a NOT_YET_ASSESSABLE development leakage report"
        )

    ledger = CalibrationErrorLedgerV1(
        dataset_manifest_hash=development_dataset_manifest_hash,
        taxonomy_version=SEMANTIC_CALIBRATION_ERROR_TAXONOMY_VERSION,
        rows=frozen,
    )

    selection = select_development_calibration_thresholds_v2(frozen)
    freeze = SemanticCalibrationFreezeV2(
        status=SemanticCalibrationFreezeStatus.FROZEN_DEVELOPMENT_ONLY,
        development_dataset_manifest_hash=development_dataset_manifest_hash,
        claim_spec_hash=claim_spec_hash,
        prompt_template_hash=prompt_template_hash,
        model_manifest_hash=model_manifest_hash,
        runtime_environment_hash=runtime_environment_hash,
        output_schema_hash=output_schema_hash,
        contradiction_policy_hash=contradiction_policy_hash,
        error_recovery_policy_hash=error_recovery_policy_hash,
        accept_example_count=50,
        reject_example_count=50,
        abstain_example_count=len(frozen) - 100,
        error_taxonomy_version=SEMANTIC_CALIBRATION_ERROR_TAXONOMY_VERSION,
        error_taxonomy_hash=ledger.taxonomy_hash,
        support_threshold=selection.support_threshold,
        reject_threshold=selection.reject_threshold,
        minimum_calibrated_confidence=selection.minimum_calibrated_confidence,
        selection_rule_id=SEMANTIC_CALIBRATION_SELECTION_RULE_V2,
        example_count=len(frozen),
        error_ledger_hash=ledger.content_hash,
        leakage_report_hash=leakage_report.content_hash,
    )
    return DevelopmentCalibrationFitResultV2(
        freeze=freeze,
        error_ledger=ledger,
        leakage_report=leakage_report,
        exact_accuracy=selection.exact_accuracy,
        false_accept_rate=selection.false_accept_rate,
        false_reject_rate=selection.false_reject_rate,
        coverage=selection.coverage,
    )
