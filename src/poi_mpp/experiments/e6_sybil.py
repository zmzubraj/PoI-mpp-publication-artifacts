"""E6 Sybil and task-budget economics with replay-authoritative simulation rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
import math
import random
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig, config_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.protocol.credit import derive_active_weight


PUBLICATION_EVIDENCE_AUTHORIZED = "PUBLICATION_EVIDENCE_AUTHORIZED"
E6_CONFIRMATORY_SCOPE = "E6_CONFIRMATORY_PUBLICATION_V1"
MIN_SUPPORTED_SIMULATIONS = 1024
MAX_REPLAY_SIMULATIONS = 8192
E6_SIMULATION_MODEL_VERSION = "POI_MPP_E6_SIMULATOR_V1"
_MICRO_QUANTUM = Decimal("0.000001")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SybilCapacityModel(StrEnum):
    IDENTITY_UNIFORM = "IDENTITY_UNIFORM"
    CAPACITY_COMMITTED = "CAPACITY_COMMITTED"
    OPERATOR_SLOT = "OPERATOR_SLOT"
    TASK_BUDGET_ONLY_ABLATION = "TASK_BUDGET_ONLY_ABLATION"
    COLLATERAL_CAP_ABLATION = "COLLATERAL_CAP_ABLATION"
    CONCENTRATION_CAP_ABLATION = "CONCENTRATION_CAP_ABLATION"


class SybilScenarioRole(StrEnum):
    SUPPORT = "SUPPORT"
    NEGATIVE_CONTROL = "NEGATIVE_CONTROL"
    BOUNDARY = "BOUNDARY"


class SybilAssumption(StrEnum):
    CAPACITY_NEUTRAL_OPERATOR_AGGREGATION_DECLARED = "CAPACITY_NEUTRAL_OPERATOR_AGGREGATION_DECLARED"
    IDENTITY_PROPORTIONAL_SCHEDULER_DECLARED = "IDENTITY_PROPORTIONAL_SCHEDULER_DECLARED"
    TASK_BUDGET_ONLY_ABLATION_DECLARED = "TASK_BUDGET_ONLY_ABLATION_DECLARED"
    COLLATERAL_CAP_ABLATION_DECLARED = "COLLATERAL_CAP_ABLATION_DECLARED"
    CONCENTRATION_CAP_ABLATION_DECLARED = "CONCENTRATION_CAP_ABLATION_DECLARED"
    COLLATERAL_RICH_ZERO_CREDIT_DECLARED = "COLLATERAL_RICH_ZERO_CREDIT_DECLARED"


class AuthorityBoundaryError(ValueError):
    """Raised when the E6 CLI would overstate publication authority."""


class E6SeedPolicy(StrEnum):
    FIXED_PER_SCENARIO = "FIXED_PER_SCENARIO"


class E6AllowedScenario(_FrozenModel):
    scenario_id: str
    scenario_contract_hash: str
    required_role: SybilScenarioRole
    required_capacity_model: SybilCapacityModel
    required_seed: int = Field(ge=0)

    @field_validator("scenario_id", "scenario_contract_hash")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("scenario_contract_hash")
    @classmethod
    def validate_hash_shape(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("scenario_contract_hash must be a lowercase SHA-256 hex digest")
        return value


class E6ConfirmatoryContract(_FrozenModel):
    schema_version: str = "POI_MPP_E6_CONFIRMATORY_CONTRACT_V1"
    publication_scope: str
    required_run_origin: EvidenceOrigin
    required_run_authorization_scope: str
    required_simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS)
    maximum_replay_simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS, le=MAX_REPLAY_SIMULATIONS)
    required_model_version: str
    epsilon_sybil: float = Field(gt=0.0, le=1.0)
    target_weight_numerator: int = Field(gt=0)
    target_weight_denominator: int = Field(gt=1)
    minimum_negative_controls: int = Field(ge=1)
    seed_policy: E6SeedPolicy
    allowed_scenarios: tuple[E6AllowedScenario, ...]
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_contract(self) -> "E6ConfirmatoryContract":
        if self.schema_version != "POI_MPP_E6_CONFIRMATORY_CONTRACT_V1":
            raise ValueError("schema_version must equal POI_MPP_E6_CONFIRMATORY_CONTRACT_V1")
        if self.publication_scope != E6_CONFIRMATORY_SCOPE:
            raise ValueError(f"publication_scope must equal {E6_CONFIRMATORY_SCOPE}")
        if self.required_run_origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
            raise ValueError("required_run_origin must equal REPRODUCIBLE_SIMULATION")
        if self.required_run_authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
            raise ValueError(
                f"required_run_authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
            )
        if self.required_model_version != E6_SIMULATION_MODEL_VERSION:
            raise ValueError(f"required_model_version must equal {E6_SIMULATION_MODEL_VERSION}")
        if self.target_weight_numerator >= self.target_weight_denominator:
            raise ValueError("target_weight_numerator must be less than target_weight_denominator")
        if not self.allowed_scenarios:
            raise ValueError("allowed_scenarios must not be empty")
        if len({item.scenario_id for item in self.allowed_scenarios}) != len(self.allowed_scenarios):
            raise ValueError("allowed_scenarios must use unique scenario_id values")
        if len({item.scenario_contract_hash for item in self.allowed_scenarios}) != len(self.allowed_scenarios):
            raise ValueError("allowed_scenarios must use unique scenario_contract_hash values")
        negative_controls = sum(1 for item in self.allowed_scenarios if item.required_role is SybilScenarioRole.NEGATIVE_CONTROL)
        if negative_controls < self.minimum_negative_controls:
            raise ValueError("allowed_scenarios must include at least minimum_negative_controls negative scenarios")
        return self


def load_e6_confirmatory_contract(path: str | Path) -> E6ConfirmatoryContract:
    contract_path = Path(path)
    try:
        raw = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"unable to load E6 confirmatory contract: {contract_path}") from error
    if not isinstance(raw, Mapping):
        raise ValueError("E6 confirmatory contract must be a mapping")
    return E6ConfirmatoryContract.model_validate(dict(raw))


class E6SimulationConfig(_FrozenModel):
    schema_version: str = "POI_MPP_E6_SIMULATION_CONFIG_V1"
    simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS, le=MAX_REPLAY_SIMULATIONS)
    seed: int = Field(ge=0)
    origin: EvidenceOrigin
    publication_scope: str | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> "E6SimulationConfig":
        if self.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE and self.publication_scope is not None:
            raise ValueError("synthetic plumbing runs cannot declare publication_scope")
        if self.publication_scope is not None and self.publication_scope != E6_CONFIRMATORY_SCOPE:
            raise ValueError(f"publication_scope must equal {E6_CONFIRMATORY_SCOPE}")
        return self


def simulation_config_contract_hash(config: E6SimulationConfig) -> str:
    return digest(
        "E6_SIMULATION_CONFIG",
        {
            "schema_version": config.schema_version,
            "simulations": config.simulations,
            "seed": config.seed,
            "origin": config.origin.value,
            "publication_scope": config.publication_scope,
        },
    )


class SybilScenario(_FrozenModel):
    scenario_id: str
    group_id: str
    role: SybilScenarioRole
    assumption_label: SybilAssumption
    capacity_model: SybilCapacityModel
    attacker_identity_count: int = Field(gt=0, le=64)
    attacker_total_capacity_units: int = Field(gt=0)
    attacker_success_probability: float = Field(ge=0.0, le=1.0)
    attacker_collateral_micros: int = Field(ge=0)
    attacker_identity_fixed_cost_micros: int = Field(ge=0)
    honest_operator_count: int = Field(gt=0)
    honest_capacity_units: int = Field(gt=0)
    honest_success_probability: float = Field(ge=0.0, le=1.0)
    honest_collateral_micros: int = Field(ge=0)
    task_count: int = Field(gt=0)
    task_credit_budget: int = Field(gt=0)
    beta_micros: int = Field(gt=0)
    concentration_cap_micros: int = Field(ge=0)
    capacity_cost_micros_per_unit: int = Field(ge=0)
    collateral_cost_multiplier_microx: int = Field(ge=0)
    capacity_subsidy_micros: int = Field(ge=0)
    target_weight_numerator: int = Field(gt=0)
    target_weight_denominator: int = Field(gt=1)

    @field_validator("scenario_id", "group_id")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator(
        "attacker_success_probability",
        "honest_success_probability",
        mode="before",
    )
    @classmethod
    def require_finite_probability(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"{info.field_name} must be a finite probability")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> "SybilScenario":
        if self.target_weight_numerator >= self.target_weight_denominator:
            raise ValueError("target_weight_numerator must be less than target_weight_denominator")
        if self.capacity_model in {
            SybilCapacityModel.CAPACITY_COMMITTED,
            SybilCapacityModel.OPERATOR_SLOT,
        } and self.attacker_success_probability > 0.0:
            if self.assumption_label is not SybilAssumption.CAPACITY_NEUTRAL_OPERATOR_AGGREGATION_DECLARED:
                raise ValueError("safe schedulers require CAPACITY_NEUTRAL_OPERATOR_AGGREGATION_DECLARED")
        if self.capacity_model is SybilCapacityModel.IDENTITY_UNIFORM and (
            self.assumption_label is not SybilAssumption.IDENTITY_PROPORTIONAL_SCHEDULER_DECLARED
        ):
            raise ValueError("identity-uniform scheduler requires IDENTITY_PROPORTIONAL_SCHEDULER_DECLARED")
        if self.capacity_model is SybilCapacityModel.TASK_BUDGET_ONLY_ABLATION and (
            self.assumption_label is not SybilAssumption.TASK_BUDGET_ONLY_ABLATION_DECLARED
        ):
            raise ValueError("task-budget-only ablation requires TASK_BUDGET_ONLY_ABLATION_DECLARED")
        if self.capacity_model is SybilCapacityModel.COLLATERAL_CAP_ABLATION and (
            self.assumption_label is not SybilAssumption.COLLATERAL_CAP_ABLATION_DECLARED
        ):
            raise ValueError("collateral-cap ablation requires COLLATERAL_CAP_ABLATION_DECLARED")
        if self.capacity_model is SybilCapacityModel.CONCENTRATION_CAP_ABLATION and (
            self.assumption_label is not SybilAssumption.CONCENTRATION_CAP_ABLATION_DECLARED
        ):
            raise ValueError("concentration-cap ablation requires CONCENTRATION_CAP_ABLATION_DECLARED")
        if self.attacker_success_probability == 0.0 and (
            self.assumption_label is not SybilAssumption.COLLATERAL_RICH_ZERO_CREDIT_DECLARED
        ):
            raise ValueError("zero-credit attacker scenarios require COLLATERAL_RICH_ZERO_CREDIT_DECLARED")
        return self


def scenario_contract_hash(scenario: SybilScenario) -> str:
    return digest(
        "E6_SYBIL_SCENARIO",
        {
            "scenario_id": scenario.scenario_id,
            "group_id": scenario.group_id,
            "role": scenario.role.value,
            "assumption_label": scenario.assumption_label.value,
            "capacity_model": scenario.capacity_model.value,
            "attacker_identity_count": scenario.attacker_identity_count,
            "attacker_total_capacity_units": scenario.attacker_total_capacity_units,
            "attacker_success_probability": scenario.attacker_success_probability,
            "attacker_collateral_micros": scenario.attacker_collateral_micros,
            "attacker_identity_fixed_cost_micros": scenario.attacker_identity_fixed_cost_micros,
            "honest_operator_count": scenario.honest_operator_count,
            "honest_capacity_units": scenario.honest_capacity_units,
            "honest_success_probability": scenario.honest_success_probability,
            "honest_collateral_micros": scenario.honest_collateral_micros,
            "task_count": scenario.task_count,
            "task_credit_budget": scenario.task_credit_budget,
            "beta_micros": scenario.beta_micros,
            "concentration_cap_micros": scenario.concentration_cap_micros,
            "capacity_cost_micros_per_unit": scenario.capacity_cost_micros_per_unit,
            "collateral_cost_multiplier_microx": scenario.collateral_cost_multiplier_microx,
            "capacity_subsidy_micros": scenario.capacity_subsidy_micros,
            "target_weight_numerator": scenario.target_weight_numerator,
            "target_weight_denominator": scenario.target_weight_denominator,
        },
    )


def _result_contract_material(row: "E6ScenarioRow") -> dict[str, object]:
    return {
        "scenario_id": row.scenario_id,
        "group_id": row.group_id,
        "role": row.role.value,
        "capacity_model": row.capacity_model.value,
        "attacker_identity_count": row.attacker_identity_count,
        "simulation_model_version": row.simulation_model_version,
        "config_contract_hash": row.config_contract_hash,
        "scenario_contract_hash": row.scenario_contract_hash,
        "attacker_expected_credit_micros": row.attacker_expected_credit_micros,
        "attacker_credit_interval_micros": row.attacker_credit_interval_micros,
        "attacker_expected_weight_micros": row.attacker_expected_weight_micros,
        "attacker_weight_interval_micros": row.attacker_weight_interval_micros,
        "attacker_expected_share": row.attacker_expected_share,
        "attacker_share_interval": row.attacker_share_interval,
        "allocated_task_count_mean": row.allocated_task_count_mean,
        "allocated_task_count_interval": row.allocated_task_count_interval,
        "unallocated_task_count_mean": row.unallocated_task_count_mean,
        "unallocated_task_count_interval": row.unallocated_task_count_interval,
        "allocated_credit_mean_micros": row.allocated_credit_mean_micros,
        "allocated_credit_interval_micros": row.allocated_credit_interval_micros,
        "task_accounting_exact": row.task_accounting_exact,
        "credit_issuance_exact": row.credit_issuance_exact,
        "budget_non_exceedance": row.budget_non_exceedance,
        "credit_utilization_ratio": row.credit_utilization_ratio,
        "zero_credit_implies_zero_weight": row.zero_credit_implies_zero_weight,
        "estimated_cost_to_target_weight_micros": row.estimated_cost_to_target_weight_micros,
        "assumption_ledger": row.assumption_ledger,
        "publication_scope": row.publication_scope,
    }


def result_contract_hash(row: "E6ScenarioRow") -> str:
    return digest("E6_SYBIL_RESULT", _result_contract_material(row))


class E6ScenarioRow(_FrozenModel):
    schema_version: str = "POI_MPP_E6_SCENARIO_ROW_V1"
    run_id: str
    experiment_id: str
    run_config_snapshot: RunConfig
    run_config_hash: str
    scenario_id: str
    group_id: str
    seed: int = Field(ge=0)
    simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS, le=MAX_REPLAY_SIMULATIONS)
    origin: EvidenceOrigin
    role: SybilScenarioRole
    assumption_label: SybilAssumption
    capacity_model: SybilCapacityModel
    attacker_identity_count: int = Field(gt=0, le=64)
    attacker_total_capacity_units: int = Field(gt=0)
    attacker_success_probability: float = Field(ge=0.0, le=1.0)
    attacker_collateral_micros: int = Field(ge=0)
    attacker_identity_fixed_cost_micros: int = Field(ge=0)
    honest_operator_count: int = Field(gt=0)
    honest_capacity_units: int = Field(gt=0)
    honest_success_probability: float = Field(ge=0.0, le=1.0)
    honest_collateral_micros: int = Field(ge=0)
    task_count: int = Field(gt=0)
    task_credit_budget: int = Field(gt=0)
    beta_micros: int = Field(gt=0)
    concentration_cap_micros: int = Field(ge=0)
    capacity_cost_micros_per_unit: int = Field(ge=0)
    collateral_cost_multiplier_microx: int = Field(ge=0)
    capacity_subsidy_micros: int = Field(ge=0)
    target_weight_numerator: int = Field(gt=0)
    target_weight_denominator: int = Field(gt=1)
    simulation_model_version: str
    config_contract_hash: str
    scenario_contract_hash: str
    result_contract_hash: str
    attacker_expected_credit_micros: str
    attacker_credit_interval_micros: tuple[str, str]
    attacker_expected_weight_micros: str
    attacker_weight_interval_micros: tuple[str, str]
    attacker_expected_share: float = Field(ge=0.0, le=1.0)
    attacker_share_interval: tuple[float, float]
    allocated_task_count_mean: str
    allocated_task_count_interval: tuple[str, str]
    unallocated_task_count_mean: str
    unallocated_task_count_interval: tuple[str, str]
    allocated_credit_mean_micros: str
    allocated_credit_interval_micros: tuple[str, str]
    task_accounting_exact: bool
    credit_issuance_exact: bool
    budget_non_exceedance: bool
    credit_utilization_ratio: float = Field(ge=0.0, le=1.0)
    zero_credit_implies_zero_weight: bool
    estimated_cost_to_target_weight_micros: str
    assumption_ledger: tuple[str, ...]
    publication_scope: str | None = None

    @field_validator(
        "run_id",
        "experiment_id",
        "run_config_hash",
        "scenario_id",
        "group_id",
        "simulation_model_version",
        "config_contract_hash",
        "scenario_contract_hash",
        "result_contract_hash",
        "attacker_expected_credit_micros",
        "attacker_expected_weight_micros",
        "allocated_task_count_mean",
        "unallocated_task_count_mean",
        "allocated_credit_mean_micros",
        "estimated_cost_to_target_weight_micros",
        mode="before",
    )
    @classmethod
    def require_nonblank_text(cls, value: object, info: ValidationInfo) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator(
        "attacker_credit_interval_micros",
        "attacker_weight_interval_micros",
        "allocated_task_count_interval",
        "unallocated_task_count_interval",
        "allocated_credit_interval_micros",
    )
    @classmethod
    def validate_decimal_interval(cls, value: tuple[str, str]) -> tuple[str, str]:
        if len(value) != 2:
            raise ValueError("decimal intervals must contain two bounds")
        lower = Decimal(value[0])
        upper = Decimal(value[1])
        if lower > upper:
            raise ValueError("decimal intervals must be ordered")
        return value

    @field_validator("attacker_share_interval")
    @classmethod
    def validate_share_interval(cls, value: tuple[float, float]) -> tuple[float, float]:
        if len(value) != 2 or value[0] > value[1]:
            raise ValueError("attacker_share_interval must contain ordered bounds")
        if any(not math.isfinite(bound) for bound in value):
            raise ValueError("attacker_share_interval must contain finite bounds")
        return value

    @field_validator("run_config_hash", "config_contract_hash", "scenario_contract_hash", "result_contract_hash")
    @classmethod
    def validate_hash_shape(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("contract hashes must be lowercase SHA-256 hex digests")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> "E6ScenarioRow":
        if self.target_weight_numerator >= self.target_weight_denominator:
            raise ValueError("target_weight_numerator must be less than target_weight_denominator")
        if self.simulation_model_version != E6_SIMULATION_MODEL_VERSION:
            raise ValueError(f"simulation_model_version must equal {E6_SIMULATION_MODEL_VERSION}")
        if self.run_config_hash != config_hash(self.run_config_snapshot):
            raise ValueError("run_config_hash must match canonical RunConfig material")
        if self.run_id != self.run_config_snapshot.run_id:
            raise ValueError("run_id must exactly bind run_config_snapshot.run_id")
        if self.experiment_id != self.run_config_snapshot.experiment_id:
            raise ValueError("experiment_id must exactly bind run_config_snapshot.experiment_id")
        if self.origin is not self.run_config_snapshot.origin:
            raise ValueError("origin must exactly bind run_config_snapshot.origin")
        expected_config_hash = digest(
            "E6_SIMULATION_CONFIG",
            {
                "schema_version": "POI_MPP_E6_SIMULATION_CONFIG_V1",
                "simulations": self.simulations,
                "seed": self.seed,
                "origin": self.origin.value,
                "publication_scope": self.publication_scope,
            },
        )
        if self.config_contract_hash != expected_config_hash:
            raise ValueError("config_contract_hash must match canonical E6 simulation-config material")
        expected_scenario_hash = digest(
            "E6_SYBIL_SCENARIO",
            {
                "scenario_id": self.scenario_id,
                "group_id": self.group_id,
                "role": self.role.value,
                "assumption_label": self.assumption_label.value,
                "capacity_model": self.capacity_model.value,
                "attacker_identity_count": self.attacker_identity_count,
                "attacker_total_capacity_units": self.attacker_total_capacity_units,
                "attacker_success_probability": self.attacker_success_probability,
                "attacker_collateral_micros": self.attacker_collateral_micros,
                "attacker_identity_fixed_cost_micros": self.attacker_identity_fixed_cost_micros,
                "honest_operator_count": self.honest_operator_count,
                "honest_capacity_units": self.honest_capacity_units,
                "honest_success_probability": self.honest_success_probability,
                "honest_collateral_micros": self.honest_collateral_micros,
                "task_count": self.task_count,
                "task_credit_budget": self.task_credit_budget,
                "beta_micros": self.beta_micros,
                "concentration_cap_micros": self.concentration_cap_micros,
                "capacity_cost_micros_per_unit": self.capacity_cost_micros_per_unit,
                "collateral_cost_multiplier_microx": self.collateral_cost_multiplier_microx,
                "capacity_subsidy_micros": self.capacity_subsidy_micros,
                "target_weight_numerator": self.target_weight_numerator,
                "target_weight_denominator": self.target_weight_denominator,
            },
        )
        if self.scenario_contract_hash != expected_scenario_hash:
            raise ValueError("scenario_contract_hash must match canonical E6 scenario material")
        if self.result_contract_hash != result_contract_hash(self):
            raise ValueError("result_contract_hash must match canonical E6 result material")
        return self


def _decimal_mean(values: Sequence[Decimal]) -> Decimal:
    return (sum(values, start=Decimal("0")) / Decimal(len(values))).quantize(_MICRO_QUANTUM, rounding=ROUND_HALF_UP)


def _bootstrap_decimal_interval(values: Sequence[Decimal], *, iterations: int, seed: int) -> tuple[str, str]:
    generator = random.Random(seed)
    estimates: list[Decimal] = []
    for _ in range(iterations):
        sample = [generator.choice(values) for _ in range(len(values))]
        estimates.append(_decimal_mean(sample))
    estimates.sort()
    lower_index = max(0, int(0.025 * (iterations - 1)))
    upper_index = min(iterations - 1, int(0.975 * (iterations - 1)))
    return (str(estimates[lower_index]), str(estimates[upper_index]))


def _bootstrap_float_interval(values: Sequence[float], *, iterations: int, seed: int) -> tuple[float, float]:
    generator = random.Random(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        sample = [generator.choice(values) for _ in range(len(values))]
        estimates.append(sum(sample) / len(sample))
    estimates.sort()
    lower_index = max(0, int(0.025 * (iterations - 1)))
    upper_index = min(iterations - 1, int(0.975 * (iterations - 1)))
    return (estimates[lower_index], estimates[upper_index])


def _split_evenly(total: int, parts: int) -> tuple[int, ...]:
    base, remainder = divmod(total, parts)
    return tuple(base + (1 if index < remainder else 0) for index in range(parts))


def _weighted_choice(generator: random.Random, weighted_items: Sequence[tuple[str, int]]) -> str:
    total_weight = sum(weight for _, weight in weighted_items)
    roll = generator.randrange(total_weight)
    cumulative = 0
    for item, weight in weighted_items:
        cumulative += weight
        if roll < cumulative:
            return item
    raise AssertionError("weighted choice must select an item")


def _attacker_identity_successes(
    generator: random.Random,
    *,
    total_units: int,
    identity_count: int,
    success_probability: float,
) -> tuple[int, ...]:
    draws = [generator.random() < success_probability for _ in range(total_units)]
    capacities = _split_evenly(total_units, identity_count)
    cursor = 0
    per_identity: list[int] = []
    for capacity in capacities:
        per_identity.append(sum(1 for draw in draws[cursor : cursor + capacity] if draw))
        cursor += capacity
    return tuple(per_identity)


def _honest_operator_successes(
    generator: random.Random,
    *,
    operator_count: int,
    capacity_units: int,
    success_probability: float,
) -> tuple[int, ...]:
    return tuple(
        sum(1 for _ in range(capacity_units) if generator.random() < success_probability)
        for _ in range(operator_count)
    )


def _winner_for_task(
    scenario: SybilScenario,
    *,
    generator: random.Random,
    attacker_successes: tuple[int, ...],
    honest_successes: tuple[int, ...],
) -> tuple[bool, int | None]:
    attacker_total_successes = sum(attacker_successes)
    eligible_honest = [index for index, successes in enumerate(honest_successes) if successes > 0]
    attacker_eligible_identities = [index for index, successes in enumerate(attacker_successes) if successes > 0]
    if attacker_total_successes == 0 and not eligible_honest:
        return (False, None)

    if scenario.capacity_model is SybilCapacityModel.IDENTITY_UNIFORM:
        tickets = [("attacker", index) for index in attacker_eligible_identities]
        tickets.extend(("honest", index) for index in eligible_honest)
        winner_kind, winner_index = tickets[generator.randrange(len(tickets))]
        return (winner_kind == "attacker", winner_index if winner_kind == "attacker" else None)

    if scenario.capacity_model is SybilCapacityModel.OPERATOR_SLOT:
        operators = ["attacker"] if attacker_total_successes > 0 else []
        operators.extend(f"honest-{index}" for index in eligible_honest)
        winner = operators[generator.randrange(len(operators))]
        if winner == "attacker":
            return (True, attacker_eligible_identities[0])
        return (False, None)

    weighted: list[tuple[str, int]] = []
    if attacker_total_successes > 0:
        weighted.append(("attacker", attacker_total_successes))
    weighted.extend((f"honest-{index}", honest_successes[index]) for index in eligible_honest)
    winner = _weighted_choice(generator, weighted)
    if winner == "attacker":
        return (True, attacker_eligible_identities[0])
    return (False, None)


def _honest_weight(scenario: SybilScenario, credit: int) -> int:
    if scenario.capacity_model is SybilCapacityModel.TASK_BUDGET_ONLY_ABLATION:
        return credit
    if scenario.capacity_model is SybilCapacityModel.COLLATERAL_CAP_ABLATION:
        return min(credit, scenario.concentration_cap_micros)
    return derive_active_weight(
        credit=credit,
        collateral=scenario.honest_collateral_micros,
        beta=scenario.beta_micros,
        concentration_cap=scenario.concentration_cap_micros,
    )


def _attacker_weight(
    scenario: SybilScenario,
    *,
    attacker_credit: int,
    attacker_credit_by_identity: Sequence[int],
) -> int:
    if scenario.capacity_model is SybilCapacityModel.TASK_BUDGET_ONLY_ABLATION:
        return attacker_credit
    if scenario.capacity_model is SybilCapacityModel.COLLATERAL_CAP_ABLATION:
        return min(attacker_credit, scenario.concentration_cap_micros)
    if scenario.capacity_model is SybilCapacityModel.CONCENTRATION_CAP_ABLATION:
        collateral_parts = _split_evenly(scenario.attacker_collateral_micros, scenario.attacker_identity_count)
        return sum(
            derive_active_weight(
                credit=credit,
                collateral=collateral,
                beta=scenario.beta_micros,
                concentration_cap=scenario.concentration_cap_micros,
            )
            for credit, collateral in zip(attacker_credit_by_identity, collateral_parts, strict=True)
        )
    return derive_active_weight(
        credit=attacker_credit,
        collateral=scenario.attacker_collateral_micros,
        beta=scenario.beta_micros,
        concentration_cap=scenario.concentration_cap_micros,
    )


def _attacker_cost_micros(scenario: SybilScenario) -> Decimal:
    collateral_component = (
        Decimal(scenario.attacker_collateral_micros)
        * Decimal(scenario.collateral_cost_multiplier_microx)
        / Decimal(1_000_000)
    )
    value = (
        Decimal(scenario.attacker_identity_count * scenario.attacker_identity_fixed_cost_micros)
        + Decimal(scenario.attacker_total_capacity_units * scenario.capacity_cost_micros_per_unit)
        + collateral_component
        - Decimal(scenario.capacity_subsidy_micros)
    )
    return max(value, Decimal("0")).quantize(_MICRO_QUANTUM, rounding=ROUND_HALF_UP)


def _assumption_ledger(scenario: SybilScenario) -> tuple[str, ...]:
    return (
        f"role={scenario.role.value}",
        f"capacity_model={scenario.capacity_model.value}",
        f"attacker_identity_count={scenario.attacker_identity_count}",
        f"attacker_total_capacity_units={scenario.attacker_total_capacity_units}",
        f"honest_operator_count={scenario.honest_operator_count}",
        f"task_count={scenario.task_count}",
        f"task_credit_budget={scenario.task_credit_budget}",
        f"target_weight_fraction={scenario.target_weight_numerator}/{scenario.target_weight_denominator}",
    )


def run_sybil_scenario(
    *,
    run_id: str,
    experiment_id: str,
    run_config: RunConfig,
    scenario: SybilScenario,
    config: E6SimulationConfig,
) -> E6ScenarioRow:
    if experiment_id != "E6":
        raise ValueError("experiment_id must equal E6")
    if run_config.run_id != run_id:
        raise ValueError("run_config.run_id must match run_id")
    if run_config.experiment_id != experiment_id:
        raise ValueError("run_config.experiment_id must match experiment_id")
    if run_config.origin is not config.origin:
        raise ValueError("run_config.origin must match config.origin")

    generator = random.Random(config.seed)
    attacker_credit_trials: list[Decimal] = []
    attacker_weight_trials: list[Decimal] = []
    attacker_share_trials: list[float] = []
    allocated_task_count_trials: list[Decimal] = []
    unallocated_task_count_trials: list[Decimal] = []
    allocated_credit_trials: list[Decimal] = []
    task_accounting_exact = True
    credit_issuance_exact = True
    budget_non_exceedance = True
    zero_credit_zero_weight_ok = True

    for _ in range(config.simulations):
        attacker_credit = 0
        attacker_credit_by_identity = [0 for _ in range(scenario.attacker_identity_count)]
        honest_credit_by_operator = [0 for _ in range(scenario.honest_operator_count)]
        allocated_task_count = 0

        for _ in range(scenario.task_count):
            attacker_successes = _attacker_identity_successes(
                generator,
                total_units=scenario.attacker_total_capacity_units,
                identity_count=scenario.attacker_identity_count,
                success_probability=scenario.attacker_success_probability,
            )
            honest_successes = _honest_operator_successes(
                generator,
                operator_count=scenario.honest_operator_count,
                capacity_units=scenario.honest_capacity_units,
                success_probability=scenario.honest_success_probability,
            )
            winner_is_attacker, attacker_identity = _winner_for_task(
                scenario,
                generator=generator,
                attacker_successes=attacker_successes,
                honest_successes=honest_successes,
            )
            if winner_is_attacker:
                attacker_credit += scenario.task_credit_budget
                assert attacker_identity is not None
                attacker_credit_by_identity[attacker_identity] += scenario.task_credit_budget
                allocated_task_count += 1
                continue
            if sum(honest_successes) == 0:
                continue
            weighted_honest = [(str(index), honest_successes[index]) for index, value in enumerate(honest_successes) if value > 0]
            honest_winner = int(_weighted_choice(generator, weighted_honest))
            honest_credit_by_operator[honest_winner] += scenario.task_credit_budget
            allocated_task_count += 1

        allocated_credit = attacker_credit + sum(honest_credit_by_operator)
        unallocated_task_count = scenario.task_count - allocated_task_count
        task_accounting_exact = task_accounting_exact and (
            allocated_task_count + unallocated_task_count == scenario.task_count
        )
        credit_issuance_exact = credit_issuance_exact and (
            allocated_credit == allocated_task_count * scenario.task_credit_budget
        )
        budget_non_exceedance = budget_non_exceedance and (
            allocated_credit <= scenario.task_count * scenario.task_credit_budget
        )

        attacker_weight = _attacker_weight(
            scenario,
            attacker_credit=attacker_credit,
            attacker_credit_by_identity=attacker_credit_by_identity,
        )
        honest_weights = [_honest_weight(scenario, credit) for credit in honest_credit_by_operator]
        if attacker_credit == 0 and attacker_weight != 0:
            zero_credit_zero_weight_ok = False
        total_weight = attacker_weight + sum(honest_weights)
        attacker_share = 0.0 if total_weight == 0 else attacker_weight / total_weight

        attacker_credit_trials.append(Decimal(attacker_credit).quantize(_MICRO_QUANTUM))
        attacker_weight_trials.append(Decimal(attacker_weight).quantize(_MICRO_QUANTUM))
        allocated_task_count_trials.append(Decimal(allocated_task_count).quantize(_MICRO_QUANTUM))
        unallocated_task_count_trials.append(Decimal(unallocated_task_count).quantize(_MICRO_QUANTUM))
        allocated_credit_trials.append(Decimal(allocated_credit).quantize(_MICRO_QUANTUM))
        attacker_share_trials.append(attacker_share)

    attacker_credit_mean = _decimal_mean(attacker_credit_trials)
    attacker_weight_mean = _decimal_mean(attacker_weight_trials)
    allocated_task_count_mean = _decimal_mean(allocated_task_count_trials)
    unallocated_task_count_mean = _decimal_mean(unallocated_task_count_trials)
    allocated_credit_mean = _decimal_mean(allocated_credit_trials)
    attacker_share_mean = sum(attacker_share_trials) / len(attacker_share_trials)
    target_fraction = Decimal(scenario.target_weight_numerator) / Decimal(scenario.target_weight_denominator)
    attack_cost = _attacker_cost_micros(scenario)
    if attacker_share_mean <= 0.0:
        estimated_cost_to_target = "INF"
    else:
        scale = target_fraction / Decimal(str(attacker_share_mean))
        estimated_cost_to_target = str((attack_cost * scale).quantize(_MICRO_QUANTUM, rounding=ROUND_HALF_UP))

    payload = {
        "run_id": run_id,
        "experiment_id": experiment_id,
        "run_config_snapshot": run_config,
        "run_config_hash": config_hash(run_config),
        "scenario_id": scenario.scenario_id,
        "group_id": scenario.group_id,
        "seed": config.seed,
        "simulations": config.simulations,
        "origin": config.origin,
        "role": scenario.role,
        "assumption_label": scenario.assumption_label,
        "capacity_model": scenario.capacity_model,
        "attacker_identity_count": scenario.attacker_identity_count,
        "attacker_total_capacity_units": scenario.attacker_total_capacity_units,
        "attacker_success_probability": scenario.attacker_success_probability,
        "attacker_collateral_micros": scenario.attacker_collateral_micros,
        "attacker_identity_fixed_cost_micros": scenario.attacker_identity_fixed_cost_micros,
        "honest_operator_count": scenario.honest_operator_count,
        "honest_capacity_units": scenario.honest_capacity_units,
        "honest_success_probability": scenario.honest_success_probability,
        "honest_collateral_micros": scenario.honest_collateral_micros,
        "task_count": scenario.task_count,
        "task_credit_budget": scenario.task_credit_budget,
        "beta_micros": scenario.beta_micros,
        "concentration_cap_micros": scenario.concentration_cap_micros,
        "capacity_cost_micros_per_unit": scenario.capacity_cost_micros_per_unit,
        "collateral_cost_multiplier_microx": scenario.collateral_cost_multiplier_microx,
        "capacity_subsidy_micros": scenario.capacity_subsidy_micros,
        "target_weight_numerator": scenario.target_weight_numerator,
        "target_weight_denominator": scenario.target_weight_denominator,
        "simulation_model_version": E6_SIMULATION_MODEL_VERSION,
        "config_contract_hash": simulation_config_contract_hash(config),
        "scenario_contract_hash": scenario_contract_hash(scenario),
        "result_contract_hash": "0" * 64,
        "attacker_expected_credit_micros": str(attacker_credit_mean),
        "attacker_credit_interval_micros": _bootstrap_decimal_interval(
            attacker_credit_trials,
            iterations=256,
            seed=config.seed + 101,
        ),
        "attacker_expected_weight_micros": str(attacker_weight_mean),
        "attacker_weight_interval_micros": _bootstrap_decimal_interval(
            attacker_weight_trials,
            iterations=256,
            seed=config.seed + 211,
        ),
        "attacker_expected_share": attacker_share_mean,
        "attacker_share_interval": _bootstrap_float_interval(
            attacker_share_trials,
            iterations=256,
            seed=config.seed + 307,
        ),
        "allocated_task_count_mean": str(allocated_task_count_mean),
        "allocated_task_count_interval": _bootstrap_decimal_interval(
            allocated_task_count_trials,
            iterations=256,
            seed=config.seed + 353,
        ),
        "unallocated_task_count_mean": str(unallocated_task_count_mean),
        "unallocated_task_count_interval": _bootstrap_decimal_interval(
            unallocated_task_count_trials,
            iterations=256,
            seed=config.seed + 379,
        ),
        "allocated_credit_mean_micros": str(allocated_credit_mean),
        "allocated_credit_interval_micros": _bootstrap_decimal_interval(
            allocated_credit_trials,
            iterations=256,
            seed=config.seed + 401,
        ),
        "task_accounting_exact": task_accounting_exact,
        "credit_issuance_exact": credit_issuance_exact,
        "budget_non_exceedance": budget_non_exceedance,
        "credit_utilization_ratio": float(
            allocated_credit_mean / Decimal(scenario.task_count * scenario.task_credit_budget)
        ),
        "zero_credit_implies_zero_weight": zero_credit_zero_weight_ok,
        "estimated_cost_to_target_weight_micros": estimated_cost_to_target,
        "assumption_ledger": _assumption_ledger(scenario),
        "publication_scope": config.publication_scope,
    }
    provisional = E6ScenarioRow.model_construct(**payload)
    payload["result_contract_hash"] = result_contract_hash(provisional)
    return E6ScenarioRow.model_validate(payload)


def scenario_from_row(row: E6ScenarioRow) -> SybilScenario:
    return SybilScenario(
        scenario_id=row.scenario_id,
        group_id=row.group_id,
        role=row.role,
        assumption_label=row.assumption_label,
        capacity_model=row.capacity_model,
        attacker_identity_count=row.attacker_identity_count,
        attacker_total_capacity_units=row.attacker_total_capacity_units,
        attacker_success_probability=row.attacker_success_probability,
        attacker_collateral_micros=row.attacker_collateral_micros,
        attacker_identity_fixed_cost_micros=row.attacker_identity_fixed_cost_micros,
        honest_operator_count=row.honest_operator_count,
        honest_capacity_units=row.honest_capacity_units,
        honest_success_probability=row.honest_success_probability,
        honest_collateral_micros=row.honest_collateral_micros,
        task_count=row.task_count,
        task_credit_budget=row.task_credit_budget,
        beta_micros=row.beta_micros,
        concentration_cap_micros=row.concentration_cap_micros,
        capacity_cost_micros_per_unit=row.capacity_cost_micros_per_unit,
        collateral_cost_multiplier_microx=row.collateral_cost_multiplier_microx,
        capacity_subsidy_micros=row.capacity_subsidy_micros,
        target_weight_numerator=row.target_weight_numerator,
        target_weight_denominator=row.target_weight_denominator,
    )


def simulation_config_from_row(row: E6ScenarioRow) -> E6SimulationConfig:
    return E6SimulationConfig(
        simulations=row.simulations,
        seed=row.seed,
        origin=row.origin,
        publication_scope=row.publication_scope,
    )


def replay_row(row: E6ScenarioRow) -> E6ScenarioRow:
    return run_sybil_scenario(
        run_id=row.run_id,
        experiment_id=row.experiment_id,
        run_config=row.run_config_snapshot,
        scenario=scenario_from_row(row),
        config=simulation_config_from_row(row),
    )


def assert_cli_authority_boundary(run_config: RunConfig, contract: E6ConfirmatoryContract) -> None:
    if run_config.experiment_id != "E6":
        raise AuthorityBoundaryError("E6 wrapper requires experiment_id E6")
    if run_config.origin is not contract.required_run_origin:
        raise AuthorityBoundaryError("E6 publication CLI is reserved for REPRODUCIBLE_SIMULATION runs")
    if run_config.authorization_scope != contract.required_run_authorization_scope:
        raise AuthorityBoundaryError(
            "E6 publication CLI requires PUBLICATION_EVIDENCE_AUTHORIZED authorization_scope"
        )
    raise AuthorityBoundaryError(
        "explicit publication freeze and artifact routing remain manual for E6; "
        "validated reproducible-simulation authority but will not auto-run publication artifacts"
    )
