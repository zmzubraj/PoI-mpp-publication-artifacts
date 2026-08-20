from __future__ import annotations

import pytest

from poi_mpp.protocol.audit_compiler import AuditPolicy, compile_audit
from poi_mpp.protocol.commitment import commit_response
from poi_mpp.protocol.types import (
    AuditDecision,
    ModelManifest,
    Receipt,
    ReceiptState,
    TaskClass,
    TaskSpec,
    TransitionContext,
)


@pytest.fixture()
def task() -> TaskSpec:
    return TaskSpec(
        task_id=1,
        task_root="0xaa" + "aa" * 31,
        worker_id="0x0000000000000000000000000000000000002001",
        task_class=TaskClass.CONSENSUS,
        active=True,
        registered=True,
        credit_budget=90,
        epoch=7,
        deadline=500,
        commitment_height=120,
        commitment_finality_depth=5,
        challenge_window_blocks=9,
        audit_domain_size=16,
    )


@pytest.fixture()
def model() -> ModelManifest:
    return ModelManifest(
        model_root="0xbb" + "bb" * 31,
        runtime_root="0xcc" + "cc" * 31,
        model_manifest_hash="0xdd" + "dd" * 31,
        assurance_class=1,
    )


@pytest.fixture()
def policy() -> AuditPolicy:
    return AuditPolicy(sample_count=4)


@pytest.fixture()
def commitment(task: TaskSpec, model: ModelManifest):
    return commit_response(
        task=task,
        model=model,
        response_hash="0x" + "11" * 32,
        trace_root="0x" + "22" * 32,
        evidence_root="0x" + "33" * 32,
        artifact_root="0x" + "44" * 32,
        nonce=bytes.fromhex("55" * 32),
    )


@pytest.fixture()
def audit_plan(task: TaskSpec, commitment, policy: AuditPolicy):
    return compile_audit(policy, task, commitment, b"beacon-1", 0)


@pytest.fixture()
def receipt(task: TaskSpec, commitment, audit_plan) -> Receipt:
    return Receipt(
        receipt_id=1,
        task_id=task.task_id,
        worker_id=task.worker_id,
        commitment_hash=commitment.commitment_hash,
        audit_id=audit_plan.audit_id,
        state=ReceiptState.PENDING,
        epoch_issued=task.epoch,
        challenge_deadline=task.commitment_height + task.challenge_window_blocks,
        nullifier="0x" + "66" * 32,
        audit_decision=None,
        audit_accepted=False,
        da_decision=None,
        data_availability_passed=False,
        activated_epoch=None,
        challenge_reason=None,
        slash_reason=None,
    )


@pytest.fixture()
def context_without_gates(task: TaskSpec) -> TransitionContext:
    return TransitionContext(
        current_height=task.commitment_height + task.challenge_window_blocks - 1,
        current_epoch=task.epoch,
        used_nullifiers=frozenset(),
    )


@pytest.fixture()
def mature_context(task: TaskSpec) -> TransitionContext:
    return TransitionContext(
        current_height=task.commitment_height + task.challenge_window_blocks,
        current_epoch=task.epoch + 1,
        used_nullifiers=frozenset(),
    )
