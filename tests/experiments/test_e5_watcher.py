from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import subprocess

import pytest

from poi_mpp.auditor.availability import ModelAssumptionError
from poi_mpp.evidence.config import approved_schema_hash
from poi_mpp.evidence.models import EvidenceOrigin


def _scenario(**overrides):
    from poi_mpp.experiments.e5_watcher import (
        WatcherAssumption,
        WatcherCorrelationModel,
        WatcherScenario,
    )

    payload = {
        "scenario_id": "independent-0001",
        "family": "INDEPENDENT",
        "assumption_label": WatcherAssumption.INDEPENDENT_WATCHERS_DECLARED,
        "correlation_model": WatcherCorrelationModel.INDEPENDENT,
        "watcher_count": 4,
        "fraud_value_micros": 2_000_000,
        "watch_cost_micros": 10_000,
        "challenge_bond_micros": 100_000,
        "challenge_reward_micros": 250_000,
        "challenge_subsidy_micros": 0,
        "attacker_bribe_micros": 0,
        "per_watcher_online_probability": 1.0,
        "per_watcher_discovery_probability": 0.5,
        "per_watcher_challenge_probability": 0.5,
        "challenge_success_probability": 0.8,
        "shared_outage_probability": 0.0,
        "shared_infrastructure_failure_probability": 0.0,
        "colluding_watchers": 0,
        "bonded_auditor_detection_probability": 0.0,
        "bonded_auditor_success_probability": 0.0,
        "bonded_auditor_cost_micros": 0,
        "bonded_auditor_reward_micros": 0,
    }
    payload.update(overrides)
    return WatcherScenario.model_validate(payload)


def _run_config_text(
    *,
    run_id: str,
    origin: str,
    authorization_scope: str,
) -> str:
    return "\n".join(
        [
            "schema_version: POI_MPP_RUN_CONFIG_V1",
            f"schema_hash: \"{approved_schema_hash()}\"",
            f"run_id: {run_id}",
            "experiment_id: E5",
            f"origin: {origin}",
            f"authorization_scope: {authorization_scope}",
            f"model_hash: \"{'1' * 64}\"",
            f"dataset_hash: \"{'2' * 64}\"",
            "parent_hashes: []",
            "data_availability:",
            "  total_shards: 16",
            "  samples: 8",
            "  replacement: false",
        ]
    )


def test_correlated_watchers_do_not_use_independent_closed_form():
    from poi_mpp.experiments.e5_watcher import (
        WatcherAssumption,
        WatcherCorrelationModel,
        independent_no_challenge_probability,
    )

    scenario = _scenario(
        scenario_id="correlated-0001",
        family="CORRELATED_OUTAGE",
        assumption_label=WatcherAssumption.CORRELATED_OUTAGE_DECLARED,
        correlation_model=WatcherCorrelationModel.CORRELATED_OUTAGE,
        shared_outage_probability=0.2,
    )

    with pytest.raises(ModelAssumptionError, match="independent"):
        independent_no_challenge_probability(scenario)


def test_negative_bond_is_rejected():
    with pytest.raises(ValueError, match="challenge_bond_micros"):
        _scenario(challenge_bond_micros=-1)


def test_independent_baseline_matches_closed_form_and_simulation_is_reproducible():
    from poi_mpp.experiments.e5_watcher import (
        E5SimulationConfig,
        independent_no_challenge_probability,
        run_watcher_scenario,
    )

    scenario = _scenario()
    expected = (1.0 - (1.0 * 0.5 * 0.5)) ** 4
    assert independent_no_challenge_probability(scenario) == pytest.approx(expected)

    config = E5SimulationConfig(simulations=4096, seed=17, origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION)
    first = run_watcher_scenario(run_id="run-e5", experiment_id="E5", scenario=scenario, config=config)
    second = run_watcher_scenario(run_id="run-e5", experiment_id="E5", scenario=scenario, config=config)

    assert first == second
    assert first.no_challenge_probability == pytest.approx(expected, abs=0.02)
    assert first.analytic_no_challenge_probability == pytest.approx(expected)
    assert first.currency_precision == "MICROS_DECIMAL"
    assert first.origin is EvidenceOrigin.REPRODUCIBLE_SIMULATION


