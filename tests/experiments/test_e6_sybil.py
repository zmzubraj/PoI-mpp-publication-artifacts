from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from poi_mpp.evidence.config import RunConfig, approved_schema_hash
from poi_mpp.evidence.models import EvidenceOrigin


def _run_config(
    *,
    run_id: str = "run-e6",
    experiment_id: str = "E6",
    origin: EvidenceOrigin = EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    authorization_scope: str = "PUBLICATION_EVIDENCE_AUTHORIZED",
) -> RunConfig:
    return RunConfig.model_validate(
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": run_id,
            "experiment_id": experiment_id,
            "origin": origin,
            "authorization_scope": authorization_scope,
            "model_hash": "3" * 64,
            "dataset_hash": "4" * 64,
            "parent_hashes": (),
            "data_availability": {
                "total_shards": 16,
                "samples": 8,
                "replacement": False,
            },
        }
    )


def _scenario(**overrides):
    from poi_mpp.experiments.e6_sybil import (
        SybilAssumption,
        SybilCapacityModel,
        SybilScenario,
        SybilScenarioRole,
    )

    payload = {
        "scenario_id": "support-capacity-committed-1",
        "group_id": "support-capacity-committed",
        "role": SybilScenarioRole.SUPPORT,
        "assumption_label": SybilAssumption.CAPACITY_NEUTRAL_OPERATOR_AGGREGATION_DECLARED,
        "capacity_model": SybilCapacityModel.CAPACITY_COMMITTED,
        "attacker_identity_count": 1,
        "attacker_total_capacity_units": 12,
        "attacker_success_probability": 0.65,
        "attacker_collateral_micros": 3_000_000,
        "attacker_identity_fixed_cost_micros": 20_000,
        "honest_operator_count": 5,
        "honest_capacity_units": 12,
        "honest_success_probability": 0.65,
        "honest_collateral_micros": 3_000_000,
        "task_count": 48,
        "task_credit_budget": 90,
        "beta_micros": 10_000,
        "concentration_cap_micros": 2_000_000,
        "capacity_cost_micros_per_unit": 25_000,
        "collateral_cost_multiplier_microx": 1_000_000,
        "capacity_subsidy_micros": 0,
        "target_weight_numerator": 1,
        "target_weight_denominator": 3,
    }
    payload.update(overrides)
    return SybilScenario.model_validate(payload)


def _write_contract(tmp_path: Path, rows, *, epsilon_sybil: float = 0.02):
    from poi_mpp.experiments.e6_sybil import E6_SIMULATION_MODEL_VERSION, load_e6_confirmatory_contract

    lines = [
        "schema_version: POI_MPP_E6_CONFIRMATORY_CONTRACT_V1",
        "publication_scope: E6_CONFIRMATORY_PUBLICATION_V1",
        "required_run_origin: REPRODUCIBLE_SIMULATION",
        "required_run_authorization_scope: PUBLICATION_EVIDENCE_AUTHORIZED",
        f"required_simulations: {rows[0].simulations}",
        "maximum_replay_simulations: 8192",
        f"required_model_version: {E6_SIMULATION_MODEL_VERSION}",
        f"epsilon_sybil: {epsilon_sybil}",
        "target_weight_numerator: 1",
        "target_weight_denominator: 3",
        "minimum_negative_controls: 2",
        "seed_policy: FIXED_PER_SCENARIO",
        "allowed_scenarios:",
    ]
    for row in rows:
        lines.extend(
            [
                f"  - scenario_id: {row.scenario_id}",
                f"    scenario_contract_hash: {row.scenario_contract_hash}",
                f"    required_role: {row.role.value}",
                f"    required_capacity_model: {row.capacity_model.value}",
                f"    required_seed: {row.seed}",
            ]
        )
    lines.extend(
        [
            "notes:",
            "  - test contract",
        ]
    )
    path = tmp_path / "e6.contract.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return load_e6_confirmatory_contract(path)


def _run_row(*, scenario, seed: int = 17, simulations: int = 1024, run_config: RunConfig | None = None):
    from poi_mpp.experiments.e6_sybil import E6SimulationConfig, run_sybil_scenario

    resolved_run_config = _run_config() if run_config is None else run_config
    return run_sybil_scenario(
        run_id=resolved_run_config.run_id,
        experiment_id="E6",
        run_config=resolved_run_config,
        scenario=scenario,
        config=E6SimulationConfig(
            simulations=simulations,
            seed=seed,
            origin=resolved_run_config.origin,
            publication_scope="E6_CONFIRMATORY_PUBLICATION_V1",
        ),
    )


def test_capacity_neutral_scheduler_preserves_operator_share_across_identity_splits():
    safe_one = _run_row(scenario=_scenario())
    safe_many = _run_row(
        scenario=_scenario(
            scenario_id="support-capacity-committed-64",
            attacker_identity_count=64,
        )
    )

    assert safe_one.attacker_expected_credit_micros == safe_many.attacker_expected_credit_micros
    assert safe_one.attacker_expected_weight_micros == safe_many.attacker_expected_weight_micros


