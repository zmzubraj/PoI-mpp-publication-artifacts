from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig, approved_schema_hash
from poi_mpp.evidence.provenance import EnvironmentManifest, freeze_run
from poi_mpp.evidence.publication_gate import evaluate_publication_gate
from poi_mpp.evidence.validation import ARTIFACT_RECORD_SCHEMA_VERSION, ProvenanceBundle, artifact_content_material


def _bundle(*, parents: list[str] | None = None) -> ProvenanceBundle:
    config = RunConfig.model_validate({"schema_version": "POI_MPP_RUN_CONFIG_V1", "schema_hash": approved_schema_hash(), "run_id": "run-1", "experiment_id": "E1", "origin": "REAL_MODEL_EXECUTION", "authorization_scope": "LOCAL_TEST_ONLY", "model_hash": "a" * 64, "dataset_hash": "b" * 64, "parent_hashes": parents or [], "data_availability": {"total_shards": 12, "samples": 6, "replacement": False}})
    environment = EnvironmentManifest(python_implementation="CPython", python_version="3.11.15", os_name="Linux", os_release="test", machine="x86_64", cpu_model=None, gpu_model=None, package_lock_hash=None, compiler_version=None, foundry_version=None, code_revision="c" * 40)
    return ProvenanceBundle(config=config, environment=environment, manifest=freeze_run(config, environment))


def _record(*, bundle: ProvenanceBundle | None = None, **overrides: object) -> dict[str, object]:
    bundle = bundle or _bundle()
    record: dict[str, object] = {"schema_version": ARTIFACT_RECORD_SCHEMA_VERSION, "artifact_id": "artifact-1", "run_id": "run-1", "experiment_id": "E1", "origin": "REAL_MODEL_EXECUTION", "stage": "FROZEN", "parent_hashes": [], "payload": {"result": {"score": 0.5}}, "denominator": 12, "ci_required": False, "claim_id": "C1", "claim_disposition": "SUPPORTED", "provenance": bundle.manifest.model_dump(mode="json"), **overrides}
    record["content_hash"] = digest("ARTIFACT_CONTENT", artifact_content_material(record))
    return record


def test_complete_negative_and_inconclusive_evidence_remain_complete():
    negative = _record(claim_disposition="NOT_SUPPORTED")
    inconclusive = _record(artifact_id="artifact-2", claim_disposition="INCONCLUSIVE")
    negative_decision = evaluate_publication_gate("C1", [negative], provenance_bundles=[_bundle()])
    inconclusive_decision = evaluate_publication_gate("C1", [inconclusive], provenance_bundles=[_bundle()])
    assert (negative_decision.completeness, negative_decision.claim_support) == ("COMPLETE", "NOT_SUPPORTED")
    assert (inconclusive_decision.completeness, inconclusive_decision.claim_support) == ("COMPLETE", "INCONCLUSIVE")


def test_gate_rejects_forged_content_and_missing_bundle():
    forged = _record()
    forged["payload"] = {"result": {"score": 1.0}}
    decision = evaluate_publication_gate("C1", [forged], provenance_bundles=[_bundle()])
    missing = evaluate_publication_gate("C1", [_record()])
    assert decision.completeness == "INCOMPLETE"
    assert any("content_hash mismatch" in reason for reason in decision.reasons)
    assert missing.completeness == "INCOMPLETE"


def test_gate_rejects_duplicate_identifiers_and_content_hashes():
    first = _record()
    duplicate_id = _record(claim_disposition="SUPPORTED")
    duplicate_hash = _record(artifact_id="artifact-2")
    duplicate_hash["content_hash"] = first["content_hash"]
    ids = evaluate_publication_gate("C1", [first, duplicate_id], provenance_bundles=[_bundle(), _bundle()])
    hashes = evaluate_publication_gate("C1", [first, duplicate_hash], provenance_bundles=[_bundle(), _bundle()])
    assert ids.completeness == "INCOMPLETE"
    assert any("duplicate artifact_id" in reason for reason in ids.reasons)
    assert hashes.completeness == "INCOMPLETE"
    assert any("duplicate content_hash" in reason for reason in hashes.reasons)


def test_gate_rejects_cycles_and_requires_parent_closure():
    first_hash, second_hash = "d" * 64, "e" * 64
    first_bundle = _bundle(parents=[second_hash])
    second_bundle = _bundle(parents=[first_hash])
    first = _record(bundle=first_bundle, parent_hashes=[second_hash])
    second = _record(bundle=second_bundle, artifact_id="artifact-2", parent_hashes=[first_hash])
    first["content_hash"] = first_hash
    second["content_hash"] = second_hash
    cycle = evaluate_publication_gate("C1", [first, second], provenance_bundles=[first_bundle, second_bundle])
    missing = evaluate_publication_gate("C1", [first], provenance_bundles=[first_bundle])
    assert cycle.completeness == "INCOMPLETE"
    assert any("parent cycle" in reason for reason in cycle.reasons)
    assert missing.completeness == "INCOMPLETE"
    assert any("unregistered parent" in reason for reason in missing.reasons)
