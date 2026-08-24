from __future__ import annotations

import hashlib

import pytest

from poi_mpp.auditor.semantic import (
    VerificationDecision,
    fit_development_calibration_v2,
    select_development_calibration_thresholds_v2,
)
from poi_mpp.auditor.semantic.models import (
    CalibrationErrorLedgerV1,
    CalibrationLeakageReportV1,
    CalibrationLeakageStatus,
    DevelopmentCalibrationObservationV2,
    SemanticCalibrationErrorCode,
    SemanticCalibrationErrorFamily,
    SemanticCalibrationFreezeStatus,
    SemanticCalibrationFreezeV2,
    development_calibration_record_binding_hash,
)
from poi_mpp.evidence.dataset_manifest_v2 import (
    DatasetManifestV2,
    DatasetSplitV2,
)
from poi_mpp.evidence.models import EvidenceOrigin


def _hash(seed: str) -> str:
    return (seed * 64)[:64]


def _observation(
    record_id: str,
    *,
    expected: VerificationDecision,
    observed: VerificationDecision,
    support: float,
    confidence: float,
    error_code: SemanticCalibrationErrorCode,
    error_family: SemanticCalibrationErrorFamily,
    attack_family: str = "BASELINE",
    subgroup: str = "all",
    difficulty: str = "standard",
    origin: EvidenceOrigin | None = EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
    dataset_record_binding_hash: str | None = None,
) -> DevelopmentCalibrationObservationV2:
    return DevelopmentCalibrationObservationV2(
        record_id=record_id,
        expected_decision=expected,
        observed_decision=observed,
        support_fraction=support,
        calibrated_confidence=confidence,
        error_code=error_code,
        error_family=error_family,
        attack_family=attack_family,
        subgroup=subgroup,
        difficulty=difficulty,
        origin=origin,
        dataset_record_binding_hash=dataset_record_binding_hash,
    )


def _valid_observations() -> tuple[DevelopmentCalibrationObservationV2, ...]:
    rows: list[DevelopmentCalibrationObservationV2] = []
    for index in range(49):
        rows.append(
            _observation(
                f"accept-easy-{index:02d}",
                expected=VerificationDecision.ACCEPT,
                observed=VerificationDecision.ACCEPT,
                support=0.70,
                confidence=0.60,
                error_code=SemanticCalibrationErrorCode.CORRECT_ACCEPT,
                error_family=SemanticCalibrationErrorFamily.DECISION,
            )
        )
    rows.append(
        _observation(
            "accept-borderline",
            expected=VerificationDecision.ACCEPT,
            observed=VerificationDecision.ACCEPT,
            support=0.60,
            confidence=0.60,
            error_code=SemanticCalibrationErrorCode.CORRECT_ACCEPT,
            error_family=SemanticCalibrationErrorFamily.DECISION,
        )
    )
    for index in range(49):
        rows.append(
            _observation(
                f"reject-easy-{index:02d}",
                expected=VerificationDecision.REJECT,
                observed=VerificationDecision.REJECT,
                support=0.10,
                confidence=0.90,
                error_code=SemanticCalibrationErrorCode.CORRECT_REJECT,
                error_family=SemanticCalibrationErrorFamily.DECISION,
            )
        )
    rows.append(
        _observation(
            "reject-borderline",
            expected=VerificationDecision.REJECT,
            observed=VerificationDecision.REJECT,
            support=0.30,
            confidence=0.60,
            error_code=SemanticCalibrationErrorCode.CORRECT_REJECT,
            error_family=SemanticCalibrationErrorFamily.DECISION,
        )
    )
    for index in range(19):
        rows.append(
            _observation(
                f"abstain-easy-{index:02d}",
                expected=VerificationDecision.ABSTAIN,
                observed=VerificationDecision.ABSTAIN,
                support=0.50,
                confidence=0.50,
                error_code=SemanticCalibrationErrorCode.CORRECT_ABSTAIN,
                error_family=SemanticCalibrationErrorFamily.DECISION,
            )
        )
    rows.append(
        _observation(
            "abstain-borderline",
            expected=VerificationDecision.ABSTAIN,
            observed=VerificationDecision.ABSTAIN,
            support=0.60,
            confidence=0.60,
            error_code=SemanticCalibrationErrorCode.CORRECT_ABSTAIN,
            error_family=SemanticCalibrationErrorFamily.DECISION,
        )
    )
    return tuple(rows)


