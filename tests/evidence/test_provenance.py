from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from poi_mpp.evidence.config import RunConfig, schema_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.evidence.provenance import (
    UNVERSIONED_BLOCKED,
    EnvironmentManifest,
    _collect_cpu_model,
    _collect_gpu_model,
    collect_environment,
    freeze_run,
    publication_build_environment_hash,
)


_HASH = "a" * 64


def _config() -> RunConfig:
    return RunConfig.model_validate(
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": schema_hash(),
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


def test_publication_build_environment_hash_excludes_only_code_revision():
    base = EnvironmentManifest(
        python_implementation="CPython",
        python_version="3.11.0",
        os_name="Darwin",
        os_release="test",
        machine="arm64",
        cpu_model=None,
        gpu_model=None,
        package_lock_hash="e" * 64,
        compiler_version=None,
        foundry_version=None,
        code_revision="f" * 40,
    )
    next_revision = base.model_copy(update={"code_revision": "a" * 40})
    changed_runtime = base.model_copy(update={"python_version": "3.12.0"})

    assert publication_build_environment_hash(base) == publication_build_environment_hash(next_revision)
    assert publication_build_environment_hash(base) != publication_build_environment_hash(changed_runtime)


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


def test_freeze_run_rechecks_approved_schema_after_unsafe_model_construction():
    unsafe = RunConfig.model_construct(
        **{
            **_config().model_dump(),
            "schema_hash": _HASH,
        }
    )
    environment = EnvironmentManifest(
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
    )

    with pytest.raises(ValueError, match="approved run configuration schema"):
        freeze_run(unsafe, environment)


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


def test_collect_environment_ignores_only_untracked_publication_outputs(tmp_path: Path):
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
    expected = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    generated = tmp_path / "results" / "publication" / "e1" / "rows.json"
    generated.parent.mkdir(parents=True)
    generated.write_text("{}", encoding="utf-8")

    environment = collect_environment(repo_root=tmp_path, lock_path=tmp_path / "missing.lock")

    assert environment.code_revision == expected


def test_collect_environment_blocks_untracked_source_outside_publication_outputs(tmp_path: Path):
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
    (tmp_path / "untracked_module.py").write_text("VALUE = 1\n", encoding="utf-8")

    environment = collect_environment(repo_root=tmp_path, lock_path=tmp_path / "missing.lock")

    assert environment.code_revision == UNVERSIONED_BLOCKED


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


@pytest.mark.parametrize(
    ("field", "unsafe"),
    [
        ("cpu_model", "/Users/test/private-cpu"),
        ("gpu_model", "gpu\ncredential=secret"),
        ("compiler_version", "~/.keys/compiler"),
        ("foundry_version", "-----BEGIN PRIVATE KEY-----"),
    ],
)
def test_environment_manifest_rejects_private_or_credential_like_public_facts(field: str, unsafe: str):
    values = {
        "python_implementation": "CPython",
        "python_version": "3.11.0",
        "os_name": "Linux",
        "os_release": "test",
        "machine": "x86_64",
        "cpu_model": None,
        "gpu_model": None,
        "package_lock_hash": None,
        "compiler_version": None,
        "foundry_version": None,
        "code_revision": "f" * 40,
    }
    values[field] = unsafe

    with pytest.raises(ValueError, match="safe public fact"):
        EnvironmentManifest(**values)


def test_cpu_collector_normalizes_allowlisted_mac_output(monkeypatch: pytest.MonkeyPatch):
    class Completed:
        stdout = "Apple   M2  Pro\n"

    monkeypatch.setattr("poi_mpp.evidence.provenance.subprocess.run", lambda *args, **kwargs: Completed())

    assert _collect_cpu_model("Darwin") == "Apple M2 Pro"


def test_cpu_collector_returns_none_when_command_is_unavailable(monkeypatch: pytest.MonkeyPatch):
    def unavailable(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError

    monkeypatch.setattr("poi_mpp.evidence.provenance.subprocess.run", unavailable)

    assert _collect_cpu_model("Darwin") is None


def test_gpu_collector_sorts_deduplicates_and_rejects_malformed_output(monkeypatch: pytest.MonkeyPatch):
    class Completed:
        stdout = (
            '{"SPDisplaysDataType":[{"sppci_model":"Zeta GPU"},'
            '{"spdisplays_chipset_model":"Alpha GPU"},{"sppci_model":"Zeta GPU"}]}'
        )

    monkeypatch.setattr("poi_mpp.evidence.provenance.subprocess.run", lambda *args, **kwargs: Completed())
    assert _collect_gpu_model("Darwin") == "Alpha GPU; Zeta GPU"

    class Malformed:
        stdout = "not-json"

    monkeypatch.setattr("poi_mpp.evidence.provenance.subprocess.run", lambda *args, **kwargs: Malformed())
    assert _collect_gpu_model("Darwin") is None


def test_collection_does_not_serialize_environment_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("POI_MPP_TEST_SECRET", "do-not-persist-this-value")

    environment = collect_environment(repo_root=tmp_path, lock_path=tmp_path / "missing.lock")

    assert "do-not-persist-this-value" not in environment.model_dump_json()
