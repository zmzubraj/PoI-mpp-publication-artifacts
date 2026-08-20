"""Deterministic aggregation for E3 grounded semantic assurance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
import math
import random

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from poi_mpp.auditor.semantic.models import SemanticOutcome, VerificationDecision


_WILSON_Z = 1.959963984540054


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IntervalKind(StrEnum):
    WILSON = "WILSON"
    BOOTSTRAP = "BOOTSTRAP"


class E3MetricPolicy(_FrozenModel):
    alpha_sem: float = Field(default=0.25, ge=0.0, le=1.0)
    minimum_useful_coverage: float = Field(default=0.5, ge=0.0, le=1.0)
    bootstrap_iterations: int = Field(default=256, gt=0)
    bootstrap_seed: int = Field(default=1, ge=0)


class RateEstimate(_FrozenModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_interval: tuple[float, float] | None = None
    zero_denominator: bool
    interval_kind: IntervalKind = IntervalKind.WILSON

    @field_validator("confidence_interval")
    @classmethod
    def validate_interval(
        cls,
        value: tuple[float, float] | None,
    ) -> tuple[float, float] | None:
        if value is None:
            return value
        if len(value) != 2 or value[0] > value[1]:
            raise ValueError("confidence_interval must contain ordered bounds")
        if any(not math.isfinite(bound) for bound in value):
            raise ValueError("confidence_interval must contain finite bounds")
        return value

    @model_validator(mode="after")
    def validate_denominator_contract(self) -> "RateEstimate":
        if self.zero_denominator:
            if self.denominator != 0:
                raise ValueError("zero_denominator requires denominator == 0")
            if self.value is not None or self.confidence_interval is not None:
                raise ValueError("zero_denominator metrics cannot carry value or interval")
            return self
        if self.denominator <= 0:
            raise ValueError("non-zero-denominator metrics require denominator > 0")
        if self.value is None or self.confidence_interval is None:
            raise ValueError("non-zero-denominator metrics require value and interval")
        if self.numerator > self.denominator:
            raise ValueError("numerator cannot exceed denominator")
        return self


class CalibrationEstimate(_FrozenModel):
    denominator: int = Field(ge=0)
    brier_score: float | None = Field(default=None, ge=0.0)
    confidence_interval: tuple[float, float] | None = None
    zero_denominator: bool
    interval_kind: IntervalKind = IntervalKind.BOOTSTRAP

    @field_validator("confidence_interval")
    @classmethod
    def validate_interval(
        cls,
        value: tuple[float, float] | None,
    ) -> tuple[float, float] | None:
        if value is None:
            return value
        if len(value) != 2 or value[0] > value[1]:
            raise ValueError("confidence_interval must contain ordered bounds")
        if any(not math.isfinite(bound) for bound in value):
            raise ValueError("confidence_interval must contain finite bounds")
        return value

    @model_validator(mode="after")
    def validate_zero_denominator_contract(self) -> "CalibrationEstimate":
        if self.zero_denominator:
            if self.denominator != 0:
                raise ValueError("zero_denominator requires denominator == 0")
            if self.brier_score is not None or self.confidence_interval is not None:
                raise ValueError("zero_denominator calibration cannot carry score or interval")
            return self
        if self.denominator <= 0:
            raise ValueError("non-zero-denominator calibration requires denominator > 0")
        if self.brier_score is None or self.confidence_interval is None:
            raise ValueError("non-zero-denominator calibration requires score and interval")
        return self


class E3ConfusionMatrix(_FrozenModel):
    valid_accept: int = Field(ge=0)
    valid_reject: int = Field(ge=0)
    valid_abstain: int = Field(ge=0)
    invalid_accept: int = Field(ge=0)
    invalid_reject: int = Field(ge=0)
    invalid_abstain: int = Field(ge=0)

    @property
    def total(self) -> int:
        return (
            self.valid_accept
            + self.valid_reject
            + self.valid_abstain
            + self.invalid_accept
            + self.invalid_reject
            + self.invalid_abstain
        )


class E3SubgroupCount(_FrozenModel):
    subgroup: str
    total: int = Field(ge=0)
    valid: int = Field(ge=0)
    invalid: int = Field(ge=0)
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    abstained: int = Field(ge=0)

    @field_validator("subgroup")
    @classmethod
    def require_nonblank_subgroup(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("subgroup must not be blank")
        return value


class E3Summary(_FrozenModel):
    schema_version: str = "POI_MPP_E3_SUMMARY_V1"
    claim_id: str
    denominator: int = Field(ge=0)
    far: RateEstimate
    frr: RateEstimate
    abstention: RateEstimate
    coverage: RateEstimate
    precision: RateEstimate
    recall: RateEstimate
    reference_agreement: RateEstimate
    calibration: CalibrationEstimate
    confusion_matrix: E3ConfusionMatrix
    subgroup_counts: tuple[E3SubgroupCount, ...]
    policy: E3MetricPolicy
    claim_disposition: str

    @field_validator("claim_id", "claim_disposition")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @model_validator(mode="after")
    def validate_total_matches_confusion(self) -> "E3Summary":
        if self.denominator != self.confusion_matrix.total:
            raise ValueError("denominator must equal confusion matrix total")
        if self.far.denominator != (
            self.confusion_matrix.invalid_accept
            + self.confusion_matrix.invalid_reject
            + self.confusion_matrix.invalid_abstain
        ):
            raise ValueError("far denominator must equal all invalid cases")
        if self.frr.denominator != (
            self.confusion_matrix.valid_accept
            + self.confusion_matrix.valid_reject
            + self.confusion_matrix.valid_abstain
        ):
            raise ValueError("frr denominator must equal all valid cases")
        return self


def _wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    if trials <= 0:
        raise ValueError("Wilson interval requires positive trials")
    proportion = successes / trials
    z_squared = _WILSON_Z * _WILSON_Z
    denominator = 1.0 + (z_squared / trials)
    centre = proportion + (z_squared / (2.0 * trials))
    margin = _WILSON_Z * math.sqrt(
        ((proportion * (1.0 - proportion)) / trials)
        + (z_squared / (4.0 * trials * trials))
    )
    lower = max(0.0, (centre - margin) / denominator)
    upper = min(1.0, (centre + margin) / denominator)
    return (lower, upper)


def _rate(numerator: int, denominator: int) -> RateEstimate:
    if denominator == 0:
        return RateEstimate(
            numerator=numerator,
            denominator=0,
            value=None,
            confidence_interval=None,
            zero_denominator=True,
        )
    return RateEstimate(
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator,
        confidence_interval=_wilson_interval(numerator, denominator),
        zero_denominator=False,
    )


def _bootstrap_interval(
    values: Sequence[float],
    *,
    iterations: int,
    seed: int,
) -> tuple[float, float]:
    if not values:
        raise ValueError("bootstrap interval requires at least one value")
    generator = random.Random(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        sample = [generator.choice(values) for _ in range(len(values))]
        estimates.append(sum(sample) / len(sample))
    estimates.sort()
    lower_index = max(0, int(0.025 * (iterations - 1)))
    upper_index = min(iterations - 1, int(0.975 * (iterations - 1)))
    return (estimates[lower_index], estimates[upper_index])


def _calibration(correctness_scores: list[float], *, policy: E3MetricPolicy) -> CalibrationEstimate:
    if not correctness_scores:
        return CalibrationEstimate(
            denominator=0,
            brier_score=None,
            confidence_interval=None,
            zero_denominator=True,
        )
    brier = sum(correctness_scores) / len(correctness_scores)
    return CalibrationEstimate(
        denominator=len(correctness_scores),
        brier_score=brier,
        confidence_interval=_bootstrap_interval(
            correctness_scores,
            iterations=policy.bootstrap_iterations,
            seed=policy.bootstrap_seed,
        ),
        zero_denominator=False,
    )


def _row_mapping(row: object) -> dict[str, object]:
    from poi_mpp.experiments.e3_semantic import E3SemanticRow

    if isinstance(row, E3SemanticRow):
        return row.model_dump(mode="python")
    if isinstance(row, BaseModel):
        return row.model_dump(mode="python")
    if isinstance(row, Mapping):
        return dict(row)
    raise ValueError("E3 rows must be mappings or typed E3SemanticRow objects")


def _claim_disposition(
    *,
    far: RateEstimate,
    frr: RateEstimate,
    coverage: RateEstimate,
    policy: E3MetricPolicy,
) -> str:
    if far.zero_denominator or frr.zero_denominator or coverage.zero_denominator:
        return "INCONCLUSIVE"
    assert far.value is not None
    assert frr.value is not None
    assert coverage.value is not None
    if coverage.value < policy.minimum_useful_coverage:
        return "NOT_SUPPORTED"
    if far.confidence_interval is None or frr.confidence_interval is None:
        return "INCONCLUSIVE"
    if far.confidence_interval[1] <= policy.alpha_sem and frr.confidence_interval[1] <= policy.alpha_sem:
        return "SUPPORTED"
    if far.value > policy.alpha_sem or frr.value > policy.alpha_sem:
        return "NOT_SUPPORTED"
    return "INCONCLUSIVE"


def semantic_metrics(
    rows: Sequence[object],
    *,
    claim_id: str = "C3",
    policy: E3MetricPolicy | None = None,
) -> E3Summary:
    from poi_mpp.experiments.e3_semantic import E3SemanticRow

    frozen_policy = policy or E3MetricPolicy()
    if not rows:
        raise ValueError("E3 summary requires semantic rows")
    canonical_rows = [
        E3SemanticRow.model_validate(_row_mapping(row))
        for row in rows
    ]

    run_ids = {row.run_id for row in canonical_rows}
    experiment_ids = {row.experiment_id for row in canonical_rows}
    case_ids = [row.case_id for row in canonical_rows]
    if len(run_ids) != 1 or len(experiment_ids) != 1:
        raise ValueError("E3 rows must share one run_id and experiment_id")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("E3 case_id values must be unique")

    valid_accept = valid_reject = valid_abstain = 0
    invalid_accept = invalid_reject = invalid_abstain = 0
    subgroup_counts: dict[str, dict[str, int]] = {}
    calibration_errors: list[float] = []
    reference_agreement_numerator = 0
    reference_agreement_denominator = 0
    total_accepts = 0
    true_accepts = 0

    for row in canonical_rows:
        subgroup = subgroup_counts.setdefault(
            row.subgroup,
            {
                "total": 0,
                "valid": 0,
                "invalid": 0,
                "accepted": 0,
                "rejected": 0,
                "abstained": 0,
            },
        )
        subgroup["total"] += 1
        if row.frozen_reference_valid:
            subgroup["valid"] += 1
        else:
            subgroup["invalid"] += 1

        if row.verifier_decision is VerificationDecision.ACCEPT:
            subgroup["accepted"] += 1
            total_accepts += 1
            if row.frozen_reference_valid:
                true_accepts += 1
                valid_accept += 1
            else:
                invalid_accept += 1
        elif row.verifier_decision is VerificationDecision.REJECT:
            subgroup["rejected"] += 1
            if row.frozen_reference_valid:
                valid_reject += 1
            else:
                invalid_reject += 1
        else:
            subgroup["abstained"] += 1
            if row.frozen_reference_valid:
                valid_abstain += 1
            else:
                invalid_abstain += 1

        if row.verifier_decision is not VerificationDecision.ABSTAIN:
            reference_agreement_denominator += 1
            if row.verifier_outcome == row.frozen_reference_outcome:
                reference_agreement_numerator += 1
            assert row.verifier_confidence is not None
            is_correct = (
                (row.verifier_decision is VerificationDecision.ACCEPT and row.frozen_reference_valid)
                or (row.verifier_decision is VerificationDecision.REJECT and not row.frozen_reference_valid)
            )
            calibration_errors.append((row.verifier_confidence - float(is_correct)) ** 2)

    confusion = E3ConfusionMatrix(
        valid_accept=valid_accept,
        valid_reject=valid_reject,
        valid_abstain=valid_abstain,
        invalid_accept=invalid_accept,
        invalid_reject=invalid_reject,
        invalid_abstain=invalid_abstain,
    )

    far = _rate(invalid_accept, invalid_accept + invalid_reject + invalid_abstain)
    frr = _rate(valid_reject, valid_accept + valid_reject + valid_abstain)
    abstention = _rate(valid_abstain + invalid_abstain, len(canonical_rows))
    coverage = _rate(valid_accept + valid_reject + invalid_accept + invalid_reject, len(canonical_rows))
    precision = _rate(true_accepts, total_accepts)
    recall = _rate(true_accepts, valid_accept + valid_reject + valid_abstain)
    reference_agreement = _rate(reference_agreement_numerator, reference_agreement_denominator)
    calibration = _calibration(calibration_errors, policy=frozen_policy)

    return E3Summary(
        claim_id=claim_id,
        denominator=len(canonical_rows),
        far=far,
        frr=frr,
        abstention=abstention,
        coverage=coverage,
        precision=precision,
        recall=recall,
        reference_agreement=reference_agreement,
        calibration=calibration,
        confusion_matrix=confusion,
        subgroup_counts=tuple(
            E3SubgroupCount(subgroup=subgroup, **counts)
            for subgroup, counts in sorted(subgroup_counts.items())
        ),
        policy=frozen_policy,
        claim_disposition=_claim_disposition(
            far=far,
            frr=frr,
            coverage=coverage,
            policy=frozen_policy,
        ),
    )
