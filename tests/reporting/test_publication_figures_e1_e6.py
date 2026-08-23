from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from poi_mpp.reporting.figures import figure_artifacts
from poi_mpp.reporting.load import LoadedBundle, LoadedExperiment


def _experiment(
    experiment_id: str,
    *,
    figure_ids: tuple[str, ...],
    points: tuple[dict[str, object], ...],
    origin: str,
    scope: str,
) -> LoadedExperiment:
    return LoadedExperiment(
        experiment_id=experiment_id,
        table_ids=(),
        figure_ids=figure_ids,
        claim_id=f"C-{experiment_id}",
        origin=origin,
        disposition="INCONCLUSIVE",
        scope=scope,
        maturity=origin,
        run_id=f"run-{experiment_id.lower()}",
        config_hash="a" * 64,
        source_hashes=("b" * 64,),
        table_rows=(),
        figure_points=points,
        summary={"claim_disposition": "INCONCLUSIVE"},
        sample_size=len(points),
        uncertainty=None,
        limits=("bounded publication slice",),
        omission_reason=None,
        input_entries=(),
        generated_outputs=(),
    )


def _bundle(*experiments: LoadedExperiment) -> LoadedBundle:
    return LoadedBundle(
        artifact_root=Path("/artifact-root"),
        output_root=Path("/output-root"),
        experiments=experiments,
        environment_hash="c" * 64,
        generator_source_closure_hash="d" * 64,
    )


def test_e1_and_e2_figures_are_deterministic_and_claim_neutral():
    e1 = _experiment(
        "E1",
        figure_ids=("F5",),
        origin="REAL_MODEL_EXECUTION",
        scope="E1_REAL_MODEL_PUBLICATION_V1",
        points=(
            {"pair_id": "pair-1", "variant": "MPP_SINGLE_PASS", "measured_ms": 8.0},
            {"pair_id": "pair-1", "variant": "TWO_RUN_BASELINE", "measured_ms": 12.5},
        ),
    )
    e2 = _experiment(
        "E2",
        figure_ids=("F6",),
        origin="REAL_MODEL_EXECUTION",
        scope="E2_REAL_MODEL_PUBLICATION_V1",
        points=(
            {
                "attack_family": "aggregate",
                "analysis_surface": "NARROW_SCOPE_PILOT",
                "exact_detected": 2,
                "empirical_detected": 1,
                "denominator": 4,
                "lower_ci": 0.30,
                "upper_ci": 0.95,
            },
        ),
    )

    first = figure_artifacts(_bundle(e1, e2))
    second = figure_artifacts(_bundle(e1, e2))

    assert first == second
    assert set(first) == {
        "figures/F5_single_pass_cost.svg",
        "figures/F5_single_pass_cost.json",
        "figures/F6_audit_soundness.svg",
        "figures/F6_audit_soundness.json",
    }
    f5 = first["figures/F5_single_pass_cost.svg"].decode()
    assert "REAL_MODEL_EXECUTION" in f5
    assert "scope=E1_REAL_MODEL_PUBLICATION_V1" in f5
    assert "INCONCLUSIVE" in f5
    assert "source_hashes:" in f5
    f6 = first["figures/F6_audit_soundness.svg"].decode()
    assert "NARROW_SCOPE_PILOT" in f6
    assert "scope=E2_REAL_MODEL_PUBLICATION_V1" in f6
    assert "INCONCLUSIVE" in f6
    f6_points = json.loads(first["figures/F6_audit_soundness.json"])
    assert f6_points[0]["denominator"] == 4
    assert f6_points[0]["overall_detection_rate"] == 0.75
    assert f6_points[0]["lower_ci"] == 0.30
    assert f6_points[0]["upper_ci"] == 0.95


