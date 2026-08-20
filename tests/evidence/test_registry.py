import os
from pathlib import Path

import pytest

from poi_mpp.evidence.canonical import canonical_bytes, digest
from poi_mpp.evidence.config import RunConfig, approved_schema_hash
from poi_mpp.evidence.provenance import EnvironmentManifest, freeze_run
from poi_mpp.evidence.registry import ArtifactRegistry
from poi_mpp.evidence.validation import (
    ARTIFACT_RECORD_SCHEMA_VERSION,
    ArtifactValidationError,
    ProvenanceBundle,
    artifact_content_material,
)


def _bundle(*, parents: list[str] | None = None) -> ProvenanceBundle:
    config = RunConfig.model_validate({"schema_version": "POI_MPP_RUN_CONFIG_V1", "schema_hash": approved_schema_hash(), "run_id": "run-1", "experiment_id": "E1", "origin": "REAL_MODEL_EXECUTION", "authorization_scope": "LOCAL_TEST_ONLY", "model_hash": "a" * 64, "dataset_hash": "b" * 64, "parent_hashes": parents or [], "data_availability": {"total_shards": 12, "samples": 6, "replacement": False}})
    environment = EnvironmentManifest(python_implementation="CPython", python_version="3.11.15", os_name="Linux", os_release="test", machine="x86_64", cpu_model=None, gpu_model=None, package_lock_hash=None, compiler_version=None, foundry_version=None, code_revision="c" * 40)
    return ProvenanceBundle(config=config, environment=environment, manifest=freeze_run(config, environment))


def _record(*, bundle: ProvenanceBundle | None = None, **overrides: object) -> dict[str, object]:
    bundle = bundle or _bundle()
    record: dict[str, object] = {"schema_version": ARTIFACT_RECORD_SCHEMA_VERSION, "artifact_id": "artifact-1", "run_id": "run-1", "experiment_id": "E1", "origin": "REAL_MODEL_EXECUTION", "stage": "FROZEN", "parent_hashes": [], "payload": {"result": {"score": 0.5}}, "denominator": 12, "ci_required": False, "claim_id": "C1", "claim_disposition": "SUPPORTED", "provenance": bundle.manifest.model_dump(mode="json"), **overrides}
    record["content_hash"] = digest("ARTIFACT_CONTENT", artifact_content_material(record))
    return record


def test_registry_persists_exact_task2_canonical_bytes(tmp_path: Path):
    registry = ArtifactRegistry(tmp_path)
    path = registry.write_atomic(_record(), provenance_bundle=_bundle())
    raw = path.read_bytes()
    envelope = registry.read_frozen(path.name)
    assert raw == canonical_bytes("FROZEN_ARTIFACT", envelope)
    assert envelope["frozen_hash"] == digest("FROZEN_ARTIFACT", {"record": envelope["record"], "provenance_bundle": envelope["provenance_bundle"]})


def test_registry_rejects_alternate_whitespace_and_key_order_encoding(tmp_path: Path):
    registry = ArtifactRegistry(tmp_path)
    path = registry.write_atomic(_record(), provenance_bundle=_bundle())
    path.write_bytes(path.read_bytes().replace(b"\",\"", b"\", \"", 1))
    with pytest.raises(ArtifactValidationError, match="canonical bytes"):
        ArtifactRegistry(tmp_path)


def test_registry_reloads_and_rejects_content_hash_mismatch(tmp_path: Path):
    registry = ArtifactRegistry(tmp_path)
    path = registry.write_atomic(_record(), provenance_bundle=_bundle())
    envelope = registry.read_frozen(path.name)
    envelope["record"]["payload"] = {"result": {"score": 9.9}}
    envelope["frozen_hash"] = digest("FROZEN_ARTIFACT", {"record": envelope["record"], "provenance_bundle": envelope["provenance_bundle"]})
    path.write_bytes(canonical_bytes("FROZEN_ARTIFACT", envelope))
    with pytest.raises(ArtifactValidationError, match="content_hash mismatch"):
        ArtifactRegistry(tmp_path)


def test_registry_rejects_duplicate_content_hash_and_wrong_filename(tmp_path: Path):
    registry = ArtifactRegistry(tmp_path)
    registry.write_atomic(_record(), provenance_bundle=_bundle())
    duplicate = _record(artifact_id="artifact-2")
    duplicate["content_hash"] = _record()["content_hash"]
    with pytest.raises(ArtifactValidationError, match="duplicate content_hash"):
        registry.write_atomic(duplicate, provenance_bundle=_bundle())
    (tmp_path / "artifact-1.frozen.json").rename(tmp_path / "wrong-name.frozen.json")
    with pytest.raises(ArtifactValidationError, match="filename"):
        ArtifactRegistry(tmp_path)


def test_registry_accepts_an_explicit_acyclic_registered_parent(tmp_path: Path):
    registry = ArtifactRegistry(tmp_path)
    parent = _record()
    registry.write_atomic(parent, provenance_bundle=_bundle())
    child_bundle = _bundle(parents=[parent["content_hash"]])
    child = _record(bundle=child_bundle, artifact_id="artifact-2", parent_hashes=[parent["content_hash"]])
    child_path = registry.write_atomic(child, provenance_bundle=child_bundle)
    assert child_path.exists()


def test_registry_rejects_symlink_root_and_symlink_entry(tmp_path: Path):
    external = tmp_path / "external"
    external.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(external, target_is_directory=True)
    with pytest.raises(ArtifactValidationError, match="symlink"):
        ArtifactRegistry(root_link)
    registry = ArtifactRegistry(tmp_path / "registry")
    registry.write_atomic(_record(), provenance_bundle=_bundle())
    (tmp_path / "registry" / "linked.frozen.json").symlink_to(tmp_path / "registry" / "artifact-1.frozen.json")
    with pytest.raises(ArtifactValidationError, match="symlink"):
        ArtifactRegistry(tmp_path / "registry")


def test_prelink_failure_leaves_no_target_or_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    registry = ArtifactRegistry(tmp_path)
    monkeypatch.setattr("poi_mpp.evidence.registry.os.link", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("pre-link failure")))
    with pytest.raises(OSError, match="pre-link failure"):
        registry.write_atomic(_record(), provenance_bundle=_bundle())
    assert not list(tmp_path.glob("*.frozen.json"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_postlink_unlink_and_directory_fsync_failure_return_success_and_recover_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    registry = ArtifactRegistry(tmp_path)
    original_unlink = os.unlink
    def fail_temp_unlink(path: str, *args: object, **kwargs: object) -> None:
        if str(path).endswith(".tmp"):
            raise OSError("post-link cleanup failure")
        original_unlink(path, *args, **kwargs)
    monkeypatch.setattr("poi_mpp.evidence.registry.os.unlink", fail_temp_unlink)
    monkeypatch.setattr(registry, "_fsync_directory", lambda: (_ for _ in ()).throw(OSError("fsync failed")))
    path = registry.write_atomic(_record(), provenance_bundle=_bundle())
    assert path.exists()
    assert list(tmp_path.glob(".*.tmp"))
    monkeypatch.undo()
    retry = ArtifactRegistry(tmp_path)
    assert not list(tmp_path.glob(".*.tmp"))
    assert retry.read_frozen(path.name)["record"]["artifact_id"] == "artifact-1"
