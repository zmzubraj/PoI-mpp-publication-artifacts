"""Credit allocation and active-weight derivation for matured receipts."""

from __future__ import annotations

from typing import Iterable

from pydantic import ConfigDict

from poi_mpp.protocol.types import Receipt, ReceiptState, TaskClass, TaskSpec
from pydantic import BaseModel


class CreditAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    by_worker: dict[str, int]
    total_credit: int


def _eligible_receipts(task: TaskSpec, receipts: Iterable[Receipt]) -> list[Receipt]:
    return sorted(
        [
            receipt
            for receipt in receipts
            if receipt.task_id == task.task_id
            and receipt.state is ReceiptState.ACTIVE
            and receipt.activated_epoch is not None
            and receipt.activated_epoch > receipt.epoch_issued
        ],
        key=lambda receipt: (receipt.worker_id, receipt.receipt_id, receipt.commitment_hash),
    )


def allocate_credit(task: TaskSpec, matured_receipts: Iterable[Receipt]) -> CreditAllocation:
    if task.task_class is not TaskClass.CONSENSUS or not task.registered or task.credit_budget == 0:
        return CreditAllocation(task_id=task.task_id, by_worker={}, total_credit=0)
    eligible = _eligible_receipts(task, matured_receipts)
    if not eligible:
        return CreditAllocation(task_id=task.task_id, by_worker={}, total_credit=0)
    base_share, remainder = divmod(task.credit_budget, len(eligible))
    by_worker: dict[str, int] = {}
    for index, receipt in enumerate(eligible):
        share = base_share + (1 if index < remainder else 0)
        if share == 0:
            continue
        by_worker[receipt.worker_id] = by_worker.get(receipt.worker_id, 0) + share
    total_credit = sum(by_worker.values())
    return CreditAllocation(task_id=task.task_id, by_worker=by_worker, total_credit=total_credit)


def derive_active_weight(credit: int, collateral: int, beta: int, concentration_cap: int) -> int:
    if credit < 0 or collateral < 0 or concentration_cap < 0:
        raise ValueError("credit, collateral, and concentration_cap must be non-negative")
    if beta <= 0:
        raise ValueError("beta must be positive")
    if credit == 0 or collateral == 0 or concentration_cap == 0:
        return 0
    return min(credit, collateral // beta, concentration_cap)
