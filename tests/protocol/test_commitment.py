from __future__ import annotations

import pytest

from poi_mpp.protocol.audit_compiler import compile_audit
from poi_mpp.protocol.commitment import commit_response
from poi_mpp.protocol.reference_machine import InvalidTransition


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
