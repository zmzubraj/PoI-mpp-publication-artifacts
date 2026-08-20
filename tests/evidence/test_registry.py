import json
import os

import pytest

from poi_mpp.evidence.models import ArtifactRecord, ArtifactStage, EvidenceOrigin
from poi_mpp.evidence.models import RunManifest
from poi_mpp.evidence.registry import ArtifactRegistry
from poi_mpp.evidence.validation import ArtifactValidationError


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
REVISION = "d" * 40


def _frozen_record(**overrides: object) -> dict[str, object]:
    record = ArtifactRecord(
        artifact_id="artifact-1",
        run_id="run-1",
        experiment_id="E1",
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        stage=ArtifactStage.GENERATED,
        content_hash=HASH_A,
    )
    for stage in (
        ArtifactStage.SCHEMA_VALID,
        ArtifactStage.SEMANTICALLY_VALID,
        ArtifactStage.FROZEN,
    ):
        record = record.advance_to(stage)
    return {
        **record.model_dump(mode="json"),
        "denominator": 12,
        "provenance": {
            "run_id": "run-1",
            "experiment_id": "E1",
            "origin": "REAL_MODEL_EXECUTION",
            "authorization_scope": "LOCAL_TEST_ONLY",
            "config_hash": HASH_B,
            "environment_hash": HASH_C,
            "code_revision": REVISION,
            "model_hash": HASH_A,
            "dataset_hash": HASH_B,
            "parent_hashes": [],
        },
        **overrides,
    }


def test_atomic_writer_persists_canonical_frozen_record(tmp_path):
    registry = ArtifactRegistry(tmp_path)

    path = registry.write_atomic(_frozen_record())

    assert path.name == "artifact-1.frozen.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["record"]["artifact_id"] == "artifact-1"
    assert len(stored["frozen_hash"]) == 64


def test_atomic_writer_does_not_leave_frozen_partial_file(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    invalid_record = _frozen_record(denominator=0)

    with pytest.raises(ArtifactValidationError):
        registry.write_atomic(invalid_record)

    assert not list(tmp_path.glob("*.frozen.json"))


def test_path_traversal_identifier_is_rejected_without_writing(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    record = _frozen_record(artifact_id="../escape")

    with pytest.raises(ArtifactValidationError, match="safe filename"):
        registry.write_atomic(record)

    assert not list(tmp_path.glob("*.frozen.json"))
    assert not (tmp_path.parent / "escape.frozen.json").exists()


def test_atomic_registry_rejects_a_publication_eligible_stage(tmp_path):
    registry = ArtifactRegistry(tmp_path)

    with pytest.raises(ArtifactValidationError, match="require FROZEN stage"):
        registry.write_atomic(_frozen_record(stage="PUBLICATION_ELIGIBLE"))

    assert not list(tmp_path.glob("*.frozen.json"))


def test_duplicate_write_cannot_overwrite_a_frozen_artifact(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    path = registry.write_atomic(_frozen_record())
    original = path.read_bytes()

    with pytest.raises(ArtifactValidationError, match="already frozen"):
        registry.write_atomic(_frozen_record(measurement=99))

    assert path.read_bytes() == original


def test_parent_closure_is_resolved_only_against_registered_artifacts(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    registry.write_atomic(_frozen_record())
    child = _frozen_record(
        artifact_id="artifact-2",
        content_hash=HASH_C,
        parent_hashes=[HASH_A],
    )
    child["provenance"] = {**child["provenance"], "parent_hashes": [HASH_A]}

    child_path = registry.write_atomic(child)

    assert child_path.exists()


def test_registry_serializes_an_explicit_task2_run_manifest_binding(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    record = _frozen_record()
    record.pop("provenance")
    manifest = RunManifest(
        run_id="run-1",
        experiment_id="E1",
        config_hash=HASH_B,
        environment_hash=HASH_C,
        code_revision=REVISION,
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        authorization_scope="LOCAL_TEST_ONLY",
        model_hash=HASH_A,
        dataset_hash=HASH_B,
        parent_hashes=(),
    )

    path = registry.write_atomic(record, manifest=manifest)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["record"]["provenance"] == manifest.model_dump(mode="json")


def test_interrupted_publish_cleans_the_temp_file_and_preserves_prior_artifact(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    registry = ArtifactRegistry(tmp_path)
    first = registry.write_atomic(_frozen_record())
    original = first.read_bytes()
    second = _frozen_record(artifact_id="artifact-2", content_hash=HASH_A)

    def interrupted_link(source: str, target: str) -> None:
        raise OSError("simulated interruption")

    monkeypatch.setattr("poi_mpp.evidence.registry.os.link", interrupted_link)
    with pytest.raises(OSError, match="simulated interruption"):
        registry.write_atomic(second)

    assert first.read_bytes() == original
    assert not (tmp_path / "artifact-2.frozen.json").exists()
    assert not list(tmp_path.glob(".*.tmp"))
