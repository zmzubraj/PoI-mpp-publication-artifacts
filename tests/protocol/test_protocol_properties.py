from __future__ import annotations

from itertools import permutations

import pytest

from poi_mpp.protocol.receipt import ActivateReceipt, OpenChallenge, RecordAudit, RecordDataAvailability, SlashReceipt
from poi_mpp.protocol.reference_machine import InvalidTransition, transition
from poi_mpp.protocol.types import AuditDecision, ReceiptState


def test_no_event_order_activates_without_all_gates(receipt, mature_context, context_without_gates):
    events = (
        RecordAudit(decision=AuditDecision.ACCEPT),
        RecordDataAvailability(available=True),
        ActivateReceipt(),
    )
    successes = 0
    for ordered in permutations(events):
        current = receipt
        for event in ordered:
            context = mature_context if not isinstance(event, ActivateReceipt) else context_without_gates
            try:
                current = transition(current, event, context)
            except InvalidTransition:
                break
        else:
            if current.state is ReceiptState.ACTIVE:
                successes += 1
    assert successes == 0


def test_slashed_receipt_never_returns_active(receipt, mature_context):
    challenged = transition(
        transition(
            transition(receipt, RecordAudit(decision=AuditDecision.ACCEPT), mature_context),
            RecordDataAvailability(available=True),
            mature_context,
        ),
        OpenChallenge(reason="challenge"),
        mature_context,
    )
    slashed = transition(challenged, SlashReceipt(reason="challenge"), mature_context)
    for event in (
        RecordAudit(decision=AuditDecision.ACCEPT),
        RecordDataAvailability(available=True),
        ActivateReceipt(),
    ):
        with pytest.raises(InvalidTransition):
            transition(slashed, event, mature_context)
