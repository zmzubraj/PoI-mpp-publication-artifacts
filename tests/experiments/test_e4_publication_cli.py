from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from poi_mpp.evidence.config import approved_schema_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.evidence.provenance import EnvironmentManifest


REPO_ROOT = Path(
    "/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts"
)
CONFIG_ROOT = REPO_ROOT / "configs" / "publication_simulation"
CONTRACT_PATH = REPO_ROOT / "configs" / "confirmatory" / "e4.publication.yaml"


def _load_cli_module():
    module_path = REPO_ROOT / "experiments" / "e4_da_withholding.py"
    spec = importlib.util.spec_from_file_location("e4_publication_cli", module_path)
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
                "run_id: test-e4-publication",
                "experiment_id: E4",
                f"origin: {origin}",
                "authorization_scope: PUBLICATION_EVIDENCE_AUTHORIZED",
                f"model_hash: \"{'1' * 64}\"",
                f"dataset_hash: \"{'2' * 64}\"",
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


def test_tracked_e4_publication_inputs_close_over_contract_and_plan() -> None:
    module = _load_cli_module()
    run_config = module.load_run_config(CONFIG_ROOT / "e4.run.yaml")
    contract = module.load_e4_publication_contract(CONTRACT_PATH)
    plan = module.load_e4_publication_plan(CONFIG_ROOT / "e4.scenarios.yaml")

    assert run_config.origin is EvidenceOrigin.REPRODUCIBLE_SIMULATION
    assert run_config.authorization_scope == "PUBLICATION_EVIDENCE_AUTHORIZED"
    assert run_config.model_hash == module.e4_model_hash(contract)
    assert run_config.dataset_hash == module.e4_dataset_hash(plan)
    assert any(entry.expected_row.interval_kind.value == "EXACT" for entry in plan.entries)
    assert any(entry.expected_row.interval_kind.value == "WILSON" for entry in plan.entries)


def test_run_publication_e4_requires_explicit_publication_authorization(tmp_path: Path) -> None:
    module = _load_cli_module()
    output_root = tmp_path / "out"

    with pytest.raises(SystemExit, match="publication-authorized"):
        module.run_publication_e4(
            config_path=CONFIG_ROOT / "e4.run.yaml",
            contract_path=CONTRACT_PATH,
            plan_path=CONFIG_ROOT / "e4.scenarios.yaml",
            output_root=output_root,
            publication_authorized=False,
        )


def test_run_publication_e4_rejects_synthetic_origin(tmp_path: Path) -> None:
    module = _load_cli_module()
    run_config_path = tmp_path / "run.yaml"
    _write_run_config(run_config_path, origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value)

    with pytest.raises(SystemExit, match="REPRODUCIBLE_SIMULATION"):
        module.run_publication_e4(
            config_path=run_config_path,
            contract_path=CONTRACT_PATH,
            plan_path=CONFIG_ROOT / "e4.scenarios.yaml",
            output_root=tmp_path / "out",
            publication_authorized=True,
        )


def test_declared_outcome_playback_writes_artifacts_but_cannot_support_c4(tmp_path: Path) -> None:
    module = _load_cli_module()
    captures: dict[str, object] = {}

    class FakeRegistry:
        def __init__(self, root: str | Path) -> None:
            self.root = Path(root)
            self.closed = False
            self.record = None

        def write_atomic(self, record: object, *, provenance_bundle: object | None = None) -> Path:
            self.record = (record, provenance_bundle)
            target = self.root / "E4-SUMMARY.frozen.json"
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

    result = module.run_publication_e4(
        config_path=CONFIG_ROOT / "e4.run.yaml",
        contract_path=CONTRACT_PATH,
        plan_path=CONFIG_ROOT / "e4.scenarios.yaml",
        output_root=tmp_path / "out",
        publication_authorized=True,
        environment_collector=fake_environment_collector,
        registry_factory=FakeRegistry,
    )

    assert result.rows_path.is_file()
    assert result.summary_path.is_file()
    assert result.metadata_path.is_file()
    assert result.registry.root == tmp_path / "out" / "registry"
    assert result.registry.closed is True
    assert result.summary.claim_id == "C4"
    assert all(row.expected_outcome_detected for row in result.rows)
    assert result.summary.claim_disposition == "INCONCLUSIVE"
    assert result.publication_record["claim_disposition"] == "INCONCLUSIVE"
    assert (
        result.publication_record["payload"]["claim_disposition_reason"]
        == "DECLARED_OUTCOME_PLAYBACK_NOT_EXECUTED_RECONSTRUCTION"
    )
    assert result.publication_decision.claim_support == "INCONCLUSIVE"
    assert (
        "DECLARED_OUTCOME_PLAYBACK_NOT_EXECUTED_RECONSTRUCTION"
        in result.publication_decision.reasons
    )

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["frozen_artifact_path"] == "E4-SUMMARY.frozen.json"
    assert str(tmp_path) not in json.dumps(metadata)
    assert metadata["method_boundary"] == "DECLARED_OUTCOME_PLAYBACK"
    assert (
        metadata["claim_disposition_reason"]
        == "DECLARED_OUTCOME_PLAYBACK_NOT_EXECUTED_RECONSTRUCTION"
    )
