import pytest
from pydantic import ValidationError

from poi_mpp.evidence.models import ArtifactRecord, ArtifactStage, EvidenceOrigin


def test_synthetic_record_cannot_be_frozen():
    with pytest.raises(ValueError, match="synthetic evidence cannot be frozen"):
        ArtifactRecord.minimal(
            origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
            stage=ArtifactStage.FROZEN,
        )


def test_synthetic_record_cannot_be_publication_eligible():
    with pytest.raises(ValueError, match="synthetic evidence cannot be frozen"):
        ArtifactRecord.minimal(
            origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
            stage=ArtifactStage.PUBLICATION_ELIGIBLE,
        )


def test_synthetic_record_may_be_semantically_valid():
    record = ArtifactRecord.minimal(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        stage=ArtifactStage.SEMANTICALLY_VALID,
    )

    assert record.stage is ArtifactStage.SEMANTICALLY_VALID


def test_artifact_record_is_immutable_and_uses_ordered_transitions():
    record = ArtifactRecord.minimal(stage=ArtifactStage.GENERATED)

    with pytest.raises(ValidationError):
        record.stage = ArtifactStage.SCHEMA_VALID

    assert record.advance_to(ArtifactStage.SCHEMA_VALID).stage is ArtifactStage.SCHEMA_VALID
    with pytest.raises(ValueError, match="invalid lifecycle transition"):
        record.advance_to(ArtifactStage.FROZEN)


@pytest.mark.parametrize("terminal_stage", [ArtifactStage.FROZEN, ArtifactStage.PUBLICATION_ELIGIBLE])
def test_normal_construction_cannot_mint_terminal_artifacts(terminal_stage):
    with pytest.raises(ValueError, match="terminal stages must be obtained through advance_to"):
        ArtifactRecord(
            artifact_id="artifact-1",
            run_id="run-1",
            experiment_id="experiment-1",
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
            stage=terminal_stage,
            content_hash="a" * 64,
        )


@pytest.mark.parametrize("terminal_stage", [ArtifactStage.FROZEN, ArtifactStage.PUBLICATION_ELIGIBLE])
def test_direct_terminal_construction_requires_a_content_hash(terminal_stage):
    with pytest.raises(ValueError, match="terminal artifacts require a lowercase SHA-256 content_hash"):
        ArtifactRecord(
            artifact_id="artifact-1",
            run_id="run-1",
            experiment_id="experiment-1",
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
            stage=terminal_stage,
        )


@pytest.mark.parametrize("field", ["artifact_id", "run_id", "experiment_id"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_record_identifiers_cannot_be_blank(field, blank):
    values = {
        "artifact_id": "artifact-1",
        "run_id": "run-1",
        "experiment_id": "experiment-1",
        "origin": EvidenceOrigin.REAL_MODEL_EXECUTION,
        "stage": ArtifactStage.GENERATED,
    }
    values[field] = blank

    with pytest.raises(ValueError, match=f"{field} must not be blank"):
        ArtifactRecord(**values)


def test_trusted_load_is_not_a_public_lifecycle_bypass():
    assert not hasattr(ArtifactRecord, "trusted_load")


@pytest.mark.parametrize("terminal_stage", [ArtifactStage.FROZEN, ArtifactStage.PUBLICATION_ELIGIBLE])
def test_model_validate_context_cannot_mint_a_terminal_artifact(terminal_stage):
    values = {
        "artifact_id": "artifact-1",
        "run_id": "run-1",
        "experiment_id": "experiment-1",
        "origin": EvidenceOrigin.REAL_MODEL_EXECUTION,
        "stage": terminal_stage,
        "content_hash": "a" * 64,
    }
    with pytest.raises(ValueError, match="terminal stages must be obtained through advance_to"):
        ArtifactRecord.model_validate(values, context={"_poi_mpp_trusted_restore": True})


def test_advance_to_terminal_stage_requires_content_hash_and_allows_a_complete_record():
    record = ArtifactRecord(
        artifact_id="artifact-1",
        run_id="run-1",
        experiment_id="experiment-1",
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        stage=ArtifactStage.GENERATED,
        content_hash="a" * 64,
    )

    schema_valid = record.advance_to(ArtifactStage.SCHEMA_VALID)
    semantic_valid = schema_valid.advance_to(ArtifactStage.SEMANTICALLY_VALID)
    assert semantic_valid.advance_to(ArtifactStage.FROZEN).stage is ArtifactStage.FROZEN
