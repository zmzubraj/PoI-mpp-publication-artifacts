from __future__ import annotations

import pytest

from poi_mpp.protocol.credit import allocate_credit, derive_active_weight
from poi_mpp.protocol.types import AuditDecision, ReceiptState, TaskClass, TaskSpec


def _task(
    *,
    task_id: int = 1,
    worker_id: str = "0x0000000000000000000000000000000000002001",
    epoch: int = 7,
    task_class: TaskClass = TaskClass.CONSENSUS,
    registered: bool = True,
    credit_budget: int = 90,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        task_root="0xaa" + "aa" * 31,
        worker_id=worker_id,
        task_class=task_class,
        registered=registered,
        credit_budget=credit_budget,
        epoch=epoch,
        deadline=500,
        commitment_height=120,
        commitment_finality_depth=5,
        challenge_window_blocks=9,
        audit_domain_size=16,
    )


def test_collateral_cannot_create_weight():
    assert derive_active_weight(credit=0, collateral=10**18, beta=10, concentration_cap=10**18) == 0


def test_task_credit_never_exceeds_budget(receipt):
    task = _task()
    active = receipt.model_copy(
        update={
            "state": ReceiptState.ACTIVE,
            "audit_decision": AuditDecision.ACCEPT,
            "audit_accepted": True,
            "da_decision": True,
            "data_availability_passed": True,
            "activated_epoch": receipt.epoch_issued + 1,
        }
    )
    allocation = allocate_credit(task, [active])
    assert sum(allocation.by_worker.values()) <= task.credit_budget


def test_credit_allocation_records_canonical_per_receipt_shares(receipt):
    task = _task(task_id=receipt.task_id, worker_id=receipt.worker_id, epoch=receipt.epoch_issued)
    first = receipt.model_copy(
        update={
            "receipt_id": 1,
            "state": ReceiptState.ACTIVE,
            "audit_decision": AuditDecision.ACCEPT,
            "audit_accepted": True,
            "da_decision": True,
            "data_availability_passed": True,
            "activated_epoch": receipt.epoch_issued + 1,
            "nullifier": "0x" + "66" * 32,
        }
    )
    second = first.model_copy(update={"receipt_id": 2, "nullifier": "0x" + "77" * 32})
    allocation = allocate_credit(task, [first, second])
    assert allocation.by_receipt == {1: 45, 2: 45}


def test_service_and_unregistered_tasks_do_not_mint_credit(receipt):
    active = receipt.model_copy(
        update={
            "state": ReceiptState.ACTIVE,
            "audit_decision": AuditDecision.ACCEPT,
            "audit_accepted": True,
            "da_decision": True,
            "data_availability_passed": True,
            "activated_epoch": receipt.epoch_issued + 1,
        }
    )
    assert allocate_credit(_task(task_class=TaskClass.SERVICE), [active]).total_credit == 0
    assert allocate_credit(_task(registered=False), [active]).total_credit == 0


def test_forged_active_receipt_does_not_mint_credit(receipt):
    task = _task(task_id=receipt.task_id, worker_id=receipt.worker_id, epoch=receipt.epoch_issued)
    forged = receipt.model_copy(
        update={
            "state": ReceiptState.ACTIVE,
            "audit_decision": AuditDecision.ACCEPT,
            "audit_accepted": True,
            "data_availability_passed": True,
            "activated_epoch": receipt.epoch_issued + 1,
        }
    )
    with pytest.raises(ValueError, match="receipt is not canonically valid"):
        allocate_credit(task, [forged])


def test_duplicate_receipt_id_and_nullifier_are_rejected(receipt):
    task = _task(task_id=receipt.task_id, worker_id=receipt.worker_id, epoch=receipt.epoch_issued)
    active_one = receipt.model_copy(
        update={
            "state": ReceiptState.ACTIVE,
            "audit_decision": AuditDecision.ACCEPT,
            "audit_accepted": True,
            "da_decision": True,
            "data_availability_passed": True,
            "activated_epoch": receipt.epoch_issued + 1,
        }
    )
    active_two = active_one.model_copy(update={"worker_id": "0x0000000000000000000000000000000000002002"})
    with pytest.raises(ValueError, match="duplicate receipt_id"):
        allocate_credit(task, [active_one, active_two])
    with pytest.raises(ValueError, match="duplicate nullifier"):
        allocate_credit(
            task,
            [active_one, active_one.model_copy(update={"receipt_id": 2})],
        )


def test_receipts_must_mature_in_exact_next_epoch(receipt):
    task = _task(task_id=receipt.task_id, worker_id=receipt.worker_id, epoch=receipt.epoch_issued)
    early = receipt.model_copy(
        update={
            "state": ReceiptState.ACTIVE,
            "audit_decision": AuditDecision.ACCEPT,
            "audit_accepted": True,
            "da_decision": True,
            "data_availability_passed": True,
            "activated_epoch": receipt.epoch_issued,
        }
    )
    late = early.model_copy(update={"activated_epoch": receipt.epoch_issued + 2})
    with pytest.raises(ValueError, match="next epoch"):
        allocate_credit(task, [early])
    with pytest.raises(ValueError, match="next epoch"):
        allocate_credit(task, [late])
