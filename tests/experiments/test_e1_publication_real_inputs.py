from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import approved_schema_hash, load_run_config
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.protocol.types import TaskClass


REPO_ROOT = Path(
    "/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts"
)
CONFIG_ROOT = REPO_ROOT / "configs" / "publication_real_e1"
MODEL_ROOT = Path(
    "/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/local-models/qwen2.5-1.5b"
)
REVISION = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
SIDECAR_PAYLOAD = {
    "repository": "Qwen/Qwen2.5-1.5B-Instruct",
    "revision": REVISION,
    "schema_version": "POI_MPP_MODEL_REVISION_SIDECAR_V1",
    "tokenizer_revision": REVISION,
}


def _load_cli_module():
    module_path = REPO_ROOT / "experiments" / "e1_single_pass_cost.py"
    spec = importlib.util.spec_from_file_location("e1_single_pass_cost_publication_real_inputs", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def test_real_publication_inputs_close_over_local_snapshot_and_policy() -> None:
    module = _load_cli_module()
    run_config = load_run_config(CONFIG_ROOT / "run.yaml")
    task = module.load_task_spec(CONFIG_ROOT / "task.yaml")
    manifest = module.load_model_manifest(CONFIG_ROOT / "model_manifest.yaml")
    policy = module.default_policy(seed=7, max_new_tokens=24)

    assert run_config.schema_hash == approved_schema_hash()
    assert run_config.run_id == "run-e1-real-pilot-qwen25-1p5b-r989aa79-s7-t24"
    assert run_config.experiment_id == "E1"
    assert run_config.origin is EvidenceOrigin.REAL_MODEL_EXECUTION
    assert run_config.authorization_scope == "PUBLICATION_EVIDENCE_AUTHORIZED"
    assert run_config.data_availability.total_shards == 8
    assert run_config.data_availability.samples == 2
    assert run_config.data_availability.replacement is False

    assert task.task_class is TaskClass.CONSENSUS
    assert task.audit_domain_size == 8
    assert task.challenge_window_blocks == 9

    assert manifest.repository == "Qwen/Qwen2.5-1.5B-Instruct"
    assert manifest.revision == REVISION
    assert manifest.tokenizer_revision == REVISION
    assert manifest.precision == "bfloat16"
    assert manifest.quantization == "none"
    assert manifest.runtime_name == "transformers"
    assert manifest.runtime_version == "5.14.1"
    assert manifest.model_file_hashes["model.safetensors"] == "dd924a11b4c220f385b51ffa522daea7c9f3d850e31b162bb5661df483c6d3ee"

    expected_dataset_hash = digest(
        "E1_REAL_PILOT_TASKSET",
        {
            "task": task.model_dump(mode="json"),
            "decode_policy": policy.model_dump(mode="json"),
        },
    )
    assert run_config.dataset_hash == expected_dataset_hash
    assert run_config.model_hash == manifest.manifest_hash(policy).removeprefix("0x")

    sidecar_path = MODEL_ROOT / "POI_MODEL_REVISION.json"
    assert json.loads(sidecar_path.read_text(encoding="utf-8")) == SIDECAR_PAYLOAD
    assert _sha256(sidecar_path) == manifest.model_file_hashes["POI_MODEL_REVISION.json"]
    assert manifest.model_file_hashes["POI_MODEL_REVISION.json"] == manifest.tokenizer_file_hashes["POI_MODEL_REVISION.json"]

    for filename, expected_hash in manifest.model_file_hashes.items():
        assert _sha256(MODEL_ROOT / filename) == expected_hash
    for filename, expected_hash in manifest.tokenizer_file_hashes.items():
        assert _sha256(MODEL_ROOT / filename) == expected_hash
