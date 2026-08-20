"""Fail-closed receipt transition rules for the PoI protocol kernel."""

from __future__ import annotations

from poi_mpp.protocol.receipt import (
    ActivateReceipt,
    ExpireReceipt,
    OpenChallenge,
    ProtocolEvent,
    RecordAudit,
    RecordDataAvailability,
    SlashReceipt,
)
from poi_mpp.protocol.types import Receipt, ReceiptState, TransitionContext


class InvalidTransition(ValueError):
    """Raised when an event would violate the declared receipt lifecycle."""


def _require_pending(receipt: Receipt, event_name: str) -> None:
    if receipt.state is not ReceiptState.PENDING:
        raise InvalidTransition(f"{event_name} requires a pending receipt")


def transition(receipt: Receipt, event: ProtocolEvent, context: TransitionContext) -> Receipt:
    if isinstance(event, RecordAudit):
        _require_pending(receipt, "RecordAudit")
        if receipt.audit_decision is not None:
            raise InvalidTransition("audit decision is already recorded")
        if receipt.da_decision is not None:
            raise InvalidTransition("audit decision cannot be recorded after data availability")
        if event.decision == "ACCEPT":
            return receipt.model_copy(
                update={"audit_decision": "ACCEPT", "audit_accepted": True}
            )
        if event.decision == "ABSTAIN":
            return receipt.model_copy(
                update={
                    "state": ReceiptState.ABSTAINED,
                    "audit_decision": "ABSTAIN",
                    "audit_accepted": False,
                    "data_availability_passed": False,
                }
            )
        return receipt.model_copy(
            update={
                "state": ReceiptState.REJECTED,
                "audit_decision": "REJECT",
                "audit_accepted": False,
                "data_availability_passed": False,
            }
        )
    if isinstance(event, RecordDataAvailability):
        _require_pending(receipt, "RecordDataAvailability")
        if receipt.da_decision is not None:
            raise InvalidTransition("data availability is already recorded")
        if event.available:
            return receipt.model_copy(
                update={"da_decision": True, "data_availability_passed": True}
            )
        return receipt.model_copy(
            update={
                "state": ReceiptState.DA_FAILED,
                "da_decision": False,
                "data_availability_passed": False,
            }
        )
    if isinstance(event, OpenChallenge):
        _require_pending(receipt, "OpenChallenge")
        if receipt.audit_decision != "ACCEPT":
            raise InvalidTransition("receipt cannot be challenged before audit acceptance")
        if receipt.da_decision is not True:
            raise InvalidTransition("receipt cannot be challenged before DA confirmation")
        if context.current_height > receipt.challenge_deadline:
            raise InvalidTransition("receipt cannot be challenged after the challenge window")
        return receipt.model_copy(
            update={
                "state": ReceiptState.CHALLENGED,
                "challenge_reason": event.reason,
            }
        )
    if isinstance(event, ActivateReceipt):
        _require_pending(receipt, "ActivateReceipt")
        if receipt.audit_decision != "ACCEPT":
            raise InvalidTransition("receipt cannot activate before audit acceptance")
        if receipt.da_decision is not True:
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
    if isinstance(event, ExpireReceipt):
        _require_pending(receipt, "ExpireReceipt")
        if context.current_height < receipt.challenge_deadline:
            raise InvalidTransition("receipt cannot expire before the challenge window elapses")
        if receipt.audit_decision == "ACCEPT" and receipt.da_decision is True:
            raise InvalidTransition("ready receipts must activate or be challenged, not expire")
        return receipt.model_copy(update={"state": ReceiptState.EXPIRED})
    if isinstance(event, SlashReceipt):
        if receipt.state is not ReceiptState.CHALLENGED:
            raise InvalidTransition("receipt must be in an open challenge before slashing")
        return receipt.model_copy(
            update={
                "state": ReceiptState.SLASHED,
                "activated_epoch": None,
                "slash_reason": event.reason,
            }
        )
    raise TypeError(f"unsupported protocol event: {type(event)!r}")
