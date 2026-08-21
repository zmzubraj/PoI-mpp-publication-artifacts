from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from poi_mpp.auditor.semantic.models import SemanticCalibrationArtifact, SemanticOutcome, VerificationDecision
from poi_mpp.datasets.manifests import DatasetManifest, DatasetRecord, DatasetSplit
from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig, approved_schema_hash
from poi_mpp.evidence.models import EvidenceOrigin, RunManifest
from poi_mpp.evidence.provenance import EnvironmentManifest, environment_hash, freeze_run
from poi_mpp.evidence.validation import ProvenanceBundle


def _hash(label: str, value: str) -> str:
    return digest(label, value)


def _record(
    *,
    record_id: str,
    split: DatasetSplit,
    origin: EvidenceOrigin,
) -> DatasetRecord:
    return DatasetRecord(
        record_id=record_id,
        split=split,
        origin=origin,
        source_family=f"{split.value.lower()}-{record_id}",
        source_hash=_hash("DATASET_SOURCE", f"{split.value}:{record_id}:source"),
        content_hash=_hash("DATASET_CONTENT", f"{split.value}:{record_id}:content"),
    )


def _manifest(
    *,
    dataset_id: str,
    split: DatasetSplit,
    origin: EvidenceOrigin,
    record_ids: tuple[str, ...],
) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        split=split,
        records=tuple(
            _record(record_id=record_id, split=split, origin=origin)
            for record_id in record_ids
        ),
    )


def _run_config(*, origin: EvidenceOrigin = EvidenceOrigin.REAL_MODEL_EXECUTION) -> RunConfig:
    return RunConfig.model_validate(
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": "run-e3",
            "experiment_id": "E3",
            "origin": origin.value,
            "authorization_scope": "LOCAL_AUTHORIZED_PILOT_ONLY",
            "model_hash": "1" * 64,
            "dataset_hash": "2" * 64,
            "parent_hashes": [],
            "data_availability": {
                "total_shards": 16,
                "samples": 8,
                "replacement": False,
            },
        }
    )


def _calibration() -> SemanticCalibrationArtifact:
    return SemanticCalibrationArtifact.create(
        dataset_label="development-e3",
        minimum_support_fraction=0.75,
        example_count=8,
    )


def _row(
    *,
    case_id: str,
    reference_valid: bool,
    verifier_decision: VerificationDecision,
    verifier_confidence: float | None = None,
    subgroup: str = "core",
):
    from poi_mpp.experiments.e3_semantic import E3SemanticRow

    reference_outcome = (
        SemanticOutcome.SUPPORTED if reference_valid else SemanticOutcome.CONTRADICTORY
    )
    if verifier_decision is VerificationDecision.ACCEPT:
        verifier_outcome = SemanticOutcome.SUPPORTED
        confidence = 0.92 if verifier_confidence is None else verifier_confidence
    elif verifier_decision is VerificationDecision.REJECT:
        verifier_outcome = SemanticOutcome.CONTRADICTORY
        confidence = 0.81 if verifier_confidence is None else verifier_confidence
    else:
        verifier_outcome = None
        confidence = verifier_confidence
    return E3SemanticRow(
        run_id="run-e3",
        experiment_id="E3",
        case_id=case_id,
        split=DatasetSplit.PLUMBING,
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        frozen_reference_valid=reference_valid,
        frozen_reference_outcome=reference_outcome,
        verifier_decision=verifier_decision,
        verifier_outcome=verifier_outcome,
        abstained=verifier_decision is VerificationDecision.ABSTAIN,
        subgroup=subgroup,
        verifier_confidence=confidence,
        calibration_hash=_calibration().content_hash,
        source_record_id=f"source-{case_id}",
        source_content_hash=_hash("SOURCE_CONTENT", case_id),
        source_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        annotation_record_id=f"annotation-{case_id}",
        annotation_hash=_hash("ANNOTATION_CONTENT", case_id),
        annotation_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        evaluator_id="fixture-evaluator",
        evaluator_hash=_hash("EVALUATOR", "fixture-evaluator"),
        evaluator_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        evaluator_independence_basis="fixture plumbing only",
    )


