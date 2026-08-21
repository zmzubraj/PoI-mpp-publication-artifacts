from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from poi_mpp.auditor.semantic.models import SemanticCalibrationArtifact, SemanticOutcome, VerificationDecision
from poi_mpp.datasets.manifests import DatasetManifest, DatasetRecord, DatasetSplit
from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig, approved_schema_hash
from poi_mpp.evidence.models import ArtifactStage, EvidenceOrigin


def _hash(label: str, value: str) -> str:
    return digest(label, value)


def _record(
    *,
    record_id: str,
    split: DatasetSplit,
    origin: EvidenceOrigin,
    salt: str,
) -> DatasetRecord:
    return DatasetRecord(
        record_id=record_id,
        split=split,
        origin=origin,
        source_family=f"{split.value.lower()}-{salt}",
        source_hash=_hash("DATASET_SOURCE", f"{split.value}:{salt}:source"),
        content_hash=_hash("DATASET_CONTENT", f"{split.value}:{salt}:content"),
    )


def _manifest(
    *,
    dataset_id: str,
    split: DatasetSplit,
    origin: EvidenceOrigin,
    record_specs: tuple[tuple[str, str], ...],
) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        split=split,
        records=tuple(
            _record(record_id=record_id, split=split, origin=origin, salt=salt)
            for record_id, salt in record_specs
        ),
    )


