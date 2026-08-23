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
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
from poi_mpp.worker.iec_schema import EvidenceItem
from poi_mpp.worker.inference import AdapterRunResult, execute_once
from poi_mpp.worker.model_manifest import PinnedModelManifest
from poi_mpp.worker.trace_schema import TraceEvent
from poi_mpp.worker.e2_tensor_capture import (
    TensorCaptureSpec,
    build_execution_audit_bundle,
    derive_tensor_product_capture,
)


def _load_cli_module():
    repo = Path("/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts")
    module_path = repo / "experiments" / "e2_tamper_detection.py"
    spec = importlib.util.spec_from_file_location("e2_tamper_detection_cli", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _task_document() -> dict[str, object]:
    return {
        "task_id": 22,
        "task_root": "0xaa" + "22" * 31,
        "worker_id": "0x0000000000000000000000000000000000002022",
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
        precision="bfloat16",
        quantization="none",
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
    dataset_hash: str,
    origin: str = EvidenceOrigin.REAL_MODEL_EXECUTION.value,
    authorization_scope: str = "PUBLICATION_EVIDENCE_AUTHORIZED",
) -> None:
    _write_yaml(
        path,
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": "run-real-e2",
            "experiment_id": "E2",
            "origin": origin,
            "authorization_scope": authorization_scope,
            "model_hash": model_hash,
            "dataset_hash": dataset_hash,
            "parent_hashes": [],
            "data_availability": {
                "total_shards": 8,
                "samples": 2,
                "replacement": False,
            },
        },
    )


class _RealFixtureAdapter:
    def run(self, *, task, manifest, policy):
        return AdapterRunResult(
            loaded_manifest=manifest,
            response="audited response",
            trace_events=(
                TraceEvent(
                    event_index=0,
                    op_name="transformers_generate_step",
                    input_hashes=("0x" + "4" * 64,),
                    output_hash="0x" + "5" * 64,
                    metadata={"token_id": 17, "surface": EvidenceOrigin.REAL_MODEL_EXECUTION.value},
                ),
            ),
            evidence_items=(
                EvidenceItem(
                    evidence_id="REAL-MODEL-EXECUTION-TRANSCRIPT",
                    artifact_label="execution-transcript-response",
                    content="audited response",
                    keywords=("audited", "response"),
                    origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
                    confidence=None,
                ),
            ),
            warmup_ms=1.0,
            inference_ms=2.0,
        )


def _fake_real_bundle(run_config, task, manifest, policy):
    execution_bundle = execute_once(
        task,
        manifest,
        policy,
        adapter=_RealFixtureAdapter(),
    )
    capture = derive_tensor_product_capture(
        activation_rows=((1.25, -0.5, 2.0, 0.75),),
        weight_rows=(
            (2.0, 4.0, 6.0, 8.0),
            (1.0, 3.0, 5.0, 7.0),
            (0.5, 1.5, 2.5, 3.5),
            (1.25, 2.25, 3.25, 4.25),
        ),
        spec=TensorCaptureSpec(
            layer_path="model.layers.0.mlp.down_proj",
            activation_token_index=0,
            input_width=4,
            output_width=4,
            fixed_point_scale=1000,
        ),
    )
    bundle = build_execution_audit_bundle(
        run_config=run_config,
        task=task,
        model_manifest=manifest,
        policy=policy,
        execution_bundle=execution_bundle,
        capture=capture,
        receipt_id="receipt-real-e2-0001",
    )
    return bundle, capture


def test_run_real_e2_requires_explicit_publication_authorization(tmp_path: Path) -> None:
    module = _load_cli_module()
    manifest = _manifest()
    policy = module.default_policy(seed=7, max_new_tokens=24)
    capture_spec = module.default_capture_spec()
    config_path = tmp_path / "run.yaml"
    task_path = tmp_path / "task.yaml"
    manifest_path = tmp_path / "manifest.yaml"
    _write_config(
        config_path,
        model_hash=manifest.manifest_hash(policy).removeprefix("0x"),
        dataset_hash=module.dataset_hash_for_inputs(task_document=_task_document(), policy=policy, capture_spec=capture_spec),
    )
    _write_yaml(task_path, _task_document())
    _write_yaml(manifest_path, manifest.model_dump(mode="json"))

    with pytest.raises(SystemExit, match="publication-authorized"):
        module.run_real_e2(
            config_path=config_path,
            task_path=task_path,
            model_manifest_path=manifest_path,
            model_path=tmp_path / "model",
            output_root=tmp_path / "out",
            publication_authorized=False,
            bundle_factory=lambda **_: None,
        )


