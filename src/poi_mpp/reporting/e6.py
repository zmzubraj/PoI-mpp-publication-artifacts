"""Deterministic E6 reporting helpers for Sybil and task-budget economics."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence.config import RunConfig, config_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e6_sybil import (
    E6_CONFIRMATORY_SCOPE,
    E6ConfirmatoryContract,
    E6ScenarioRow,
    E6SeedPolicy,
    MAX_REPLAY_SIMULATIONS,
    MIN_SUPPORTED_SIMULATIONS,
    replay_row,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class T11Row(_FrozenModel):
    scenario_id: str
    identities: int = Field(gt=0)
    capacity_model: str
    expected_credit_micros: str
    baseline_credit_micros: str
    sybil_advantage_micros: str
    confidence_interval_micros: tuple[str, str]


class F9Point(_FrozenModel):
    scenario_id: str
    identities: int = Field(gt=0)
    capacity_model: str
    normalized_expected_credit: float = Field(ge=0.0)


class F10Point(_FrozenModel):
    scenario_id: str
    identities: int = Field(gt=0)
    capacity_model: str
    target_weight_fraction: str
    estimated_cost_to_target_weight_micros: str


class E6Summary(_FrozenModel):
    schema_version: str = "POI_MPP_E6_SUMMARY_V1"
    claim_id: str
    denominator: int = Field(gt=0)
    scenario_count: int = Field(gt=0)
    support_row_count: int = Field(ge=0)
    negative_control_count: int = Field(ge=0)
    boundary_row_count: int = Field(ge=0)
    origins: tuple[str, ...]
    assumption_ledger: tuple[str, ...]
    epsilon_sybil: float = Field(gt=0.0, le=1.0)
    minimum_negative_controls: int = Field(ge=1)
    max_support_upper_advantage: float
    max_negative_control_upper_advantage: float
    exact_credit_conservation_all: bool
    zero_credit_zero_weight_all: bool
    claim_disposition: str

    @field_validator("claim_id", "claim_disposition")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary text fields must not be blank")
        return value

    @model_validator(mode="after")
    def validate_counts(self) -> "E6Summary":
        if self.denominator != self.scenario_count:
            raise ValueError("denominator must equal scenario_count")
        total_roles = self.support_row_count + self.negative_control_count + self.boundary_row_count
        if total_roles != self.scenario_count:
            raise ValueError("row-role counts must sum to scenario_count")
        return self


def _decimal_text(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001")))


def _revalidate_row(row: object) -> E6ScenarioRow:
    if isinstance(row, BaseModel):
        payload = row.model_dump(mode="json")
    elif isinstance(row, Mapping):
        payload = dict(row)
    else:
        payload = row
    try:
        return E6ScenarioRow.model_validate(payload)
    except Exception as error:
        raise ValueError("E6 row does not match canonical simulator replay") from error


def _row_payload(row: object) -> dict[str, object]:
    if isinstance(row, BaseModel):
        return row.model_dump(mode="python")
    if isinstance(row, Mapping):
        return dict(row)
    raise ValueError("E6 rows must be mappings or BaseModel instances")


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
    contract: E6ConfirmatoryContract | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    simulations = _payload_int(payload, "simulations")
    if simulations is None:
        raise ValueError("rows.simulations must be a plain integer")
    if simulations < MIN_SUPPORTED_SIMULATIONS:
        raise ValueError("rows.simulations cannot be below the E6 minimum")
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


def _authoritative_row(row: object) -> E6ScenarioRow:
    canonical = _revalidate_row(row)
    replayed = replay_row(canonical)
    if canonical.model_dump(mode="json") != replayed.model_dump(mode="json"):
        raise ValueError("E6 row does not match canonical simulator replay")
    return replayed


def publication_precheck_reasons(
    rows: tuple[E6ScenarioRow, ...] | list[E6ScenarioRow],
    *,
    contract: E6ConfirmatoryContract | None = None,
) -> tuple[str, ...]:
    if not rows:
        return ("E6 publication precheck requires at least one row",)
    reasons: list[str] = []
    raw_rows = tuple(_row_payload(row) for row in rows)
    for payload in raw_rows:
        reasons.extend(_precheck_row_contract(payload, contract=contract))
    if contract is None:
        reasons.append("E6 confirmatory contract is required for publication support")
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
            if contract.seed_policy is E6SeedPolicy.FIXED_PER_SCENARIO and row.seed != allowed.required_seed:
                reasons.append(f"seed mismatch for {scenario_id}")
    return tuple(dict.fromkeys(reasons))


def _group_baselines(rows: tuple[E6ScenarioRow, ...]) -> dict[tuple[str, str], E6ScenarioRow]:
    baselines: dict[tuple[str, str], E6ScenarioRow] = {}
    for row in rows:
        if row.attacker_identity_count != 1:
            continue
        baselines[(row.group_id, row.capacity_model.value)] = row
    return baselines


def t11_rows(rows: tuple[E6ScenarioRow, ...] | list[E6ScenarioRow]) -> tuple[T11Row, ...]:
    canonical_rows = tuple(_revalidate_row(row) for row in rows)
    baselines = _group_baselines(canonical_rows)
    output: list[T11Row] = []
    for row in canonical_rows:
        baseline = baselines.get((row.group_id, row.capacity_model.value))
        if baseline is None:
            raise ValueError(f"missing identity_count=1 baseline for group {row.group_id}")
        current_mean = Decimal(row.attacker_expected_credit_micros)
        baseline_mean = Decimal(baseline.attacker_expected_credit_micros)
        if row.seed == baseline.seed and row.simulations == baseline.simulations:
            interval = (
                _decimal_text(current_mean - baseline_mean),
                _decimal_text(current_mean - baseline_mean),
            )
        else:
            current_lower, current_upper = (
                Decimal(row.attacker_credit_interval_micros[0]),
                Decimal(row.attacker_credit_interval_micros[1]),
            )
            baseline_lower, baseline_upper = (
                Decimal(baseline.attacker_credit_interval_micros[0]),
                Decimal(baseline.attacker_credit_interval_micros[1]),
            )
            interval = (
                _decimal_text(current_lower - baseline_upper),
                _decimal_text(current_upper - baseline_lower),
            )
        output.append(
            T11Row(
                scenario_id=row.scenario_id,
                identities=row.attacker_identity_count,
                capacity_model=row.capacity_model.value,
                expected_credit_micros=_decimal_text(current_mean),
                baseline_credit_micros=_decimal_text(baseline_mean),
                sybil_advantage_micros=_decimal_text(current_mean - baseline_mean),
                confidence_interval_micros=interval,
            )
        )
    return tuple(output)


def f9_points(rows: tuple[E6ScenarioRow, ...] | list[E6ScenarioRow]) -> tuple[F9Point, ...]:
    canonical_rows = tuple(_revalidate_row(row) for row in rows)
    baselines = _group_baselines(canonical_rows)
    output: list[F9Point] = []
    for row in canonical_rows:
        baseline = baselines.get((row.group_id, row.capacity_model.value))
        if baseline is None:
            raise ValueError(f"missing identity_count=1 baseline for group {row.group_id}")
        baseline_credit = Decimal(baseline.attacker_expected_credit_micros)
        normalized = 0.0 if baseline_credit == 0 else float(Decimal(row.attacker_expected_credit_micros) / baseline_credit)
        output.append(
            F9Point(
                scenario_id=row.scenario_id,
                identities=row.attacker_identity_count,
                capacity_model=row.capacity_model.value,
                normalized_expected_credit=normalized,
            )
        )
    return tuple(output)


def f10_points(rows: tuple[E6ScenarioRow, ...] | list[E6ScenarioRow]) -> tuple[F10Point, ...]:
    canonical_rows = tuple(_revalidate_row(row) for row in rows)
    return tuple(
        F10Point(
            scenario_id=row.scenario_id,
            identities=row.attacker_identity_count,
            capacity_model=row.capacity_model.value,
            target_weight_fraction=f"{row.target_weight_numerator}/{row.target_weight_denominator}",
            estimated_cost_to_target_weight_micros=row.estimated_cost_to_target_weight_micros,
        )
        for row in canonical_rows
    )


def summarize_e6_rows(
    rows: tuple[E6ScenarioRow, ...] | list[E6ScenarioRow],
    *,
    claim_id: str = "C6",
    contract: E6ConfirmatoryContract | None = None,
) -> E6Summary:
    if not rows:
        raise ValueError("E6 summary requires at least one row")
    canonical_rows = tuple(_revalidate_row(row) for row in rows)
    if len({row.scenario_id for row in canonical_rows}) != len(canonical_rows):
        raise ValueError("E6 rows must use unique scenario_id values")
    baselines = _group_baselines(canonical_rows)
    for row in canonical_rows:
        if (row.group_id, row.capacity_model.value) not in baselines:
            raise ValueError(f"missing identity_count=1 baseline for group {row.group_id}")

    if contract is not None:
        reasons = publication_precheck_reasons(canonical_rows, contract=contract)
        if reasons:
            raise ValueError(reasons[0])

    t11 = t11_rows(canonical_rows)
    support_upper_advantages: list[float] = []
    negative_upper_advantages: list[float] = []
    for row, summary_row in zip(canonical_rows, t11, strict=True):
        upper = float(Decimal(summary_row.confidence_interval_micros[1]))
        if row.role.value == "SUPPORT":
            support_upper_advantages.append(upper)
        elif row.role.value == "NEGATIVE_CONTROL":
            negative_upper_advantages.append(upper)

    origins = tuple(sorted({row.origin.value for row in canonical_rows}))
    assumptions = tuple(sorted({entry for row in canonical_rows for entry in row.assumption_ledger}))
    exact_credit_conservation_all = all(row.exact_credit_conservation for row in canonical_rows)
    zero_credit_zero_weight_all = all(row.zero_credit_implies_zero_weight for row in canonical_rows)

    epsilon = contract.epsilon_sybil if contract is not None else 0.02
    minimum_negative_controls = contract.minimum_negative_controls if contract is not None else 1
    support_ready = (
        contract is not None
        and EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value not in origins
        and support_upper_advantages
        and max(support_upper_advantages) <= epsilon
        and len(negative_upper_advantages) >= minimum_negative_controls
        and exact_credit_conservation_all
        and zero_credit_zero_weight_all
    )
    claim_disposition = "SUPPORTED" if support_ready else "INCONCLUSIVE"
    return E6Summary(
        claim_id=claim_id,
        denominator=len(canonical_rows),
        scenario_count=len(canonical_rows),
        support_row_count=sum(1 for row in canonical_rows if row.role.value == "SUPPORT"),
        negative_control_count=sum(1 for row in canonical_rows if row.role.value == "NEGATIVE_CONTROL"),
        boundary_row_count=sum(1 for row in canonical_rows if row.role.value == "BOUNDARY"),
        origins=origins,
        assumption_ledger=assumptions,
        epsilon_sybil=epsilon,
        minimum_negative_controls=minimum_negative_controls,
        max_support_upper_advantage=max(support_upper_advantages, default=0.0),
        max_negative_control_upper_advantage=max(negative_upper_advantages, default=0.0),
        exact_credit_conservation_all=exact_credit_conservation_all,
        zero_credit_zero_weight_all=zero_credit_zero_weight_all,
        claim_disposition=claim_disposition,
    )