def _run_config(
    *,
    run_id: str,
    origin: EvidenceOrigin,
    authorization_scope: str,
) -> RunConfig:
    return RunConfig.model_validate(
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": run_id,
            "experiment_id": "E3",
            "origin": origin.value,
            "authorization_scope": authorization_scope,
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


def _plumbing_row(
    *,
    case_id: str,
    reference_valid: bool,
    verifier_decision: VerificationDecision,
    subgroup: str = "core",
    source_salt: str | None = None,
    annotation_salt: str | None = None,
):
    from poi_mpp.experiments.e3_semantic import E3SemanticRow

    reference_outcome = (
        SemanticOutcome.SUPPORTED if reference_valid else SemanticOutcome.CONTRADICTORY
    )
    if verifier_decision is VerificationDecision.ACCEPT:
        verifier_outcome = SemanticOutcome.SUPPORTED
        verifier_confidence = 0.92
    elif verifier_decision is VerificationDecision.REJECT:
        verifier_outcome = SemanticOutcome.CONTRADICTORY
        verifier_confidence = 0.81
    else:
        verifier_outcome = None
        verifier_confidence = None
    source_tag = source_salt or case_id
    annotation_tag = annotation_salt or case_id
    return E3SemanticRow(
        run_id="run-e3-plumbing",
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
        verifier_confidence=verifier_confidence,
        calibration_hash=_calibration().content_hash,
        source_record_id=f"source-{case_id}",
        source_content_hash=_hash("DATASET_CONTENT", f"{DatasetSplit.PLUMBING.value}:{source_tag}:content"),
        source_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        annotation_record_id=f"annotation-{case_id}",
        annotation_hash=_hash("DATASET_CONTENT", f"{DatasetSplit.PLUMBING.value}:{annotation_tag}:content"),
        annotation_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        evaluator_id="synthetic-plumbing-evaluator",
        evaluator_hash=_hash("EVAL_HASH", "synthetic-plumbing-evaluator"),
        evaluator_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        evaluator_independence_basis="SYNTHETIC_NON_EVIDENCE_PLUMBING_ONLY",
    )


def _plumbing_config():
    from poi_mpp.experiments.e3_semantic import (
        E3DevelopmentDataset,
        E3ManifestClosure,
        E3SyntheticPlumbingConfig,
        E3SyntheticPlumbingEvaluator,
    )

    return E3SyntheticPlumbingConfig(
        run_config=_run_config(
            run_id="run-e3-plumbing",
            origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
            authorization_scope="LOCAL_TEST_ONLY",
        ),
        development_dataset=E3DevelopmentDataset(
            dataset_id="development-e3",
            manifest=_manifest(
                dataset_id="development-e3",
                split=DatasetSplit.DEVELOPMENT,
                origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
                record_specs=(("dev-1", "dev-1"), ("dev-2", "dev-2")),
            ),
            calibration=_calibration(),
        ),
        manifests=E3ManifestClosure(
            case_manifest=_manifest(
                dataset_id="cases-e3",
                split=DatasetSplit.PLUMBING,
                origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                record_specs=(("case-1", "case-1"), ("case-2", "case-2")),
            ),
            source_manifest=_manifest(
                dataset_id="sources-e3",
                split=DatasetSplit.PLUMBING,
                origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                record_specs=(("source-case-1", "case-1"), ("source-case-2", "case-2")),
            ),
            annotation_manifest=_manifest(
                dataset_id="annotations-e3",
                split=DatasetSplit.PLUMBING,
                origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                record_specs=(("annotation-case-1", "case-1"), ("annotation-case-2", "case-2")),
            ),
        ),
        evaluators=(
            E3SyntheticPlumbingEvaluator(
                evaluator_id="synthetic-plumbing-evaluator",
                evaluator_hash=_hash("EVAL_HASH", "synthetic-plumbing-evaluator"),
                origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                independence_basis="SYNTHETIC_NON_EVIDENCE_PLUMBING_ONLY",
            ),
        ),
    )


def _confirmatory_config():
    from poi_mpp.experiments.e3_semantic import (
        E3ConfirmatoryConfig,
        E3DeclaredEvaluator,
        E3DevelopmentDataset,
        E3ManifestClosure,
        E3_CONFIRMATORY_SCOPE,
    )

    return E3ConfirmatoryConfig(
        run_config=_run_config(
            run_id="run-e3-confirm",
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
            authorization_scope="PUBLICATION_EVIDENCE_AUTHORIZED",
        ),
        publication_scope=E3_CONFIRMATORY_SCOPE,
        development_dataset=E3DevelopmentDataset(
            dataset_id="development-e3",
            manifest=_manifest(
                dataset_id="development-e3",
                split=DatasetSplit.DEVELOPMENT,
                origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
                record_specs=(("dev-1", "dev-1"), ("dev-2", "dev-2")),
            ),
            calibration=_calibration(),
        ),
        manifests=E3ManifestClosure(
            case_manifest=_manifest(
                dataset_id="cases-e3-confirm",
                split=DatasetSplit.CONFIRMATORY,
                origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
                record_specs=(("case-1", "case-1"),),
            ),
            source_manifest=_manifest(
                dataset_id="sources-e3-confirm",
                split=DatasetSplit.CONFIRMATORY,
                origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
                record_specs=(("source-case-1", "case-1"),),
            ),
            annotation_manifest=_manifest(
                dataset_id="annotations-e3-confirm",
                split=DatasetSplit.CONFIRMATORY,
                origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
                record_specs=(("annotation-case-1", "case-1"),),
            ),
        ),
        evaluators=(
            E3DeclaredEvaluator(
                evaluator_id="real-evaluator-1",
                evaluator_hash=_hash("EVAL_HASH", "real-evaluator-1"),
                origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
                independence_basis="declared-only-no-authority",
            ),
        ),
        license_id="license-1",
        privacy_status="PUBLIC",
        annotation_protocol_id="proto-1",
    )


def _confirmatory_row():
    from poi_mpp.experiments.e3_semantic import E3SemanticRow

    return E3SemanticRow(
        run_id="run-e3-confirm",
        experiment_id="E3",
        case_id="case-1",
        split=DatasetSplit.CONFIRMATORY,
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        frozen_reference_valid=True,
        frozen_reference_outcome=SemanticOutcome.SUPPORTED,
        verifier_decision=VerificationDecision.ACCEPT,
        verifier_outcome=SemanticOutcome.SUPPORTED,
        abstained=False,
        subgroup="core",
        verifier_confidence=0.95,
        calibration_hash=_calibration().content_hash,
        source_record_id="source-case-1",
        source_content_hash=_hash("DATASET_CONTENT", f"{DatasetSplit.CONFIRMATORY.value}:case-1:content"),
        source_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        annotation_record_id="annotation-case-1",
        annotation_hash=_hash("DATASET_CONTENT", f"{DatasetSplit.CONFIRMATORY.value}:case-1:content"),
        annotation_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        evaluator_id="real-evaluator-1",
        evaluator_hash=_hash("EVAL_HASH", "real-evaluator-1"),
        evaluator_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        evaluator_independence_basis="declared-only-no-authority",
    )


def test_far_denominator_is_all_invalid_cases() -> None:
    from poi_mpp.reporting.e3 import semantic_metrics

    records = (
        _plumbing_row(case_id="case-1", reference_valid=False, verifier_decision=VerificationDecision.ACCEPT),
        _plumbing_row(case_id="case-2", reference_valid=False, verifier_decision=VerificationDecision.REJECT),
        _plumbing_row(case_id="case-3", reference_valid=True, verifier_decision=VerificationDecision.ACCEPT),
        _plumbing_row(case_id="case-4", reference_valid=True, verifier_decision=VerificationDecision.REJECT),
    )

    result = semantic_metrics(records)

    assert result.far.denominator == 2
    assert result.far.numerator == 1
    assert result.frr.denominator == 2
    assert result.reference_agreement.denominator == 4


def test_zero_denominator_is_explicit_when_no_invalid_cases() -> None:
    from poi_mpp.reporting.e3 import semantic_metrics

    records = (
        _plumbing_row(case_id="case-1", reference_valid=True, verifier_decision=VerificationDecision.ABSTAIN),
        _plumbing_row(case_id="case-2", reference_valid=True, verifier_decision=VerificationDecision.ABSTAIN),
    )

    result = semantic_metrics(records)

    assert result.far.denominator == 0
    assert result.far.zero_denominator is True
    assert result.far.value is None
    assert result.coverage.numerator == 0
    assert result.calibration.zero_denominator is True


def test_synthetic_plumbing_runner_emits_nonterminal_metrics() -> None:
    from poi_mpp.experiments.e3_semantic import run_synthetic_plumbing_semantic

    result = run_synthetic_plumbing_semantic(
        config=_plumbing_config(),
        rows=(
            _plumbing_row(case_id="case-1", reference_valid=True, verifier_decision=VerificationDecision.ACCEPT),
            _plumbing_row(case_id="case-2", reference_valid=False, verifier_decision=VerificationDecision.REJECT),
        ),
    )

    assert result.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE
    assert result.stage is ArtifactStage.SEMANTICALLY_VALID
    assert result.summary.denominator == 2
    assert result.summary.coverage.numerator == 2


def test_plumbing_requires_source_manifest_closure_before_metrics() -> None:
    from poi_mpp.experiments.e3_semantic import E3EvaluationContractError, run_synthetic_plumbing_semantic

    with pytest.raises(E3EvaluationContractError, match="source manifest"):
        run_synthetic_plumbing_semantic(
            config=_plumbing_config(),
            rows=(
                _plumbing_row(
                    case_id="case-1",
                    reference_valid=True,
                    verifier_decision=VerificationDecision.ACCEPT,
                    source_salt="forged-source",
                ),
                _plumbing_row(case_id="case-2", reference_valid=False, verifier_decision=VerificationDecision.REJECT),
            ),
        )


def test_plumbing_requires_annotation_manifest_closure_before_metrics() -> None:
    from poi_mpp.experiments.e3_semantic import E3EvaluationContractError, run_synthetic_plumbing_semantic

    with pytest.raises(E3EvaluationContractError, match="annotation manifest"):
        run_synthetic_plumbing_semantic(
            config=_plumbing_config(),
            rows=(
                _plumbing_row(case_id="case-1", reference_valid=True, verifier_decision=VerificationDecision.ACCEPT),
                _plumbing_row(
                    case_id="case-2",
                    reference_valid=False,
                    verifier_decision=VerificationDecision.REJECT,
                    annotation_salt="forged-annotation",
                ),
            ),
        )


def test_real_confirmatory_waits_for_external_evaluator_authority() -> None:
    from poi_mpp.experiments.e3_semantic import PublicationEligibilityError, run_confirmatory_semantic

    with pytest.raises(PublicationEligibilityError, match="WAITING_EXTERNAL_EVALUATOR_AUTHORITY"):
        run_confirmatory_semantic(
            config=_confirmatory_config(),
            rows=(_confirmatory_row(),),
        )


def test_confirmatory_row_outside_manifest_is_rejected_before_authority_boundary() -> None:
    from poi_mpp.experiments.e3_semantic import PublicationEligibilityError, run_confirmatory_semantic

    forged_row = _confirmatory_row().model_copy(update={"source_record_id": "source-missing"})

    with pytest.raises(PublicationEligibilityError, match="source manifest"):
        run_confirmatory_semantic(
            config=_confirmatory_config(),
            rows=(forged_row,),
        )


def test_cli_loads_schema_then_stops_at_external_authority_boundary() -> None:
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
    assert "WAITING_EXTERNAL_EVALUATOR_AUTHORITY" in combined
    assert "schema_hash" not in combined


def test_cli_rejects_corrupt_schema_copy_before_authority_boundary(tmp_path: Path) -> None:
    repo = Path("/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts")
    schema_copy = tmp_path / "e3.schema.yaml"
    schema_copy.write_text("not: [valid\n", encoding="utf-8")

    completed = subprocess.run(
        [
            str(repo / ".venv/bin/python"),
            str(repo / "experiments/e3_semantic_eval.py"),
            "--config",
            str(repo / "configs/pilot/e3.yaml"),
            "--schema",
            str(schema_copy),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    combined = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode != 0
    assert "unable to load E3 confirmatory schema" in combined
    assert "WAITING_EXTERNAL_EVALUATOR_AUTHORITY" not in combined


def test_cli_rejects_mismatched_schema_copy_before_authority_boundary(tmp_path: Path) -> None:
    repo = Path("/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts")
    schema_copy = tmp_path / "e3.schema.yaml"
    schema_copy.write_text(
        (
            "schema_version: POI_MPP_E3_CONFIRMATORY_SCOPE_V1\n"
            "publication_scope: WRONG_SCOPE\n"
            "required_run_origin: REAL_MODEL_EXECUTION\n"
            "required_run_authorization_scope: PUBLICATION_EVIDENCE_AUTHORIZED\n"
            "required_calibration_split: DEVELOPMENT\n"
            "required_confirmatory_manifest_split: CONFIRMATORY\n"
            "forbidden_confirmatory_origins:\n"
            "  - SYNTHETIC_NON_EVIDENCE\n"
            "required_confirmatory_metadata:\n"
            "  - license_id\n"
            "  - privacy_status\n"
            "  - annotation_protocol_id\n"
            "required_evaluator_fields:\n"
            "  - evaluator_id\n"
            "  - evaluator_hash\n"
            "  - independence_basis\n"
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(repo / ".venv/bin/python"),
            str(repo / "experiments/e3_semantic_eval.py"),
            "--config",
            str(repo / "configs/pilot/e3.yaml"),
            "--schema",
            str(schema_copy),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    combined = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode != 0
    assert "publication_scope must equal E3_CONFIRMATORY_PUBLICATION_V1" in combined
    assert "WAITING_EXTERNAL_EVALUATOR_AUTHORITY" not in combined
