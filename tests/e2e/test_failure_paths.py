from __future__ import annotations

import hashlib
import socket
from pathlib import Path

import pytest
import yaml

from poi_mpp.protocol.types import ReceiptState
from poi_mpp.orchestration import run_mpp as orchestration
from poi_mpp.orchestration.run_mpp import LocalMPPConfig, RealPathBlocker, load_local_mpp_config, run_local_mpp


ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config_with_local_artifacts(tmp_path: Path) -> LocalMPPConfig:
    model_root = tmp_path / "model"
    tokenizer_root = tmp_path / "tokenizer"
    model_root.mkdir(exist_ok=True)
    tokenizer_root.mkdir(exist_ok=True)

    model_file = model_root / "model.safetensors"
    tokenizer_file = tokenizer_root / "tokenizer.json"
    model_file.write_bytes(b"task21-local-model")
    tokenizer_file.write_bytes(b'{"tokenizer":"task21"}')

    return LocalMPPConfig.model_validate(
        {
            "schema_version": "POI_MPP_LOCAL_MPP_CONFIG_V1",
            "run_config": {
                "schema_version": "POI_MPP_RUN_CONFIG_V1",
                "run_id": "task21-real-run-local",
                "experiment_id": "E3",
                "origin": "REAL_MODEL_EXECUTION",
                "authorization_scope": "PUBLICATION_EVIDENCE_AUTHORIZED",
                "model_hash": "5" * 64,
                "dataset_hash": "6" * 64,
                "parent_hashes": [],
                "data_availability": {
                    "total_shards": 8,
                    "samples": 4,
                    "replacement": False,
                },
            },
            "model": {
                "model_root": str(model_root),
                "tokenizer_root": str(tokenizer_root),
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
                        "model.safetensors": _hash_file(model_file),
                    },
                    "tokenizer_file_hashes": {
                        "tokenizer.json": _hash_file(tokenizer_file),
                    },
                },
                "decode_policy": {
                    "seed": 11,
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


def test_valid_local_model_artifact_advances_to_external_evaluator_blocker(tmp_path: Path) -> None:
    result = run_local_mpp(_config_with_local_artifacts(tmp_path))

    assert result.real_path.blocker is RealPathBlocker.WAITING_EXTERNAL_EVALUATOR_AUTHORITY
    assert result.synthetic.failure_paths.execution_rejection_state == "REJECTED"
    assert result.synthetic.failure_paths.semantic_abstention_state == "ABSTAINED"
    assert result.synthetic.failure_paths.da_failure_state == "DA_FAILED"
    assert result.synthetic.failure_paths.successful_challenge_state == "SLASHED"


def test_loader_rejects_unknown_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "local.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "POI_MPP_LOCAL_MPP_CONFIG_V1",
                "run_config": {
                    "schema_version": "POI_MPP_RUN_CONFIG_V1",
                    "run_id": "bad-config",
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
                        "model_file_hashes": {"model.safetensors": "3" * 64},
                        "tokenizer_file_hashes": {"tokenizer.json": "4" * 64},
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
                "unexpected": "rejected",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown configuration fields"):
        load_local_mpp_config(config_path)


@pytest.mark.parametrize(
    "candidate",
    (
        "/tmp/escape.json",
        "./synthetic/happy/execution_bundle.json",
        "synthetic/../escape.json",
        r"synthetic\happy\execution_bundle.json",
    ),
)
def test_relative_path_validator_rejects_noncanonical_or_host_paths(candidate: str) -> None:
    with pytest.raises(ValueError):
        orchestration._validate_relative_path(candidate)


def test_safe_env_forces_offline_mode_and_drops_proxy_inheritance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.invalid:8443")
    monkeypatch.setenv("ALL_PROXY", "socks5://proxy.example.invalid:1080")

    env = orchestration._safe_env()

    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["HF_DATASETS_OFFLINE"] == "1"
    assert env["NO_PROXY"] == "127.0.0.1,localhost"
    assert "HTTP_PROXY" not in env
    assert "HTTPS_PROXY" not in env
    assert "ALL_PROXY" not in env


def test_config_rejects_non_loopback_hosts_and_model_uris(tmp_path: Path) -> None:
    bad_host = _config_with_local_artifacts(tmp_path).model_dump(mode="python")
    bad_host["chain"] = {
        "host": "10.0.0.8",
        "port": _free_port(),
        "chain_id": 31337,
        "startup_timeout_seconds": 20,
        "command_timeout_seconds": 120,
    }
    with pytest.raises(ValueError, match="loopback"):
        LocalMPPConfig.model_validate(bad_host)

    payload = _config_with_local_artifacts(tmp_path).model_dump(mode="python")
    payload["model"]["model_root"] = "https://example.invalid/model"
    with pytest.raises(ValueError, match="local filesystem path"):
        LocalMPPConfig.model_validate(payload)


def test_monkeypatched_expected_epoch_cannot_change_authoritative_readback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestration, "_expected_happy_credit_epoch", lambda task_epoch: task_epoch + 99)

    with pytest.raises(RuntimeError, match="authoritative receipt"):
        run_local_mpp(_config_with_local_artifacts(tmp_path))


def test_mismatching_authoritative_chain_readback_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = orchestration._read_authoritative_receipt

    def _tampered(*args, **kwargs):
        receipt = original(*args, **kwargs)
        return receipt.model_copy(update={"state": ReceiptState.PENDING})

    monkeypatch.setattr(orchestration, "_read_authoritative_receipt", _tampered)

    with pytest.raises(RuntimeError, match="authoritative receipt"):
        run_local_mpp(_config_with_local_artifacts(tmp_path))


def test_run_all_script_pins_offline_localhost_only_execution() -> None:
    script = (ROOT / "scripts" / "run_all.sh").read_text(encoding="utf-8")

    assert "HF_HUB_OFFLINE=1" in script
    assert "TRANSFORMERS_OFFLINE=1" in script
    assert "HF_DATASETS_OFFLINE=1" in script
    assert "NO_PROXY=127.0.0.1,localhost" in script
    assert "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY" in script
    assert "localhost Anvil exception" in script
