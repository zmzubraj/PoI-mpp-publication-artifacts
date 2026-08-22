from __future__ import annotations

import json
import socket
from pathlib import Path

from poi_mpp.orchestration import run_mpp as orchestration
from poi_mpp.orchestration.run_mpp import LocalMPPConfig, RealPathBlocker, SyntheticDisposition, run_local_mpp


ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _base_config(tmp_path: Path) -> LocalMPPConfig:
    return LocalMPPConfig.model_validate(
        {
            "schema_version": "POI_MPP_LOCAL_MPP_CONFIG_V1",
            "run_config": {
                "schema_version": "POI_MPP_RUN_CONFIG_V1",
                "run_id": "task21-real-run",
                "experiment_id": "E3",
                "origin": "REAL_MODEL_EXECUTION",
                "authorization_scope": "PUBLICATION_EVIDENCE_AUTHORIZED",
                "model_hash": "1" * 64,
                "dataset_hash": "2" * 64,
                "parent_hashes": [],
                "data_availability": {
                    "total_shards": 8,
                    "samples": 4,
                    "replacement": False,
                },
            },
            "model": {
                "model_root": str(tmp_path / "missing-model"),
                "tokenizer_root": str(tmp_path / "missing-tokenizer"),
                "manifest": {
                    "model_id": "local-qwen-1.5b",
                    "repository": "Qwen/Qwen2.5-1.5B-Instruct",
                    "revision": "1" * 40,
                    "tokenizer_id": "Qwen/Qwen2.5-1.5B-Instruct",
                    "tokenizer_revision": "2" * 40,
                    "license_id": "apache-2.0",
                    "parameter_scale": "1.5B",
                    "precision": "int4",
                    "quantization": "q4_k_m",
                    "runtime_name": "transformers",
                    "runtime_version": "4.44.0",
                    "model_file_hashes": {
                        "model.safetensors": "3" * 64,
                    },
                    "tokenizer_file_hashes": {
                        "tokenizer.json": "4" * 64,
                    },
                },
                "decode_policy": {
                    "seed": 7,
                    "max_new_tokens": 24,
                    "do_sample": False,
                    "temperature": 0.0,
                    "top_p": 1.0,
                    "top_k": 0,
                    "repetition_penalty": 1.0,
                    "stop_sequences": [],
                },
            },
            "chain": {
                "host": "127.0.0.1",
                "port": _free_port(),
                "chain_id": 31337,
                "startup_timeout_seconds": 20,
                "command_timeout_seconds": 120,
            },
            "semantic": {
                "confirmatory_schema_path": str(ROOT / "configs" / "confirmatory" / "e3.schema.yaml"),
                "evaluator_registry_reference": "authority://external-evaluator-registry/task21",
            },
            "output_root": str(tmp_path / "out"),
            "committee_size": 1,
        }
    )


def test_real_path_blocks_without_local_model_and_synthetic_happy_path_completes(tmp_path: Path) -> None:
    config = _base_config(tmp_path)

    result = run_local_mpp(config)

    assert result.real_path.blocker is RealPathBlocker.WAITING_LOCAL_MODEL_ARTIFACT
    assert result.contracts.chain_id == config.chain.chain_id
    assert result.synthetic.happy_path.receipt_state == "ACTIVE"
    assert result.synthetic.happy_path.credit_epoch == result.synthetic.happy_path.task_epoch + 1
    assert result.synthetic.happy_path.committee_members == (result.contracts.worker_address,)
    assert result.synthetic.failure_paths.service_task_credit_total == 0
    assert result.synthetic.failure_paths.replay_rejection_error_code == "REPLAY_REJECTED"
    assert result.synthetic.summary_disposition is SyntheticDisposition.NON_PUBLICATION_MECHANICS
    assert orchestration._resolve_output_relative_path(
        config.output_root,
        result.synthetic.happy_path.execution_bundle_path,
    ).is_file()
    assert orchestration._resolve_output_relative_path(
        config.output_root,
        result.synthetic.happy_path.committee_artifact_path,
    ).is_file()
    assert all(
        artifact.summary_disposition is SyntheticDisposition.NON_PUBLICATION_MECHANICS
        for artifact in result.synthetic.artifacts
    )


def test_serialized_result_uses_output_relative_posix_paths_and_hash_closure_survives_reload(tmp_path: Path) -> None:
    config = _base_config(tmp_path)

    result = run_local_mpp(config)
    result_path = config.output_root / "run_mpp_result.json"
    raw = result_path.read_bytes()
    payload = orchestration._decode_canonical_json(raw, "TASK21_JSON")
    reloaded = orchestration.LocalMPPResult.model_validate(payload)

    decoded = raw.decode("utf-8")
    assert str(config.output_root.resolve()) not in decoded
    assert str(tmp_path.resolve()) not in decoded
    assert payload["synthetic"]["happy_path"]["execution_bundle_path"] == "synthetic/happy/execution_bundle.json"
    assert payload["synthetic"]["happy_path"]["committee_artifact_path"] == "synthetic/happy/committee.json"
    assert reloaded.contracts.anvil_log is not None
    assert reloaded.contracts.anvil_log.captured_bytes <= orchestration._ANVIL_LOG_LIMIT
    assert orchestration._resolve_output_relative_path(
        config.output_root,
        reloaded.contracts.anvil_log.relative_path,
    ).stat().st_size <= orchestration._ANVIL_LOG_LIMIT

    artifact_by_hash = {artifact.content_hash: artifact for artifact in reloaded.synthetic.artifacts}
    for artifact in reloaded.synthetic.artifacts:
        assert artifact.relative_path == artifact.relative_path.replace("\\", "/")
        assert not artifact.relative_path.startswith("/")
        assert str(artifact.relative_path) == Path(artifact.relative_path).as_posix()
        resolved = orchestration._resolve_output_relative_path(config.output_root, artifact.relative_path)
        assert resolved.is_file()
        assert orchestration._hash_file(resolved) == artifact.content_hash
        artifact_payload = orchestration._decode_canonical_json(resolved.read_bytes(), "TASK21_JSON")
        assert artifact_payload["parent_hashes"] == list(artifact.parent_hashes)
        for parent_hash in artifact.parent_hashes:
            assert parent_hash in artifact_by_hash

    assert orchestration._resolve_output_relative_path(
        config.output_root,
        reloaded.synthetic.happy_path.execution_bundle_path,
    ) == orchestration._resolve_output_relative_path(config.output_root, "synthetic/happy/execution_bundle.json")
    assert orchestration._resolve_output_relative_path(
        config.output_root,
        reloaded.synthetic.happy_path.committee_artifact_path,
    ) == orchestration._resolve_output_relative_path(config.output_root, "synthetic/happy/committee.json")
