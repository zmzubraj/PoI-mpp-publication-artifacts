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

__all__ = [
    "E1ExecutionSample",
    "E1ExperimentResult",
    "E1MeasurementRow",
    "E2ReceiptRow",
    "build_fixture_bundle",
    "build_publication_record",
    "evaluate_receipt",
    "run_e1_cost_experiment",
    "run_two_run_baseline",
    "validate_attack_receipt",
]
