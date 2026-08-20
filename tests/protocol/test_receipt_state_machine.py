from __future__ import annotations

import pytest

from poi_mpp.protocol.receipt import ActivateReceipt, RecordAudit, RecordDataAvailability, SlashReceipt
from poi_mpp.protocol.reference_machine import InvalidTransition, transition
from poi_mpp.protocol.types import ReceiptState, TransitionContext


def test_receipt_cannot_activate_before_audit_da_and_window(receipt, context_without_gates):
    with pytest.raises(InvalidTransition):
        transition(receipt, ActivateReceipt(), context_without_gates)


def test_receipt_activates_only_after_all_gates(receipt, mature_context):
    audited = transition(receipt, RecordAudit(decision="ACCEPT"), mature_context)
    available = transition(audited, RecordDataAvailability(available=True), mature_context)
    activated = transition(available, ActivateReceipt(), mature_context)
    assert activated.state is ReceiptState.ACTIVE
    assert activated.activated_epoch == mature_context.current_epoch


def test_successful_challenge_slashes_receipt(receipt, mature_context):
    slashed = transition(receipt, SlashReceipt(reason="semantic mismatch"), mature_context)
    assert slashed.state is ReceiptState.SLASHED
    with pytest.raises(InvalidTransition):
        transition(slashed, ActivateReceipt(), mature_context)


def test_reused_nullifier_is_rejected(receipt, mature_context):
    audited = transition(receipt, RecordAudit(decision="ACCEPT"), mature_context)
    available = transition(audited, RecordDataAvailability(available=True), mature_context)
    reused = TransitionContext(
        current_height=mature_context.current_height,
        current_epoch=mature_context.current_epoch,
        used_nullifiers=frozenset({receipt.nullifier}),
    )
    with pytest.raises(InvalidTransition, match="nullifier"):
        transition(available, ActivateReceipt(), reused)
