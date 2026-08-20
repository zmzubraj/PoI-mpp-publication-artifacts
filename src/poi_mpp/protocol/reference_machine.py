"""Fail-closed receipt transition rules for the PoI protocol kernel."""

from __future__ import annotations

from poi_mpp.protocol.receipt import ActivateReceipt, ProtocolEvent, RecordAudit, RecordDataAvailability, SlashReceipt
from poi_mpp.protocol.types import Receipt, ReceiptState, TransitionContext


class InvalidTransition(ValueError):
    """Raised when an event would violate the declared receipt lifecycle."""


def _require_pending(receipt: Receipt, event_name: str) -> None:
    if receipt.state is not ReceiptState.PENDING:
        raise InvalidTransition(f"{event_name} requires a pending receipt")


def transition(receipt: Receipt, event: ProtocolEvent, context: TransitionContext) -> Receipt:
    if isinstance(event, RecordAudit):
        _require_pending(receipt, "RecordAudit")
        if event.decision == "ACCEPT":
            return receipt.model_copy(update={"audit_accepted": True})
        return receipt.model_copy(
            update={
                "state": ReceiptState.REJECTED,
                "audit_accepted": False,
                "data_availability_passed": False,
            }
        )
    if isinstance(event, RecordDataAvailability):
        _require_pending(receipt, "RecordDataAvailability")
        if event.available:
            return receipt.model_copy(update={"data_availability_passed": True})
        return receipt.model_copy(
            update={
                "state": ReceiptState.REJECTED,
                "data_availability_passed": False,
            }
        )
    if isinstance(event, ActivateReceipt):
        _require_pending(receipt, "ActivateReceipt")
        if not receipt.audit_accepted:
            raise InvalidTransition("receipt cannot activate before audit acceptance")
        if not receipt.data_availability_passed:
            raise InvalidTransition("receipt cannot activate before DA confirmation")
        if context.current_height < receipt.challenge_deadline:
            raise InvalidTransition("receipt cannot activate before challenge window elapses")
        if context.current_epoch <= receipt.epoch_issued:
            raise InvalidTransition("current-epoch receipts cannot create current-epoch authority")
        if receipt.nullifier in context.used_nullifiers:
            raise InvalidTransition("nullifier has already been used")
        return receipt.model_copy(
            update={
                "state": ReceiptState.ACTIVE,
                "activated_epoch": context.current_epoch,
            }
        )
    if isinstance(event, SlashReceipt):
        if receipt.state in {ReceiptState.REJECTED, ReceiptState.SLASHED}:
            raise InvalidTransition("slashed or rejected receipts cannot be slashed again")
        return receipt.model_copy(
            update={
                "state": ReceiptState.SLASHED,
                "activated_epoch": None,
                "slash_reason": event.reason,
            }
        )
    raise TypeError(f"unsupported protocol event: {type(event)!r}")