def test_run_real_e2_rejects_model_hash_mismatch_before_bundle_execution(tmp_path: Path) -> None:
    module = _load_cli_module()
    manifest = _manifest()
    policy = module.default_policy(seed=7, max_new_tokens=24)
    capture_spec = module.default_capture_spec()
    config_path = tmp_path / "run.yaml"
    task_path = tmp_path / "task.yaml"
    manifest_path = tmp_path / "manifest.yaml"
    _write_config(
        config_path,
        model_hash="0" * 64,
        dataset_hash=module.dataset_hash_for_inputs(task_document=_task_document(), policy=policy, capture_spec=capture_spec),
    )
    _write_yaml(task_path, _task_document())
    _write_yaml(manifest_path, manifest.model_dump(mode="json"))

    def unexpected_bundle_factory(**_: object) -> object:
        raise AssertionError("bundle_factory should not be called when model_hash is mismatched")

    with pytest.raises(SystemExit, match="run_config.model_hash"):
        module.run_real_e2(
            config_path=config_path,
            task_path=task_path,
            model_manifest_path=manifest_path,
            model_path=tmp_path / "model",
            output_root=tmp_path / "out",
            publication_authorized=True,
            bundle_factory=unexpected_bundle_factory,
        )


def test_run_real_e2_rejects_capture_shape_outside_frozen_narrow_scope(
    tmp_path: Path,
) -> None:
    module = _load_cli_module()
    manifest = _manifest()
    policy = module.default_policy(seed=7, max_new_tokens=24)
    capture_spec = TensorCaptureSpec(
        layer_path="model.layers.0.mlp.down_proj",
        activation_token_index=0,
        input_width=3,
        output_width=4,
        fixed_point_scale=1000,
    )
    config_path = tmp_path / "run.yaml"
    task_path = tmp_path / "task.yaml"
    manifest_path = tmp_path / "manifest.yaml"
    capture_path = tmp_path / "capture.yaml"
    _write_config(
        config_path,
        model_hash=manifest.manifest_hash(policy).removeprefix("0x"),
        dataset_hash=module.dataset_hash_for_inputs(
            task_document=_task_document(),
            policy=policy,
            capture_spec=capture_spec,
        ),
    )
    _write_yaml(task_path, _task_document())
    _write_yaml(manifest_path, manifest.model_dump(mode="json"))
    _write_yaml(capture_path, capture_spec.model_dump(mode="json"))

    with pytest.raises(SystemExit, match="frozen 4x4 activation slice"):
        module.run_real_e2(
            config_path=config_path,
            task_path=task_path,
            model_manifest_path=manifest_path,
            model_path=tmp_path / "model",
            output_root=tmp_path / "out",
            publication_authorized=True,
            capture_spec_path=capture_path,
            bundle_factory=lambda **_: (_ for _ in ()).throw(
                AssertionError("bundle factory must not run for an unfrozen capture shape")
            ),
        )


