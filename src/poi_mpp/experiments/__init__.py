"""Experiment entrypoints for publication-bound MPP slices."""

from poi_mpp.experiments.e1_cost import (
    E1ExecutionSample,
    E1ExperimentResult,
    E1MeasurementRow,
    run_e1_cost_experiment,
    run_two_run_baseline,
)
from poi_mpp.experiments.e2_tamper import (
    E2ReceiptRow,
    build_fixture_bundle,
    build_publication_record,
    evaluate_receipt,
    validate_attack_receipt,
)
from poi_mpp.experiments.e3_semantic import (
    E3ConfirmatoryConfig,
    E3ConfirmatoryDataset,
    E3ConfirmatoryResult,
    E3DevelopmentDataset,
    E3EvaluatorAuthority,
    E3SemanticRow,
    PublicationEligibilityError,
    run_confirmatory_semantic,
)

__all__ = [
    "E1ExecutionSample",
    "E1ExperimentResult",
    "E1MeasurementRow",
    "E2ReceiptRow",
    "E3ConfirmatoryConfig",
    "E3ConfirmatoryDataset",
    "E3ConfirmatoryResult",
    "E3DevelopmentDataset",
    "E3EvaluatorAuthority",
    "E3SemanticRow",
    "PublicationEligibilityError",
    "build_fixture_bundle",
    "build_publication_record",
    "evaluate_receipt",
    "run_confirmatory_semantic",
    "run_e1_cost_experiment",
    "run_two_run_baseline",
    "validate_attack_receipt",
]
