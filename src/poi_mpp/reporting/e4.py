"""Deterministic E4 reporting helpers for T9/F8 inputs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e4_da import ClaimTarget, E4ScenarioRow


MIN_E4_SUPPORTED_SCENARIOS = 2
MIN_E4_OBSERVED_DENOMINATOR = 10
MAX_E4_INTERVAL_WIDTH = 0.5


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class T9Row(_FrozenModel):
    scenario_id: str
    observation_key: str
    mode: str
    claim_target: str
    expected_outcome: str
    assumption_label: str
    origin: str
    denominator: int = Field(gt=0)
    miss_probability: float = Field(ge=0.0, le=1.0)
    confidence_interval: tuple[float, float]
    reconstruction_status: str
    observed_availability_success: bool
    observed_attack_detected: bool
    expected_outcome_detected: bool


class F8Point(_FrozenModel):
    scenario_id: str
    observation_key: str
    mode: str
    miss_probability: float = Field(ge=0.0, le=1.0)
    lower_bound: float = Field(ge=0.0, le=1.0)
    upper_bound: float = Field(ge=0.0, le=1.0)


class E4Summary(_FrozenModel):
    schema_version: str = "POI_MPP_E4_SUMMARY_V1"
    claim_id: str
    denominator: int = Field(gt=0)
    scenario_count: int = Field(gt=0)
    claim_target: ClaimTarget
    origins: tuple[str, ...]
    assumption_ledger: tuple[str, ...]
    minimum_supported_scenarios: int = Field(ge=MIN_E4_SUPPORTED_SCENARIOS)
    minimum_observed_denominator: int = Field(ge=MIN_E4_OBSERVED_DENOMINATOR)
    maximum_supported_interval_width: float = Field(gt=0.0, le=1.0)
    exact_scenario_count: int = Field(ge=0)
    observed_scenario_count: int = Field(ge=0)
    expected_outcome_detected_count: int = Field(ge=0)
    claim_disposition: str

    @field_validator("claim_id", "claim_disposition")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary text fields must not be blank")
        return value

    @model_validator(mode="after")
    def validate_counts(self) -> "E4Summary":
        if self.denominator != self.scenario_count:
            raise ValueError("denominator must equal scenario_count")
        if self.exact_scenario_count + self.observed_scenario_count != self.scenario_count:
            raise ValueError("exact_scenario_count + observed_scenario_count must equal scenario_count")
        if self.expected_outcome_detected_count > self.scenario_count:
            raise ValueError("expected_outcome_detected_count cannot exceed scenario_count")
        return self


def t9_rows(rows: list[E4ScenarioRow] | tuple[E4ScenarioRow, ...]) -> tuple[T9Row, ...]:
    return tuple(
        T9Row(
            scenario_id=row.scenario_id,
            observation_key=row.observation_key,
            mode=row.mode.value,
            claim_target=row.claim_target.value,
            expected_outcome=row.expected_outcome,
            assumption_label=row.assumption_label.value,
            origin=row.origin.value,
            denominator=row.denominator,
            miss_probability=row.miss_probability,
            confidence_interval=row.confidence_interval,
            reconstruction_status=row.reconstruction_status,
            observed_availability_success=row.observed_availability_success,
            observed_attack_detected=row.observed_attack_detected,
            expected_outcome_detected=row.expected_outcome_detected,
        )
        for row in rows
    )


def f8_points(rows: list[E4ScenarioRow] | tuple[E4ScenarioRow, ...]) -> tuple[F8Point, ...]:
    return tuple(
        F8Point(
            scenario_id=row.scenario_id,
            observation_key=row.observation_key,
            mode=row.mode.value,
            miss_probability=row.miss_probability,
            lower_bound=row.confidence_interval[0],
            upper_bound=row.confidence_interval[1],
        )
        for row in rows
    )


def summarize_e4_rows(
    rows: list[E4ScenarioRow] | tuple[E4ScenarioRow, ...],
    *,
    claim_id: str = "C4",
) -> E4Summary:
    if not rows:
        raise ValueError("E4 summary requires at least one row")
    if len({row.scenario_id for row in rows}) != len(rows):
        raise ValueError("E4 rows must use unique scenario_id values")
    if len({row.observation_key for row in rows}) != len(rows):
        raise ValueError("E4 rows must use unique observation_key values")
    if len({row.certificate_observation_key for row in rows}) != len(rows):
        raise ValueError("E4 rows must use unique certificate_observation_key values")
    if len({row.seed_observation_key for row in rows}) != len(rows):
        raise ValueError("E4 rows must use unique seed_observation_key values")
    origins = tuple(sorted({row.origin.value for row in rows}))
    assumptions = tuple(sorted({row.assumption_label.value for row in rows}))
    claim_targets = {row.claim_target for row in rows}
    if len(claim_targets) != 1:
        raise ValueError("E4 rows must share one claim_target per summary")
    claim_target = next(iter(claim_targets))
    exact_scenarios = sum(1 for row in rows if row.interval_kind.value == "EXACT")
    expected_outcome_detected_count = sum(1 for row in rows if row.expected_outcome_detected)
    observed_rows = [row for row in rows if row.interval_kind.value == "WILSON"]
    observed_denominators_ok = all(row.denominator >= MIN_E4_OBSERVED_DENOMINATOR for row in observed_rows)
    interval_widths_ok = all(
        (row.confidence_interval[1] - row.confidence_interval[0]) <= MAX_E4_INTERVAL_WIDTH for row in rows
    )
    support_ready = (
        len(rows) >= MIN_E4_SUPPORTED_SCENARIOS
        and expected_outcome_detected_count == len(rows)
        and observed_denominators_ok
        and interval_widths_ok
    )
    if EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value in origins:
        claim_disposition = "INCONCLUSIVE"
    elif claim_target is ClaimTarget.AVAILABILITY_SUCCESS:
        claim_disposition = (
            "SUPPORTED"
            if support_ready and all(row.observed_availability_success for row in rows)
            else "INCONCLUSIVE"
        )
    else:
        claim_disposition = (
            "SUPPORTED"
            if support_ready and all(row.expected_outcome_detected for row in rows)
            else "INCONCLUSIVE"
        )
    return E4Summary(
        claim_id=claim_id,
        denominator=len(rows),
        scenario_count=len(rows),
        claim_target=claim_target,
        origins=origins,
        assumption_ledger=assumptions,
        minimum_supported_scenarios=MIN_E4_SUPPORTED_SCENARIOS,
        minimum_observed_denominator=MIN_E4_OBSERVED_DENOMINATOR,
        maximum_supported_interval_width=MAX_E4_INTERVAL_WIDTH,
        exact_scenario_count=exact_scenarios,
        observed_scenario_count=len(rows) - exact_scenarios,
        expected_outcome_detected_count=expected_outcome_detected_count,
        claim_disposition=claim_disposition,
    )