def test_identity_uniform_scheduler_rewards_identity_splitting():
    from poi_mpp.reporting.e6 import summarize_e6_rows

    baseline = _run_row(
        scenario=_scenario(
            scenario_id="negative-identity-uniform-1",
            group_id="negative-identity-uniform",
            role="NEGATIVE_CONTROL",
            assumption_label="IDENTITY_PROPORTIONAL_SCHEDULER_DECLARED",
            capacity_model="IDENTITY_UNIFORM",
            attacker_identity_count=1,
        )
    )
    split = _run_row(
        scenario=_scenario(
            scenario_id="negative-identity-uniform-64",
            group_id="negative-identity-uniform",
            role="NEGATIVE_CONTROL",
            assumption_label="IDENTITY_PROPORTIONAL_SCHEDULER_DECLARED",
            capacity_model="IDENTITY_UNIFORM",
            attacker_identity_count=64,
        )
    )

    summary = summarize_e6_rows([baseline, split])
    assert summary.max_negative_control_upper_advantage > summary.epsilon_sybil
    assert summary.min_negative_control_lower_advantage > summary.epsilon_sybil


def test_collateral_rich_zero_credit_operator_stays_at_zero_weight():
    row = _run_row(
        scenario=_scenario(
            scenario_id="boundary-zero-credit-rich",
            group_id="boundary-zero-credit-rich",
            role="BOUNDARY",
            assumption_label="COLLATERAL_RICH_ZERO_CREDIT_DECLARED",
            attacker_identity_count=64,
            attacker_success_probability=0.0,
            attacker_collateral_micros=10_000_000_000,
        )
    )

    assert row.attacker_expected_credit_micros == "0.000000"
    assert row.attacker_expected_weight_micros == "0.000000"
    assert row.zero_credit_implies_zero_weight
    assert row.task_accounting_exact
    assert row.credit_issuance_exact
    assert row.budget_non_exceedance


def test_publication_support_requires_confirmatory_contract_and_replay_authority(tmp_path: Path):
    from poi_mpp.reporting.e6 import publication_precheck_reasons, summarize_e6_rows

    support_one = _run_row(scenario=_scenario())
    support_many = _run_row(
        scenario=_scenario(
            scenario_id="support-capacity-committed-64",
            attacker_identity_count=64,
        )
    )
    slot_one = _run_row(
        scenario=_scenario(
            scenario_id="support-operator-slot-1",
            group_id="support-operator-slot",
            capacity_model="OPERATOR_SLOT",
            assumption_label="CAPACITY_NEUTRAL_OPERATOR_AGGREGATION_DECLARED",
        )
    )
    slot_many = _run_row(
        scenario=_scenario(
            scenario_id="support-operator-slot-64",
            group_id="support-operator-slot",
            capacity_model="OPERATOR_SLOT",
            assumption_label="CAPACITY_NEUTRAL_OPERATOR_AGGREGATION_DECLARED",
            attacker_identity_count=64,
        )
    )
    negative_one = _run_row(
        scenario=_scenario(
            scenario_id="negative-identity-uniform-1",
            group_id="negative-identity-uniform",
            role="NEGATIVE_CONTROL",
            assumption_label="IDENTITY_PROPORTIONAL_SCHEDULER_DECLARED",
            capacity_model="IDENTITY_UNIFORM",
            attacker_identity_count=1,
        )
    )
    negative_many = _run_row(
        scenario=_scenario(
            scenario_id="negative-identity-uniform-64",
            group_id="negative-identity-uniform",
            role="NEGATIVE_CONTROL",
            assumption_label="IDENTITY_PROPORTIONAL_SCHEDULER_DECLARED",
            capacity_model="IDENTITY_UNIFORM",
            attacker_identity_count=64,
        )
    )
    rows = [support_one, support_many, slot_one, slot_many, negative_one, negative_many]

    assert "confirmatory contract" in publication_precheck_reasons(rows)[0].lower()
    contract = _write_contract(tmp_path, rows)
    assert summarize_e6_rows(rows, contract=contract).claim_disposition == "SUPPORTED"


