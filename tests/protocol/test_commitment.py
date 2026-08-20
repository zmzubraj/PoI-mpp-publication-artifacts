from __future__ import annotations

import pytest

from poi_mpp.protocol.audit_compiler import compile_audit
from poi_mpp.protocol.commitment import commit_response
from poi_mpp.protocol.reference_machine import InvalidTransition
from poi_mpp.protocol.types import ResponseCommitment


def test_commitment_digest_binds_all_roots_and_nonce(task, model):
    baseline = commit_response(
        task=task,
        model=model,
        response_hash="1" * 64,
        trace_root="2" * 64,
        evidence_root="3" * 64,
        artifact_root="4" * 64,
        nonce=b"seed-1",
    )
    changed_trace = commit_response(
        task=task,
        model=model,
        response_hash="1" * 64,
        trace_root="9" * 64,
        evidence_root="3" * 64,
        artifact_root="4" * 64,
        nonce=b"seed-1",
    )
    changed_nonce = commit_response(
        task=task,
        model=model,
        response_hash="1" * 64,
        trace_root="2" * 64,
        evidence_root="3" * 64,
        artifact_root="4" * 64,
        nonce=b"seed-2",
    )
    assert baseline.commitment_hash != changed_trace.commitment_hash
    assert baseline.commitment_hash != changed_nonce.commitment_hash


def test_audit_cannot_compile_before_commitment_finality(task, commitment, policy):
    commitment = commitment.model_copy(update={"finalized_height": None})
    with pytest.raises(InvalidTransition, match="not finalized"):
        compile_audit(policy, task, commitment, b"beacon", 0)


def test_commitment_direct_constructor_is_not_public(task):
    with pytest.raises(ValueError, match="issued via commit_response"):
        ResponseCommitment(
            task_id=task.task_id,
            worker_id=task.worker_id,
            task_class=task.task_class,
            task_epoch=task.epoch,
            task_root="a" * 64,
            model_id="model-1",
            model_manifest_hash="b" * 64,
            response_hash="1" * 64,
            trace_root="2" * 64,
            evidence_root="3" * 64,
            artifact_root="4" * 64,
            nonce_hex="11",
            commitment_hash="5" * 64,
            commitment_height=task.commitment_height,
            commitment_finality_depth=task.commitment_finality_depth,
            finalized_height=task.commitment_height + task.commitment_finality_depth,
        )


def test_compile_audit_rejects_forged_commitment_field_update(task, commitment, policy):
    forged = commitment.model_copy(update={"worker_id": "worker-attacker"})
    with pytest.raises(InvalidTransition, match="commitment is invalid"):
        compile_audit(policy, task, forged, b"beacon", 0)


def test_compile_audit_rejects_forged_finality_relation(task, commitment, policy):
    forged = commitment.model_copy(update={"finalized_height": commitment.finalized_height + 1})
    with pytest.raises(InvalidTransition, match="commitment is invalid"):
        compile_audit(policy, task, forged, b"beacon", 0)
