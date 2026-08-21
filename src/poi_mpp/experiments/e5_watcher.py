"""E5 watcher/dispute economics with explicit model boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
import math
import random
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from poi_mpp.auditor.availability import ModelAssumptionError
from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig
from poi_mpp.evidence.models import EvidenceOrigin


PUBLICATION_EVIDENCE_AUTHORIZED = "PUBLICATION_EVIDENCE_AUTHORIZED"
E5_CONFIRMATORY_SCOPE = "E5_CONFIRMATORY_PUBLICATION_V1"
MIN_SUPPORTED_SIMULATIONS = 2048
_WILSON_Z = 1.959963984540054
_MICRO_QUANTUM = Decimal("0.000001")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WatcherScenarioFamily(StrEnum):
    INDEPENDENT = "INDEPENDENT"
    CORRELATED_OUTAGE = "CORRELATED_OUTAGE"
    SHARED_INFRASTRUCTURE = "SHARED_INFRASTRUCTURE"
    HETEROGENEOUS_COST = "HETEROGENEOUS_COST"
    COLLUSION = "COLLUSION"
    BRIBERY_SUBSIDY = "BRIBERY_SUBSIDY"
    BONDED_AUDITOR = "BONDED_AUDITOR"


class WatcherCorrelationModel(StrEnum):
    INDEPENDENT = "INDEPENDENT"
    CORRELATED_OUTAGE = "CORRELATED_OUTAGE"
    SHARED_INFRASTRUCTURE = "SHARED_INFRASTRUCTURE"
    COLLUSION = "COLLUSION"


class WatcherAssumption(StrEnum):
    INDEPENDENT_WATCHERS_DECLARED = "INDEPENDENT_WATCHERS_DECLARED"
    CORRELATED_OUTAGE_DECLARED = "CORRELATED_OUTAGE_DECLARED"
    SHARED_INFRASTRUCTURE_DECLARED = "SHARED_INFRASTRUCTURE_DECLARED"
    HETEROGENEOUS_COST_DECLARED = "HETEROGENEOUS_COST_DECLARED"
    COLLUSION_DECLARED = "COLLUSION_DECLARED"
    BRIBERY_SUBSIDY_DECLARED = "BRIBERY_SUBSIDY_DECLARED"
    BONDED_AUDITOR_BACKSTOP_DECLARED = "BONDED_AUDITOR_BACKSTOP_DECLARED"


class AuthorityBoundaryError(ValueError):
    """Raised when the E5 CLI would overstate publication authority."""


class E5ConfirmatoryScope(_FrozenModel):
    schema_version: str = "POI_MPP_E5_CONFIRMATORY_SCOPE_V1"
    publication_scope: str
    required_run_origin: EvidenceOrigin
    required_run_authorization_scope: str
    minimum_supported_simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS)
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_contract(self) -> "E5ConfirmatoryScope":
        if self.schema_version != "POI_MPP_E5_CONFIRMATORY_SCOPE_V1":
            raise ValueError("schema_version must equal POI_MPP_E5_CONFIRMATORY_SCOPE_V1")
        if self.publication_scope != E5_CONFIRMATORY_SCOPE:
            raise ValueError(f"publication_scope must equal {E5_CONFIRMATORY_SCOPE}")
        if self.required_run_origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
            raise ValueError("required_run_origin must equal REPRODUCIBLE_SIMULATION")
        if self.required_run_authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
            raise ValueError(
                f"required_run_authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
            )
        if self.minimum_supported_simulations < MIN_SUPPORTED_SIMULATIONS:
            raise ValueError("minimum_supported_simulations cannot weaken the frozen E5 floor")
        return self


def default_e5_confirmatory_scope() -> E5ConfirmatoryScope:
    return E5ConfirmatoryScope(
        publication_scope=E5_CONFIRMATORY_SCOPE,
        required_run_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        required_run_authorization_scope=PUBLICATION_EVIDENCE_AUTHORIZED,
        minimum_supported_simulations=MIN_SUPPORTED_SIMULATIONS,
        notes=(
            "E5 publication artifacts are reproducible simulations only; they are not production dispute evidence.",
            "Synthetic fixtures remain plumbing-only and cannot satisfy confirmatory publication scope.",
        ),
    )


def load_e5_confirmatory_scope(path: str | Path) -> E5ConfirmatoryScope:
    scope_path = Path(path)
    try:
        raw = yaml.safe_load(scope_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"unable to load E5 confirmatory scope: {scope_path}") from error
    if not isinstance(raw, Mapping):
        raise ValueError("E5 confirmatory scope must be a mapping")
    return E5ConfirmatoryScope.model_validate(dict(raw))


class WatcherScenario(_FrozenModel):
    scenario_id: str
    family: WatcherScenarioFamily
    assumption_label: WatcherAssumption
    correlation_model: WatcherCorrelationModel
    watcher_count: int = Field(gt=0)
    fraud_value_micros: int = Field(ge=0)
    watch_cost_micros: int = Field(ge=0)
    challenge_bond_micros: int = Field(ge=0)
    challenge_reward_micros: int = Field(ge=0)
    challenge_subsidy_micros: int = Field(ge=0)
    attacker_bribe_micros: int = Field(ge=0)
    per_watcher_online_probability: float = Field(ge=0.0, le=1.0)
    per_watcher_discovery_probability: float = Field(ge=0.0, le=1.0)
    per_watcher_challenge_probability: float = Field(ge=0.0, le=1.0)
    challenge_success_probability: float = Field(ge=0.0, le=1.0)
    shared_outage_probability: float = Field(ge=0.0, le=1.0)
    shared_infrastructure_failure_probability: float = Field(ge=0.0, le=1.0)
    colluding_watchers: int = Field(ge=0)
    bonded_auditor_detection_probability: float = Field(ge=0.0, le=1.0)
    bonded_auditor_success_probability: float = Field(ge=0.0, le=1.0)
    bonded_auditor_cost_micros: int = Field(ge=0)
    bonded_auditor_reward_micros: int = Field(ge=0)
    watcher_cost_micros_by_watcher: tuple[int, ...] | None = None

    @field_validator("scenario_id")
    @classmethod
    def require_nonblank_scenario_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scenario_id must not be blank")
        return value

    @field_validator(
        "fraud_value_micros",
        "watch_cost_micros",
        "challenge_bond_micros",
        "challenge_reward_micros",
        "challenge_subsidy_micros",
        "attacker_bribe_micros",
        "bonded_auditor_cost_micros",
        "bonded_auditor_reward_micros",
        mode="before",
    )
    @classmethod
    def require_nonnegative_ints(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{info.field_name} must be a non-negative integer")
        return value

    @field_validator(
        "per_watcher_online_probability",
        "per_watcher_discovery_probability",
        "per_watcher_challenge_probability",
        "challenge_success_probability",
        "shared_outage_probability",
        "shared_infrastructure_failure_probability",
        "bonded_auditor_detection_probability",
        "bonded_auditor_success_probability",
        mode="before",
    )
    @classmethod
    def require_finite_probability(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"{info.field_name} must be a finite probability")
        return value

    @field_validator("watcher_cost_micros_by_watcher")
    @classmethod
    def validate_cost_vector(cls, value: tuple[int, ...] | None) -> tuple[int, ...] | None:
        if value is None:
            return value
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise ValueError("watcher_cost_micros_by_watcher must contain non-negative integers")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> "WatcherScenario":
        if self.colluding_watchers > self.watcher_count:
            raise ValueError("colluding_watchers cannot exceed watcher_count")
        if self.watcher_cost_micros_by_watcher is not None and len(self.watcher_cost_micros_by_watcher) != self.watcher_count:
            raise ValueError("watcher_cost_micros_by_watcher must align with watcher_count")
        if self.family is WatcherScenarioFamily.INDEPENDENT:
            if self.assumption_label is not WatcherAssumption.INDEPENDENT_WATCHERS_DECLARED:
                raise ValueError("independent scenarios require INDEPENDENT_WATCHERS_DECLARED")
            if self.correlation_model is not WatcherCorrelationModel.INDEPENDENT:
                raise ValueError("independent scenarios require correlation_model INDEPENDENT")
            if self.shared_outage_probability != 0.0 or self.shared_infrastructure_failure_probability != 0.0:
                raise ValueError("independent scenarios cannot declare shared failures")
            if self.colluding_watchers != 0:
                raise ValueError("independent scenarios cannot declare colluding_watchers")
            if self.watcher_cost_micros_by_watcher is not None:
                raise ValueError("independent scenarios must use homogeneous watch_cost_micros")
            if (
                self.bonded_auditor_detection_probability != 0.0
                or self.bonded_auditor_success_probability != 0.0
                or self.bonded_auditor_cost_micros != 0
                or self.bonded_auditor_reward_micros != 0
            ):
                raise ValueError("independent scenarios cannot include bonded auditor backstops")
        elif self.family is WatcherScenarioFamily.CORRELATED_OUTAGE:
            if self.assumption_label is not WatcherAssumption.CORRELATED_OUTAGE_DECLARED:
                raise ValueError("correlated outage scenarios require CORRELATED_OUTAGE_DECLARED")
            if self.correlation_model is not WatcherCorrelationModel.CORRELATED_OUTAGE:
                raise ValueError("correlated outage scenarios require correlation_model CORRELATED_OUTAGE")
            if self.shared_outage_probability <= 0.0:
                raise ValueError("correlated outage scenarios require shared_outage_probability > 0")
        elif self.family is WatcherScenarioFamily.SHARED_INFRASTRUCTURE:
            if self.assumption_label is not WatcherAssumption.SHARED_INFRASTRUCTURE_DECLARED:
                raise ValueError("shared infrastructure scenarios require SHARED_INFRASTRUCTURE_DECLARED")
            if self.correlation_model is not WatcherCorrelationModel.SHARED_INFRASTRUCTURE:
                raise ValueError("shared infrastructure scenarios require correlation_model SHARED_INFRASTRUCTURE")
            if self.shared_infrastructure_failure_probability <= 0.0:
                raise ValueError("shared infrastructure scenarios require failure probability > 0")
        elif self.family is WatcherScenarioFamily.HETEROGENEOUS_COST:
            if self.assumption_label is not WatcherAssumption.HETEROGENEOUS_COST_DECLARED:
                raise ValueError("heterogeneous cost scenarios require HETEROGENEOUS_COST_DECLARED")
            if self.watcher_cost_micros_by_watcher is None:
                raise ValueError("heterogeneous cost scenarios require watcher_cost_micros_by_watcher")
        elif self.family is WatcherScenarioFamily.COLLUSION:
            if self.assumption_label is not WatcherAssumption.COLLUSION_DECLARED:
                raise ValueError("collusion scenarios require COLLUSION_DECLARED")
            if self.correlation_model is not WatcherCorrelationModel.COLLUSION:
                raise ValueError("collusion scenarios require correlation_model COLLUSION")
            if self.colluding_watchers <= 0:
                raise ValueError("collusion scenarios require colluding_watchers > 0")
        elif self.family is WatcherScenarioFamily.BRIBERY_SUBSIDY:
            if self.assumption_label is not WatcherAssumption.BRIBERY_SUBSIDY_DECLARED:
                raise ValueError("bribery/subsidy scenarios require BRIBERY_SUBSIDY_DECLARED")
            if self.attacker_bribe_micros == 0 and self.challenge_subsidy_micros == 0:
                raise ValueError("bribery/subsidy scenarios require a bribe or subsidy parameter")
            if self.attacker_bribe_micros > 0 and self.colluding_watchers <= 0:
                raise ValueError("bribery/subsidy scenarios with attacker_bribe_micros require colluding_watchers > 0")
        elif self.family is WatcherScenarioFamily.BONDED_AUDITOR:
            if self.assumption_label is not WatcherAssumption.BONDED_AUDITOR_BACKSTOP_DECLARED:
                raise ValueError("bonded auditor scenarios require BONDED_AUDITOR_BACKSTOP_DECLARED")
            if self.bonded_auditor_detection_probability <= 0.0 or self.bonded_auditor_success_probability <= 0.0:
                raise ValueError("bonded auditor scenarios require positive detection and success probabilities")
        return self


class E5SimulationConfig(_FrozenModel):
    simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS)
    seed: int = Field(ge=0)
    origin: EvidenceOrigin
    publication_scope: str | None = None

    @model_validator(mode="after")
    def validate_origin(self) -> "E5SimulationConfig":
        if self.origin not in {
            EvidenceOrigin.REPRODUCIBLE_SIMULATION,
            EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        }:
            raise ValueError("E5 simulation origin must be REPRODUCIBLE_SIMULATION or SYNTHETIC_NON_EVIDENCE")
        if self.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE and self.publication_scope is not None:
            raise ValueError("synthetic plumbing runs cannot declare publication_scope")
        return self


def simulation_config_contract_hash(config: E5SimulationConfig) -> str:
    return digest(
        "E5_SIMULATION_CONFIG",
        {
            "schema_version": "POI_MPP_E5_SIMULATION_CONFIG_V1",
            "simulations": config.simulations,
            "origin": config.origin.value,
            "publication_scope": config.publication_scope,
        },
    )


def scenario_contract_hash(scenario: WatcherScenario) -> str:
    return digest("E5_WATCHER_SCENARIO", scenario.model_dump(mode="json"))


class E5ScenarioRow(_FrozenModel):
    schema_version: str = "POI_MPP_E5_SCENARIO_ROW_V1"
    run_id: str
    experiment_id: str
    scenario_id: str
    seed: int = Field(ge=0)
    simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS)
    origin: EvidenceOrigin
    family: WatcherScenarioFamily
    assumption_label: WatcherAssumption
    correlation_model: WatcherCorrelationModel
    fraud_value_micros: int = Field(ge=0)
    watch_cost_micros: int = Field(ge=0)
    challenge_bond_micros: int = Field(ge=0)
    challenge_reward_micros: int = Field(ge=0)
    challenge_subsidy_micros: int = Field(ge=0)
    attacker_bribe_micros: int = Field(ge=0)
    watcher_count: int = Field(gt=0)
    per_watcher_online_probability: float = Field(ge=0.0, le=1.0)
    per_watcher_discovery_probability: float = Field(ge=0.0, le=1.0)
    per_watcher_challenge_probability: float = Field(ge=0.0, le=1.0)
    declared_challenge_success_probability: float = Field(ge=0.0, le=1.0)
    shared_outage_probability: float = Field(ge=0.0, le=1.0)
    shared_infrastructure_failure_probability: float = Field(ge=0.0, le=1.0)
    colluding_watchers: int = Field(ge=0)
    bonded_auditor_detection_probability: float = Field(ge=0.0, le=1.0)
    bonded_auditor_success_probability: float = Field(ge=0.0, le=1.0)
    bonded_auditor_cost_micros: int = Field(ge=0)
    bonded_auditor_reward_micros: int = Field(ge=0)
    watcher_cost_micros_by_watcher: tuple[int, ...] | None = None
    config_contract_hash: str
    scenario_contract_hash: str
    no_challenge_probability: float = Field(ge=0.0, le=1.0)
    invalid_maturity_probability: float = Field(ge=0.0, le=1.0)
    challenge_probability: float = Field(ge=0.0, le=1.0)
    challenge_success_probability: float = Field(ge=0.0, le=1.0)
    challenge_failure_probability: float = Field(ge=0.0, le=1.0)
    no_challenge_interval: tuple[float, float]
    invalid_maturity_interval: tuple[float, float]
    challenge_success_interval: tuple[float, float]
    watcher_expected_utility_micros: str
    watcher_expected_utility_interval_micros: tuple[str, str]
    bonded_auditor_expected_utility_micros: str
    bonded_auditor_expected_utility_interval_micros: tuple[str, str]
    analytic_no_challenge_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    analytic_invalid_maturity_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    convergence_reference: str
    convergence_delta: float = Field(ge=0.0)
    currency_precision: str = "MICROS_DECIMAL"
    assumption_ledger: tuple[str, ...]
    publication_scope: str | None = None

    @field_validator(
        "run_id",
        "experiment_id",
        "scenario_id",
        "config_contract_hash",
        "scenario_contract_hash",
        "watcher_expected_utility_micros",
        "bonded_auditor_expected_utility_micros",
        "convergence_reference",
        mode="before",
    )
    @classmethod
    def require_nonblank_text(cls, value: object, info: ValidationInfo) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator(
        "no_challenge_interval",
        "invalid_maturity_interval",
        "challenge_success_interval",
    )
    @classmethod
    def validate_probability_interval(cls, value: tuple[float, float]) -> tuple[float, float]:
        if len(value) != 2 or value[0] > value[1]:
            raise ValueError("probability intervals must contain ordered bounds")
        if any(not math.isfinite(bound) for bound in value):
            raise ValueError("probability intervals must contain finite bounds")
        return value

    @field_validator(
        "watcher_expected_utility_interval_micros",
        "bonded_auditor_expected_utility_interval_micros",
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

    @field_validator("config_contract_hash", "scenario_contract_hash")
    @classmethod
    def validate_contract_hash_shape(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("contract hashes must be lowercase SHA-256 hex digests")
        return value

    @model_validator(mode="after")
    def validate_probabilities(self) -> "E5ScenarioRow":
        if self.challenge_success_probability > self.challenge_probability:
            raise ValueError("challenge_success_probability cannot exceed challenge_probability")
        if self.challenge_failure_probability > self.challenge_probability:
            raise ValueError("challenge_failure_probability cannot exceed challenge_probability")
        if not math.isclose(
            self.challenge_probability,
            self.challenge_success_probability + self.challenge_failure_probability,
            abs_tol=1e-9,
        ):
            raise ValueError("challenge_probability must equal success + failure")
        if not math.isclose(self.invalid_maturity_probability, 1.0 - self.challenge_success_probability, abs_tol=1e-9):
            raise ValueError("invalid_maturity_probability must equal 1 - challenge_success_probability")
        if self.currency_precision != "MICROS_DECIMAL":
            raise ValueError("currency_precision must equal MICROS_DECIMAL")
        expected_config_hash = digest(
            "E5_SIMULATION_CONFIG",
            {
                "schema_version": "POI_MPP_E5_SIMULATION_CONFIG_V1",
                "simulations": self.simulations,
                "origin": self.origin.value,
                "publication_scope": self.publication_scope,
            },
        )
        if self.config_contract_hash != expected_config_hash:
            raise ValueError("config_contract_hash must match canonical E5 simulation-config material")
        expected_scenario_hash = digest(
            "E5_WATCHER_SCENARIO",
            {
                "scenario_id": self.scenario_id,
                "family": self.family.value,
                "assumption_label": self.assumption_label.value,
                "correlation_model": self.correlation_model.value,
                "watcher_count": self.watcher_count,
                "fraud_value_micros": self.fraud_value_micros,
                "watch_cost_micros": self.watch_cost_micros,
                "challenge_bond_micros": self.challenge_bond_micros,
                "challenge_reward_micros": self.challenge_reward_micros,
                "challenge_subsidy_micros": self.challenge_subsidy_micros,
                "attacker_bribe_micros": self.attacker_bribe_micros,
                "per_watcher_online_probability": self.per_watcher_online_probability,
                "per_watcher_discovery_probability": self.per_watcher_discovery_probability,
                "per_watcher_challenge_probability": self.per_watcher_challenge_probability,
                "challenge_success_probability": self.declared_challenge_success_probability,
                "shared_outage_probability": self.shared_outage_probability,
                "shared_infrastructure_failure_probability": self.shared_infrastructure_failure_probability,
                "colluding_watchers": self.colluding_watchers,
                "bonded_auditor_detection_probability": self.bonded_auditor_detection_probability,
                "bonded_auditor_success_probability": self.bonded_auditor_success_probability,
                "bonded_auditor_cost_micros": self.bonded_auditor_cost_micros,
                "bonded_auditor_reward_micros": self.bonded_auditor_reward_micros,
                "watcher_cost_micros_by_watcher": self.watcher_cost_micros_by_watcher,
            },
        )
        if self.scenario_contract_hash != expected_scenario_hash:
            raise ValueError("scenario_contract_hash must match canonical E5 scenario material")
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


def _decimal_mean(values: Sequence[Decimal]) -> Decimal:
    return (sum(values, start=Decimal("0")) / Decimal(len(values))).quantize(_MICRO_QUANTUM, rounding=ROUND_HALF_UP)


def _bootstrap_decimal_interval(values: Sequence[Decimal], *, iterations: int, seed: int) -> tuple[str, str]:
    if not values:
        raise ValueError("bootstrap interval requires at least one value")
    generator = random.Random(seed)
    estimates: list[Decimal] = []
    for _ in range(iterations):
        sample = [generator.choice(values) for _ in range(len(values))]
        estimates.append(_decimal_mean(sample))
    estimates.sort()
    lower_index = max(0, int(0.025 * (iterations - 1)))
    upper_index = min(iterations - 1, int(0.975 * (iterations - 1)))
    return (str(estimates[lower_index]), str(estimates[upper_index]))


def _mean_watch_costs(scenario: WatcherScenario) -> int:
    if scenario.watcher_cost_micros_by_watcher is None:
        return scenario.watch_cost_micros
    return int(sum(scenario.watcher_cost_micros_by_watcher) / len(scenario.watcher_cost_micros_by_watcher))


def _watcher_cost_vector(scenario: WatcherScenario) -> tuple[int, ...]:
    if scenario.watcher_cost_micros_by_watcher is not None:
        return scenario.watcher_cost_micros_by_watcher
    return tuple(scenario.watch_cost_micros for _ in range(scenario.watcher_count))


def _attempt_probability(scenario: WatcherScenario) -> float:
    return (
        scenario.per_watcher_online_probability
        * scenario.per_watcher_discovery_probability
        * scenario.per_watcher_challenge_probability
    )


def independent_no_challenge_probability(scenario: WatcherScenario) -> float:
    if scenario.family is not WatcherScenarioFamily.INDEPENDENT:
        raise ModelAssumptionError("independent closed form is only valid for fully independent watcher scenarios")
    return (1.0 - _attempt_probability(scenario)) ** scenario.watcher_count


def independent_invalid_maturity_probability(scenario: WatcherScenario) -> float:
    if scenario.family is not WatcherScenarioFamily.INDEPENDENT:
        raise ModelAssumptionError("independent closed form is only valid for fully independent watcher scenarios")
    per_watcher_success = _attempt_probability(scenario) * scenario.challenge_success_probability
    return (1.0 - per_watcher_success) ** scenario.watcher_count


def _trial_utilities(
    scenario: WatcherScenario,
    *,
    generator: random.Random,
) -> tuple[bool, bool, Decimal, Decimal]:
    shared_outage = (
        scenario.shared_outage_probability > 0.0 and generator.random() < scenario.shared_outage_probability
    )
    shared_infrastructure = (
        scenario.shared_infrastructure_failure_probability > 0.0
        and generator.random() < scenario.shared_infrastructure_failure_probability
    )
    watcher_utility = Decimal("0")
    auditor_utility = Decimal("0")
    any_challenge = False
    challenge_success = False

    for index, base_cost in enumerate(_watcher_cost_vector(scenario)):
        utility = -Decimal(base_cost)
        if shared_outage or shared_infrastructure:
            watcher_utility += utility
            continue
        if generator.random() > scenario.per_watcher_online_probability:
            watcher_utility += utility
            continue
        if generator.random() > scenario.per_watcher_discovery_probability:
            watcher_utility += utility
            continue
        if index < scenario.colluding_watchers:
            utility += Decimal(scenario.attacker_bribe_micros)
            watcher_utility += utility
            continue
        if generator.random() > scenario.per_watcher_challenge_probability:
            watcher_utility += utility
            continue
        any_challenge = True
        if generator.random() < scenario.challenge_success_probability:
            challenge_success = True
            utility += Decimal(scenario.challenge_reward_micros + scenario.challenge_subsidy_micros)
        else:
            utility -= Decimal(scenario.challenge_bond_micros)
        watcher_utility += utility

    if scenario.bonded_auditor_detection_probability > 0.0 and not challenge_success:
        auditor_utility -= Decimal(scenario.bonded_auditor_cost_micros)
        if generator.random() < scenario.bonded_auditor_detection_probability:
            any_challenge = True
            if generator.random() < scenario.bonded_auditor_success_probability:
                challenge_success = True
                auditor_utility += Decimal(scenario.bonded_auditor_reward_micros)

    return any_challenge, challenge_success, watcher_utility, auditor_utility


def _assumption_ledger(scenario: WatcherScenario) -> tuple[str, ...]:
    entries = [
        f"family={scenario.family.value}",
        f"correlation_model={scenario.correlation_model.value}",
        f"watchers={scenario.watcher_count}",
        f"per_watcher_attempt_probability={_attempt_probability(scenario):.6f}",
        f"challenge_success_probability={scenario.challenge_success_probability:.6f}",
        f"fraud_value_micros={scenario.fraud_value_micros}",
    ]
    if scenario.shared_outage_probability > 0.0:
        entries.append(f"shared_outage_probability={scenario.shared_outage_probability:.6f}")
    if scenario.shared_infrastructure_failure_probability > 0.0:
        entries.append(
            f"shared_infrastructure_failure_probability={scenario.shared_infrastructure_failure_probability:.6f}"
        )
    if scenario.colluding_watchers > 0:
        entries.append(f"colluding_watchers={scenario.colluding_watchers}")
    if scenario.challenge_subsidy_micros > 0:
        entries.append(f"challenge_subsidy_micros={scenario.challenge_subsidy_micros}")
    if scenario.attacker_bribe_micros > 0:
        entries.append(f"attacker_bribe_micros={scenario.attacker_bribe_micros}")
    if scenario.bonded_auditor_detection_probability > 0.0:
        entries.append(
            f"bonded_auditor_detection_probability={scenario.bonded_auditor_detection_probability:.6f}"
        )
    return tuple(entries)


def run_watcher_scenario(
    *,
    run_id: str,
    experiment_id: str,
    scenario: WatcherScenario,
    config: E5SimulationConfig,
) -> E5ScenarioRow:
    if experiment_id != "E5":
        raise ValueError("experiment_id must equal E5")
    generator = random.Random(config.seed)
    no_challenge_count = 0
    challenge_success_count = 0
    challenge_failure_count = 0
    watcher_utilities: list[Decimal] = []
    auditor_utilities: list[Decimal] = []
    first_half_invalid = 0
    second_half_invalid = 0

    for trial_index in range(config.simulations):
        any_challenge, challenge_success, watcher_utility, auditor_utility = _trial_utilities(
            scenario,
            generator=generator,
        )
        if not any_challenge:
            no_challenge_count += 1
        if challenge_success:
            challenge_success_count += 1
        elif any_challenge:
            challenge_failure_count += 1

        invalid_maturity = not challenge_success
        if trial_index < config.simulations // 2:
            first_half_invalid += int(invalid_maturity)
        else:
            second_half_invalid += int(invalid_maturity)
        watcher_utilities.append(watcher_utility / Decimal(scenario.watcher_count))
        auditor_utilities.append(auditor_utility)

    no_challenge_probability = no_challenge_count / config.simulations
    challenge_success_probability = challenge_success_count / config.simulations
    challenge_failure_probability = challenge_failure_count / config.simulations
    challenge_probability = challenge_success_probability + challenge_failure_probability
    invalid_maturity_probability = 1.0 - challenge_success_probability

    analytic_no_challenge: float | None = None
    analytic_invalid_maturity: float | None = None
    if scenario.family is WatcherScenarioFamily.INDEPENDENT:
        analytic_no_challenge = independent_no_challenge_probability(scenario)
        analytic_invalid_maturity = independent_invalid_maturity_probability(scenario)
        convergence_reference = "analytic_no_challenge"
        convergence_delta = abs(no_challenge_probability - analytic_no_challenge)
    else:
        first_half_trials = config.simulations // 2
        second_half_trials = config.simulations - first_half_trials
        first_half_rate = first_half_invalid / first_half_trials
        second_half_rate = second_half_invalid / second_half_trials
        convergence_reference = "half_split_invalid_maturity"
        convergence_delta = abs(first_half_rate - second_half_rate)

    return E5ScenarioRow(
        run_id=run_id,
        experiment_id=experiment_id,
        scenario_id=scenario.scenario_id,
        seed=config.seed,
        simulations=config.simulations,
        origin=config.origin,
        family=scenario.family,
        assumption_label=scenario.assumption_label,
        correlation_model=scenario.correlation_model,
        fraud_value_micros=scenario.fraud_value_micros,
        watch_cost_micros=scenario.watch_cost_micros,
        challenge_bond_micros=scenario.challenge_bond_micros,
        challenge_reward_micros=scenario.challenge_reward_micros,
        challenge_subsidy_micros=scenario.challenge_subsidy_micros,
        attacker_bribe_micros=scenario.attacker_bribe_micros,
        watcher_count=scenario.watcher_count,
        per_watcher_online_probability=scenario.per_watcher_online_probability,
        per_watcher_discovery_probability=scenario.per_watcher_discovery_probability,
        per_watcher_challenge_probability=scenario.per_watcher_challenge_probability,
        declared_challenge_success_probability=scenario.challenge_success_probability,
        shared_outage_probability=scenario.shared_outage_probability,
        shared_infrastructure_failure_probability=scenario.shared_infrastructure_failure_probability,
        colluding_watchers=scenario.colluding_watchers,
        bonded_auditor_detection_probability=scenario.bonded_auditor_detection_probability,
        bonded_auditor_success_probability=scenario.bonded_auditor_success_probability,
        bonded_auditor_cost_micros=scenario.bonded_auditor_cost_micros,
        bonded_auditor_reward_micros=scenario.bonded_auditor_reward_micros,
        watcher_cost_micros_by_watcher=scenario.watcher_cost_micros_by_watcher,
        config_contract_hash=simulation_config_contract_hash(config),
        scenario_contract_hash=scenario_contract_hash(scenario),
        no_challenge_probability=no_challenge_probability,
        invalid_maturity_probability=invalid_maturity_probability,
        challenge_probability=challenge_probability,
        challenge_success_probability=challenge_success_probability,
        challenge_failure_probability=challenge_failure_probability,
        no_challenge_interval=_wilson_interval(no_challenge_count, config.simulations),
        invalid_maturity_interval=_wilson_interval(
            config.simulations - challenge_success_count, config.simulations
        ),
        challenge_success_interval=_wilson_interval(challenge_success_count, config.simulations),
        watcher_expected_utility_micros=str(_decimal_mean(watcher_utilities)),
        watcher_expected_utility_interval_micros=_bootstrap_decimal_interval(
            watcher_utilities,
            iterations=256,
            seed=config.seed + 1_001,
        ),
        bonded_auditor_expected_utility_micros=str(_decimal_mean(auditor_utilities)),
        bonded_auditor_expected_utility_interval_micros=_bootstrap_decimal_interval(
            auditor_utilities,
            iterations=256,
            seed=config.seed + 2_003,
        ),
        analytic_no_challenge_probability=analytic_no_challenge,
        analytic_invalid_maturity_probability=analytic_invalid_maturity,
        convergence_reference=convergence_reference,
        convergence_delta=convergence_delta,
        assumption_ledger=_assumption_ledger(scenario),
        publication_scope=config.publication_scope,
    )


def assert_cli_authority_boundary(
    run_config: RunConfig,
    scope: E5ConfirmatoryScope,
) -> None:
    if run_config.experiment_id != "E5":
        raise AuthorityBoundaryError("E5 wrapper requires experiment_id E5")
    if run_config.origin is not scope.required_run_origin:
        raise AuthorityBoundaryError("E5 publication CLI is reserved for REPRODUCIBLE_SIMULATION runs")
    if run_config.authorization_scope != scope.required_run_authorization_scope:
        raise AuthorityBoundaryError(
            "E5 publication CLI requires PUBLICATION_EVIDENCE_AUTHORIZED authorization_scope"
        )
    raise AuthorityBoundaryError(
        "explicit publication freeze and artifact routing remain manual for E5; "
        "validated reproducible-simulation authority but will not auto-run publication artifacts"
    )