def test_forged_output_is_rejected_by_publication_replay(tmp_path: Path):
    from poi_mpp.reporting.e6 import summarize_e6_rows

    baseline = _run_row(scenario=_scenario())
    split = _run_row(
        scenario=_scenario(
            scenario_id="support-capacity-committed-64",
            attacker_identity_count=64,
        )
    )
    slot_one = _run_row(
        scenario=_scenario(
            scenario_id="support-operator-slot-1",
            group_id="support-operator-slot",
            capacity_model="OPERATOR_SLOT",
            assumption_label="CAPACITY_NEUTRAL_OPERATOR_AGGREGATION_DECLARED",
        )
    )
    slot_many = _run_row(
        scenario=_scenario(
            scenario_id="support-operator-slot-64",
            group_id="support-operator-slot",
            capacity_model="OPERATOR_SLOT",
            assumption_label="CAPACITY_NEUTRAL_OPERATOR_AGGREGATION_DECLARED",
            attacker_identity_count=64,
        )
    )
    negative_one = _run_row(
        scenario=_scenario(
            scenario_id="negative-identity-uniform-1",
            group_id="negative-identity-uniform",
            role="NEGATIVE_CONTROL",
            assumption_label="IDENTITY_PROPORTIONAL_SCHEDULER_DECLARED",
            capacity_model="IDENTITY_UNIFORM",
            attacker_identity_count=1,
        )
    )
    negative_many = _run_row(
        scenario=_scenario(
            scenario_id="negative-identity-uniform-64",
            group_id="negative-identity-uniform",
            role="NEGATIVE_CONTROL",
            assumption_label="IDENTITY_PROPORTIONAL_SCHEDULER_DECLARED",
            capacity_model="IDENTITY_UNIFORM",
            attacker_identity_count=64,
        )
    )
    contract = _write_contract(
        tmp_path,
        [baseline, split, slot_one, slot_many, negative_one, negative_many],
    )
    forged = split.model_copy(
        update={
            "attacker_expected_credit_micros": "9999.000000",
            "result_contract_hash": split.result_contract_hash,
        }
    )

    with pytest.raises(ValueError, match="canonical simulator replay"):
        summarize_e6_rows([baseline, forged, slot_one, slot_many, negative_one, negative_many], contract=contract)


def test_duplicate_scenarios_do_not_inflate_confirmatory_breadth(tmp_path: Path):
    from poi_mpp.reporting.e6 import summarize_e6_rows

    baseline = _run_row(scenario=_scenario())
    duplicate = baseline.model_copy(update={"scenario_id": "support-capacity-committed-1"})

    with pytest.raises(ValueError, match="unique scenario_id"):
        summarize_e6_rows([baseline, duplicate])


def test_flat_negative_controls_do_not_support_confirmatory_publication(tmp_path: Path):
    from poi_mpp.reporting.e6 import summarize_e6_rows

    safe_negative_one = _run_row(
        scenario=_scenario(
            scenario_id="negative-flat-operator-slot-1",
            group_id="negative-flat-operator-slot",
            role="NEGATIVE_CONTROL",
            assumption_label="CAPACITY_NEUTRAL_OPERATOR_AGGREGATION_DECLARED",
            capacity_model="OPERATOR_SLOT",
            attacker_identity_count=1,
        )
    )
    safe_negative_many = _run_row(
        scenario=_scenario(
            scenario_id="negative-flat-operator-slot-64",
            group_id="negative-flat-operator-slot",
            role="NEGATIVE_CONTROL",
            assumption_label="CAPACITY_NEUTRAL_OPERATOR_AGGREGATION_DECLARED",
            capacity_model="OPERATOR_SLOT",
            attacker_identity_count=64,
        )
    )
    support_one = _run_row(scenario=_scenario())
    support_many = _run_row(
        scenario=_scenario(
            scenario_id="support-capacity-committed-64",
            attacker_identity_count=64,
        )
    )
    contract = _write_contract(tmp_path, [support_one, support_many, safe_negative_one, safe_negative_many])

    assert summarize_e6_rows(
        [support_one, support_many, safe_negative_one, safe_negative_many],
        contract=contract,
    ).claim_disposition == "INCONCLUSIVE"


def test_zero_success_accounting_distinguishes_exact_equality_from_utilization():
    row = _run_row(
        scenario=_scenario(
            scenario_id="boundary-zero-success-accounting",
            group_id="boundary-zero-success-accounting",
            role="BOUNDARY",
            assumption_label="COLLATERAL_RICH_ZERO_CREDIT_DECLARED",
            attacker_success_probability=0.0,
            honest_success_probability=0.0,
            attacker_collateral_micros=5_000_000_000,
        )
    )

    assert row.task_accounting_exact
    assert row.credit_issuance_exact
    assert row.budget_non_exceedance
    assert row.allocated_task_count_mean == "0.000000"
    assert row.unallocated_task_count_mean == "48.000000"
    assert row.allocated_credit_mean_micros == "0.000000"
    assert row.credit_utilization_ratio == 0.0


def test_cli_stops_at_publication_authority_boundary(tmp_path: Path):
    run_config_path = tmp_path / "run.yaml"
    run_config_path.write_text(
        "\n".join(
            [
                "schema_version: POI_MPP_RUN_CONFIG_V1",
                f"schema_hash: \"{approved_schema_hash()}\"",
                "run_id: run-e6-cli",
                "experiment_id: E6",
                "origin: REPRODUCIBLE_SIMULATION",
                "authorization_scope: PUBLICATION_EVIDENCE_AUTHORIZED",
                f"model_hash: \"{'3' * 64}\"",
                f"dataset_hash: \"{'4' * 64}\"",
                "parent_hashes: []",
                "data_availability:",
                "  total_shards: 16",
                "  samples: 8",
                "  replacement: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "./.venv/bin/python",
            "experiments/e6_sybil_economics.py",
            "--run-config",
            str(run_config_path),
            "--confirmatory-contract",
            "configs/confirmatory/e6.yaml",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "publication" in result.stderr.lower()
