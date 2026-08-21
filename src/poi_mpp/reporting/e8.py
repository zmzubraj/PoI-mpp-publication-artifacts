"""Deterministic E8 reporting helpers for next-epoch committee simulation."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence.config import RunConfig, config_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e8_consensus import (
    COMMITTEE_ALGORITHM_VERSION,
    E8_CONFIRMATORY_SCOPE,
    E8ConfirmatoryContract,
    E8ScenarioRow,
    E8SeedPolicy,
    MAX_REPLAY_SIMULATIONS,
    MIN_SUPPORTED_SIMULATIONS,
    CommitteeScenarioRole,
    SamplingDisposition,
    pair_exogenous_hash,
    replay_row,
    scenario_from_row,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class T13Row(_FrozenModel):
    scenario_id: str
    role: str
    ablation: str
    sampling_disposition: str
    total_active_weight_micros: int = Field(ge=0)
    attacker_active_weight_micros: int = Field(ge=0)
    attacker_active_weight_share: float = Field(ge=0.0, le=1.0)
    max_operator_weight_share: float = Field(ge=0.0, le=1.0)
    attacker_weight_threshold_probability_ge_one_third: float | None = Field(default=None, ge=0.0, le=1.0)
    attacker_weight_threshold_probability_ge_two_thirds: float | None = Field(default=None, ge=0.0, le=1.0)
    attacker_seat_threshold_probability_ge_one_third: float | None = Field(default=None, ge=0.0, le=1.0)
    attacker_seat_threshold_probability_ge_two_thirds: float | None = Field(default=None, ge=0.0, le=1.0)
    estimated_attacker_cost_micros: str

    @field_validator("scenario_id", "role", "ablation", "sampling_disposition", "estimated_attacker_cost_micros")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("T13 text fields must not be blank")
        return value


class F11Point(_FrozenModel):
    scenario_id: str
    ablation: str
    estimand: str
    threshold: str
    probability: float = Field(ge=0.0, le=1.0)

    @field_validator("scenario_id", "ablation", "estimand", "threshold")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("F11 text fields must not be blank")
        return value


class E8Summary(_FrozenModel):
    schema_version: str = "POI_MPP_E8_SUMMARY_V1"
    claim_id: str
    denominator: int = Field(gt=0)
    scenario_count: int = Field(gt=0)
    support_row_count: int = Field(ge=0)
    negative_control_count: int = Field(ge=0)
    boundary_row_count: int = Field(ge=0)
    origins: tuple[str, ...]
    ablations: tuple[str, ...]
    assumption_ledger: tuple[str, ...]
    algorithm_version: str
    sampled_row_count: int = Field(ge=0)
    nonterminal_row_count: int = Field(ge=0)
    claim_disposition: str

    @field_validator("claim_id", "algorithm_version", "claim_disposition")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary text fields must not be blank")
        return value

    @model_validator(mode="after")
    def validate_counts(self) -> "E8Summary":
        if self.denominator != self.scenario_count:
            raise ValueError("denominator must equal scenario_count")
        total_roles = self.support_row_count + self.negative_control_count + self.boundary_row_count
        if total_roles != self.scenario_count:
            raise ValueError("row-role counts must sum to scenario_count")
        return self


def _revalidate_row(row: object) -> E8ScenarioRow:
    if isinstance(row, BaseModel):
        payload = row.model_dump(mode="json")
    elif isinstance(row, Mapping):
        payload = dict(row)
    else:
        payload = row
    try:
        return E8ScenarioRow.model_validate(payload)
    except Exception as error:
        raise ValueError("E8 row does not match canonical simulator replay") from error


def _row_payload(row: object) -> dict[str, object]:
    if isinstance(row, BaseModel):
        return row.model_dump(mode="python")
    if isinstance(row, Mapping):
        return dict(row)
    raise ValueError("E8 rows must be mappings or BaseModel instances")


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
    contract: E8ConfirmatoryContract | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    simulations = _payload_int(payload, "simulations")
    if simulations is None:
        raise ValueError("rows.simulations must be a plain integer")
    if simulations < MIN_SUPPORTED_SIMULATIONS:
        raise ValueError("rows.simulations cannot be below the E8 minimum")
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


def _authoritative_row(row: object) -> E8ScenarioRow:
    canonical = _revalidate_row(row)
    replayed = replay_row(canonical)
    if canonical.model_dump(mode="json") != replayed.model_dump(mode="json"):
        raise ValueError("E8 row does not match canonical simulator replay")
    return replayed


def publication_precheck_reasons(
    rows: tuple[E8ScenarioRow, ...] | list[E8ScenarioRow],
    *,
    contract: E8ConfirmatoryContract | None = None,
) -> tuple[str, ...]:
    if not rows:
        return ("E8 publication precheck requires at least one row",)
    reasons: list[str] = []
    raw_rows = tuple(_row_payload(row) for row in rows)
    for payload in raw_rows:
        reasons.extend(_precheck_row_contract(payload, contract=contract))
    if contract is None:
        reasons.append("E8 confirmatory contract is required for publication support")
        return tuple(dict.fromkeys(reasons))
    if reasons:
        return tuple(dict.fromkeys(reasons))

    canonical_rows = tuple(_authoritative_row(row) for row in rows)
    if len({row.scenario_id for row in canonical_rows}) != len(canonical_rows):
        raise ValueError("rows must use unique scenario_id values")
    if len({row.result_contract_hash for row in canonical_rows}) != len(canonical_rows):
        raise ValueError("rows must use unique result_contract_hash values")

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
    if any(row.committee_algorithm_version != contract.required_algorithm_version for row in canonical_rows):
        reasons.append("rows.committee_algorithm_version must exactly match the confirmatory contract")
    if any(row.committee_size != contract.required_committee_size for row in canonical_rows):
        reasons.append("rows.committee_size must exactly match the confirmatory contract")
    if any(row.target_epoch <= 0 for row in canonical_rows):
        reasons.append("rows.target_epoch must be positive for next-epoch simulation")

    contract_scenarios = {item.scenario_id: item for item in contract.allowed_scenarios}
    row_scenarios = {row.scenario_id: row for row in canonical_rows}
    if set(row_scenarios) != set(contract_scenarios):
        reasons.append("rows.scenario_id set must exactly close against the confirmatory contract")
    else:
        for scenario_id, row in row_scenarios.items():
            allowed = contract_scenarios[scenario_id]
            if row.scenario_contract_hash != allowed.scenario_contract_hash:
                reasons.append(f"scenario_contract_hash mismatch for {scenario_id}")
            if contract.seed_policy is E8SeedPolicy.FIXED_PER_SCENARIO and row.seed != allowed.required_seed:
                reasons.append(f"seed mismatch for {scenario_id}")
            if row.role is not allowed.required_role:
                reasons.append(f"role mismatch for {scenario_id}")
            if row.ablation is not allowed.required_ablation:
                reasons.append(f"ablation mismatch for {scenario_id}")
    return tuple(dict.fromkeys(reasons))


def t13_rows(rows: tuple[E8ScenarioRow, ...] | list[E8ScenarioRow]) -> tuple[T13Row, ...]:
    return tuple(
        T13Row(
            scenario_id=row.scenario_id,
            role=row.role.value,
            ablation=row.ablation.value,
            sampling_disposition=row.sampling_disposition.value,
            total_active_weight_micros=row.total_active_weight_micros,
            attacker_active_weight_micros=row.attacker_active_weight_micros,
            attacker_active_weight_share=row.attacker_active_weight_share,
            max_operator_weight_share=row.max_operator_weight_share,
            attacker_weight_threshold_probability_ge_one_third=row.attacker_weight_threshold_probability_ge_one_third,
            attacker_weight_threshold_probability_ge_two_thirds=row.attacker_weight_threshold_probability_ge_two_thirds,
            attacker_seat_threshold_probability_ge_one_third=row.attacker_seat_threshold_probability_ge_one_third,
            attacker_seat_threshold_probability_ge_two_thirds=row.attacker_seat_threshold_probability_ge_two_thirds,
            estimated_attacker_cost_micros=row.estimated_attacker_cost_micros,
        )
        for row in rows
    )


def f11_points(rows: tuple[E8ScenarioRow, ...] | list[E8ScenarioRow]) -> tuple[F11Point, ...]:
    points: list[F11Point] = []
    for row in rows:
        for estimand, threshold, probability in (
            ("ATTACKER_COMMITTEE_WEIGHT_SHARE", "GE_ONE_THIRD", row.attacker_weight_threshold_probability_ge_one_third),
            ("ATTACKER_COMMITTEE_WEIGHT_SHARE", "GE_TWO_THIRDS", row.attacker_weight_threshold_probability_ge_two_thirds),
            ("ATTACKER_COMMITTEE_SEAT_SHARE", "GE_ONE_THIRD", row.attacker_seat_threshold_probability_ge_one_third),
            ("ATTACKER_COMMITTEE_SEAT_SHARE", "GE_TWO_THIRDS", row.attacker_seat_threshold_probability_ge_two_thirds),
        ):
            if probability is None:
                continue
            points.append(
                F11Point(
                    scenario_id=row.scenario_id,
                    ablation=row.ablation.value,
                    estimand=estimand,
                    threshold=threshold,
                    probability=probability,
                )
            )
    return tuple(points)


def summarize_e8_rows(
    rows: tuple[E8ScenarioRow, ...] | list[E8ScenarioRow],
    *,
    contract: E8ConfirmatoryContract | None = None,
) -> E8Summary:
    canonical_rows = tuple(_authoritative_row(row) for row in rows)
    if len({row.scenario_id for row in canonical_rows}) != len(canonical_rows):
        raise ValueError("rows must use unique scenario_id values")
    reasons = publication_precheck_reasons(canonical_rows, contract=contract)
    support_row_count = sum(1 for row in canonical_rows if row.role is CommitteeScenarioRole.SUPPORT)
    negative_control_count = sum(1 for row in canonical_rows if row.role is CommitteeScenarioRole.NEGATIVE_CONTROL)
    boundary_row_count = sum(1 for row in canonical_rows if row.role is CommitteeScenarioRole.BOUNDARY)
    sampled_row_count = sum(1 for row in canonical_rows if row.sampling_disposition is SamplingDisposition.COMMITTEE_SAMPLED)
    nonterminal_row_count = len(canonical_rows) - sampled_row_count
    claim_disposition = "INCONCLUSIVE"
    if contract is not None and not reasons:
        assertion_failures: list[str] = []
        rows_by_id = {row.scenario_id: row for row in canonical_rows}
        for allowed in contract.allowed_scenarios:
            row = rows_by_id.get(allowed.scenario_id)
            if row is None:
                assertion_failures.append(f"missing scenario row for {allowed.scenario_id}")
                continue
            if row.scenario_contract_hash != allowed.scenario_contract_hash:
                assertion_failures.append(f"scenario hash mismatch for {allowed.scenario_id}")
                continue
            if allowed.required_role is CommitteeScenarioRole.SUPPORT:
                assert allowed.support_assertions is not None
                checks = (
                    (row.attacker_active_weight_share, allowed.support_assertions.max_attacker_active_weight_share, "attacker_active_weight_share"),
                    (
                        row.attacker_weight_threshold_probability_ge_one_third,
                        allowed.support_assertions.max_attacker_weight_probability_ge_one_third,
                        "attacker_weight_threshold_probability_ge_one_third",
                    ),
                    (
                        row.attacker_weight_threshold_probability_ge_two_thirds,
                        allowed.support_assertions.max_attacker_weight_probability_ge_two_thirds,
                        "attacker_weight_threshold_probability_ge_two_thirds",
                    ),
                    (
                        row.attacker_seat_threshold_probability_ge_one_third,
                        allowed.support_assertions.max_attacker_seat_probability_ge_one_third,
                        "attacker_seat_threshold_probability_ge_one_third",
                    ),
                    (
                        row.attacker_seat_threshold_probability_ge_two_thirds,
                        allowed.support_assertions.max_attacker_seat_probability_ge_two_thirds,
                        "attacker_seat_threshold_probability_ge_two_thirds",
                    ),
                )
                for measured, maximum, label in checks:
                    if measured is None or measured > maximum:
                        assertion_failures.append(f"{allowed.scenario_id} exceeds support point bound for {label}")
                interval_checks = (
                    (
                        row.attacker_weight_threshold_probability_ge_one_third_interval,
                        allowed.support_assertions.max_attacker_weight_probability_ge_one_third_upper_bound,
                        "attacker_weight_threshold_probability_ge_one_third_interval",
                    ),
                    (
                        row.attacker_weight_threshold_probability_ge_two_thirds_interval,
                        allowed.support_assertions.max_attacker_weight_probability_ge_two_thirds_upper_bound,
                        "attacker_weight_threshold_probability_ge_two_thirds_interval",
                    ),
                    (
                        row.attacker_seat_threshold_probability_ge_one_third_interval,
                        allowed.support_assertions.max_attacker_seat_probability_ge_one_third_upper_bound,
                        "attacker_seat_threshold_probability_ge_one_third_interval",
                    ),
                    (
                        row.attacker_seat_threshold_probability_ge_two_thirds_interval,
                        allowed.support_assertions.max_attacker_seat_probability_ge_two_thirds_upper_bound,
                        "attacker_seat_threshold_probability_ge_two_thirds_interval",
                    ),
                )
                for interval, maximum, label in interval_checks:
                    if interval is None or interval[1] > maximum:
                        assertion_failures.append(f"{allowed.scenario_id} exceeds support uncertainty bound for {label}")
            elif allowed.required_role is CommitteeScenarioRole.BOUNDARY:
                assert allowed.boundary_assertions is not None
                if row.sampling_disposition is not allowed.boundary_assertions.required_sampling_disposition:
                    assertion_failures.append(f"{allowed.scenario_id} violates required boundary disposition")
                if row.total_active_weight_micros != allowed.boundary_assertions.required_total_active_weight_micros:
                    assertion_failures.append(f"{allowed.scenario_id} violates required boundary total weight")
                if row.attacker_active_weight_micros != allowed.boundary_assertions.required_attacker_active_weight_micros:
                    assertion_failures.append(f"{allowed.scenario_id} violates required boundary attacker weight")
                if allowed.boundary_assertions.require_zero_credit_implies_zero_weight and not row.zero_credit_implies_zero_weight:
                    assertion_failures.append(f"{allowed.scenario_id} violates zero-credit-implies-zero-weight boundary")
            else:
                assert allowed.negative_assertions is not None
                pair = allowed.negative_assertions
                support_row = rows_by_id.get(pair.paired_support_scenario_id)
                if support_row is None:
                    assertion_failures.append(f"{allowed.scenario_id} is missing paired support row")
                    continue
                if support_row.scenario_contract_hash != pair.paired_support_scenario_hash:
                    assertion_failures.append(f"{allowed.scenario_id} paired support hash mismatch")
                    continue
                support_scenario = scenario_from_row(support_row)
                negative_scenario = scenario_from_row(row)
                if pair_exogenous_hash(support_scenario) != pair.required_pair_exogenous_hash:
                    assertion_failures.append(f"{allowed.scenario_id} paired support exogenous hash mismatch")
                if pair_exogenous_hash(negative_scenario) != pair.required_pair_exogenous_hash:
                    assertion_failures.append(f"{allowed.scenario_id} negative exogenous hash mismatch")
                if row.seed != support_row.seed:
                    assertion_failures.append(f"{allowed.scenario_id} does not preserve paired seed")
                if row.attacker_active_weight_share - support_row.attacker_active_weight_share < pair.min_attacker_active_weight_share_delta:
                    assertion_failures.append(f"{allowed.scenario_id} misses minimum attacker active-weight-share delta")
                delta_checks = (
                    (
                        row.attacker_weight_threshold_probability_ge_one_third_interval,
                        support_row.attacker_weight_threshold_probability_ge_one_third_interval,
                        pair.min_attacker_weight_probability_ge_one_third_lower_advantage,
                        "attacker_weight_threshold_probability_ge_one_third",
                    ),
                    (
                        row.attacker_weight_threshold_probability_ge_two_thirds_interval,
                        support_row.attacker_weight_threshold_probability_ge_two_thirds_interval,
                        pair.min_attacker_weight_probability_ge_two_thirds_lower_advantage,
                        "attacker_weight_threshold_probability_ge_two_thirds",
                    ),
                    (
                        row.attacker_seat_threshold_probability_ge_one_third_interval,
                        support_row.attacker_seat_threshold_probability_ge_one_third_interval,
                        pair.min_attacker_seat_probability_ge_one_third_lower_advantage,
                        "attacker_seat_threshold_probability_ge_one_third",
                    ),
                    (
                        row.attacker_seat_threshold_probability_ge_two_thirds_interval,
                        support_row.attacker_seat_threshold_probability_ge_two_thirds_interval,
                        pair.min_attacker_seat_probability_ge_two_thirds_lower_advantage,
                        "attacker_seat_threshold_probability_ge_two_thirds",
                    ),
                )
                for negative_interval, support_interval, minimum_delta, label in delta_checks:
                    if minimum_delta is None:
                        continue
                    if negative_interval is None or support_interval is None:
                        assertion_failures.append(f"{allowed.scenario_id} missing interval for paired negative assertion {label}")
                        continue
                    if negative_interval[0] - support_interval[1] < minimum_delta:
                        assertion_failures.append(f"{allowed.scenario_id} misses paired lower-bound advantage for {label}")

        if (
            len(canonical_rows) >= contract.minimum_scenario_breadth
            and negative_control_count >= contract.minimum_negative_controls
            and boundary_row_count >= contract.minimum_boundary_rows
            and not assertion_failures
        ):
            claim_disposition = "SUPPORTED"
    return E8Summary(
        claim_id="C13",
        denominator=len(canonical_rows),
        scenario_count=len(canonical_rows),
        support_row_count=support_row_count,
        negative_control_count=negative_control_count,
        boundary_row_count=boundary_row_count,
        origins=tuple(sorted({row.origin.value for row in canonical_rows})),
        ablations=tuple(sorted({row.ablation.value for row in canonical_rows})),
        assumption_ledger=tuple(
            sorted({entry for row in canonical_rows for entry in row.assumption_ledger})
        ),
        algorithm_version=COMMITTEE_ALGORITHM_VERSION,
        sampled_row_count=sampled_row_count,
        nonterminal_row_count=nonterminal_row_count,
        claim_disposition=claim_disposition,
    )