def test_failed_challenges_reduce_expected_utility_when_bond_is_positive():
    from poi_mpp.experiments.e5_watcher import E5SimulationConfig, run_watcher_scenario

    shared = {
        "challenge_success_probability": 0.25,
        "per_watcher_online_probability": 1.0,
        "per_watcher_discovery_probability": 1.0,
        "per_watcher_challenge_probability": 1.0,
        "watch_cost_micros": 0,
    }
    zero_bond = _scenario(scenario_id="utility-zero-bond", challenge_bond_micros=0, **shared)
    positive_bond = _scenario(scenario_id="utility-positive-bond", challenge_bond_micros=400_000, **shared)

    config = E5SimulationConfig(simulations=4096, seed=5, origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION)
    zero_result = run_watcher_scenario(run_id="run-e5", experiment_id="E5", scenario=zero_bond, config=config)
    positive_result = run_watcher_scenario(run_id="run-e5", experiment_id="E5", scenario=positive_bond, config=config)

    assert Decimal(positive_result.watcher_expected_utility_micros) < Decimal(
        zero_result.watcher_expected_utility_micros
    )


def test_bonded_auditor_backstop_reduces_invalid_maturity_probability():
    from poi_mpp.experiments.e5_watcher import (
        E5SimulationConfig,
        WatcherAssumption,
        WatcherCorrelationModel,
        run_watcher_scenario,
    )

    base = _scenario(
        scenario_id="shared-no-backstop",
        family="SHARED_INFRASTRUCTURE",
        assumption_label=WatcherAssumption.SHARED_INFRASTRUCTURE_DECLARED,
        correlation_model=WatcherCorrelationModel.SHARED_INFRASTRUCTURE,
        shared_infrastructure_failure_probability=0.4,
    )
    backstop = _scenario(
        scenario_id="shared-with-backstop",
        family="BONDED_AUDITOR",
        assumption_label=WatcherAssumption.BONDED_AUDITOR_BACKSTOP_DECLARED,
        correlation_model=WatcherCorrelationModel.SHARED_INFRASTRUCTURE,
        shared_infrastructure_failure_probability=0.4,
        bonded_auditor_detection_probability=0.9,
        bonded_auditor_success_probability=1.0,
        bonded_auditor_cost_micros=25_000,
        bonded_auditor_reward_micros=150_000,
    )

    config = E5SimulationConfig(simulations=4096, seed=11, origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION)
    base_result = run_watcher_scenario(run_id="run-e5", experiment_id="E5", scenario=base, config=config)
    backstop_result = run_watcher_scenario(run_id="run-e5", experiment_id="E5", scenario=backstop, config=config)

    assert backstop_result.invalid_maturity_probability < base_result.invalid_maturity_probability


def test_reporting_requires_unique_scenario_seed_pairs_and_marks_synthetic_rows_inconclusive():
    from poi_mpp.experiments.e5_watcher import E5SimulationConfig, run_watcher_scenario
    from poi_mpp.reporting.e5 import summarize_e5_rows, t10_rows

    reproducible = run_watcher_scenario(
        run_id="run-e5",
        experiment_id="E5",
        scenario=_scenario(scenario_id="report-1"),
        config=E5SimulationConfig(
            simulations=4096,
            seed=7,
            origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
            publication_scope="E5_CONFIRMATORY_PUBLICATION_V1",
        ),
    )
    synthetic = run_watcher_scenario(
        run_id="run-e5",
        experiment_id="E5",
        scenario=_scenario(scenario_id="report-2", fraud_value_micros=8_000_000),
        config=E5SimulationConfig(simulations=4096, seed=8, origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE),
    )

    table_rows = t10_rows((reproducible, synthetic))
    assert table_rows[0].watchers == 4
    assert table_rows[1].fraud_value_micros == 8_000_000

    summary = summarize_e5_rows((reproducible, synthetic))
    assert summary.claim_disposition == "INCONCLUSIVE"

    with pytest.raises(ValueError, match="unique scenario_id"):
        summarize_e5_rows((reproducible, reproducible))


def test_publication_support_requires_exact_scope_reproducible_origin_and_contract_hashes():
    from poi_mpp.experiments.e5_watcher import E5SimulationConfig, run_watcher_scenario
    from poi_mpp.reporting.e5 import publication_precheck_reasons, summarize_e5_rows

    first = run_watcher_scenario(
        run_id="run-e5",
        experiment_id="E5",
        scenario=_scenario(scenario_id="pub-1"),
        config=E5SimulationConfig(
            simulations=4096,
            seed=17,
            origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
            publication_scope="E5_CONFIRMATORY_PUBLICATION_V1",
        ),
    )
    second = run_watcher_scenario(
        run_id="run-e5",
        experiment_id="E5",
        scenario=_scenario(scenario_id="pub-2", fraud_value_micros=9_000_000),
        config=E5SimulationConfig(
            simulations=4096,
            seed=19,
            origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
            publication_scope="E5_CONFIRMATORY_PUBLICATION_V1",
        ),
    )

    supported = summarize_e5_rows((first, second))
    assert supported.claim_disposition == "SUPPORTED"
    assert publication_precheck_reasons((first, second)) == ()

    wrong_scope = run_watcher_scenario(
        run_id="run-e5",
        experiment_id="E5",
        scenario=_scenario(scenario_id="pub-3", fraud_value_micros=5_000_000),
        config=E5SimulationConfig(
            simulations=4096,
            seed=23,
            origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
            publication_scope="WRONG_SCOPE",
        ),
    )
    assert summarize_e5_rows((first, wrong_scope)).claim_disposition == "INCONCLUSIVE"
    assert publication_precheck_reasons((first, wrong_scope))

    forged_hash = second.model_copy(update={"scenario_contract_hash": "0" * 64})
    with pytest.raises(ValueError, match="scenario_contract_hash"):
        summarize_e5_rows((first, forged_hash))


