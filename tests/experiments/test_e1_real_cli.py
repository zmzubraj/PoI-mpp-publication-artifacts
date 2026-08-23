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
from poi_mpp.protocol.types import TaskClass
from poi_mpp.protocol.types import TaskSpec
from poi_mpp.worker import DeterministicDecodePolicy, PinnedModelManifest


def _load_cli_module():
    repo = Path("/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts")
    module_path = repo / "experiments" / "e1_single_pass_cost.py"
    spec = importlib.util.spec_from_file_location("e1_single_pass_cost_cli", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _task_document() -> dict[str, object]:
    return {
        "task_id": 11,
        "task_root": "0xaa" + "11" * 31,
        "worker_id": "0x0000000000000000000000000000000000002011",
        "task_class": TaskClass.CONSENSUS.value,
        "active": True,
        "registered": True,
        "credit_budget": 90,
        "epoch": 7,
        "deadline": 500,
        "commitment_height": 120,
        "commitment_finality_depth": 5,
        "challenge_window_blocks": 9,
        "audit_domain_size": 16,
    }


def _manifest() -> PinnedModelManifest:
    return PinnedModelManifest(
        model_id="local-qwen-1.5b",
        repository="Qwen/Qwen2.5-1.5B-Instruct",
        revision="9" * 40,
        tokenizer_id="Qwen/Qwen2.5-1.5B-Instruct",
        tokenizer_revision="9" * 40,
        license_id="apache-2.0",
        parameter_scale="1.5B",
        precision="int4",
        quantization="q4_k_m",
        runtime_name="transformers",
        runtime_version="4.44.0",
        model_file_hashes={
            "POI_MODEL_REVISION.json": "1" * 64,
            "model.safetensors": "2" * 64,
        },
        tokenizer_file_hashes={
            "POI_MODEL_REVISION.json": "1" * 64,
            "tokenizer.json": "3" * 64,
        },
    )


def _write_yaml(path: Path, payload: dict[str, object]) -> None:
    import yaml

    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_config(
    path: Path,
    *,
    model_hash: str,
    origin: str = EvidenceOrigin.REAL_MODEL_EXECUTION.value,
    authorization_scope: str = "PUBLICATION_EVIDENCE_AUTHORIZED",
) -> None:
    _write_yaml(
        path,
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": "run-real-e1",
            "experiment_id": "E1",
            "origin": origin,
            "authorization_scope": authorization_scope,
            "model_hash": model_hash,
            "dataset_hash": "b" * 64,
            "parent_hashes": [],
            "data_availability": {
                "total_shards": 8,
                "samples": 2,
                "replacement": False,
            },
        },
    )


def test_run_real_e1_requires_explicit_publication_authorization(tmp_path: Path) -> None:
    module = _load_cli_module()
    manifest = _manifest()
    policy = DeterministicDecodePolicy(seed=7, max_new_tokens=24)
    config_path = tmp_path / "run.yaml"
    task_path = tmp_path / "task.yaml"
    manifest_path = tmp_path / "manifest.yaml"
    _write_config(config_path, model_hash=manifest.manifest_hash(policy).removeprefix("0x"))
    _write_yaml(task_path, _task_document())
    _write_yaml(manifest_path, manifest.model_dump(mode="json"))

    with pytest.raises(SystemExit, match="publication-authorized"):
        module.run_real_e1(
            config_path=config_path,
            task_path=task_path,
            model_manifest_path=manifest_path,
            model_path=tmp_path / "model",
            output_root=tmp_path / "out",
            publication_authorized=False,
            runner_factory=lambda **_: None,
        )


def test_run_real_e1_rejects_model_hash_mismatch_before_runner_execution(tmp_path: Path) -> None:
    module = _load_cli_module()
    manifest = _manifest()
    config_path = tmp_path / "run.yaml"
    task_path = tmp_path / "task.yaml"
    manifest_path = tmp_path / "manifest.yaml"
    _write_config(config_path, model_hash="0" * 64)
    _write_yaml(task_path, _task_document())
    _write_yaml(manifest_path, manifest.model_dump(mode="json"))

    def unexpected_runner(**_: object) -> object:
        raise AssertionError("runner_factory should not be called when model_hash is mismatched")

    with pytest.raises(SystemExit, match="run_config.model_hash"):
        module.run_real_e1(
            config_path=config_path,
            task_path=task_path,
            model_manifest_path=manifest_path,
            model_path=tmp_path / "model",
            output_root=tmp_path / "out",
            publication_authorized=True,
            runner_factory=unexpected_runner,
        )


def test_run_real_e1_rejects_dataset_hash_mismatch_before_runner_execution(tmp_path: Path) -> None:
    module = _load_cli_module()
    manifest = _manifest()
    policy = DeterministicDecodePolicy(seed=7, max_new_tokens=24)
    config_path = tmp_path / "run.yaml"
    task_path = tmp_path / "task.yaml"
    manifest_path = tmp_path / "manifest.yaml"
    _write_config(config_path, model_hash=manifest.manifest_hash(policy).removeprefix("0x"))
    _write_yaml(task_path, _task_document())
    _write_yaml(manifest_path, manifest.model_dump(mode="json"))
    def unexpected_runner(**_: object) -> object:
        raise AssertionError("runner must not execute")

    with pytest.raises(SystemExit, match="dataset_hash"):
        module.run_real_e1(
            config_path=config_path,
            task_path=task_path,
            model_manifest_path=manifest_path,
            model_path=tmp_path / "model",
            output_root=tmp_path / "out",
            publication_authorized=True,
            warmup_pairs=1,
            runner_factory=unexpected_runner,
        )


