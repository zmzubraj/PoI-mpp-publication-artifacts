from __future__ import annotations

import json
from pathlib import Path

import pytest

from poi_mpp.protocol.commitment import commit_response
from poi_mpp.protocol.credit import allocate_credit, derive_active_weight
from poi_mpp.protocol.receipt import (
    ActivateReceipt,
    ExpireReceipt,
    OpenChallenge,
    RecordAudit,
    RecordDataAvailability,
    SlashReceipt,
)
from poi_mpp.protocol.reference_machine import InvalidTransition, transition
from poi_mpp.protocol.types import (
    AuditDecision,
    ModelManifest,
    Receipt,
    ResponseCommitment,
    TaskSpec,
    TransitionContext,
)


ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "tests" / "fixtures" / "protocol_vectors.json"


def _load_vectors() -> dict[str, object]:
    return json.loads(VECTORS.read_text())


def _task(payload: dict[str, object]) -> TaskSpec:
    return TaskSpec.model_validate(payload)


def _model(payload: dict[str, object]) -> ModelManifest:
    return ModelManifest.model_validate(payload)


def _receipt(payload: dict[str, object]) -> Receipt:
    return Receipt.model_validate(payload)


def _context(payload: dict[str, object]) -> TransitionContext:
    values = dict(payload)
    values["used_nullifiers"] = frozenset(values["used_nullifiers"])
    return TransitionContext.model_validate(values)


def _event(payload: dict[str, object]):
    kind = payload["kind"]
    if kind == "RecordAudit":
        return RecordAudit(decision=AuditDecision(payload["decision"]))
    if kind == "RecordDataAvailability":
        return RecordDataAvailability(available=bool(payload["available"]))
    if kind == "OpenChallenge":
        return OpenChallenge(reason=str(payload["reason"]))
    if kind == "ActivateReceipt":
        return ActivateReceipt()
    if kind == "ExpireReceipt":
        return ExpireReceipt()
    if kind == "SlashReceipt":
        return SlashReceipt(reason=str(payload["reason"]))
    raise AssertionError(f"unsupported event kind: {kind}")


def test_protocol_vectors_fixture_exists():
    assert VECTORS.is_file()


def test_protocol_vectors_include_commitment_state_and_credit_sections():
    payload = _load_vectors()
    assert "commitment_vectors" in payload
    assert "state_vectors" in payload
    assert "credit_vectors" in payload


def test_python_commitment_vectors_match_foundry_verified_export():
    payload = _load_vectors()
    for vector in payload["commitment_vectors"]:
        task = _task(vector["task"])
        model = _model(vector["model"])
        commitment = commit_response(
            task=task,
            model=model,
            response_hash=vector["inputs"]["response_hash"],
            trace_root=vector["inputs"]["trace_root"],
            evidence_root=vector["inputs"]["evidence_root"],
            artifact_root=vector["inputs"]["artifact_root"],
            nonce=bytes.fromhex(vector["inputs"]["nonce"][2:]),
        )
        assert commitment.task_commitment == vector["expected"]["task_commitment"]
        assert commitment.model_commitment == vector["expected"]["model_commitment"]
        assert commitment.commitment_hash == vector["expected"]["commitment_hash"]
        assert commitment.finalized_height == vector["expected"]["finalized_height"]


def test_python_state_vectors_match_foundry_verified_export():
    payload = _load_vectors()
    for vector in payload["state_vectors"]:
        receipt = _receipt(vector["receipt"])
        events = [_event(item) for item in vector["events"]]
        contexts = [_context(item) for item in vector["contexts"]]
        current = receipt
        if "expected_error" in vector:
            with pytest.raises(InvalidTransition, match=vector["expected_error"]["python"]):
                for event, context in zip(events, contexts, strict=True):
                    current = transition(current, event, context)
            continue
        for event, context in zip(events, contexts, strict=True):
            current = transition(current, event, context)
        assert int(current.state) == vector["expected"]["state"]
        assert current.activated_epoch == vector["expected"]["activated_epoch"]


def test_python_credit_vectors_match_foundry_verified_export():
    payload = _load_vectors()
    for vector in payload["credit_vectors"]:
        task = _task(vector["task"])
        receipts = [_receipt(item) for item in vector["receipts"]]
        if "expected_error" in vector:
            with pytest.raises(ValueError, match=vector["expected_error"]["python"]):
                allocate_credit(task, receipts)
            continue
        allocation = allocate_credit(task, receipts)
        assert list(allocation.ordered_receipt_ids) == vector["expected"]["ordered_receipt_ids"]
        assert allocation.by_receipt == {int(key): value for key, value in vector["expected"]["by_receipt"].items()}
        assert allocation.by_worker == vector["expected"]["by_worker"]
        assert allocation.total_credit == vector["expected"]["total_credit"]
        active_weight = vector["expected"].get("active_weight")
        if active_weight is not None:
            assert derive_active_weight(
                active_weight["credit"],
                active_weight["collateral"],
                active_weight["beta"],
                active_weight["concentration_cap"],
            ) == active_weight["weight"]
