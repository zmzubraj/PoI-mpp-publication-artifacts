"""Versioned, immutable claim specifications for publication-bound evidence."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
import math
import operator
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator, field_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import EvidenceOrigin


_CLAIM_ID = re.compile(r"C[1-9][0-9]*\Z")
_METRIC_ID = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class _FrozenClaimModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceMaturity(StrEnum):
    V0_ASSERTED = "V0_ASSERTED"
    V1_ANALYTIC = "V1_ANALYTIC"
    V2_SIMULATED = "V2_SIMULATED"
    V3_INTERNAL = "V3_INTERNAL"
    V4_EXTERNAL = "V4_EXTERNAL"
    V5_FIELD = "V5_FIELD"


class ClaimDisposition(StrEnum):
    SUPPORTED = "SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class MetricValueSource(StrEnum):
    POINT_ESTIMATE = "POINT_ESTIMATE"
    LOWER_CONFIDENCE_BOUND = "LOWER_CONFIDENCE_BOUND"
    UPPER_CONFIDENCE_BOUND = "UPPER_CONFIDENCE_BOUND"


class ThresholdOperator(StrEnum):
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="


_OPERATORS = {
    ThresholdOperator.LT: operator.lt,
    ThresholdOperator.LE: operator.le,
    ThresholdOperator.GT: operator.gt,
    ThresholdOperator.GE: operator.ge,
}


def _conditions_are_jointly_feasible(
    conditions: tuple["ClaimRuleCondition", ...],
) -> bool:
    bounds: dict[
        tuple[str, MetricValueSource],
        tuple[float | None, bool, float | None, bool],
    ] = {}
    for condition in conditions:
        key = (condition.metric_id, condition.source)
        lower, lower_inclusive, upper, upper_inclusive = bounds.get(
            key, (None, False, None, False)
        )
        if condition.operator in {ThresholdOperator.GT, ThresholdOperator.GE}:
            inclusive = condition.operator is ThresholdOperator.GE
            if lower is None or condition.threshold > lower:
                lower, lower_inclusive = condition.threshold, inclusive
            elif condition.threshold == lower:
                lower_inclusive = lower_inclusive and inclusive
        else:
            inclusive = condition.operator is ThresholdOperator.LE
            if upper is None or condition.threshold < upper:
                upper, upper_inclusive = condition.threshold, inclusive
            elif condition.threshold == upper:
                upper_inclusive = upper_inclusive and inclusive
        if lower is not None and upper is not None:
            if lower > upper:
                return False
            if lower == upper and not (lower_inclusive and upper_inclusive):
                return False
        bounds[key] = (lower, lower_inclusive, upper, upper_inclusive)
    return True


def _normalized_string(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if value != value.strip() or not value:
        raise ValueError(f"{field_name} must not be blank or padded")
    return value


def _normalized_identifier(value: str, *, field_name: str, pattern: re.Pattern[str]) -> str:
    normalized = _normalized_string(value, field_name=field_name)
    if pattern.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} has an invalid format")
    return normalized


def _normalized_exact_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an exact integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _normalized_finite_float(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _normalized_unique_strings(
    values: Any,
    *,
    field_name: str,
    pattern: re.Pattern[str] | None = None,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a sequence")
    normalized = tuple(
        _normalized_identifier(item, field_name=field_name, pattern=pattern)
        if pattern is not None
        else _normalized_string(item, field_name=field_name)
        for item in values
    )
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


class ClaimScope(_FrozenClaimModel):
    model_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    environment_ids: tuple[str, ...]
    experiment_ids: tuple[str, ...]

    @field_validator("model_ids", "task_ids", "environment_ids", "experiment_ids", mode="before")
    @classmethod
    def normalize_scope_items(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _normalized_unique_strings(value, field_name=info.field_name)


class ClaimMetricSpec(_FrozenClaimModel):
    metric_id: str
    denominator_id: str
    minimum_denominator: int
    confidence_interval_required: bool
    threshold_hint: float | None = None

    @field_validator("metric_id", mode="before")
    @classmethod
    def normalize_metric_id(cls, value: Any) -> str:
        return _normalized_identifier(value, field_name="metric_id", pattern=_METRIC_ID)

    @field_validator("denominator_id", mode="before")
    @classmethod
    def normalize_denominator_id(cls, value: Any) -> str:
        return _normalized_identifier(value, field_name="denominator_id", pattern=_SAFE_TOKEN)

    @field_validator("minimum_denominator", mode="before")
    @classmethod
    def normalize_minimum_denominator(cls, value: Any) -> int:
        return _normalized_exact_positive_int(value, field_name="minimum_denominator")

    @field_validator("threshold_hint", mode="before")
    @classmethod
    def normalize_threshold_hint(cls, value: Any) -> float | None:
        if value is None:
            return None
        return _normalized_finite_float(value, field_name="threshold_hint")


class ClaimMetricObservation(_FrozenClaimModel):
    metric_id: str
    point_estimate: float
    denominator: int
    confidence_interval: tuple[float, float] | None = None

    @field_validator("metric_id", mode="before")
    @classmethod
    def normalize_metric_id(cls, value: Any) -> str:
        return _normalized_identifier(value, field_name="metric_id", pattern=_METRIC_ID)

    @field_validator("point_estimate", mode="before")
    @classmethod
    def normalize_point_estimate(cls, value: Any) -> float:
        return _normalized_finite_float(value, field_name="point_estimate")

    @field_validator("denominator", mode="before")
    @classmethod
    def normalize_denominator(cls, value: Any) -> int:
        return _normalized_exact_positive_int(value, field_name="denominator")

    @field_validator("confidence_interval", mode="before")
    @classmethod
    def normalize_confidence_interval(cls, value: Any) -> tuple[float, float] | None:
        if value is None:
            return None
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("confidence_interval must contain exactly two bounds")
        lower = _normalized_finite_float(value[0], field_name="confidence_interval")
        upper = _normalized_finite_float(value[1], field_name="confidence_interval")
        if lower > upper:
            raise ValueError("confidence_interval lower bound exceeds upper bound")
        return (lower, upper)


class ClaimRuleCondition(_FrozenClaimModel):
    metric_id: str
    source: MetricValueSource
    operator: ThresholdOperator
    threshold: float
    minimum_denominator: int

    @field_validator("metric_id", mode="before")
    @classmethod
    def normalize_metric_id(cls, value: Any) -> str:
        return _normalized_identifier(value, field_name="metric_id", pattern=_METRIC_ID)

    @field_validator("threshold", mode="before")
    @classmethod
    def normalize_threshold(cls, value: Any) -> float:
        return _normalized_finite_float(value, field_name="threshold")

    @field_validator("minimum_denominator", mode="before")
    @classmethod
    def normalize_minimum_denominator(cls, value: Any) -> int:
        return _normalized_exact_positive_int(value, field_name="minimum_denominator")

    def evaluate(self, observation: ClaimMetricObservation | None) -> bool:
        if observation is None or observation.denominator < self.minimum_denominator:
            return False
        metric_value: float
        if self.source is MetricValueSource.POINT_ESTIMATE:
            metric_value = observation.point_estimate
        elif observation.confidence_interval is None:
            return False
        elif self.source is MetricValueSource.LOWER_CONFIDENCE_BOUND:
            metric_value = observation.confidence_interval[0]
        else:
            metric_value = observation.confidence_interval[1]
        return _OPERATORS[self.operator](metric_value, self.threshold)


class ClaimDecisionRule(_FrozenClaimModel):
    disposition: ClaimDisposition
    conditions: tuple[ClaimRuleCondition, ...]
    reason: str

    @field_validator("conditions", mode="before")
    @classmethod
    def normalize_conditions(cls, value: Any) -> tuple[ClaimRuleCondition, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("conditions must be a sequence")
        conditions = tuple(
            item if isinstance(item, ClaimRuleCondition) else ClaimRuleCondition.model_validate(item)
            for item in value
        )
        if not conditions:
            raise ValueError("conditions must not be empty")
        identities = {
            (
                condition.metric_id,
                condition.source.value,
                condition.operator.value,
                condition.threshold,
                condition.minimum_denominator,
            )
            for condition in conditions
        }
        if len(identities) != len(conditions):
            raise ValueError("conditions must not contain duplicates")
        return tuple(
            sorted(
                conditions,
                key=lambda item: (
                    item.metric_id,
                    item.source.value,
                    item.operator.value,
                    item.threshold,
                    item.minimum_denominator,
                ),
            )
        )

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: Any) -> str:
        return _normalized_string(value, field_name="reason")

    def evaluate(self, metrics: Mapping[str, ClaimMetricObservation]) -> bool:
        return all(condition.evaluate(metrics.get(condition.metric_id)) for condition in self.conditions)


class ClaimSpecV2(_FrozenClaimModel):
    schema_version: Literal["POI_MPP_CLAIM_SPEC_V2"] = "POI_MPP_CLAIM_SPEC_V2"
    claim_id: str
    revision: int
    admissible_wording: str
    scope: ClaimScope
    evidence_maturity_ceiling: EvidenceMaturity
    allowed_evidence_origins: tuple[EvidenceOrigin, ...]
    primary_metrics: tuple[ClaimMetricSpec, ...]
    confidence_interval_method: str
    supported_rule: ClaimDecisionRule
    inconclusive_rule: ClaimDecisionRule
    not_supported_rule: ClaimDecisionRule
    required_artifacts: tuple[str, ...]
    prohibited_generalizations: tuple[str, ...]

    @field_validator("claim_id", mode="before")
    @classmethod
    def normalize_claim_id(cls, value: Any) -> str:
        return _normalized_identifier(value, field_name="claim_id", pattern=_CLAIM_ID)

    @field_validator("revision", mode="before")
    @classmethod
    def normalize_revision(cls, value: Any) -> int:
        return _normalized_exact_positive_int(value, field_name="revision")

    @field_validator("admissible_wording", mode="before")
    @classmethod
    def normalize_admissible_wording(cls, value: Any) -> str:
        return _normalized_string(value, field_name="admissible_wording")

    @field_validator("allowed_evidence_origins", mode="before")
    @classmethod
    def normalize_allowed_origins(cls, value: Any) -> tuple[EvidenceOrigin, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("allowed_evidence_origins must be a sequence")
        origins = tuple(
            item if isinstance(item, EvidenceOrigin) else EvidenceOrigin(item)
            for item in value
        )
        if not origins:
            raise ValueError("allowed_evidence_origins must not be empty")
        if EvidenceOrigin.SYNTHETIC_NON_EVIDENCE in origins:
            raise ValueError("allowed_evidence_origins cannot include SYNTHETIC_NON_EVIDENCE")
        if len(set(origins)) != len(origins):
            raise ValueError("allowed_evidence_origins must not contain duplicates")
        return tuple(sorted(origins, key=lambda item: item.value))

    @field_validator("primary_metrics", mode="before")
    @classmethod
    def normalize_primary_metrics(cls, value: Any) -> tuple[ClaimMetricSpec, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("primary_metrics must be a sequence")
        metrics = tuple(
            item if isinstance(item, ClaimMetricSpec) else ClaimMetricSpec.model_validate(item)
            for item in value
        )
        if not metrics:
            raise ValueError("primary_metrics must not be empty")
        metric_ids = [metric.metric_id for metric in metrics]
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("primary_metrics must not contain duplicate metric_id values")
        return tuple(sorted(metrics, key=lambda item: item.metric_id))

    @field_validator("confidence_interval_method", mode="before")
    @classmethod
    def normalize_confidence_interval_method(cls, value: Any) -> str:
        return _normalized_identifier(
            value,
            field_name="confidence_interval_method",
            pattern=_SAFE_TOKEN,
        )

    @field_validator("required_artifacts", mode="before")
    @classmethod
    def normalize_required_artifacts(cls, value: Any) -> tuple[str, ...]:
        return _normalized_unique_strings(
            value,
            field_name="required_artifacts",
            pattern=_SAFE_TOKEN,
        )

    @field_validator("prohibited_generalizations", mode="before")
    @classmethod
    def normalize_prohibited_generalizations(cls, value: Any) -> tuple[str, ...]:
        return _normalized_unique_strings(value, field_name="prohibited_generalizations")

    @model_validator(mode="after")
    def validate_rule_bindings(self) -> "ClaimSpecV2":
        if self.supported_rule.disposition is not ClaimDisposition.SUPPORTED:
            raise ValueError("supported_rule disposition must be SUPPORTED")
        if self.inconclusive_rule.disposition is not ClaimDisposition.INCONCLUSIVE:
            raise ValueError("inconclusive_rule disposition must be INCONCLUSIVE")
        if self.not_supported_rule.disposition is not ClaimDisposition.NOT_SUPPORTED:
            raise ValueError("not_supported_rule disposition must be NOT_SUPPORTED")
        metric_ids = {metric.metric_id for metric in self.primary_metrics}
        for rule_name, rule in (
            ("supported_rule", self.supported_rule),
            ("inconclusive_rule", self.inconclusive_rule),
            ("not_supported_rule", self.not_supported_rule),
        ):
            for condition in rule.conditions:
                if condition.metric_id not in metric_ids:
                    raise ValueError(f"{rule_name} references unknown metric_id")
        if self.admissible_wording in self.prohibited_generalizations:
            raise ValueError(
                "prohibited_generalizations must not include the admissible_wording"
            )
        for rule_name, rule in (
            ("supported_rule", self.supported_rule),
            ("inconclusive_rule", self.inconclusive_rule),
            ("not_supported_rule", self.not_supported_rule),
        ):
            if not _conditions_are_jointly_feasible(rule.conditions):
                raise ValueError(f"{rule_name} contains contradictory conditions")
        if _conditions_are_jointly_feasible(
            self.supported_rule.conditions + self.not_supported_rule.conditions
        ):
            raise ValueError("supported_rule and not_supported_rule overlap")
        return self

    def canonical_material(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def claim_spec_hash(self) -> str:
        return digest("CLAIM_SPEC_V2", self.canonical_material())

    def assert_publication_statement(self, statement: str) -> None:
        normalized = _normalized_string(statement, field_name="statement")
        if normalized == self.admissible_wording:
            return
        if normalized in self.prohibited_generalizations:
            raise ValueError("statement is a prohibited generalization")
        raise ValueError("statement must match the exact admissible wording")

    def adjudicate(
        self,
        *,
        metrics: Mapping[str, ClaimMetricObservation],
        origin: EvidenceOrigin,
        statement: str,
    ) -> ClaimDisposition:
        self.assert_publication_statement(statement)
        if origin not in self.allowed_evidence_origins:
            raise ValueError(f"unsupported evidence origin: {origin.value}")
        observations = {
            metric_id: observation
            if isinstance(observation, ClaimMetricObservation)
            else ClaimMetricObservation.model_validate(observation)
            for metric_id, observation in metrics.items()
        }
        supported = self.supported_rule.evaluate(observations)
        not_supported = self.not_supported_rule.evaluate(observations)
        if supported and not_supported:
            raise ValueError("ambiguous claim adjudication")
        if supported:
            return ClaimDisposition.SUPPORTED
        if not_supported:
            return ClaimDisposition.NOT_SUPPORTED
        if self.inconclusive_rule.evaluate(observations):
            return ClaimDisposition.INCONCLUSIVE
        return ClaimDisposition.INCONCLUSIVE
