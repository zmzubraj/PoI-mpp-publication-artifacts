"""Development-only calibration for deterministic semantic verification."""

from __future__ import annotations

from poi_mpp.auditor.semantic.models import (
    DevelopmentCalibrationExample,
    SemanticCalibrationArtifact,
)


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