def test_run_real_e1_wires_runner_provenance_and_registry(tmp_path: Path) -> None:
    module = _load_cli_module()
    manifest = _manifest()
    policy = DeterministicDecodePolicy(seed=7, max_new_tokens=24)
    config_path = tmp_path / "run.yaml"
    task_path = tmp_path / "task.yaml"
    manifest_path = tmp_path / "manifest.yaml"
    _write_config(config_path, model_hash=manifest.manifest_hash(policy).removeprefix("0x"))
    _write_yaml(task_path, _task_document())
    _write_yaml(manifest_path, manifest.model_dump(mode="json"))
    task = TaskSpec.model_validate(_task_document())
    config = __import__("yaml").safe_load(config_path.read_text(encoding="utf-8"))
    config["dataset_hash"] = module.e1_dataset_hash(task, policy)
    _write_yaml(config_path, config)

    captures: dict[str, object] = {}

    class FakeRegistry:
        def __init__(self, root: str | Path) -> None:
            self.root = Path(root)
            self.closed = False

        def close(self) -> None:
            self.closed = True

    def fake_environment_collector(*, repo_root: Path, lock_path: Path) -> EnvironmentManifest:
        captures["repo_root"] = repo_root
        captures["lock_path"] = lock_path
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

    def fake_runner_factory(**kwargs: object) -> object:
        captures["runner_factory"] = kwargs
        return SimpleNamespace(kind="runner")

    def fake_experiment_runner(**kwargs: object) -> object:
        captures["experiment_runner"] = kwargs
        return SimpleNamespace(
            raw_rows_path=Path(kwargs["output_dir"]) / "rows.parquet",
            publication_decision=SimpleNamespace(
                completeness="INCOMPLETE",
                claim_disposition="INCONCLUSIVE",
            ),
            frozen_artifact_path=None,
        )

    result = module.run_real_e1(
        config_path=config_path,
        task_path=task_path,
        model_manifest_path=manifest_path,
        model_path=tmp_path / "model",
        tokenizer_path=tmp_path / "tokenizer",
        output_root=tmp_path / "out",
        publication_authorized=True,
        warmup_pairs=1,
        runner_factory=fake_runner_factory,
        environment_collector=fake_environment_collector,
        registry_factory=FakeRegistry,
        experiment_runner=fake_experiment_runner,
        repo_root=tmp_path / "repo",
        lock_path=tmp_path / "repo" / "requirements.lock",
    )

    assert result.raw_rows_path == tmp_path / "out" / "rows.parquet"
    assert captures["runner_factory"]["manifest"] == manifest
    assert captures["runner_factory"]["policy"] == policy
    assert captures["runner_factory"]["model_path"] == tmp_path / "model"
    assert captures["runner_factory"]["tokenizer_path"] == tmp_path / "tokenizer"
    assert captures["repo_root"] == tmp_path / "repo"
    assert captures["lock_path"] == tmp_path / "repo" / "requirements.lock"

    experiment_args = captures["experiment_runner"]
    assert experiment_args["runner"].kind == "runner"
    assert experiment_args["output_dir"] == tmp_path / "out"
    assert experiment_args["registry"].root == tmp_path / "out" / "registry"
    assert experiment_args["registry"].closed is True
    assert experiment_args["provenance_bundle"].manifest.run_id == "run-real-e1"
    assert experiment_args["provenance_bundle"].manifest.model_hash == manifest.manifest_hash(policy).removeprefix("0x")


def test_main_prints_gate_decision_claim_support(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _load_cli_module()
    manifest = _manifest()
    policy = DeterministicDecodePolicy(seed=7, max_new_tokens=24)
    config_path = tmp_path / "run.yaml"
    task_path = tmp_path / "task.yaml"
    manifest_path = tmp_path / "manifest.yaml"
    _write_config(config_path, model_hash=manifest.manifest_hash(policy).removeprefix("0x"))
    _write_yaml(task_path, _task_document())
    _write_yaml(manifest_path, manifest.model_dump(mode="json"))
    task = TaskSpec.model_validate(_task_document())
    config = __import__("yaml").safe_load(config_path.read_text(encoding="utf-8"))
    config["dataset_hash"] = module.e1_dataset_hash(task, policy)
    _write_yaml(config_path, config)

    def fake_run_real_e1(**_: object) -> object:
        return SimpleNamespace(
            raw_rows_path=tmp_path / "out" / "rows.parquet",
            publication_decision=SimpleNamespace(
                completeness="INCOMPLETE",
                claim_support="INCONCLUSIVE",
            ),
            frozen_artifact_path=tmp_path / "out" / "registry" / "frozen.json",
        )

    module.run_real_e1 = fake_run_real_e1
    module.main(
        [
            "--config",
            str(config_path),
            "--task",
            str(task_path),
            "--model-manifest",
            str(manifest_path),
            "--model-path",
            str(tmp_path / "model"),
            "--output-root",
            str(tmp_path / "out"),
            "--warmup-pairs",
            "1",
            "--publication-authorized",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["publication_completeness"] == "INCOMPLETE"
    assert payload["publication_claim_disposition"] == "INCONCLUSIVE"
    assert payload["raw_rows_path"] == "rows.parquet"
    assert payload["frozen_artifact_path"] == "frozen.json"
    assert str(tmp_path) not in json.dumps(payload)