def test_e4_and_e6_figures_follow_helper_point_contracts_without_e5_collision():
    e4 = _experiment(
        "E4",
        figure_ids=("F8",),
        origin="REPRODUCIBLE_SIMULATION",
        scope="E4_CONFIRMATORY_PUBLICATION_V1",
        points=(
            {
                "scenario_id": "withheld",
                "observation_key": "obs-1",
                "mode": "EXACT",
                "miss_probability": 0.25,
                "lower_bound": 0.25,
                "upper_bound": 0.25,
            },
        ),
    )
    e5 = _experiment(
        "E5",
        figure_ids=(),
        origin="REPRODUCIBLE_SIMULATION",
        scope="E5_CONFIRMATORY_PUBLICATION_V1",
        points=(
            {
                "scenario_id": "watcher",
                "fraud_value_micros": 100,
                "invalid_maturity_probability": 0.1,
                "lower_bound": 0.05,
                "upper_bound": 0.2,
            },
        ),
    )
    e6 = _experiment(
        "E6",
        figure_ids=("F9", "F10"),
        origin="REPRODUCIBLE_SIMULATION",
        scope="E6_CONFIRMATORY_PUBLICATION_V1",
        points=(
            {
                "scenario_id": "shared-1",
                "identities": 1,
                "capacity_model": "SHARED_CAPACITY",
                "normalized_expected_credit": 1.0,
            },
            {
                "scenario_id": "shared-4",
                "identities": 4,
                "capacity_model": "SHARED_CAPACITY",
                "normalized_expected_credit": 1.1,
            },
            {
                "scenario_id": "cost-4",
                "identities": 4,
                "capacity_model": "SHARED_CAPACITY",
                "target_weight_fraction": "1/3",
                "estimated_cost_to_target_weight_micros": "4200000",
            },
        ),
    )

    outputs = figure_artifacts(_bundle(e4, e5, e6))

    assert set(outputs) == {
        "figures/F8_da_withholding.svg",
        "figures/F8_da_withholding.json",
        "figures/F9_sybil_advantage.svg",
        "figures/F9_sybil_advantage.json",
        "figures/F10_economic_security.svg",
        "figures/F10_economic_security.json",
    }
    assert "REPRODUCIBLE_SIMULATION" in outputs["figures/F8_da_withholding.svg"].decode()
    assert "scope=E4_CONFIRMATORY_PUBLICATION_V1" in outputs["figures/F8_da_withholding.svg"].decode()
    assert "scope=E6_CONFIRMATORY_PUBLICATION_V1" in outputs["figures/F9_sybil_advantage.svg"].decode()
    assert "INCONCLUSIVE" in outputs["figures/F10_economic_security.svg"].decode()
    assert json.loads(outputs["figures/F9_sybil_advantage.json"])[-1]["identities"] == 4
    assert json.loads(outputs["figures/F10_economic_security.json"])[0]["target_weight_fraction"] == "1/3"
    assert not any("E5" in path or "watcher" in path for path in outputs)


def test_e2_summary_fallback_uses_combined_detection_count_not_ci_bound():
    experiment = _experiment(
        "E2",
        figure_ids=("F6",),
        origin="REAL_MODEL_EXECUTION",
        scope="E2_REAL_MODEL_PUBLICATION_V1",
        points=(),
    )
    experiment = replace(
        experiment,
        summary={
            "denominator": 4,
            "exact_detected": 2,
            "empirical_detected": 1,
            "confidence_interval": [0.30, 0.95],
            "claim_disposition": "INCONCLUSIVE",
        },
    )

    outputs = figure_artifacts(_bundle(experiment))
    points = json.loads(outputs["figures/F6_audit_soundness.json"])

    assert points == [
        {
            "analysis_surface": "SUPPORTED_AUDIT_SURFACES",
            "attack_family": "aggregate",
            "denominator": 4,
            "empirical_detected": 1,
            "exact_detected": 2,
            "lower_ci": 0.30,
            "overall_detection_rate": 0.75,
            "upper_ci": 0.95,
        }
    ]


def test_e2_zero_supported_denominator_emits_truthful_status_artifact():
    experiment = _experiment(
        "E2",
        figure_ids=("F6",),
        origin="REAL_MODEL_EXECUTION",
        scope="E2_REAL_MODEL_PUBLICATION_V1",
        points=(),
    )
    experiment = replace(
        experiment,
        summary={
            "denominator": 0,
            "exact_detected": 0,
            "empirical_detected": 0,
            "confidence_interval": [0.0, 1.0],
            "claim_disposition": "INCONCLUSIVE",
        },
    )

    outputs = figure_artifacts(_bundle(experiment))
    svg = outputs["figures/F6_audit_soundness.svg"].decode()

    assert "no supported audit-surface denominator" in svg
    assert "REAL_MODEL_EXECUTION" in svg
    assert "scope=E2_REAL_MODEL_PUBLICATION_V1" in svg
    assert "INCONCLUSIVE" in svg
    assert json.loads(outputs["figures/F6_audit_soundness.json"]) == []
