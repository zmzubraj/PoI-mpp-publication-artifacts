from __future__ import annotations

import pytest

from poi_mpp.protocol.receipt import (
    ActivateReceipt,
    ExpireReceipt,
    OpenChallenge,
    RecordAudit,
    RecordDataAvailability,
    SlashReceipt,
)
from poi_mpp.protocol.reference_machine import InvalidTransition, transition
from poi_mpp.protocol.types import AuditDecision, Receipt, ReceiptState, TransitionContext


def _assert_roundtrip_valid(receipt: Receipt) -> None:
    assert Receipt.model_validate(receipt.model_dump(mode="json")) == receipt


def test_receipt_cannot_activate_before_audit_da_and_window(receipt, context_without_gates):
    with pytest.raises(InvalidTransition):
        transition(receipt, ActivateReceipt(), context_without_gates)


def test_receipt_activates_only_after_all_gates(receipt, mature_context):
    audited = transition(receipt, RecordAudit(decision=AuditDecision.ACCEPT), mature_context)
    available = transition(audited, RecordDataAvailability(available=True), mature_context)
    activated = transition(available, ActivateReceipt(), mature_context)
    assert activated.state is ReceiptState.ACTIVE
    assert activated.activated_epoch == mature_context.current_epoch
    _assert_roundtrip_valid(activated)


def test_successful_challenge_slashes_receipt(receipt, mature_context):
    audited = transition(receipt, RecordAudit(decision=AuditDecision.ACCEPT), mature_context)
    available = transition(audited, RecordDataAvailability(available=True), mature_context)
    challenged = transition(available, OpenChallenge(reason="semantic mismatch"), mature_context)
    assert challenged.state is ReceiptState.CHALLENGED
    _assert_roundtrip_valid(challenged)
    slashed = transition(challenged, SlashReceipt(reason="semantic mismatch"), mature_context)
    assert slashed.state is ReceiptState.SLASHED
    _assert_roundtrip_valid(slashed)
    with pytest.raises(InvalidTransition):
        transition(slashed, ActivateReceipt(), mature_context)


def test_reused_nullifier_is_rejected(receipt, mature_context):
    audited = transition(receipt, RecordAudit(decision=AuditDecision.ACCEPT), mature_context)
    available = transition(audited, RecordDataAvailability(available=True), mature_context)
    reused = TransitionContext(
        current_height=mature_context.current_height,
        current_epoch=mature_context.current_epoch,
        used_nullifiers=frozenset({receipt.nullifier}),
    )
    with pytest.raises(InvalidTransition, match="nullifier"):
        transition(available, ActivateReceipt(), reused)


def test_duplicate_audit_record_is_rejected(receipt, mature_context):
    audited = transition(receipt, RecordAudit(decision=AuditDecision.ACCEPT), mature_context)
    with pytest.raises(InvalidTransition, match="already recorded"):
        transition(audited, RecordAudit(decision=AuditDecision.ABSTAIN), mature_context)


def test_duplicate_data_availability_record_is_rejected(receipt, mature_context):
    available = transition(receipt, RecordDataAvailability(available=True), mature_context)
    with pytest.raises(InvalidTransition, match="already recorded"):
        transition(available, RecordDataAvailability(available=False), mature_context)


def test_abstained_receipt_has_explicit_terminal_state(receipt, mature_context):
    abstained = transition(receipt, RecordAudit(decision=AuditDecision.ABSTAIN), mature_context)
    assert abstained.state is ReceiptState.ABSTAINED
    _assert_roundtrip_valid(abstained)


def test_failed_data_availability_has_explicit_terminal_state(receipt, mature_context):
    failed = transition(receipt, RecordDataAvailability(available=False), mature_context)
    assert failed.state is ReceiptState.DA_FAILED
    _assert_roundtrip_valid(failed)


def test_slash_requires_open_challenge(receipt, mature_context):
    with pytest.raises(InvalidTransition, match="challenge"):
        transition(receipt, SlashReceipt(reason="semantic mismatch"), mature_context)


def test_receipt_can_expire_without_activation_prerequisites(receipt, mature_context):
    expired = transition(receipt, ExpireReceipt(), mature_context)
    assert expired.state is ReceiptState.EXPIRED
    _assert_roundtrip_valid(expired)


@pytest.mark.parametrize("decision", [AuditDecision.REJECT, AuditDecision.ABSTAIN])
def test_terminal_audit_after_data_availability_is_forbidden(receipt, mature_context, decision):
    available = transition(receipt, RecordDataAvailability(available=True), mature_context)
    with pytest.raises(InvalidTransition, match="data availability"):
        transition(available, RecordAudit(decision=decision), mature_context)


def test_rejected_receipt_roundtrips_after_audit_terminal_state(receipt, mature_context):
    rejected = transition(receipt, RecordAudit(decision=AuditDecision.REJECT), mature_context)
    assert rejected.state is ReceiptState.REJECTED
    _assert_roundtrip_valid(rejected)
