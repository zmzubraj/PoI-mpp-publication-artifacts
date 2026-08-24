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
from poi_mpp.protocol.types import (
    AuditDecision,
    Receipt,
    ReceiptState,
    ReceiptVerificationMode,
    TransitionContext,
)


class InvalidTransition(ValueError):
    """Raised when an event would violate the declared receipt lifecycle."""


def _require_pending(receipt: Receipt, event_name: str) -> None:
    if receipt.state is not ReceiptState.PENDING:
        raise InvalidTransition(f"{event_name} requires a pending receipt")


def transition(
    receipt: Receipt,
    event: ProtocolEvent,
    context: TransitionContext,
    *,
    semantic_verification_result: object | None = None,
) -> Receipt:
    if isinstance(event, RecordAudit):
        _require_pending(receipt, "RecordAudit")
        if receipt.audit_decision is not None:
            raise InvalidTransition("audit decision is already recorded")
        if receipt.da_decision is not None:
            raise InvalidTransition("audit decision cannot be recorded after data availability")
        receipt_is_semantic = (
            receipt.verification_mode is ReceiptVerificationMode.SEMANTIC_PUBLICATION
        )
        event_is_semantic = event.semantic_task_root is not None
        if receipt_is_semantic != event_is_semantic:
            raise InvalidTransition("semantic audit binding requirement mismatch")
        if receipt_is_semantic:
            if semantic_verification_result is None:
                raise InvalidTransition("semantic verification result is required")
            from poi_mpp.auditor.semantic.verifier_v2 import (
                GroundedVerificationResultV2,
                audit_decision_from_verification,
            )

            if not isinstance(
                semantic_verification_result,
                GroundedVerificationResultV2,
            ):
                raise InvalidTransition("semantic verification result type is invalid")
            if event.decision is not audit_decision_from_verification(
                semantic_verification_result
            ):
                raise InvalidTransition("semantic audit decision mismatch")
            if event.verification_result_digest != (
                f"0x{semantic_verification_result.result_digest}"
            ):
                raise InvalidTransition("semantic verification result digest mismatch")
            if event.semantic_task_root != semantic_verification_result.task_root:
                raise InvalidTransition("semantic verification result task_root mismatch")
            if event.semantic_response_hash != (
                f"0x{semantic_verification_result.response_hash}"
            ):
                raise InvalidTransition("semantic verification result response_hash mismatch")
            if event.semantic_commitment_hash != (
                semantic_verification_result.response_commitment_hash
            ):
                raise InvalidTransition("semantic verification result commitment_hash mismatch")
            if event.semantic_task_root != receipt.semantic_task_root:
                raise InvalidTransition("semantic audit task_root mismatch")
            if event.semantic_response_hash != receipt.semantic_response_hash:
                raise InvalidTransition("semantic audit response_hash mismatch")
            if event.semantic_commitment_hash != receipt.commitment_hash:
                raise InvalidTransition("semantic audit commitment_hash mismatch")
        elif semantic_verification_result is not None:
            raise InvalidTransition("legacy receipts cannot consume semantic verification results")
        audit_update = {
            "audit_verification_result_digest": event.verification_result_digest,
        }
        if event.decision is AuditDecision.ACCEPT:
            return receipt.model_copy(
                update={
                    "audit_decision": AuditDecision.ACCEPT,
                    "audit_accepted": True,
                    **audit_update,
                }
            )
        if event.decision is AuditDecision.ABSTAIN:
            return receipt.model_copy(
                update={
                    "state": ReceiptState.ABSTAINED,
                    "audit_decision": AuditDecision.ABSTAIN,
                    "audit_accepted": False,
                    "data_availability_passed": False,
                    **audit_update,
                }
            )
        return receipt.model_copy(
            update={
                "state": ReceiptState.REJECTED,
                "audit_decision": AuditDecision.REJECT,
                "audit_accepted": False,
                "data_availability_passed": False,
                **audit_update,
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
        if receipt.audit_decision is not AuditDecision.ACCEPT:
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
        if receipt.audit_decision is not AuditDecision.ACCEPT:
            raise InvalidTransition("receipt cannot activate before audit acceptance")
        if receipt.da_decision is not True:
            raise InvalidTransition("receipt cannot activate before DA confirmation")
        if context.current_height < receipt.challenge_deadline:
            raise InvalidTransition("receipt cannot activate before challenge window elapses")
        target_epoch = receipt.epoch_issued + 1
        if context.current_epoch <= receipt.epoch_issued:
            raise InvalidTransition("current-epoch receipts cannot create current-epoch authority")
        if context.current_epoch > target_epoch:
            raise InvalidTransition("receipt activation window is closed")
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
        if receipt.audit_decision is AuditDecision.ACCEPT and receipt.da_decision is True:
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
