import math

import pytest

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig, approved_schema_hash
from poi_mpp.evidence.provenance import EnvironmentManifest, freeze_run
from poi_mpp.evidence.validation import (
    ARTIFACT_RECORD_SCHEMA_VERSION,
    ArtifactValidationError,
    ProvenanceBundle,
    artifact_content_material,
    validate_artifact,
)


def _bundle(*, code_revision: str = "c" * 40) -> ProvenanceBundle:
    config = RunConfig.model_validate({
        "schema_version": "POI_MPP_RUN_CONFIG_V1", "schema_hash": approved_schema_hash(),
        "run_id": "run-1", "experiment_id": "E1", "origin": "REAL_MODEL_EXECUTION",
        "authorization_scope": "LOCAL_TEST_ONLY", "model_hash": "a" * 64,
        "dataset_hash": "b" * 64, "parent_hashes": [],
        "data_availability": {"total_shards": 12, "samples": 6, "replacement": False},
    })
    environment = EnvironmentManifest(
        python_implementation="CPython", python_version="3.11.15", os_name="Linux",
        os_release="test", machine="x86_64", cpu_model=None, gpu_model=None,
        package_lock_hash=None, compiler_version=None, foundry_version=None, code_revision=code_revision,
    )
    return ProvenanceBundle(config=config, environment=environment, manifest=freeze_run(config, environment))


def _record(*, bundle: ProvenanceBundle | None = None, **overrides: object) -> dict[str, object]:
    bundle = bundle or _bundle()
    record: dict[str, object] = {
        "schema_version": ARTIFACT_RECORD_SCHEMA_VERSION, "artifact_id": "artifact-1",
        "run_id": "run-1", "experiment_id": "E1", "origin": "REAL_MODEL_EXECUTION",
        "stage": "FROZEN", "parent_hashes": [], "payload": {"result": {"score": 0.5}},
        "denominator": 12, "ci_required": False, "claim_id": "C1",
        "claim_disposition": "SUPPORTED", "provenance": bundle.manifest.model_dump(mode="json"),
        **overrides,
    }
    record["content_hash"] = digest("ARTIFACT_CONTENT", artifact_content_material(record))
    return record


def test_valid_content_bound_artifact_is_complete():
    report = validate_artifact(_record(), provenance_bundle=_bundle())
    assert report.completeness == "COMPLETE"
    assert report.reasons == ()


def test_forged_or_changed_payload_with_old_hash_is_rejected():
    forged = _record()
    forged["payload"] = {"result": {"score": 0.9}}
    with pytest.raises(ArtifactValidationError, match="content_hash mismatch"):
        validate_artifact(forged, provenance_bundle=_bundle())


@pytest.mark.parametrize("field", ["schema_version", "payload"])
def test_schema_and_nonempty_result_payload_are_required(field: str):
    record = _record()
    record[field] = "FOREIGN" if field == "schema_version" else {}
    record["content_hash"] = digest("ARTIFACT_CONTENT", artifact_content_material(record))
    with pytest.raises(ArtifactValidationError):
        validate_artifact(record, provenance_bundle=_bundle())


def test_provenance_requires_a_typed_cross_validated_bundle():
    report = validate_artifact(_record(), raise_on_error=False)
    assert report.completeness == "INCOMPLETE"
    assert any("typed provenance bundle" in reason for reason in report.reasons)

    forged = _record()
    forged["provenance"] = {**forged["provenance"], "model_hash": "f" * 64}
    with pytest.raises(ArtifactValidationError, match="embedded provenance"):
        validate_artifact(forged, provenance_bundle=_bundle())


def test_model_construct_does_not_become_a_trusted_provenance_bundle():
    bundle = _bundle()
    unsafe_config = RunConfig.model_construct(
        **{
            **bundle.config.model_dump(),
            "data_availability": bundle.config.data_availability,
            "schema_hash": "f" * 64,
        }
    )
    unsafe = ProvenanceBundle(config=unsafe_config, environment=bundle.environment, manifest=bundle.manifest)
    with pytest.raises(ArtifactValidationError, match="approved run configuration schema"):
        validate_artifact(_record(), provenance_bundle=unsafe)


def test_synthetic_and_unversioned_inputs_are_incomplete():
    synthetic = _record(origin="SYNTHETIC_NON_EVIDENCE")
    synthetic["content_hash"] = digest("ARTIFACT_CONTENT", artifact_content_material(synthetic))
    with pytest.raises(ArtifactValidationError, match="synthetic"):
        validate_artifact(synthetic, provenance_bundle=_bundle())

    blocked_bundle = _bundle(code_revision="UNVERSIONED_BLOCKED")
    blocked = _record(bundle=blocked_bundle)
    with pytest.raises(ArtifactValidationError, match="UNVERSIONED_BLOCKED"):
        validate_artifact(blocked, provenance_bundle=blocked_bundle)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_numeric_value_fails_closed(value: float):
    record = _record()
    record["payload"] = {"result": [value]}
    with pytest.raises(ArtifactValidationError, match="non-finite"):
        validate_artifact(record, provenance_bundle=_bundle())


@pytest.mark.parametrize("denominator", [0, -1, 1.5, True])
def test_top_level_denominator_is_exact_positive_integer(denominator: object):
    with pytest.raises(ArtifactValidationError, match="denominator"):
        validate_artifact(_record(denominator=denominator), provenance_bundle=_bundle())


def test_substring_bait_does_not_satisfy_required_denominator():
    record = _record()
    record.pop("denominator")
    record["payload"] = {"not_a_denominator": 12, "result": {"score": 0.5}}
    record["content_hash"] = digest("ARTIFACT_CONTENT", artifact_content_material(record))
    with pytest.raises(ArtifactValidationError, match="missing top-level denominator"):
        validate_artifact(record, provenance_bundle=_bundle())


def test_nested_state_and_ci_declarations_are_fail_closed():
    nested_state = _record(payload={"result": [{"interrupted": "false"}]})
    with pytest.raises(ArtifactValidationError, match="state flag"):
        validate_artifact(nested_state, provenance_bundle=_bundle())

    missing_nested_ci = _record(payload={"result": [{"ci_applicable": True}]})
    with pytest.raises(ArtifactValidationError, match="confidence interval"):
        validate_artifact(missing_nested_ci, provenance_bundle=_bundle())

    bad_nested_ci = _record()
    bad_nested_ci["payload"] = {"result": [{"ci_applicable": True, "confidence_interval": [0.9, 0.1]}]}
    with pytest.raises(ArtifactValidationError, match="confidence interval"):
        validate_artifact(bad_nested_ci, provenance_bundle=_bundle())


def test_parent_hashes_and_claim_material_change_the_content_hash():
    base = _record()
    changed_parent = {**base, "parent_hashes": ["d" * 64]}
    changed_claim = {**base, "claim_disposition": "NOT_SUPPORTED"}
    assert digest("ARTIFACT_CONTENT", artifact_content_material(base)) != digest("ARTIFACT_CONTENT", artifact_content_material(changed_parent))
    assert digest("ARTIFACT_CONTENT", artifact_content_material(base)) != digest("ARTIFACT_CONTENT", artifact_content_material(changed_claim))
