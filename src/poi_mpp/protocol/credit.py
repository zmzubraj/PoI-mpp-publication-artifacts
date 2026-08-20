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


def _canonical_receipt(receipt: Receipt) -> Receipt:
    try:
        return Receipt.model_validate(receipt.model_dump(mode="json"))
    except Exception as error:  # pragma: no cover - defensive boundary
        raise ValueError("receipt is not canonically valid") from error


def _eligible_receipts(
    task: TaskSpec,
    receipts: Iterable[Receipt],
    *,
    target_epoch: int,
) -> list[Receipt]:
    task_receipts: list[Receipt] = []
    seen_receipt_ids: set[str] = set()
    seen_nullifiers: set[str] = set()
    for raw_receipt in receipts:
        receipt = _canonical_receipt(raw_receipt)
        if receipt.task_id != task.task_id:
            continue
        if receipt.state is not ReceiptState.ACTIVE:
            continue
        if receipt.receipt_id in seen_receipt_ids:
            raise ValueError("duplicate receipt_id is not allowed")
        if receipt.nullifier in seen_nullifiers:
            raise ValueError("duplicate nullifier is not allowed")
        seen_receipt_ids.add(receipt.receipt_id)
        seen_nullifiers.add(receipt.nullifier)
        if (
            receipt.audit_decision != "ACCEPT"
            or not receipt.audit_accepted
            or receipt.da_decision is not True
            or not receipt.data_availability_passed
            or receipt.challenge_reason is not None
            or receipt.slash_reason is not None
        ):
            raise ValueError("receipt is not canonically valid")
        if receipt.epoch_issued != task.epoch or receipt.activated_epoch != target_epoch:
            raise ValueError("active receipts must mature in the exact next epoch")
        task_receipts.append(receipt)
    return sorted(
        task_receipts,
        key=lambda receipt: (receipt.worker_id, receipt.receipt_id, receipt.commitment_hash),
    )


def allocate_credit(
    task: TaskSpec,
    matured_receipts: Iterable[Receipt],
    *,
    target_epoch: int | None = None,
) -> CreditAllocation:
    allocation_epoch = task.epoch + 1 if target_epoch is None else target_epoch
    if allocation_epoch <= task.epoch:
        raise ValueError("target_epoch must be the exact next epoch after the task epoch")
    if allocation_epoch != task.epoch + 1:
        raise ValueError("target_epoch must be the exact next epoch after the task epoch")
    if task.task_class is not TaskClass.CONSENSUS or not task.registered or task.credit_budget == 0:
        return CreditAllocation(task_id=task.task_id, by_worker={}, total_credit=0)
    eligible = _eligible_receipts(task, matured_receipts, target_epoch=allocation_epoch)
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
