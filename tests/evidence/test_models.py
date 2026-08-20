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