def test_duplicate_scenario_ids_do_not_count_as_distinct_confirmatory_scenarios():
    from poi_mpp.experiments.e5_watcher import E5SimulationConfig, run_watcher_scenario
    from poi_mpp.reporting.e5 import summarize_e5_rows

    first = run_watcher_scenario(
        run_id="run-e5",
        experiment_id="E5",
        scenario=_scenario(scenario_id="replicate"),
        config=E5SimulationConfig(
            simulations=4096,
            seed=3,
            origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
            publication_scope="E5_CONFIRMATORY_PUBLICATION_V1",
        ),
    )
    replicate = run_watcher_scenario(
        run_id="run-e5",
        experiment_id="E5",
        scenario=_scenario(scenario_id="replicate"),
        config=E5SimulationConfig(
            simulations=4096,
            seed=4,
            origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
            publication_scope="E5_CONFIRMATORY_PUBLICATION_V1",
        ),
    )

    with pytest.raises(ValueError, match="unique scenario_id"):
        summarize_e5_rows((first, replicate))


def test_bribery_requires_declared_recipients_and_changes_modeled_economics():
    from poi_mpp.experiments.e5_watcher import (
        E5SimulationConfig,
        WatcherAssumption,
        WatcherCorrelationModel,
        run_watcher_scenario,
    )

    with pytest.raises(ValueError, match="colluding_watchers > 0"):
        _scenario(
            scenario_id="bad-bribe",
            family="BRIBERY_SUBSIDY",
            assumption_label=WatcherAssumption.BRIBERY_SUBSIDY_DECLARED,
            correlation_model=WatcherCorrelationModel.COLLUSION,
            attacker_bribe_micros=50_000,
            colluding_watchers=0,
        )

    collusion = _scenario(
        scenario_id="plain-collusion",
        family="COLLUSION",
        assumption_label=WatcherAssumption.COLLUSION_DECLARED,
        correlation_model=WatcherCorrelationModel.COLLUSION,
        colluding_watchers=2,
        per_watcher_online_probability=1.0,
        per_watcher_discovery_probability=1.0,
        per_watcher_challenge_probability=1.0,
        challenge_success_probability=1.0,
        watch_cost_micros=0,
    )
    bribed = _scenario(
        scenario_id="bribed-collusion",
        family="BRIBERY_SUBSIDY",
        assumption_label=WatcherAssumption.BRIBERY_SUBSIDY_DECLARED,
        correlation_model=WatcherCorrelationModel.COLLUSION,
        colluding_watchers=2,
        attacker_bribe_micros=50_000,
        challenge_subsidy_micros=25_000,
        per_watcher_online_probability=1.0,
        per_watcher_discovery_probability=1.0,
        per_watcher_challenge_probability=1.0,
        challenge_success_probability=1.0,
        watch_cost_micros=0,
    )
    config = E5SimulationConfig(simulations=4096, seed=29, origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION)
    collusion_result = run_watcher_scenario(
        run_id="run-e5",
        experiment_id="E5",
        scenario=collusion,
        config=config,
    )
    bribed_result = run_watcher_scenario(
        run_id="run-e5",
        experiment_id="E5",
        scenario=bribed,
        config=config,
    )

    assert Decimal(bribed_result.watcher_expected_utility_micros) > Decimal(
        collusion_result.watcher_expected_utility_micros
    )


def test_cli_validates_confirmatory_scope_then_stops_before_auto_publication(tmp_path: Path):
    repo = Path("/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts")
    config_path = tmp_path / "e5.yaml"
    config_path.write_text(
        _run_config_text(
            run_id="run-e5-cli",
            origin="REPRODUCIBLE_SIMULATION",
            authorization_scope="PUBLICATION_EVIDENCE_AUTHORIZED",
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(repo / ".venv/bin/python"),
            str(repo / "experiments/e5_watcher_economics.py"),
            "--config",
            str(config_path),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    combined = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode != 0
    assert "explicit publication freeze and artifact routing remain manual for E5" in combined
    assert "schema_hash" not in combined
