from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from poi_mpp.evidence.config import approved_schema_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.evidence.provenance import EnvironmentManifest
from poi_mpp.experiments.e6_sybil import E6SimulationConfig, run_sybil_scenario


REPO_ROOT = Path(
    "/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts"
)
CONFIG_ROOT = REPO_ROOT / "configs" / "publication_simulation"
CONTRACT_PATH = REPO_ROOT / "configs" / "confirmatory" / "e6.yaml"


def _load_cli_module():
    module_path = REPO_ROOT / "experiments" / "e6_sybil_economics.py"
    spec = importlib.util.spec_from_file_location("e6_publication_cli", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_run_config(path: Path, *, origin: str = EvidenceOrigin.REPRODUCIBLE_SIMULATION.value) -> None:
    path.write_text(
        "\n".join(
            [
                "schema_version: POI_MPP_RUN_CONFIG_V1",
                f"schema_hash: \"{approved_schema_hash()}\"",
                "run_id: test-e6-publication",
                "experiment_id: E6",
                f"origin: {origin}",
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


def test_tracked_e6_publication_inputs_close_over_contract_and_plan() -> None:
    module = _load_cli_module()
    run_config = module.load_run_config(CONFIG_ROOT / "e6.run.yaml")
    contract = module.load_e6_confirmatory_contract(CONTRACT_PATH)
    plan = module.load_e6_publication_plan(CONFIG_ROOT / "e6.scenarios.yaml")

    assert run_config.origin is EvidenceOrigin.REPRODUCIBLE_SIMULATION
    assert run_config.authorization_scope == "PUBLICATION_EVIDENCE_AUTHORIZED"
    assert run_config.model_hash == module.e6_model_hash(contract)
    assert run_config.dataset_hash == module.e6_dataset_hash(plan)
    contract_hashes = {item.scenario_id: item.scenario_contract_hash for item in contract.allowed_scenarios}
    plan_hashes = {entry.scenario.scenario_id: module.scenario_contract_hash(entry.scenario) for entry in plan.entries}
    assert contract_hashes == plan_hashes


def test_run_publication_e6_requires_explicit_publication_authorization(tmp_path: Path) -> None:
    module = _load_cli_module()
    with pytest.raises(SystemExit, match="publication-authorized"):
        module.run_publication_e6(
            run_config_path=CONFIG_ROOT / "e6.run.yaml",
            contract_path=CONTRACT_PATH,
            plan_path=CONFIG_ROOT / "e6.scenarios.yaml",
            output_root=tmp_path / "out",
            publication_authorized=False,
        )


def test_run_publication_e6_rejects_synthetic_origin(tmp_path: Path) -> None:
    module = _load_cli_module()
    run_config_path = tmp_path / "run.yaml"
    _write_run_config(run_config_path, origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value)

    with pytest.raises(SystemExit, match="REPRODUCIBLE_SIMULATION|synthetic"):
        module.run_publication_e6(
            run_config_path=run_config_path,
            contract_path=CONTRACT_PATH,
            plan_path=CONFIG_ROOT / "e6.scenarios.yaml",
            output_root=tmp_path / "out",
            publication_authorized=True,
        )


def test_run_publication_e6_writes_rows_summary_and_registry(tmp_path: Path) -> None:
    module = _load_cli_module()
    plan = module.load_e6_publication_plan(CONFIG_ROOT / "e6.scenarios.yaml")
    run_config = module.load_run_config(CONFIG_ROOT / "e6.run.yaml")

    rows = tuple(
        run_sybil_scenario(
            run_id=run_config.run_id,
            experiment_id="E6",
            run_config=run_config,
            scenario=entry.scenario,
            config=E6SimulationConfig(
                simulations=1024,
                seed=entry.required_seed,
                origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
                publication_scope="E6_CONFIRMATORY_PUBLICATION_V1",
            ),
        )
        for entry in plan.entries
    )

    class FakeRegistry:
        def __init__(self, root: str | Path) -> None:
            self.root = Path(root)
            self.closed = False

        def write_atomic(self, record: object, *, provenance_bundle: object | None = None) -> Path:
            target = self.root / "E6-SUMMARY.frozen.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
            return target

        def close(self) -> None:
            self.closed = True

    def fake_environment_collector(**_: object) -> EnvironmentManifest:
        return EnvironmentManifest(
            python_implementation="CPython",
            python_version="3.11.15",
            os_name="Linux",
            os_release="test",
            machine="x86_64",
            cpu_model=None,
            gpu_model=None,
            package_lock_hash="c" * 64,
            compiler_version=None,
            foundry_version=None,
            code_revision="d" * 40,
        )

    result = module.run_publication_e6(
        run_config_path=CONFIG_ROOT / "e6.run.yaml",
        contract_path=CONTRACT_PATH,
        plan_path=CONFIG_ROOT / "e6.scenarios.yaml",
        output_root=tmp_path / "out",
        publication_authorized=True,
        environment_collector=fake_environment_collector,
        registry_factory=FakeRegistry,
        rows_builder=lambda **_: rows,
    )

    assert result.rows_path.is_file()
    assert result.summary_path.is_file()
    assert result.metadata_path.is_file()
    assert result.summary.claim_id == "C6"
    assert result.summary.claim_disposition in {"SUPPORTED", "INCONCLUSIVE"}
    assert result.registry.closed is True
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["frozen_artifact_path"] == "E6-SUMMARY.frozen.json"
    assert str(tmp_path) not in json.dumps(metadata)
