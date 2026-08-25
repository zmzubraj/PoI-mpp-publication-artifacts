from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from poi_mpp.evidence.canonical import digest
from poi_mpp.experiments.e5_multiseed import (
    E5SourcePlan,
    execute_e5_multiseed,
    load_e5_multiseed_config,
)
from poi_mpp.experiments.e6_multiseed import (
    E6SourcePlan,
    execute_e6_multiseed,
    load_e6_multiseed_config,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
E5_CONFIG = REPO_ROOT / "configs" / "confirmatory" / "e5.multiseed.v2.yaml"
E6_CONFIG = REPO_ROOT / "configs" / "confirmatory" / "e6.multiseed.v2.yaml"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_yaml(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, default_flow_style=False, sort_keys=True),
        encoding="utf-8",
    )


def _copy_source_bundle(tmp_path: Path, source: Path) -> tuple[Path, dict[str, object]]:
    repo_root = tmp_path / "repo"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    for field_name in ("source_contract_path", "source_plan_path", "source_run_config_path"):
        relative = Path(payload[field_name])
        original = REPO_ROOT / relative
        copied = repo_root / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes(original.read_bytes())
        payload[field_name.replace("_path", "_sha256")] = _sha256(copied)
    config_path = repo_root / "configs" / "confirmatory" / source.name
    _canonical_yaml(config_path, payload)
    return config_path, payload


@pytest.mark.parametrize(
    ("config_path", "loader", "experiment_id", "scenario_count"),
    [
        (E5_CONFIG, load_e5_multiseed_config, "E5", 2),
        (E6_CONFIG, load_e6_multiseed_config, "E6", 6),
    ],
)
def test_tracked_multiseed_configs_are_canonical_and_hash_bound(
    config_path: Path,
    loader: object,
    experiment_id: str,
    scenario_count: int,
) -> None:
    config = loader(config_path)

    assert config.experiment_id == experiment_id
    assert config.evidence_origin == "REPRODUCIBLE_SIMULATION"
    assert config.claim_scope == "SCENARIO_SPECIFIC_SENSITIVITY_ONLY"
    assert config.failure_disposition == "INCONCLUSIVE"
    assert len(config.seeds) >= 3
    assert len(set(config.seeds)) == len(config.seeds)
    assert len(config.expected_scenario_ids) == scenario_count
    assert config.source_contract_sha256 == _sha256(config.source_contract_path)
    assert config.source_plan_sha256 == _sha256(config.source_plan_path)
    assert config.source_run_config_sha256 == _sha256(config.source_run_config_path)


@pytest.mark.parametrize(
    ("source", "loader"),
    [(E5_CONFIG, load_e5_multiseed_config), (E6_CONFIG, load_e6_multiseed_config)],
)
def test_multiseed_loader_rejects_noncanonical_yaml(tmp_path: Path, source: Path, loader: object) -> None:
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    target = tmp_path / source.name
    target.write_text("# noncanonical comment\n" + yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="canonical YAML"):
        loader(target, repo_root=REPO_ROOT)


@pytest.mark.parametrize(
    ("source", "loader"),
    [(E5_CONFIG, load_e5_multiseed_config), (E6_CONFIG, load_e6_multiseed_config)],
)
def test_multiseed_loader_rejects_tampered_source_hash(tmp_path: Path, source: Path, loader: object) -> None:
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["source_plan_sha256"] = "0" * 64
    target = tmp_path / source.name
    _canonical_yaml(target, payload)

    with pytest.raises(ValueError, match="source_plan_sha256 mismatch"):
        loader(target, repo_root=REPO_ROOT)


@pytest.mark.parametrize(
    ("source", "loader"),
    [(E5_CONFIG, load_e5_multiseed_config), (E6_CONFIG, load_e6_multiseed_config)],
)
def test_multiseed_loader_rejects_symlink_config(tmp_path: Path, source: Path, loader: object) -> None:
    link = tmp_path / source.name
    link.symlink_to(source)

    with pytest.raises(ValueError, match="symlink"):
        loader(link, repo_root=REPO_ROOT)


@pytest.mark.parametrize(
    ("source", "loader"),
    [(E5_CONFIG, load_e5_multiseed_config), (E6_CONFIG, load_e6_multiseed_config)],
)
def test_multiseed_loader_rejects_symlink_source(tmp_path: Path, source: Path, loader: object) -> None:
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    real_contract = REPO_ROOT / payload["source_contract_path"]
    linked_contract = tmp_path / "linked-contract.yaml"
    linked_contract.symlink_to(real_contract)
    payload["source_contract_path"] = str(linked_contract)
    target = tmp_path / source.name
    _canonical_yaml(target, payload)

    with pytest.raises(ValueError, match="symlink"):
        loader(target, repo_root=REPO_ROOT)


@pytest.mark.parametrize(
    ("source", "loader"),
    [(E5_CONFIG, load_e5_multiseed_config), (E6_CONFIG, load_e6_multiseed_config)],
)
def test_multiseed_loader_rejects_run_authorization_scope_drift(
    tmp_path: Path, source: Path, loader: object
) -> None:
    config_path, payload = _copy_source_bundle(tmp_path, source)
    repo_root = tmp_path / "repo"
    run_config_path = repo_root / payload["source_run_config_path"]
    run_config = yaml.safe_load(run_config_path.read_text(encoding="utf-8"))
    run_config["authorization_scope"] = "LOCAL_TEST_ONLY"
    _canonical_yaml(run_config_path, run_config)
    payload["source_run_config_sha256"] = _sha256(run_config_path)
    _canonical_yaml(config_path, payload)

    with pytest.raises(ValueError, match="authorization_scope"):
        loader(config_path, repo_root=repo_root)


