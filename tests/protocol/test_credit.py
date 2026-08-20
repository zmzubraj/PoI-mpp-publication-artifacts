from __future__ import annotations

from poi_mpp.protocol.credit import allocate_credit, derive_active_weight
from poi_mpp.protocol.types import ReceiptState, TaskClass, TaskSpec


def _task(*, task_class: TaskClass = TaskClass.CONSENSUS, registered: bool = True, credit_budget: int = 90) -> TaskSpec:
    return TaskSpec(
        task_id="task-credit-1",
        worker_id="worker-1",
        task_class=task_class,
        registered=registered,
        epoch=7,
        commitment_height=120,
        commitment_finality_depth=5,
        challenge_window_blocks=9,
        audit_domain_size=16,
        credit_budget=credit_budget,
    )


def test_collateral_cannot_create_weight():
    assert derive_active_weight(credit=0, collateral=10**18, beta=10, concentration_cap=10**18) == 0


def test_task_credit_never_exceeds_budget(receipt):
    task = _task()
    active = receipt.model_copy(
        update={
            "state": ReceiptState.ACTIVE,
            "audit_accepted": True,
            "data_availability_passed": True,
            "activated_epoch": receipt.epoch_issued + 1,
        }
    )
    allocation = allocate_credit(task, [active])
    assert sum(allocation.by_worker.values()) <= task.credit_budget


def test_service_and_unregistered_tasks_do_not_mint_credit(receipt):
    active = receipt.model_copy(
        update={
            "state": ReceiptState.ACTIVE,
            "audit_accepted": True,
            "data_availability_passed": True,
            "activated_epoch": receipt.epoch_issued + 1,
        }
    )
    assert allocate_credit(_task(task_class=TaskClass.SERVICE), [active]).total_credit == 0
    assert allocate_credit(_task(registered=False), [active]).total_credit == 0
