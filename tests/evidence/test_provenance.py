from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from poi_mpp.evidence.config import RunConfig
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.evidence.provenance import (
    UNVERSIONED_BLOCKED,
    EnvironmentManifest,
    collect_environment,
    freeze_run,
)


_HASH = "a" * 64


def _config() -> RunConfig:
    return RunConfig.model_validate(
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": _HASH,
            "run_id": "run-001",
            "experiment_id": "E1",
            "origin": "REPRODUCIBLE_SIMULATION",
            "authorization_scope": "LOCAL_TEST_ONLY",
            "model_hash": "b" * 64,
            "dataset_hash": "c" * 64,
            "parent_hashes": ["d" * 64],
            "data_availability": {
                "total_shards": 16,
                "samples": 8,
                "replacement": False,
            },
        }
    )


def test_environment_manifest_is_frozen_and_explicit_about_absent_fields():
    environment = EnvironmentManifest(
        python_implementation="CPython",
        python_version="3.11.0",
        os_name="Darwin",
        os_release="test",
        machine="arm64",
        cpu_model=None,
        gpu_model=None,
        package_lock_hash=None,
        compiler_version=None,
        foundry_version=None,
        code_revision="f" * 40,
    )

    assert environment.cpu_model is None
    assert environment.gpu_model is None
    with pytest.raises(ValidationError):
        environment.os_name = "changed"


def test_freeze_run_binds_config_environment_and_provenance_deterministically():
    config = _config()
    environment = EnvironmentManifest(
        python_implementation="CPython",
        python_version="3.11.0",
        os_name="Linux",
        os_release="test",
        machine="x86_64",
        cpu_model=None,
        gpu_model=None,
        package_lock_hash="e" * 64,
        compiler_version=None,
        foundry_version=None,
        code_revision="f" * 40,
    )

    first = freeze_run(config, environment)
    second = freeze_run(config, environment)

    assert first == second
    assert first.config_hash != ""
    assert first.environment_hash != ""
    assert first.code_revision == environment.code_revision
    assert first.model_hash == config.model_hash
    assert first.dataset_hash == config.dataset_hash
    assert first.origin is EvidenceOrigin.REPRODUCIBLE_SIMULATION
    assert first.authorization_scope == "LOCAL_TEST_ONLY"
    assert first.parent_hashes == config.parent_hashes


def test_collect_environment_binds_clean_git_revision(tmp_path: Path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "tracked.txt").write_text("frozen", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )

    environment = collect_environment(repo_root=tmp_path, lock_path=tmp_path / "missing.lock")
    expected = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert environment.code_revision == expected
    assert environment.package_lock_hash is None


def test_collect_environment_blocks_dirty_checkout_without_touching_real_checkout(tmp_path: Path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "tracked.txt").write_text("frozen", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )
    (tmp_path / "tracked.txt").write_text("modified", encoding="utf-8")

    assert (
        collect_environment(repo_root=tmp_path, lock_path=tmp_path / "missing.lock").code_revision
        == UNVERSIONED_BLOCKED
    )


def test_collect_environment_marks_unversioned_roots_blocked_without_touching_checkout(tmp_path: Path):
    environment = collect_environment(repo_root=tmp_path, lock_path=tmp_path / "missing.lock")

    assert environment.code_revision == UNVERSIONED_BLOCKED
    assert freeze_run(_config(), environment).code_revision == UNVERSIONED_BLOCKED
    assert environment == collect_environment(repo_root=tmp_path, lock_path=tmp_path / "missing.lock")


def test_environment_manifest_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        EnvironmentManifest(
            python_implementation="CPython",
            python_version="3.11.0",
            os_name="Linux",
            os_release="test",
            machine="x86_64",
            cpu_model=None,
            gpu_model=None,
            package_lock_hash=None,
            compiler_version=None,
            foundry_version=None,
            code_revision="f" * 40,
            secret_environment_value="must-not-be-recorded",
        )


def test_collection_does_not_serialize_environment_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("POI_MPP_TEST_SECRET", "do-not-persist-this-value")

    environment = collect_environment(repo_root=tmp_path, lock_path=tmp_path / "missing.lock")

    assert "do-not-persist-this-value" not in environment.model_dump_json()
