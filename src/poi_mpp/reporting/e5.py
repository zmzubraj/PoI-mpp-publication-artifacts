"""Deterministic E5 reporting helpers for watcher/dispute economics."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence.config import RunConfig, config_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e5_watcher import (
    E5_CONFIRMATORY_SCOPE,
    E5ConfirmatoryContract,
    E5ScenarioRow,
    E5SeedPolicy,
    MAX_REPLAY_SIMULATIONS,
    MIN_SUPPORTED_SIMULATIONS,
    replay_row,
)


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


def _row_payload(row: object) -> dict[str, object]:
    if isinstance(row, BaseModel):
        return row.model_dump(mode="python")
    if isinstance(row, Mapping):
        return dict(row)
    raise ValueError("E5 rows must be mappings or BaseModel instances")


def _payload_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _payload_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _payload_origin(payload: Mapping[str, object]) -> str | None:
    value = payload.get("origin")
    if isinstance(value, EvidenceOrigin):
        return value.value
    if isinstance(value, str) and value.strip():
        return value
    return None


def _precheck_row_contract(
    payload: Mapping[str, object],
    *,
    contract: E5ConfirmatoryContract | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    simulations = _payload_int(payload, "simulations")
    if simulations is None:
        raise ValueError("rows.simulations must be a plain integer")
    if simulations < MIN_SUPPORTED_SIMULATIONS:
        raise ValueError("rows.simulations cannot be below the E5 minimum")
    if simulations > MAX_REPLAY_SIMULATIONS:
        raise ValueError("rows.simulations exceed the hard replay maximum")
    if contract is not None and simulations > contract.maximum_replay_simulations:
        raise ValueError("rows.simulations exceed the confirmatory contract replay maximum")

    raw_run_config = payload.get("run_config_snapshot")
    if raw_run_config is None:
        reasons.append("rows.run_config_snapshot must be present for confirmatory publication review")
        return tuple(reasons)

    try:
        run_config = RunConfig.model_validate(raw_run_config)
    except Exception:
        reasons.append("rows.run_config_snapshot must validate against the canonical RunConfig schema")
        return tuple(reasons)

    run_config_hash = _payload_text(payload, "run_config_hash")
    if run_config_hash is None:
        reasons.append("rows.run_config_hash must be present for confirmatory publication review")
        return tuple(reasons)
    if len(run_config_hash) != 64 or any(character not in "0123456789abcdef" for character in run_config_hash):
        reasons.append("rows.run_config_hash must be a lowercase SHA-256 hex digest")
        return tuple(reasons)
    if run_config_hash != config_hash(run_config):
        reasons.append("rows.run_config_hash must exactly bind run_config_snapshot")
        return tuple(reasons)

    if _payload_text(payload, "run_id") != run_config.run_id:
        reasons.append("rows.run_id must exactly bind run_config_snapshot.run_id")
    if _payload_text(payload, "experiment_id") != run_config.experiment_id:
        reasons.append("rows.experiment_id must exactly bind run_config_snapshot.experiment_id")
    if _payload_origin(payload) != run_config.origin.value:
        reasons.append("rows.origin must exactly bind run_config_snapshot.origin")

    if contract is not None and run_config.authorization_scope != contract.required_run_authorization_scope:
        reasons.append("rows.run_config_snapshot.authorization_scope must exactly match the confirmatory contract")
    return tuple(reasons)


def _authoritative_row(row: object) -> E5ScenarioRow:
    canonical = _revalidate_row(row)
    replayed = replay_row(canonical)
    if canonical.model_dump(mode="json") != replayed.model_dump(mode="json"):
        raise ValueError("E5 row does not match canonical simulator replay")
    return replayed


def publication_precheck_reasons(
    rows: tuple[E5ScenarioRow, ...] | list[E5ScenarioRow],
    *,
    contract: E5ConfirmatoryContract | None = None,
) -> tuple[str, ...]:
    if not rows:
        return ("E5 publication precheck requires at least one row",)
    reasons: list[str] = []
    raw_rows = tuple(_row_payload(row) for row in rows)
    for payload in raw_rows:
        reasons.extend(_precheck_row_contract(payload, contract=contract))
    if contract is None:
        reasons.append("E5 confirmatory contract is required for publication support")
        return tuple(dict.fromkeys(reasons))
    if reasons:
        return tuple(dict.fromkeys(reasons))
    canonical_rows = tuple(_authoritative_row(row) for row in rows)
    if len({row.origin for row in canonical_rows}) != 1 or canonical_rows[0].origin is not contract.required_run_origin:
        reasons.append("rows.origin must exactly match the confirmatory contract")
    if any(row.run_config_snapshot.origin is not contract.required_run_origin for row in canonical_rows):
        reasons.append("rows.run_config_snapshot.origin must exactly match the confirmatory contract")
    if any(
        row.run_config_snapshot.authorization_scope != contract.required_run_authorization_scope
        for row in canonical_rows
    ):
        reasons.append("rows.run_config_snapshot.authorization_scope must exactly match the confirmatory contract")
    if (
        len({row.publication_scope for row in canonical_rows}) != 1
        or canonical_rows[0].publication_scope != contract.publication_scope
    ):
        reasons.append("rows.publication_scope must exactly match the confirmatory contract")
    if any(row.simulations != contract.required_simulations for row in canonical_rows):
        reasons.append("rows.simulations must exactly match the confirmatory contract")
    if any(row.simulation_model_version != contract.required_model_version for row in canonical_rows):
        reasons.append("rows.simulation_model_version must exactly match the confirmatory contract")
    if len({row.scenario_id for row in canonical_rows}) != len(canonical_rows):
        reasons.append("rows must use unique scenario_id values")
    contract_scenarios = {item.scenario_id: item for item in contract.allowed_scenarios}
    row_scenarios = {row.scenario_id: row for row in canonical_rows}
    if set(row_scenarios) != set(contract_scenarios):
        reasons.append("rows.scenario_id set must exactly close against the confirmatory contract")
    else:
        for scenario_id, row in row_scenarios.items():
            allowed = contract_scenarios[scenario_id]
            if row.scenario_contract_hash != allowed.scenario_contract_hash:
                reasons.append(f"scenario_contract_hash mismatch for {scenario_id}")
            if contract.seed_policy is E5SeedPolicy.FIXED_PER_SCENARIO and row.seed != allowed.required_seed:
                reasons.append(f"seed mismatch for {scenario_id}")
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
    contract: E5ConfirmatoryContract | None = None,
) -> E5Summary:
    if not rows:
        raise ValueError("E5 summary requires at least one row")
    raw_rows = tuple(_row_payload(row) for row in rows)
    scenario_ids = tuple(_payload_text(payload, "scenario_id") or "<missing-scenario-id>" for payload in raw_rows)
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("E5 rows require unique scenario_id values")
    publication_reasons = publication_precheck_reasons(rows, contract=contract)
    if publication_reasons:
        origins = tuple(sorted({origin for payload in raw_rows if (origin := _payload_origin(payload)) is not None}))
        families = tuple(
            sorted({family for payload in raw_rows if (family := _payload_text(payload, "family")) is not None})
        )
        assumption_ledger = tuple(
            sorted(
                {
                    entry
                    for payload in raw_rows
                    for entry in (
                        payload.get("assumption_ledger")
                        if isinstance(payload.get("assumption_ledger"), (list, tuple))
                        else ()
                    )
                    if isinstance(entry, str) and entry.strip()
                }
            )
        )
        simulations = [value for payload in raw_rows if (value := _payload_int(payload, "simulations")) is not None]
        return E5Summary(
            claim_id=claim_id,
            denominator=len(raw_rows),
            scenario_count=len(raw_rows),
            origins=origins,
            families=families,
            assumption_ledger=assumption_ledger,
            minimum_supported_scenarios=MIN_E5_SUPPORTED_SCENARIOS,
            minimum_supported_simulations=min(simulations) if simulations else 0,
            maximum_supported_interval_width=MAX_E5_INTERVAL_WIDTH,
            supported_scenario_count=0,
            claim_disposition="INCONCLUSIVE",
        )
    canonical_rows = tuple(_authoritative_row(row) for row in rows)
    origins = tuple(sorted({row.origin.value for row in canonical_rows}))
    families = tuple(sorted({row.family.value for row in canonical_rows}))
    assumption_ledger = tuple(sorted({entry for row in canonical_rows for entry in row.assumption_ledger}))
    supported_rows = [
        row
        for row in canonical_rows
        if (row.invalid_maturity_interval[1] - row.invalid_maturity_interval[0]) <= MAX_E5_INTERVAL_WIDTH
        and (row.no_challenge_interval[1] - row.no_challenge_interval[0]) <= MAX_E5_INTERVAL_WIDTH
    ]
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