def _confirmatory_config(
    *,
    dataset_origin: EvidenceOrigin,
    confirmatory_manifest: DatasetManifest,
):
    from poi_mpp.experiments.e3_semantic import (
        E3ConfirmatoryConfig,
        E3ConfirmatoryDataset,
        E3DevelopmentDataset,
        E3EvaluatorAuthority,
    )

    return E3ConfirmatoryConfig(
        run_config=_run_config(origin=EvidenceOrigin.REAL_MODEL_EXECUTION),
        publication_scope="LOCAL_TEST_ONLY",
        development_dataset=E3DevelopmentDataset(
            dataset_id="development-e3",
            manifest=_manifest(
                dataset_id="development-e3",
                split=DatasetSplit.DEVELOPMENT,
                origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
                record_ids=("dev-1", "dev-2"),
            ),
            calibration=_calibration(),
        ),
        dataset=E3ConfirmatoryDataset(
            dataset_id="confirm-e3",
            origin=dataset_origin,
            manifest=confirmatory_manifest,
            license_id=None,
            privacy_status=None,
            annotation_protocol_id=None,
        ),
        evaluators=(
            E3EvaluatorAuthority(
                evaluator_id="eval-1",
                evaluator_hash=_hash("EVAL_HASH", "eval-1"),
                origin=dataset_origin,
                independence_basis="fixture evaluator",
                verified=False,
            ),
        ),
        provenance_bundle=None,
    )


def _publication_bundle(
    *,
    run_origin: EvidenceOrigin,
    forged_manifest: RunManifest | None = None,
) -> tuple[RunConfig, ProvenanceBundle]:
    run_config = RunConfig.model_validate(
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": "run-e3-publication",
            "experiment_id": "E3",
            "origin": run_origin.value,
            "authorization_scope": "PUBLICATION_EVIDENCE_AUTHORIZED",
            "model_hash": "3" * 64,
            "dataset_hash": "4" * 64,
            "parent_hashes": [],
            "data_availability": {
                "total_shards": 16,
                "samples": 8,
                "replacement": False,
            },
        }
    )
    environment = EnvironmentManifest(
        python_implementation="CPython",
        python_version="3.11.15",
        os_name="Darwin",
        os_release="26.0.0",
        machine="arm64",
        cpu_model="Apple M4",
        gpu_model="Apple GPU",
        package_lock_hash="5" * 64,
        compiler_version=None,
        foundry_version=None,
        code_revision="6" * 40,
    )
    manifest = forged_manifest or freeze_run(run_config, environment)
    return run_config, ProvenanceBundle(
        config=run_config,
        environment=environment,
        manifest=manifest,
    )


def _publication_config(
    *,
    run_origin: EvidenceOrigin,
    dataset_origin: EvidenceOrigin,
    forged_manifest: RunManifest | None = None,
):
    from poi_mpp.experiments.e3_semantic import (
        E3ConfirmatoryConfig,
        E3ConfirmatoryDataset,
        E3DevelopmentDataset,
        E3EvaluatorAuthority,
        E3_CONFIRMATORY_SCOPE,
    )

    run_config, provenance_bundle = _publication_bundle(
        run_origin=run_origin,
        forged_manifest=forged_manifest,
    )
    return E3ConfirmatoryConfig(
        run_config=run_config,
        publication_scope=E3_CONFIRMATORY_SCOPE,
        development_dataset=E3DevelopmentDataset(
            dataset_id="development-e3",
            manifest=_manifest(
                dataset_id="development-e3",
                split=DatasetSplit.DEVELOPMENT,
                origin=run_origin,
                record_ids=("dev-1", "dev-2"),
            ),
            calibration=_calibration(),
        ),
        dataset=E3ConfirmatoryDataset(
            dataset_id="confirm-e3",
            origin=dataset_origin,
            manifest=_manifest(
                dataset_id="confirm-e3",
                split=DatasetSplit.CONFIRMATORY,
                origin=dataset_origin,
                record_ids=("confirm-1", "confirm-2"),
            ),
            license_id="license-1",
            privacy_status="PUBLIC",
            annotation_protocol_id="proto-1",
        ),
        evaluators=(
            E3EvaluatorAuthority(
                evaluator_id="eval-1",
                evaluator_hash=_hash("EVAL_HASH", "eval-1"),
                origin=run_origin,
                independence_basis="independent reviewer",
                verified=True,
            ),
        ),
        provenance_bundle=provenance_bundle,
    )


