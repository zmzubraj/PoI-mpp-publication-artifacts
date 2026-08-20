from poi_mpp.evidence.publication_gate import evaluate_publication_gate

from poi_mpp.evidence.models import ArtifactRecord, ArtifactStage, EvidenceOrigin


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


def test_publication_gate_rejects_synthetic_parent():
    synthetic_record = _frozen_record(origin="SYNTHETIC_NON_EVIDENCE")
    synthetic_record["provenance"] = {
        **synthetic_record["provenance"],
        "origin": "SYNTHETIC_NON_EVIDENCE",
    }

    decision = evaluate_publication_gate("C3", [synthetic_record])

    assert decision.completeness == "INCOMPLETE"
    assert "synthetic" in decision.reasons[0].lower()


def test_complete_negative_evidence_remains_publishable():
    negative = _frozen_record(claim_id="C1", claim_disposition="NOT_SUPPORTED")

    decision = evaluate_publication_gate("C1", [negative])

    assert decision.completeness == "COMPLETE"
    assert decision.claim_support == "NOT_SUPPORTED"


def test_complete_inconclusive_evidence_remains_publishable():
    inconclusive = _frozen_record(claim_id="C1", claim_disposition="INCONCLUSIVE")

    decision = evaluate_publication_gate("C1", [inconclusive])

    assert decision.completeness == "COMPLETE"
    assert decision.claim_support == "INCONCLUSIVE"


def test_missing_parent_keeps_claim_gate_incomplete_even_if_claim_is_supported():
    record = _frozen_record(
        parent_hashes=["e" * 64], claim_id="C1", claim_disposition="SUPPORTED"
    )
    record["provenance"] = {
        **record["provenance"],
        "parent_hashes": ["e" * 64],
    }

    decision = evaluate_publication_gate("C1", [record])

    assert decision.completeness == "INCOMPLETE"
    assert decision.claim_support == "INCONCLUSIVE"
    assert any("unregistered parent" in reason for reason in decision.reasons)


def test_mixed_complete_claim_dispositions_are_inconclusive_not_rewritten():
    supported = _frozen_record(claim_id="C1", claim_disposition="SUPPORTED")
    negative = _frozen_record(
        artifact_id="artifact-2", claim_id="C1", claim_disposition="NOT_SUPPORTED"
    )

    decision = evaluate_publication_gate("C1", [supported, negative])

    assert decision.completeness == "COMPLETE"
    assert decision.claim_support == "INCONCLUSIVE"
    assert any("mixed" in reason for reason in decision.reasons)


def test_empty_or_unversioned_input_fails_closed():
    empty = evaluate_publication_gate("C1", [])
    assert empty.completeness == "INCOMPLETE"

    blocked = _frozen_record(claim_id="C1", claim_disposition="SUPPORTED")
    blocked["provenance"] = {
        **blocked["provenance"],
        "code_revision": "UNVERSIONED_BLOCKED",
    }
    decision = evaluate_publication_gate("C1", [blocked])
    assert decision.completeness == "INCOMPLETE"
    assert any("UNVERSIONED_BLOCKED" in reason for reason in decision.reasons)