@pytest.mark.parametrize(
    ("source", "loader", "plan_model", "digest_domain"),
    [
        (E5_CONFIG, load_e5_multiseed_config, E5SourcePlan, "E5_PUBLICATION_DATASET_HASH"),
        (E6_CONFIG, load_e6_multiseed_config, E6SourcePlan, "E6_PUBLICATION_DATASET_HASH"),
    ],
)
def test_multiseed_loader_rejects_source_plan_required_seed_drift(
    tmp_path: Path,
    source: Path,
    loader: object,
    plan_model: object,
    digest_domain: str,
) -> None:
    config_path, payload = _copy_source_bundle(tmp_path, source)
    repo_root = tmp_path / "repo"
    plan_path = repo_root / payload["source_plan_path"]
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    plan["entries"][0]["required_seed"] = 999
    _canonical_yaml(plan_path, plan)
    payload["source_plan_sha256"] = _sha256(plan_path)

    run_config_path = repo_root / payload["source_run_config_path"]
    run_config = yaml.safe_load(run_config_path.read_text(encoding="utf-8"))
    parsed_plan = plan_model.model_validate(plan)
    run_config["dataset_hash"] = digest(digest_domain, parsed_plan.model_dump(mode="json"))
    _canonical_yaml(run_config_path, run_config)
    payload["source_run_config_sha256"] = _sha256(run_config_path)
    _canonical_yaml(config_path, payload)

    with pytest.raises(ValueError, match="required_seed"):
        loader(config_path, repo_root=repo_root)


def test_e5_multiseed_replay_is_deterministic_and_preserves_scope(tmp_path: Path) -> None:
    first = execute_e5_multiseed(E5_CONFIG, tmp_path / "first.json")
    second = execute_e5_multiseed(E5_CONFIG, tmp_path / "second.json")

    assert first == second
    assert first["evidence_origin"] == "REPRODUCIBLE_SIMULATION"
    assert first["claim_scope"] == "SCENARIO_SPECIFIC_SENSITIVITY_ONLY"
    assert first["claim_disposition"] == "SENSITIVITY_ONLY_NO_CLAIM_UPGRADE"
    assert first["seed_denominator"] == len(first["seeds"])
    assert first["attempt_denominator"] == len(first["seeds"]) * 2
    assert first["failure_count"] == 0
    assert all(row["status"] == "COMPLETE" for row in first["seed_results"])
    assert all(row["raw_row_hash"] for row in first["seed_results"])
    assert all(row["raw_row"]["origin"] == "REPRODUCIBLE_SIMULATION" for row in first["seed_results"])
    assert first["artifact_hash"] == _sha256(tmp_path / "first.json")


def test_e6_multiseed_replay_is_deterministic_and_preserves_scope(tmp_path: Path) -> None:
    first = execute_e6_multiseed(E6_CONFIG, tmp_path / "first.json")
    second = execute_e6_multiseed(E6_CONFIG, tmp_path / "second.json")

    assert first == second
    assert first["evidence_origin"] == "REPRODUCIBLE_SIMULATION"
    assert first["claim_scope"] == "SCENARIO_SPECIFIC_SENSITIVITY_ONLY"
    assert first["claim_disposition"] == "SENSITIVITY_ONLY_NO_CLAIM_UPGRADE"
    assert first["seed_denominator"] == len(first["seeds"])
    assert first["attempt_denominator"] == len(first["seeds"]) * 6
    assert first["failure_count"] == 0
    assert all(row["status"] == "COMPLETE" for row in first["seed_results"])
    assert all(row["raw_row"]["origin"] == "REPRODUCIBLE_SIMULATION" for row in first["seed_results"])
    assert all(row["task_accounting_exact"] for row in first["seed_results"])
    assert all(row["credit_issuance_exact"] for row in first["seed_results"])
    assert all(row["budget_non_exceedance"] for row in first["seed_results"])
    assert all(row["zero_credit_implies_zero_weight"] for row in first["seed_results"])
    assert first["artifact_hash"] == _sha256(tmp_path / "first.json")


def test_multiseed_execution_records_failure_and_fails_closed(tmp_path: Path) -> None:
    calls = 0

    def failing_runner(**kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected seed failure")
        return kwargs["default_runner"](**kwargs["default_kwargs"])

    result = execute_e5_multiseed(E5_CONFIG, tmp_path / "failed.json", runner=failing_runner)

    assert result["failure_count"] == 1
    assert result["claim_disposition"] == "INCONCLUSIVE"
    assert any(row["status"] == "FAILED" for row in result["seed_results"])
    assert "injected seed failure" in result["failure_reasons"]


def test_multiseed_artifact_detects_byte_tamper(tmp_path: Path) -> None:
    result = execute_e6_multiseed(E6_CONFIG, tmp_path / "result.json")
    artifact_path = tmp_path / "result.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["failure_count"] = 999
    artifact_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    assert _sha256(artifact_path) != result["artifact_hash"]


@pytest.mark.parametrize(
    ("script_name", "config_path"),
    [
        ("e5_multiseed_sensitivity.py", E5_CONFIG),
        ("e6_multiseed_sensitivity.py", E6_CONFIG),
    ],
)
def test_multiseed_cli_requires_explicit_execute(
    tmp_path: Path, script_name: str, config_path: Path
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "experiments" / script_name),
            "--config",
            str(config_path),
            "--output",
            str(tmp_path / "result.json"),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--execute" in completed.stderr
    assert not (tmp_path / "result.json").exists()