def _publication_row(
    *,
    case_id: str = "case-1",
    origin: EvidenceOrigin = EvidenceOrigin.REAL_MODEL_EXECUTION,
    source_origin: EvidenceOrigin = EvidenceOrigin.REAL_MODEL_EXECUTION,
    annotation_origin: EvidenceOrigin = EvidenceOrigin.REAL_MODEL_EXECUTION,
    evaluator_origin: EvidenceOrigin = EvidenceOrigin.REAL_MODEL_EXECUTION,
    evaluator_hash: str | None = None,
    evaluator_independence_basis: str = "independent reviewer",
):
    from poi_mpp.experiments.e3_semantic import E3SemanticRow

    return E3SemanticRow(
        run_id="run-e3-publication",
        experiment_id="E3",
        case_id=case_id,
        split=DatasetSplit.CONFIRMATORY,
        origin=origin,
        frozen_reference_valid=True,
        frozen_reference_outcome=SemanticOutcome.SUPPORTED,
        verifier_decision=VerificationDecision.ACCEPT,
        verifier_outcome=SemanticOutcome.SUPPORTED,
        abstained=False,
        subgroup="core",
        verifier_confidence=0.92,
        calibration_hash=_calibration().content_hash,
        source_record_id=f"source-{case_id}",
        source_content_hash=_hash("SOURCE_CONTENT", f"pub-{case_id}"),
        source_origin=source_origin,
        annotation_record_id=f"annotation-{case_id}",
        annotation_hash=_hash("ANNOTATION_CONTENT", f"pub-{case_id}"),
        annotation_origin=annotation_origin,
        evaluator_id="eval-1",
        evaluator_hash=evaluator_hash or _hash("EVAL_HASH", "eval-1"),
        evaluator_origin=evaluator_origin,
        evaluator_independence_basis=evaluator_independence_basis,
    )


def test_far_denominator_is_all_invalid_cases() -> None:
    from poi_mpp.reporting.e3 import semantic_metrics

    records = (
        _row(case_id="case-1", reference_valid=False, verifier_decision=VerificationDecision.ACCEPT),
        _row(case_id="case-2", reference_valid=False, verifier_decision=VerificationDecision.REJECT),
        _row(case_id="case-3", reference_valid=True, verifier_decision=VerificationDecision.ACCEPT),
        _row(case_id="case-4", reference_valid=True, verifier_decision=VerificationDecision.REJECT),
    )

    result = semantic_metrics(records)

    assert result.far.denominator == 2
    assert result.far.numerator == 1
    assert result.frr.denominator == 2
    assert result.reference_agreement.denominator == 4


def test_zero_denominator_is_explicit_when_no_invalid_cases() -> None:
    from poi_mpp.reporting.e3 import semantic_metrics

    records = (
        _row(case_id="case-1", reference_valid=True, verifier_decision=VerificationDecision.ABSTAIN),
        _row(case_id="case-2", reference_valid=True, verifier_decision=VerificationDecision.ABSTAIN),
    )

    result = semantic_metrics(records)

    assert result.far.denominator == 0
    assert result.far.zero_denominator is True
    assert result.far.value is None
    assert result.coverage.numerator == 0
    assert result.calibration.zero_denominator is True


