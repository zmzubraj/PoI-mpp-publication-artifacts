"""Deterministic E5 reporting helpers for watcher/dispute economics."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e5_watcher import E5ScenarioRow, E5_CONFIRMATORY_SCOPE


MIN_E5_SUPPORTED_SCENARIOS = 2
MAX_E5_INTERVAL_WIDTH = 0.2


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class T10Row(_FrozenModel):
    scenario_id: str
    fraud_value_micros: int = Field(ge=0)
    audit_cost_micros: int = Field(ge=0)
    challenge_bond_micros: int = Field(ge=0)
    reward_micros: int = Field(ge=0)
    watchers: int = Field(gt=0)
    challenge_probability: float = Field(ge=0.0, le=1.0)
    maturity_probability: float = Field(ge=0.0, le=1.0)
    watcher_expected_utility_micros: str
    origin: str
    assumption_label: str

    @field_validator("scenario_id", "watcher_expected_utility_micros", "origin", "assumption_label")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("T10 text fields must not be blank")
        return value


class InvalidMaturitySensitivityPoint(_FrozenModel):
    scenario_id: str
    fraud_value_micros: int = Field(ge=0)
    invalid_maturity_probability: float = Field(ge=0.0, le=1.0)
    lower_bound: float = Field(ge=0.0, le=1.0)
    upper_bound: float = Field(ge=0.0, le=1.0)


class E5Summary(_FrozenModel):
    schema_version: str = "POI_MPP_E5_SUMMARY_V1"
    claim_id: str
    denominator: int = Field(gt=0)
    scenario_count: int = Field(gt=0)
    origins: tuple[str, ...]
    families: tuple[str, ...]
    assumption_ledger: tuple[str, ...]
    minimum_supported_scenarios: int = Field(ge=MIN_E5_SUPPORTED_SCENARIOS)
    minimum_supported_simulations: int = Field(ge=0)
    maximum_supported_interval_width: float = Field(gt=0.0, le=1.0)
    supported_scenario_count: int = Field(ge=0)
    claim_disposition: str

    @field_validator("claim_id", "claim_disposition")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary text fields must not be blank")
        return value

    @model_validator(mode="after")
    def validate_counts(self) -> "E5Summary":
        if self.denominator != self.scenario_count:
            raise ValueError("denominator must equal scenario_count")
        if self.supported_scenario_count > self.scenario_count:
            raise ValueError("supported_scenario_count cannot exceed scenario_count")
        return self


def _revalidate_row(row: object) -> E5ScenarioRow:
    if isinstance(row, BaseModel):
        payload = row.model_dump(mode="json")
    elif isinstance(row, Mapping):
        payload = dict(row)
    else:
        payload = row
    return E5ScenarioRow.model_validate(payload)


def publication_precheck_reasons(
    rows: tuple[E5ScenarioRow, ...] | list[E5ScenarioRow],
) -> tuple[str, ...]:
    if not rows:
        return ("E5 publication precheck requires at least one row",)
    canonical_rows = tuple(_revalidate_row(row) for row in rows)
    reasons: list[str] = []
    if len({row.origin for row in canonical_rows}) != 1:
        reasons.append("rows must share one origin")
    elif canonical_rows[0].origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
        reasons.append("rows.origin must equal REPRODUCIBLE_SIMULATION")
    if len({row.publication_scope for row in canonical_rows}) != 1:
        reasons.append("rows must share one publication_scope")
    elif canonical_rows[0].publication_scope != E5_CONFIRMATORY_SCOPE:
        reasons.append(f"rows.publication_scope must equal {E5_CONFIRMATORY_SCOPE}")
    if len({row.config_contract_hash for row in canonical_rows}) != 1:
        reasons.append("rows must share one config_contract_hash")
    if len({row.scenario_id for row in canonical_rows}) != len(canonical_rows):
        reasons.append("rows must use unique scenario_id values")
    if len({row.scenario_contract_hash for row in canonical_rows}) != len(canonical_rows):
        reasons.append("rows must use unique scenario_contract_hash values")
    return tuple(dict.fromkeys(reasons))


def t10_rows(rows: tuple[E5ScenarioRow, ...] | list[E5ScenarioRow]) -> tuple[T10Row, ...]:
    return tuple(
        T10Row(
            scenario_id=row.scenario_id,
            fraud_value_micros=row.fraud_value_micros,
            audit_cost_micros=row.watch_cost_micros,
            challenge_bond_micros=row.challenge_bond_micros,
            reward_micros=row.challenge_reward_micros + row.challenge_subsidy_micros,
            watchers=row.watcher_count,
            challenge_probability=row.challenge_probability,
            maturity_probability=row.invalid_maturity_probability,
            watcher_expected_utility_micros=row.watcher_expected_utility_micros,
            origin=row.origin.value,
            assumption_label=row.assumption_label.value,
        )
        for row in rows
    )


def invalid_maturity_sensitivity_points(
    rows: tuple[E5ScenarioRow, ...] | list[E5ScenarioRow],
) -> tuple[InvalidMaturitySensitivityPoint, ...]:
    return tuple(
        InvalidMaturitySensitivityPoint(
            scenario_id=row.scenario_id,
            fraud_value_micros=row.fraud_value_micros,
            invalid_maturity_probability=row.invalid_maturity_probability,
            lower_bound=row.invalid_maturity_interval[0],
            upper_bound=row.invalid_maturity_interval[1],
        )
        for row in rows
    )


def summarize_e5_rows(
    rows: tuple[E5ScenarioRow, ...] | list[E5ScenarioRow],
    *,
    claim_id: str = "C5",
) -> E5Summary:
    if not rows:
        raise ValueError("E5 summary requires at least one row")
    canonical_rows = tuple(_revalidate_row(row) for row in rows)
    if len({row.scenario_id for row in canonical_rows}) != len(canonical_rows):
        raise ValueError("E5 rows require unique scenario_id values")
    origins = tuple(sorted({row.origin.value for row in canonical_rows}))
    families = tuple(sorted({row.family.value for row in canonical_rows}))
    assumption_ledger = tuple(sorted({entry for row in canonical_rows for entry in row.assumption_ledger}))
    supported_rows = [
        row
        for row in canonical_rows
        if (row.invalid_maturity_interval[1] - row.invalid_maturity_interval[0]) <= MAX_E5_INTERVAL_WIDTH
        and (row.no_challenge_interval[1] - row.no_challenge_interval[0]) <= MAX_E5_INTERVAL_WIDTH
    ]
    publication_reasons = publication_precheck_reasons(canonical_rows)
    claim_disposition = (
        "SUPPORTED"
        if len(canonical_rows) >= MIN_E5_SUPPORTED_SCENARIOS
        and len(supported_rows) == len(canonical_rows)
        and not publication_reasons
        else "INCONCLUSIVE"
    )
    return E5Summary(
        claim_id=claim_id,
        denominator=len(canonical_rows),
        scenario_count=len(canonical_rows),
        origins=origins,
        families=families,
        assumption_ledger=assumption_ledger,
        minimum_supported_scenarios=MIN_E5_SUPPORTED_SCENARIOS,
        minimum_supported_simulations=min(row.simulations for row in canonical_rows),
        maximum_supported_interval_width=MAX_E5_INTERVAL_WIDTH,
        supported_scenario_count=len(supported_rows),
        claim_disposition=claim_disposition,
    )
