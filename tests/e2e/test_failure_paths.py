from __future__ import annotations

import hashlib
import os
import socket
import subprocess
from pathlib import Path
import sys

import pytest
import yaml

from poi_mpp.protocol.types import ReceiptState
from poi_mpp.orchestration import run_mpp as orchestration
from poi_mpp.orchestration.run_mpp import LocalMPPConfig, RealPathBlocker, load_local_mpp_config, run_local_mpp


ROOT = Path(__file__).resolve().parents[2]
PYTHON_BIN = ROOT / ".venv" / "bin" / "python"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _subprocess_env(*, pythonpath: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("PYTHONPATH", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    return env


def _managed_macos_alias_path(path: Path) -> tuple[Path, Path]:
    if sys.platform != "darwin":
        pytest.skip("managed /var and /tmp alias coverage is macOS-specific")
    canonical = Path(os.path.abspath(str(path)))
    canonical_text = canonical.as_posix()
    for managed_prefix, alias_prefix in (("/private/var", "/var"), ("/private/tmp", "/tmp")):
        if canonical_text == managed_prefix or canonical_text.startswith(f"{managed_prefix}/"):
            suffix = canonical_text[len(managed_prefix) :]
            return canonical, Path(f"{alias_prefix}{suffix}")
    pytest.skip("tmp path is not rooted under a managed macOS /private alias prefix")


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


def test_successful_challenge_state_is_forwarded_from_kernel_failure_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = orchestration._run_reference_machine_failures

    def _tampered(*args, **kwargs):
        summary = original(*args, **kwargs)
        return summary.model_copy(update={"successful_challenge_state": "CHALLENGED"})

    monkeypatch.setattr(orchestration, "_run_reference_machine_failures", _tampered)

    result = run_local_mpp(_config_with_local_artifacts(tmp_path))

    assert result.synthetic.failure_paths.successful_challenge_state == "CHALLENGED"


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


def test_wrapper_help_works_from_foreign_cwd_without_editable_install(tmp_path: Path) -> None:
    completed = subprocess.run(
        [str(PYTHON_BIN), str(ROOT / "scripts" / "run_mpp.py"), "--help"],
        cwd=tmp_path,
        env=_subprocess_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Run local Task 21 MPP orchestration" in completed.stdout


def test_module_help_works_from_foreign_cwd_with_repo_src_pythonpath(tmp_path: Path) -> None:
    completed = subprocess.run(
        [str(PYTHON_BIN), "-m", "poi_mpp.orchestration.run_mpp", "--help"],
        cwd=tmp_path,
        env=_subprocess_env(pythonpath=str(ROOT / "src")),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Run local Task 21 MPP orchestration" in completed.stdout


def test_module_help_is_warning_clean_under_python_w_error(tmp_path: Path) -> None:
    completed = subprocess.run(
        [str(PYTHON_BIN), "-W", "error", "-m", "poi_mpp.orchestration.run_mpp", "--help"],
        cwd=tmp_path,
        env=_subprocess_env(pythonpath=str(ROOT / "src")),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Run local Task 21 MPP orchestration" in completed.stdout


def test_loader_resolves_relative_model_and_tokenizer_roots_from_config_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    foreign_cwd = tmp_path / "foreign-cwd"
    config_dir.mkdir()
    foreign_cwd.mkdir()
    (config_dir / "models").mkdir()
    (config_dir / "tokenizers").mkdir()
    config_path = config_dir / "local.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "POI_MPP_LOCAL_MPP_CONFIG_V1",
                "run_config": {
                    "schema_version": "POI_MPP_RUN_CONFIG_V1",
                    "run_id": "relative-roots",
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
                    "model_root": "models",
                    "tokenizer_root": "tokenizers",
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
                "output_root": "out",
                "committee_size": 1,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(foreign_cwd)
    loaded = load_local_mpp_config(config_path)

    assert loaded.model.model_root == Path(os.path.abspath(str(config_dir / "models")))
    assert loaded.model.tokenizer_root == Path(os.path.abspath(str(config_dir / "tokenizers")))


def test_loader_canonicalizes_managed_macos_alias_roots(tmp_path: Path) -> None:
    canonical_root, alias_root = _managed_macos_alias_path(tmp_path)
    model_root = canonical_root / "model"
    tokenizer_root = canonical_root / "tokenizer"
    output_root = canonical_root / "out"
    model_root.mkdir(exist_ok=True)
    tokenizer_root.mkdir(exist_ok=True)
    model_file = model_root / "model.safetensors"
    tokenizer_file = tokenizer_root / "tokenizer.json"
    model_file.write_bytes(b"task21-macos-model")
    tokenizer_file.write_bytes(b'{"tokenizer":"task21-macos"}')
    config_path = canonical_root / "local.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "POI_MPP_LOCAL_MPP_CONFIG_V1",
                "run_config": {
                    "schema_version": "POI_MPP_RUN_CONFIG_V1",
                    "run_id": "managed-macos-alias",
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
                    "model_root": str(alias_root / "model"),
                    "tokenizer_root": str(alias_root / "tokenizer"),
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
                        "model_file_hashes": {"model.safetensors": _hash_file(model_file)},
                        "tokenizer_file_hashes": {"tokenizer.json": _hash_file(tokenizer_file)},
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
                "output_root": str(alias_root / "out"),
                "committee_size": 1,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    loaded = load_local_mpp_config(config_path)
    result = run_local_mpp(loaded)

    assert loaded.model.model_root == model_root
    assert loaded.model.tokenizer_root == tokenizer_root
    assert loaded.output_root == output_root
    assert result.real_path.blocker is RealPathBlocker.WAITING_EXTERNAL_EVALUATOR_AUTHORITY


@pytest.mark.parametrize("label, filename", (("model", "model.safetensors"), ("tokenizer", "tokenizer.json")))
def test_managed_macos_alias_rejects_user_symlinked_artifact_roots_without_path_leak(
    tmp_path: Path,
    label: str,
    filename: str,
) -> None:
    canonical_root, alias_root = _managed_macos_alias_path(tmp_path)
    external = canonical_root / "external"
    external.mkdir()
    (external / filename).write_bytes(b"task21-managed-alias-symlink")
    symlink_root = canonical_root / f"{label}-link"
    symlink_root.symlink_to(external, target_is_directory=True)

    payload = _config_with_local_artifacts(canonical_root).model_dump(mode="python")
    payload["model"][f"{label}_root"] = str(alias_root / f"{label}-link")
    payload["model"]["manifest"][f"{'model' if label == 'model' else 'tokenizer'}_file_hashes"] = {
        filename: hashlib.sha256(b"task21-managed-alias-symlink").hexdigest()
    }

    result = run_local_mpp(LocalMPPConfig.model_validate(payload))

    assert result.real_path.blocker is RealPathBlocker.WAITING_LOCAL_MODEL_ARTIFACT
    assert any(reason == f"configured {label} root is not a trusted local directory" for reason in result.real_path.reasons)
    assert all(str(canonical_root) not in reason for reason in result.real_path.reasons)
    assert all(str(alias_root) not in reason for reason in result.real_path.reasons)


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


@pytest.mark.parametrize("label", ("model", "tokenizer"))
def test_symlinked_local_artifact_root_is_rejected_without_path_leak(
    tmp_path: Path,
    label: str,
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    (external / ("model.safetensors" if label == "model" else "tokenizer.json")).write_bytes(
        b"task21-outside-artifact"
    )
    link_root = tmp_path / f"{label}-link"
    link_root.symlink_to(external, target_is_directory=True)

    payload = _config_with_local_artifacts(tmp_path).model_dump(mode="python")
    payload["model"][f"{label}_root"] = str(link_root)
    payload["model"]["manifest"][f"{'model' if label == 'model' else 'tokenizer'}_file_hashes"] = {
        "model.safetensors" if label == "model" else "tokenizer.json": hashlib.sha256(
            b"task21-outside-artifact"
        ).hexdigest()
    }
    result = run_local_mpp(LocalMPPConfig.model_validate(payload))

    assert result.real_path.blocker is RealPathBlocker.WAITING_LOCAL_MODEL_ARTIFACT
    assert any(f"configured {label} root is not a trusted local directory" == reason for reason in result.real_path.reasons)
    assert all(str(tmp_path.resolve()) not in reason for reason in result.real_path.reasons)


@pytest.mark.parametrize("label, filename", (("model", "model.safetensors"), ("tokenizer", "tokenizer.json")))
def test_hardlinked_local_artifact_leaf_is_rejected_without_path_leak(
    tmp_path: Path,
    label: str,
    filename: str,
) -> None:
    config = _config_with_local_artifacts(tmp_path).model_dump(mode="python")
    outside = tmp_path / f"{label}-outside.bin"
    outside.write_bytes(b"task21-hardlink-artifact")
    root = Path(config["model"][f"{label}_root"])
    target = root / filename
    target.unlink()
    os.link(outside, target)
    config["model"]["manifest"][f"{'model' if label == 'model' else 'tokenizer'}_file_hashes"] = {
        filename: hashlib.sha256(b"task21-hardlink-artifact").hexdigest()
    }

    result = run_local_mpp(LocalMPPConfig.model_validate(config))

    assert result.real_path.blocker is RealPathBlocker.WAITING_LOCAL_MODEL_ARTIFACT
    assert any(
        reason == f"configured {label} artifact file is not a trusted local file: {filename}"
        for reason in result.real_path.reasons
    )
    assert all(str(tmp_path.resolve()) not in reason for reason in result.real_path.reasons)


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

    assert 'export PYTHONPATH="${repo_root}/src' in script
    assert '"${python_bin}" -m poi_mpp.orchestration.run_mpp' in script
    assert "HF_HUB_OFFLINE=1" in script
    assert "TRANSFORMERS_OFFLINE=1" in script
    assert "HF_DATASETS_OFFLINE=1" in script
    assert "NO_PROXY=127.0.0.1,localhost" in script
    assert "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY" in script
    assert "localhost Anvil exception" in script


def test_direct_writer_rejects_symlinked_output_root_before_outside_write(tmp_path: Path) -> None:
    external = tmp_path / "external-out"
    external.mkdir()
    symlink_root = tmp_path / "out-link"
    symlink_root.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="output root"):
        orchestration._write_json_atomic(symlink_root, "result.json", {"status": "blocked"})

    assert list(external.iterdir()) == []


def test_managed_macos_alias_output_root_supports_canonical_write_and_rejects_user_symlink(tmp_path: Path) -> None:
    canonical_root, alias_root = _managed_macos_alias_path(tmp_path)
    written_root = canonical_root / "alias-out"
    target, _ = orchestration._write_json_atomic(alias_root / "alias-out", "result.json", {"status": "blocked"})

    assert target == written_root / "result.json"
    assert target.exists()

    external = canonical_root / "external-out"
    external.mkdir()
    symlink_root = canonical_root / "alias-link"
    symlink_root.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="output root"):
        orchestration._write_json_atomic(alias_root / "alias-link", "result.json", {"status": "blocked"})

    assert list(external.iterdir()) == []


def test_run_local_mpp_rejects_symlinked_output_root_before_outside_write(tmp_path: Path) -> None:
    external = tmp_path / "external-out"
    external.mkdir()
    symlink_root = tmp_path / "out-link"
    symlink_root.symlink_to(external, target_is_directory=True)
    config = _config_with_local_artifacts(tmp_path).model_copy(update={"output_root": symlink_root})

    with pytest.raises(ValueError, match="output root"):
        run_local_mpp(config)

    assert list(external.iterdir()) == []