def test_synthetic_confirmation_is_rejected() -> None:
    from poi_mpp.experiments.e3_semantic import PublicationEligibilityError, run_confirmatory_semantic

    config = _confirmatory_config(
        dataset_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        confirmatory_manifest=_manifest(
            dataset_id="confirm-e3",
            split=DatasetSplit.PLUMBING,
            origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
            record_ids=("plumb-1",),
        ),
    )

    with pytest.raises(PublicationEligibilityError, match="synthetic non-evidence"):
        run_confirmatory_semantic(config=config, rows=(_row(case_id="case-1", reference_valid=True, verifier_decision=VerificationDecision.ACCEPT),))


def test_confirmatory_overlap_is_rejected() -> None:
    from poi_mpp.experiments.e3_semantic import PublicationEligibilityError, run_confirmatory_semantic

    overlapping_manifest = _manifest(
        dataset_id="confirm-e3",
        split=DatasetSplit.CONFIRMATORY,
        origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        record_ids=("dev-1",),
    )
    config = _confirmatory_config(
        dataset_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        confirmatory_manifest=overlapping_manifest,
    )

    with pytest.raises(PublicationEligibilityError, match="overlap"):
        run_confirmatory_semantic(config=config, rows=(_row(case_id="case-1", reference_valid=True, verifier_decision=VerificationDecision.ACCEPT),))


def test_confirmatory_requires_real_model_execution_origin() -> None:
    from poi_mpp.experiments.e3_semantic import PublicationEligibilityError, run_confirmatory_semantic

    config = _publication_config(
        run_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        dataset_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    )

    with pytest.raises(PublicationEligibilityError, match="run_config.origin must equal REAL_MODEL_EXECUTION"):
        run_confirmatory_semantic(
            config=config,
            rows=(
                _publication_row(
                    origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
                    source_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
                    annotation_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
                    evaluator_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
                ),
            ),
        )


def test_row_evaluator_provenance_must_match_verified_registry() -> None:
    from poi_mpp.experiments.e3_semantic import PublicationEligibilityError, run_confirmatory_semantic

    config = _publication_config(
        run_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        dataset_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
    )

    with pytest.raises(PublicationEligibilityError, match="evaluator_hash must match the verified evaluator registry"):
        run_confirmatory_semantic(
            config=config,
            rows=(
                _publication_row(
                    evaluator_hash=_hash("ROW_EVAL_HASH", "mismatch"),
                    evaluator_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                    evaluator_independence_basis="caller supplied mismatch",
                ),
            ),
        )


def test_forged_provenance_bundle_is_rejected() -> None:
    from poi_mpp.experiments.e3_semantic import PublicationEligibilityError, run_confirmatory_semantic

    forged_manifest = RunManifest(
        run_id="run-e3-publication",
        experiment_id="E3",
        config_hash=_hash("FORGED_CONFIG", "x"),
        environment_hash=environment_hash(
            EnvironmentManifest(
                python_implementation="CPython",
                python_version="3.11.15",
                os_name="Darwin",
                os_release="26.0.0",
                machine="arm64",
                cpu_model="Apple M4",
                gpu_model="Apple GPU",
                package_lock_hash="5" * 64,
                compiler_version=None,
                foundry_version=None,
                code_revision="6" * 40,
            )
        ),
        code_revision="UNVERSIONED_BLOCKED",
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        authorization_scope="PUBLICATION_EVIDENCE_AUTHORIZED",
        model_hash="3" * 64,
        dataset_hash="4" * 64,
        parent_hashes=(),
    )
    config = _publication_config(
        run_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        dataset_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        forged_manifest=forged_manifest,
    )

    with pytest.raises(PublicationEligibilityError, match="provenance manifest does not equal recomputed freeze_run"):
        run_confirmatory_semantic(config=config, rows=(_publication_row(),))


def test_cli_loads_pilot_config_then_stops_at_authority_boundary() -> None:
    repo = Path("/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts")
    completed = subprocess.run(
        [
            str(repo / ".venv/bin/python"),
            str(repo / "experiments/e3_semantic_eval.py"),
            "--config",
            str(repo / "configs/pilot/e3.yaml"),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    combined = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode != 0
    assert "frozen confirmatory dataset manifest" in combined
    assert "schema_hash" not in combined
