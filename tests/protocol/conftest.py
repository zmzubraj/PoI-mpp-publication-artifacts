from __future__ import annotations

import pytest

from poi_mpp.protocol.audit_compiler import AuditPolicy, compile_audit
from poi_mpp.protocol.commitment import commit_response
from poi_mpp.protocol.types import (
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
        task_id="task-grounded-1",
        worker_id="worker-1",
        task_class=TaskClass.CONSENSUS,
        registered=True,
        epoch=7,
        commitment_height=120,
        commitment_finality_depth=5,
        challenge_window_blocks=9,
        audit_domain_size=16,
    )


@pytest.fixture()
def model() -> ModelManifest:
    return ModelManifest(
        model_id="open-weight-3b",
        model_root="a" * 64,
        revision="b" * 40,
        parameter_count=3_000_000_000,
    )


@pytest.fixture()
def policy() -> AuditPolicy:
    return AuditPolicy(sample_count=4)


@pytest.fixture()
def commitment(task: TaskSpec, model: ModelManifest):
    return commit_response(
        task=task,
        model=model,
        response_hash="1" * 64,
        trace_root="2" * 64,
        evidence_root="3" * 64,
        artifact_root="4" * 64,
        nonce=b"seed-1",
    )


@pytest.fixture()
def audit_plan(task: TaskSpec, commitment, policy: AuditPolicy):
    return compile_audit(policy, task, commitment, b"beacon-1", 0)


@pytest.fixture()
def receipt(task: TaskSpec, commitment, audit_plan) -> Receipt:
    return Receipt(
        receipt_id="receipt-1",
        task_id=task.task_id,
        worker_id=task.worker_id,
        commitment_hash=commitment.commitment_hash,
        audit_id=audit_plan.audit_id,
        state=ReceiptState.PENDING,
        epoch_issued=task.epoch,
        challenge_deadline=task.commitment_height + task.challenge_window_blocks,
        nullifier="5" * 64,
        audit_accepted=False,
        data_availability_passed=False,
        activated_epoch=None,
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
