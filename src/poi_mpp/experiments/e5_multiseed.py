"""Deterministic E5 multi-seed sensitivity execution without claim promotion."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from pydantic import Field
import yaml

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import load_run_config
from poi_mpp.experiments.e5_e6_multiseed import (
    CLAIM_SCOPE,
    NO_UPGRADE_DISPOSITION,
    FrozenModel,
    MultiSeedConfig,
    canonical_json_bytes,
    failure_text,
    load_canonical_multiseed_config,
    run_attempt,
    sha256_bytes,
    source_binding,
    write_sensitivity_artifact,
)
from poi_mpp.experiments.e5_watcher import (
    E5_CONFIRMATORY_SCOPE,
    E5_SIMULATION_MODEL_VERSION,
    E5SimulationConfig,
    WatcherScenario,
    load_e5_confirmatory_contract,
    run_watcher_scenario,
    scenario_contract_hash,
)


SCHEMA_VERSION = "POI_MPP_E5_MULTI_SEED_SENSITIVITY_V2"


class E5PlanEntry(FrozenModel):
    required_seed: int = Field(ge=0)
    scenario: WatcherScenario


class E5SourcePlan(FrozenModel):
    schema_version: str
    contract_path: str
    publication_scope: str
    simulations: int = Field(ge=1)
    required_model_version: str
    entries: tuple[E5PlanEntry, ...]


def _load_mapping(path: Path, *, label: str) -> dict[str, object]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"unable to load {label}: {path}") from error
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return dict(raw)


def load_e5_multiseed_config(
    path: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> MultiSeedConfig:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    config, _ = load_canonical_multiseed_config(
        path,
        repo_root=root,
        expected_experiment_id="E5",
        expected_schema_version=SCHEMA_VERSION,
    )
    contract = load_e5_confirmatory_contract(config.source_contract_path)
    plan_raw = _load_mapping(config.source_plan_path, label="E5 source plan")
    plan = E5SourcePlan.model_validate(plan_raw)
    run_config = load_run_config(config.source_run_config_path)

    if config.required_model_version != E5_SIMULATION_MODEL_VERSION:
        raise ValueError(f"required_model_version must equal {E5_SIMULATION_MODEL_VERSION}")
    if contract.required_model_version != config.required_model_version:
        raise ValueError("contract model version must match multi-seed config")
    if plan.required_model_version != config.required_model_version:
        raise ValueError("plan model version must match multi-seed config")
    if config.simulations_per_seed != contract.required_simulations or plan.simulations != contract.required_simulations:
        raise ValueError("simulations_per_seed must preserve the frozen confirmatory denominator")
    if plan.publication_scope != E5_CONFIRMATORY_SCOPE or contract.publication_scope != E5_CONFIRMATORY_SCOPE:
        raise ValueError("source scope must remain E5_CONFIRMATORY_PUBLICATION_V1")
    scenario_ids = tuple(entry.scenario.scenario_id for entry in plan.entries)
    if scenario_ids != config.expected_scenario_ids:
        raise ValueError("expected_scenario_ids must exactly preserve source-plan order")
    allowed = {item.scenario_id: item for item in contract.allowed_scenarios}
    if set(scenario_ids) != set(allowed):
        raise ValueError("source plan must exactly close against the frozen E5 contract")
    for entry in plan.entries:
        expected = allowed[entry.scenario.scenario_id]
        if scenario_contract_hash(entry.scenario) != expected.scenario_contract_hash:
            raise ValueError(f"scenario hash mismatch for {entry.scenario.scenario_id}")
        if entry.required_seed != expected.required_seed:
            raise ValueError(f"required_seed mismatch for {entry.scenario.scenario_id}")
    if any(seed in {item.required_seed for item in contract.allowed_scenarios} for seed in config.seeds):
        raise ValueError("sensitivity seeds must be distinct from frozen confirmatory seeds")
    if run_config.experiment_id != "E5" or run_config.origin.value != "REPRODUCIBLE_SIMULATION":
        raise ValueError("source run config must bind E5 REPRODUCIBLE_SIMULATION")
    if run_config.authorization_scope != contract.required_run_authorization_scope:
        raise ValueError("source run config authorization_scope mismatch")
    if run_config.model_hash != digest("E5_PUBLICATION_MODEL_HASH", contract.model_dump(mode="json")):
        raise ValueError("source run config model_hash does not bind the frozen E5 contract")
    if run_config.dataset_hash != digest("E5_PUBLICATION_DATASET_HASH", plan.model_dump(mode="json")):
        raise ValueError("source run config dataset_hash does not bind the frozen E5 plan")
    return config


def execute_e5_multiseed(
    config_path: str | Path,
    output_path: str | Path,
    *,
    repo_root: str | Path | None = None,
    runner: Callable[..., object] | None = None,
) -> dict[str, object]:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    config, config_hash = load_canonical_multiseed_config(
        config_path,
        repo_root=root,
        expected_experiment_id="E5",
        expected_schema_version=SCHEMA_VERSION,
    )
    load_e5_multiseed_config(config_path, repo_root=root)
    contract = load_e5_confirmatory_contract(config.source_contract_path)
    plan = E5SourcePlan.model_validate(_load_mapping(config.source_plan_path, label="E5 source plan"))
    run_config = load_run_config(config.source_run_config_path)

    results: list[dict[str, object]] = []
    failure_reasons: list[str] = []
    by_scenario: dict[str, list[dict[str, object]]] = {scenario_id: [] for scenario_id in config.expected_scenario_ids}
    for seed in config.seeds:
        for entry in plan.entries:
            kwargs = {
                "run_id": run_config.run_id,
                "experiment_id": "E5",
                "run_config": run_config,
                "scenario": entry.scenario,
                "config": E5SimulationConfig(
                    simulations=config.simulations_per_seed,
                    seed=seed,
                    origin=config.evidence_origin,
                    publication_scope=contract.publication_scope,
                ),
            }
            try:
                row = run_attempt(runner=runner, default_runner=run_watcher_scenario, default_kwargs=kwargs)
                row_payload = row.model_dump(mode="json")
                result = {
                    "scenario_id": entry.scenario.scenario_id,
                    "seed": seed,
                    "simulations": row.simulations,
                    "status": "COMPLETE",
                    "failure_reason": None,
                    "raw_row_hash": sha256_bytes(canonical_json_bytes(row_payload)),
                    "raw_row": row_payload,
                    "challenge_probability": row.challenge_probability,
                    "invalid_maturity_probability": row.invalid_maturity_probability,
                    "invalid_maturity_interval": list(row.invalid_maturity_interval),
                    "watcher_expected_utility_micros": row.watcher_expected_utility_micros,
                }
                by_scenario[entry.scenario.scenario_id].append(result)
            except Exception as error:
                reason = failure_text(error)
                failure_reasons.append(reason)
                result = {
                    "scenario_id": entry.scenario.scenario_id,
                    "seed": seed,
                    "simulations": config.simulations_per_seed,
                    "status": "FAILED",
                    "failure_reason": reason,
                    "raw_row_hash": None,
                    "raw_row": None,
                }
            results.append(result)

    summaries: list[dict[str, object]] = []
    for scenario_id in config.expected_scenario_ids:
        completed = by_scenario[scenario_id]
        summaries.append(
            {
                "scenario_id": scenario_id,
                "seed_denominator": len(config.seeds),
                "completed_seed_count": len(completed),
                "failed_seed_count": len(config.seeds) - len(completed),
                "invalid_maturity_min": min((float(row["invalid_maturity_probability"]) for row in completed), default=None),
                "invalid_maturity_max": max((float(row["invalid_maturity_probability"]) for row in completed), default=None),
                "challenge_probability_min": min((float(row["challenge_probability"]) for row in completed), default=None),
                "challenge_probability_max": max((float(row["challenge_probability"]) for row in completed), default=None),
            }
        )
    failure_count = len(failure_reasons)
    body: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": "E5",
        "evidence_origin": config.evidence_origin.value,
        "claim_scope": CLAIM_SCOPE,
        "claim_disposition": config.failure_disposition if failure_count else NO_UPGRADE_DISPOSITION,
        "scientific_limit": "Sensitivity across frozen scenarios and declared seeds only; no production or general economic claim.",
        "required_model_version": config.required_model_version,
        "seeds": list(config.seeds),
        "seed_denominator": len(config.seeds),
        "scenario_denominator": len(config.expected_scenario_ids),
        "attempt_denominator": len(config.seeds) * len(config.expected_scenario_ids),
        "completed_count": len(results) - failure_count,
        "failure_count": failure_count,
        "failure_reasons": failure_reasons,
        "seed_results": results,
        "scenario_summaries": summaries,
        **source_binding(config, config_hash=config_hash, run_config=run_config),
    }
    return write_sensitivity_artifact(output_path, body)
