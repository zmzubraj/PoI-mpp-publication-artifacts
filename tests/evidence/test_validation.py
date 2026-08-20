import math

import pytest

from poi_mpp.evidence.models import ArtifactRecord, ArtifactStage, EvidenceOrigin
from poi_mpp.evidence.validation import ArtifactValidationError, validate_artifact


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


def test_valid_frozen_artifact_is_complete():
    report = validate_artifact(_frozen_record())

    assert report.completeness == "COMPLETE"
    assert report.reasons == ()


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_numeric_value_fails_closed(value: float):
    with pytest.raises(ArtifactValidationError, match="non-finite"):
        validate_artifact(_frozen_record(measurement=value))


@pytest.mark.parametrize("denominator", [0, -1, 1.5, True])
def test_zero_or_invalid_denominator_fails_closed(denominator: object):
    with pytest.raises(ArtifactValidationError, match="denominator"):
        validate_artifact(_frozen_record(denominator=denominator))


def test_declared_confidence_interval_is_required_and_must_be_finite():
    with pytest.raises(ArtifactValidationError, match="confidence interval"):
        validate_artifact(_frozen_record(ci_required=True))

    with pytest.raises(ArtifactValidationError, match="non-finite"):
        validate_artifact(
            _frozen_record(ci_required=True, confidence_interval=[0.1, math.inf])
        )


def test_missing_parent_cannot_be_inferred_or_silently_accepted():
    record = _frozen_record(parent_hashes=[HASH_C])
    record["provenance"] = {**record["provenance"], "parent_hashes": [HASH_C]}

    with pytest.raises(ArtifactValidationError, match="parent closure"):
        validate_artifact(record)

    with pytest.raises(ArtifactValidationError, match="unregistered parent"):
        validate_artifact(record, known_parent_hashes=[])


def test_parent_closure_requires_the_exact_registered_hash():
    record = _frozen_record(parent_hashes=[HASH_C])
    record["provenance"] = {**record["provenance"], "parent_hashes": [HASH_C]}

    assert validate_artifact(record, known_parent_hashes=[HASH_C]).completeness == "COMPLETE"


def test_interrupted_partial_or_silently_omitted_inputs_are_incomplete():
    for state in (
        {"interrupted": True},
        {"partial": True},
        {"silently_omitted_inputs": True},
    ):
        with pytest.raises(ArtifactValidationError):
            validate_artifact(_frozen_record(**state))


def test_synthetic_and_unversioned_records_are_rejected_before_publication():
    synthetic = _frozen_record(origin="SYNTHETIC_NON_EVIDENCE")
    synthetic["provenance"] = {
        **synthetic["provenance"],
        "origin": "SYNTHETIC_NON_EVIDENCE",
    }
    with pytest.raises(ArtifactValidationError, match="synthetic"):
        validate_artifact(synthetic)

    blocked = _frozen_record()
    blocked["provenance"] = {
        **blocked["provenance"],
        "code_revision": "UNVERSIONED_BLOCKED",
    }
    with pytest.raises(ArtifactValidationError, match="UNVERSIONED_BLOCKED"):
        validate_artifact(blocked)
