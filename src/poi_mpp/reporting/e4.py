"""Deterministic E4 reporting helpers for T9/F8 inputs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.experiments.e4_da import E4ScenarioRow


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class T9Row(_FrozenModel):
    scenario_id: str
    mode: str
    assumption_label: str
    origin: str
    denominator: int = Field(gt=0)
    miss_probability: float = Field(ge=0.0, le=1.0)
    confidence_interval: tuple[float, float]
    reconstruction_status: str


class F8Point(_FrozenModel):
    scenario_id: str
    mode: str
    miss_probability: float = Field(ge=0.0, le=1.0)
    lower_bound: float = Field(ge=0.0, le=1.0)
    upper_bound: float = Field(ge=0.0, le=1.0)


class E4Summary(_FrozenModel):
    schema_version: str = "POI_MPP_E4_SUMMARY_V1"
    claim_id: str
    denominator: int = Field(gt=0)
    scenario_count: int = Field(gt=0)
    origins: tuple[str, ...]
    assumption_ledger: tuple[str, ...]
    exact_scenario_count: int = Field(ge=0)
    observed_scenario_count: int = Field(ge=0)
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
        return self


def t9_rows(rows: list[E4ScenarioRow] | tuple[E4ScenarioRow, ...]) -> tuple[T9Row, ...]:
    return tuple(
        T9Row(
            scenario_id=row.scenario_id,
            mode=row.mode.value,
            assumption_label=row.assumption_label.value,
            origin=row.origin.value,
            denominator=row.denominator,
            miss_probability=row.miss_probability,
            confidence_interval=row.confidence_interval,
            reconstruction_status=row.reconstruction_status,
        )
        for row in rows
    )


def f8_points(rows: list[E4ScenarioRow] | tuple[E4ScenarioRow, ...]) -> tuple[F8Point, ...]:
    return tuple(
        F8Point(
            scenario_id=row.scenario_id,
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
    origins = tuple(sorted({row.origin.value for row in rows}))
    assumptions = tuple(sorted({row.assumption_label.value for row in rows}))
    exact_scenarios = sum(1 for row in rows if row.interval_kind.value == "EXACT")
    claim_disposition = "SUPPORTED" if origins == ("REPRODUCIBLE_SIMULATION",) else "INCONCLUSIVE"
    return E4Summary(
        claim_id=claim_id,
        denominator=len(rows),
        scenario_count=len(rows),
        origins=origins,
        assumption_ledger=assumptions,
        exact_scenario_count=exact_scenarios,
        observed_scenario_count=len(rows) - exact_scenarios,
        claim_disposition=claim_disposition,
    )