def test_run_real_e2_wires_bundle_provenance_and_raw_artifacts(tmp_path: Path) -> None:
    module = _load_cli_module()
    manifest = _manifest()
    policy = module.default_policy(seed=7, max_new_tokens=24)
    capture_spec = module.default_capture_spec()
    config_path = tmp_path / "run.yaml"
    task_path = tmp_path / "task.yaml"
    manifest_path = tmp_path / "manifest.yaml"
    _write_config(
        config_path,
        model_hash=manifest.manifest_hash(policy).removeprefix("0x"),
        dataset_hash=module.dataset_hash_for_inputs(task_document=_task_document(), policy=policy, capture_spec=capture_spec),
    )
    _write_yaml(task_path, _task_document())
    _write_yaml(manifest_path, manifest.model_dump(mode="json"))

    captures: dict[str, object] = {}

    class FakeRegistry:
        def __init__(self, root: str | Path) -> None:
            self.root = Path(root)
            self.closed = False

        def write_atomic(self, record, *, provenance_bundle):
            captures["registry_record"] = record
            captures["registry_bundle"] = provenance_bundle
            return self.root / "frozen.json"

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

    def fake_bundle_factory(**kwargs: object):
        captures["bundle_factory"] = kwargs
        return _fake_real_bundle(kwargs["run_config"], kwargs["task"], kwargs["manifest"], kwargs["policy"])

    result = module.run_real_e2(
        config_path=config_path,
        task_path=task_path,
        model_manifest_path=manifest_path,
        model_path=tmp_path / "model",
        tokenizer_path=tmp_path / "tokenizer",
        output_root=tmp_path / "out",
        publication_authorized=True,
        bundle_factory=fake_bundle_factory,
        environment_collector=fake_environment_collector,
        registry_factory=FakeRegistry,
        repo_root=tmp_path / "repo",
        lock_path=tmp_path / "repo" / "requirements.lock",
    )

    assert result.raw_rows_path == tmp_path / "out" / "e2_receipt_rows.json"
    assert result.capture_artifact_path == tmp_path / "out" / "e2_tensor_capture.json"
    assert result.publication_record_path == tmp_path / "out" / "e2_publication_record.json"
    assert json.loads(result.capture_artifact_path.read_text(encoding="utf-8"))["layer_path"] == "model.layers.0.mlp.down_proj"
    publication_record = json.loads(result.publication_record_path.read_text(encoding="utf-8"))
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    raw_rows = json.loads(result.raw_rows_path.read_text(encoding="utf-8"))
    attacked_rows = [row for row in raw_rows if row["is_attacked"]]
    assert len(attacked_rows) == 4
    assert all(row["detected"] for row in attacked_rows)
    assert {row["origin"] for row in raw_rows} == {"REAL_MODEL_EXECUTION"}
    assert publication_record["claim_id"] == "C2"
    assert publication_record["payload"]["measurement_design"] == "NARROW_SCOPE_PILOT"
    assert publication_record["payload"]["claim_disposition_reason"] == (
        "NARROW_SCOPE_PILOT is methodologically capped at INCONCLUSIVE; "
        "one model, one task, one layer, one token, one 4x4 activation slice, "
        "and four attack observations cannot support paper claim C2"
    )
    assert publication_record["claim_disposition"] == "INCONCLUSIVE"
    assert summary["measurement_design"] == "NARROW_SCOPE_PILOT"
    assert summary["claim_disposition"] == "INCONCLUSIVE"
    assert result.publication_decision.completeness == "COMPLETE"
    assert result.publication_decision.claim_support == "INCONCLUSIVE"
    assert result.frozen_artifact_path == tmp_path / "out" / "registry" / "frozen.json"
    assert captures["registry_record"] == publication_record
    assert captures["bundle_factory"]["model_path"] == tmp_path / "model"
    assert captures["bundle_factory"]["tokenizer_path"] == tmp_path / "tokenizer"
    assert captures["repo_root"] == tmp_path / "repo"
    assert captures["lock_path"] == tmp_path / "repo" / "requirements.lock"


def test_main_prints_only_public_artifact_references(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_cli_module()
    manifest = _manifest()
    policy = module.default_policy(seed=7, max_new_tokens=24)
    capture_spec = module.default_capture_spec()
    config_path = tmp_path / "run.yaml"
    task_path = tmp_path / "task.yaml"
    manifest_path = tmp_path / "manifest.yaml"
    _write_config(
        config_path,
        model_hash=manifest.manifest_hash(policy).removeprefix("0x"),
        dataset_hash=module.dataset_hash_for_inputs(
            task_document=_task_document(),
            policy=policy,
            capture_spec=capture_spec,
        ),
    )
    _write_yaml(task_path, _task_document())
    _write_yaml(manifest_path, manifest.model_dump(mode="json"))

    module.run_real_e2 = lambda **_: SimpleNamespace(
        raw_rows_path=tmp_path / "out" / "e2_receipt_rows.json",
        capture_artifact_path=tmp_path / "out" / "e2_tensor_capture.json",
        publication_record_path=tmp_path / "out" / "e2_publication_record.json",
        summary_path=tmp_path / "out" / "e2_summary.json",
        publication_decision=SimpleNamespace(
            completeness="COMPLETE",
            claim_support="SUPPORTED",
        ),
        frozen_artifact_path=tmp_path / "out" / "registry" / "frozen.json",
    )

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
            "--publication-authorized",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["raw_rows_path"] == "e2_receipt_rows.json"
    assert payload["capture_artifact_path"] == "e2_tensor_capture.json"
    assert payload["publication_record_path"] == "e2_publication_record.json"
    assert payload["summary_path"] == "e2_summary.json"
    assert payload["frozen_artifact_path"] == "frozen.json"
    assert payload["measurement_design"] == "NARROW_SCOPE_PILOT"
    assert payload["claim_disposition_reason"].startswith(
        "NARROW_SCOPE_PILOT is methodologically capped at INCONCLUSIVE"
    )
    assert str(tmp_path) not in json.dumps(payload)