def _leakage_report(
    *,
    development_manifest_hash: str = _hash("a"),
    confirmatory_manifest_hash: str | None = None,
    status: CalibrationLeakageStatus = CalibrationLeakageStatus.NOT_YET_ASSESSABLE,
    record_overlap_count: int = 0,
) -> CalibrationLeakageReportV1:
    return CalibrationLeakageReportV1(
        development_manifest_hash=development_manifest_hash,
        confirmatory_manifest_hash=confirmatory_manifest_hash,
        record_overlap_count=record_overlap_count,
        content_overlap_count=0,
        item_overlap_count=0,
        label_overlap_count=0,
        dedup_overlap_count=0,
        source_overlap_count=0,
        source_family_overlap_count=0,
        near_duplicate_overlap_count=0,
        status=status,
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _development_manifest(
    observations: tuple[DevelopmentCalibrationObservationV2, ...],
) -> DatasetManifestV2:
    expected_outcome = {
        VerificationDecision.ACCEPT: "SUPPORTED_GROUNDS",
        VerificationDecision.REJECT: "REJECTED_GROUNDS",
        VerificationDecision.ABSTAIN: "ABSTAIN_GROUNDS",
    }
    records = []
    for index, row in enumerate(observations, start=1):
        records.append(
            {
                "record_id": row.record_id,
                "item_path": f"items/{row.record_id}.json",
                "label_path": f"labels/{row.record_id}.json",
                "item_hash": _digest(f"item:{row.record_id}:{index}"),
                "label_hash": _digest(f"label:{row.record_id}:{index}"),
                "content_hash": _digest(f"content:{row.record_id}:{index}"),
                "split": DatasetSplitV2.DEVELOPMENT.value,
                "license_id": "CC-BY-4.0",
                "privacy_status": "AUTHORIZED_PUBLIC",
                "expected_decision": row.expected_decision.value,
                "expected_semantic_outcome": expected_outcome[row.expected_decision],
                "error_family": "BASELINE",
                "subgroup": row.subgroup,
                "difficulty": row.difficulty,
                "deduplication_group": f"group-{index:03d}",
                "annotation": {
                    "annotation_scope": "semantic-development",
                    "annotation_hash": _digest(f"annotation:{row.record_id}:{index}"),
                    "agreement_fraction": 1.0,
                },
                "evidence_origin": EvidenceOrigin.REAL_MODEL_EXECUTION.value,
            }
        )
    return DatasetManifestV2.model_validate(
        {
            "dataset_id": "e3-v2-development",
            "split": DatasetSplitV2.DEVELOPMENT.value,
            "records": records,
        }
    )


def _bound_observations(
    observations: tuple[DevelopmentCalibrationObservationV2, ...],
    manifest: DatasetManifestV2,
    *,
    origin: EvidenceOrigin,
) -> tuple[DevelopmentCalibrationObservationV2, ...]:
    by_id = {record.record_id: record for record in manifest.records}
    return tuple(
        row.model_copy(
            update={
                "origin": origin,
                "dataset_record_binding_hash": development_calibration_record_binding_hash(
                    by_id[row.record_id]
                ),
            }
        )
        for row in observations
    )


def test_synthetic_plumbing_can_select_thresholds_but_cannot_freeze_calibration():
    observations = _valid_observations()
    manifest = _development_manifest(observations)
    bound_synthetic = _bound_observations(
        observations,
        manifest,
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
    )

    selection = select_development_calibration_thresholds_v2(observations)

    assert selection.support_threshold == pytest.approx(0.70)
    assert selection.reject_threshold == pytest.approx(0.30)
    assert selection.minimum_calibrated_confidence == pytest.approx(0.60)
    assert selection.exact_accuracy == pytest.approx(119 / 120)
    assert selection.false_accept_rate == pytest.approx(0.0)
    assert selection.false_reject_rate == pytest.approx(0.0)
    assert selection.coverage == pytest.approx(0.825)

    with pytest.raises(
        ValueError,
        match="frozen development calibration requires REAL_MODEL_EXECUTION observations",
    ):
        fit_development_calibration_v2(
            bound_synthetic,
            development_dataset_manifest=manifest,
            claim_spec_hash=_hash("b"),
            prompt_template_hash=_hash("c"),
            model_manifest_hash=_hash("d"),
            runtime_environment_hash=_hash("e"),
            output_schema_hash=_hash("f"),
            contradiction_policy_hash=_hash("1"),
            error_recovery_policy_hash=_hash("2"),
            leakage_report=_leakage_report(
                development_manifest_hash=manifest.dataset_manifest_hash()
            ),
        )


def test_fit_development_calibration_v2_rejects_duplicate_records_and_non_real_origin():
    manifest = _development_manifest(_valid_observations())
    rows = list(
        _bound_observations(
            _valid_observations(),
            manifest,
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        )
    )
    rows[-1] = rows[0]
    with pytest.raises(ValueError, match="duplicate record_id"):
        fit_development_calibration_v2(
            tuple(rows),
            development_dataset_manifest=manifest,
            claim_spec_hash=_hash("b"),
            prompt_template_hash=_hash("c"),
            model_manifest_hash=_hash("d"),
            runtime_environment_hash=_hash("e"),
            output_schema_hash=_hash("f"),
            contradiction_policy_hash=_hash("1"),
            error_recovery_policy_hash=_hash("2"),
            leakage_report=_leakage_report(
                development_manifest_hash=manifest.dataset_manifest_hash()
            ),
        )

    synthetic = _observation(
            "synthetic-row",
            expected=VerificationDecision.ACCEPT,
            observed=VerificationDecision.ACCEPT,
            support=0.90,
            confidence=0.90,
            error_code=SemanticCalibrationErrorCode.CORRECT_ACCEPT,
            error_family=SemanticCalibrationErrorFamily.DECISION,
            origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        )
    assert synthetic.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE

    simulation_rows = _bound_observations(
        _valid_observations(),
        manifest,
        origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    )
    with pytest.raises(
        ValueError,
        match="frozen development calibration requires REAL_MODEL_EXECUTION observations",
    ):
        fit_development_calibration_v2(
            simulation_rows,
            development_dataset_manifest=manifest,
            claim_spec_hash=_hash("b"),
            prompt_template_hash=_hash("c"),
            model_manifest_hash=_hash("d"),
            runtime_environment_hash=_hash("e"),
            output_schema_hash=_hash("f"),
            contradiction_policy_hash=_hash("1"),
            error_recovery_policy_hash=_hash("2"),
            leakage_report=_leakage_report(
                development_manifest_hash=manifest.dataset_manifest_hash()
            ),
        )


def test_calibration_leakage_report_enforces_confirmatory_status_rules():
    with pytest.raises(ValueError, match="CLEAR leakage status requires zero overlap counts"):
        CalibrationLeakageReportV1(
            development_manifest_hash=_hash("a"),
            confirmatory_manifest_hash=_hash("b"),
            record_overlap_count=1,
            content_overlap_count=0,
            item_overlap_count=0,
            label_overlap_count=0,
            dedup_overlap_count=0,
            source_overlap_count=0,
            source_family_overlap_count=0,
            near_duplicate_overlap_count=0,
            status=CalibrationLeakageStatus.CLEAR,
        )


def test_phase3_freeze_rejects_a_post_confirmatory_leakage_report() -> None:
    manifest = _development_manifest(_valid_observations())
    real_rows = _bound_observations(
        _valid_observations(),
        manifest,
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
    )
    clear_report = _leakage_report(
        development_manifest_hash=manifest.dataset_manifest_hash(),
        confirmatory_manifest_hash=_hash("9"),
        status=CalibrationLeakageStatus.CLEAR,
    )

    with pytest.raises(
        ValueError,
        match="Phase-3 calibration requires a NOT_YET_ASSESSABLE development leakage report",
    ):
        fit_development_calibration_v2(
            real_rows,
            development_dataset_manifest=manifest,
            claim_spec_hash=_hash("b"),
            prompt_template_hash=_hash("c"),
            model_manifest_hash=_hash("d"),
            runtime_environment_hash=_hash("e"),
            output_schema_hash=_hash("f"),
            contradiction_policy_hash=_hash("1"),
            error_recovery_policy_hash=_hash("2"),
            leakage_report=clear_report,
        )

    with pytest.raises(ValueError, match="confirmatory leakage assessment cannot remain NOT_YET_ASSESSABLE"):
        CalibrationLeakageReportV1(
            development_manifest_hash=_hash("a"),
            confirmatory_manifest_hash=_hash("b"),
            record_overlap_count=0,
            content_overlap_count=0,
            item_overlap_count=0,
            label_overlap_count=0,
            dedup_overlap_count=0,
            source_overlap_count=0,
            source_family_overlap_count=0,
            near_duplicate_overlap_count=0,
            status=CalibrationLeakageStatus.NOT_YET_ASSESSABLE,
        )


def test_error_ledger_and_freeze_are_hash_bound_and_sorted():
    rows = (
        _observation(
            "zeta",
            expected=VerificationDecision.REJECT,
            observed=VerificationDecision.REJECT,
            support=0.10,
            confidence=0.80,
            error_code=SemanticCalibrationErrorCode.CORRECT_REJECT,
            error_family=SemanticCalibrationErrorFamily.DECISION,
        ),
        _observation(
            "alpha",
            expected=VerificationDecision.ABSTAIN,
            observed=VerificationDecision.ABSTAIN,
            support=0.40,
            confidence=0.40,
            error_code=SemanticCalibrationErrorCode.CORRECT_ABSTAIN,
            error_family=SemanticCalibrationErrorFamily.DECISION,
        ),
    )
    ledger = CalibrationErrorLedgerV1(dataset_manifest_hash=_hash("a"), rows=rows)

    assert tuple(row.record_id for row in ledger.rows) == ("alpha", "zeta")
    assert len(ledger.content_hash) == 64

    with pytest.raises(ValueError, match="frozen development calibration requires exactly 50 ACCEPT examples"):
        SemanticCalibrationFreezeV2(
            status=SemanticCalibrationFreezeStatus.FROZEN_DEVELOPMENT_ONLY,
            development_dataset_manifest_hash=_hash("a"),
            claim_spec_hash=_hash("b"),
            prompt_template_hash=_hash("c"),
            model_manifest_hash=_hash("d"),
            runtime_environment_hash=_hash("e"),
            accept_example_count=49,
            reject_example_count=50,
            abstain_example_count=21,
            error_taxonomy_version="POI_MPP_SEMANTIC_CALIBRATION_ERROR_TAXONOMY_V1",
            support_threshold=0.70,
            reject_threshold=0.30,
            minimum_calibrated_confidence=0.60,
            selection_rule_id="TRI_STATE_ACCURACY_FAIL_CLOSED_V1",
            example_count=120,
            error_ledger_hash=ledger.content_hash,
            leakage_report_hash=_leakage_report().content_hash,
            output_schema_hash=_hash("1"),
            contradiction_policy_hash=_hash("2"),
            error_recovery_policy_hash=_hash("3"),
            error_taxonomy_hash=ledger.taxonomy_hash,
            content_hash=_hash("f"),
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_v2_calibration_rejects_non_finite_probabilities(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        _observation(
            "non-finite",
            expected=VerificationDecision.ACCEPT,
            observed=VerificationDecision.ACCEPT,
            support=value,
            confidence=0.9,
            error_code=SemanticCalibrationErrorCode.CORRECT_ACCEPT,
            error_family=SemanticCalibrationErrorFamily.DECISION,
        )


def test_v2_calibration_rejects_missing_provenance_and_inconsistent_error_code() -> None:
    with pytest.raises(ValueError, match="error_code is inconsistent"):
        _observation(
            "mislabelled",
            expected=VerificationDecision.REJECT,
            observed=VerificationDecision.ACCEPT,
            support=0.9,
            confidence=0.9,
            error_code=SemanticCalibrationErrorCode.CORRECT_ACCEPT,
            error_family=SemanticCalibrationErrorFamily.DECISION,
        )

    manifest = _development_manifest(_valid_observations())
    rows = list(
        _bound_observations(
            _valid_observations(),
            manifest,
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        )
    )
    rows[0] = _observation(
        "missing-origin",
        expected=VerificationDecision.ACCEPT,
        observed=VerificationDecision.ACCEPT,
        support=0.7,
        confidence=0.6,
        error_code=SemanticCalibrationErrorCode.CORRECT_ACCEPT,
        error_family=SemanticCalibrationErrorFamily.DECISION,
        origin=None,
    )
    with pytest.raises(ValueError, match="development observations require explicit provenance"):
        fit_development_calibration_v2(
            rows,
            development_dataset_manifest=manifest,
            claim_spec_hash=_hash("b"),
            prompt_template_hash=_hash("c"),
            model_manifest_hash=_hash("d"),
            runtime_environment_hash=_hash("e"),
            output_schema_hash=_hash("f"),
            contradiction_policy_hash=_hash("1"),
            error_recovery_policy_hash=_hash("2"),
            leakage_report=_leakage_report(
                development_manifest_hash=manifest.dataset_manifest_hash()
            ),
        )


def test_phase3_freeze_rejects_forged_dataset_record_binding() -> None:
    manifest = _development_manifest(_valid_observations())
    rows = list(
        _bound_observations(
            _valid_observations(),
            manifest,
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        )
    )
    rows[0] = rows[0].model_copy(
        update={
            "dataset_record_binding_hash": rows[1].dataset_record_binding_hash,
        }
    )

    with pytest.raises(ValueError, match="dataset record binding hash mismatch"):
        fit_development_calibration_v2(
            tuple(rows),
            development_dataset_manifest=manifest,
            claim_spec_hash=_hash("b"),
            prompt_template_hash=_hash("c"),
            model_manifest_hash=_hash("d"),
            runtime_environment_hash=_hash("e"),
            output_schema_hash=_hash("f"),
            contradiction_policy_hash=_hash("1"),
            error_recovery_policy_hash=_hash("2"),
            leakage_report=_leakage_report(
                development_manifest_hash=manifest.dataset_manifest_hash()
            ),
        )


def test_phase3_freeze_rejects_missing_dataset_record_binding() -> None:
    manifest = _development_manifest(_valid_observations())
    rows = list(
        _bound_observations(
            _valid_observations(),
            manifest,
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        )
    )
    rows[0] = rows[0].model_copy(update={"dataset_record_binding_hash": None})

    with pytest.raises(ValueError, match="dataset_record_binding_hash"):
        fit_development_calibration_v2(
            tuple(rows),
            development_dataset_manifest=manifest,
            claim_spec_hash=_hash("b"),
            prompt_template_hash=_hash("c"),
            model_manifest_hash=_hash("d"),
            runtime_environment_hash=_hash("e"),
            output_schema_hash=_hash("f"),
            contradiction_policy_hash=_hash("1"),
            error_recovery_policy_hash=_hash("2"),
            leakage_report=_leakage_report(
                development_manifest_hash=manifest.dataset_manifest_hash()
            ),
        )


def test_phase3_freeze_rejects_attack_family_drift_under_valid_record_binding() -> None:
    manifest = _development_manifest(_valid_observations())
    rows = list(
        _bound_observations(
            _valid_observations(),
            manifest,
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        )
    )
    rows[0] = rows[0].model_copy(update={"attack_family": "ARBITRARY_ATTACK_FAMILY"})

    with pytest.raises(
        ValueError,
        match="development observation attack_family does not match the authoritative dataset manifest",
    ):
        fit_development_calibration_v2(
            tuple(rows),
            development_dataset_manifest=manifest,
            claim_spec_hash=_hash("b"),
            prompt_template_hash=_hash("c"),
            model_manifest_hash=_hash("d"),
            runtime_environment_hash=_hash("e"),
            output_schema_hash=_hash("f"),
            contradiction_policy_hash=_hash("1"),
            error_recovery_policy_hash=_hash("2"),
            leakage_report=_leakage_report(
                development_manifest_hash=manifest.dataset_manifest_hash()
            ),
        )


def test_v2_freeze_rejects_non_canonical_selection_rule_id() -> None:
    ledger = CalibrationErrorLedgerV1(
        dataset_manifest_hash=_hash("a"),
        rows=(
            _observation(
                "alpha",
                expected=VerificationDecision.ACCEPT,
                observed=VerificationDecision.ACCEPT,
                support=0.8,
                confidence=0.8,
                error_code=SemanticCalibrationErrorCode.CORRECT_ACCEPT,
                error_family=SemanticCalibrationErrorFamily.DECISION,
            ),
        ),
    )

    with pytest.raises(ValueError, match="selection_rule_id must equal"):
        SemanticCalibrationFreezeV2(
            status=SemanticCalibrationFreezeStatus.READY_FOR_DATA,
            development_dataset_manifest_hash=_hash("a"),
            claim_spec_hash=_hash("b"),
            prompt_template_hash=_hash("c"),
            model_manifest_hash=_hash("d"),
            runtime_environment_hash=_hash("e"),
            accept_example_count=0,
            reject_example_count=0,
            abstain_example_count=0,
            error_taxonomy_version="POI_MPP_SEMANTIC_CALIBRATION_ERROR_TAXONOMY_V1",
            support_threshold=0.70,
            reject_threshold=0.30,
            minimum_calibrated_confidence=0.60,
            selection_rule_id="TRI_STATE_ACCURACY_FAIL_CLOSED_V2",
            example_count=0,
            error_ledger_hash=ledger.content_hash,
            leakage_report_hash=_leakage_report().content_hash,
            output_schema_hash=_hash("1"),
            contradiction_policy_hash=_hash("2"),
            error_recovery_policy_hash=_hash("3"),
            error_taxonomy_hash=ledger.taxonomy_hash,
        )


def test_error_ledger_rejects_conflicting_duplicate_record_ids() -> None:
    first = _observation(
        "duplicate",
        expected=VerificationDecision.ACCEPT,
        observed=VerificationDecision.ACCEPT,
        support=0.8,
        confidence=0.8,
        error_code=SemanticCalibrationErrorCode.CORRECT_ACCEPT,
        error_family=SemanticCalibrationErrorFamily.DECISION,
    )
    conflicting = first.model_copy(
        update={
            "observed_decision": VerificationDecision.ABSTAIN,
            "error_code": SemanticCalibrationErrorCode.INCORRECT_ABSTAIN,
        }
    )
    with pytest.raises(ValueError, match="duplicate record_id"):
        CalibrationErrorLedgerV1(
            dataset_manifest_hash=_hash("a"),
            rows=(first, conflicting),
        )
