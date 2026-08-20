from __future__ import annotations

import json
from pathlib import Path
import subprocess

from poi_mpp.protocol.commitment import commit_response
from poi_mpp.protocol.credit import allocate_credit, derive_active_weight
from poi_mpp.protocol.types import (
    AuditDecision,
    ModelManifest,
    Receipt,
    ReceiptState,
    TaskClass,
    TaskSpec,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
OUTPUT = ROOT / "tests" / "fixtures" / "protocol_vectors.json"

WORKER = "0x0000000000000000000000000000000000002001"


def _task(*, commitment_height: int = 1, credit_budget: int = 100) -> TaskSpec:
    return TaskSpec(
        task_id=1,
        task_root="0x04838d077a606ff8949dbe7f0d79f9095388b6c5dd49a0c8fa4b1e74ce1cdba9",
        worker_id=WORKER,
        task_class=TaskClass.CONSENSUS,
        registered=True,
        credit_budget=credit_budget,
        epoch=1,
        deadline=500,
        commitment_height=commitment_height,
        commitment_finality_depth=2,
        challenge_window_blocks=5,
        audit_domain_size=16,
    )


def _model() -> ModelManifest:
    return ModelManifest(
        model_root="0x44a56b126c2f006b1dd376d118236897abc703751abb78eaac730e554dd49f77",
        runtime_root="0xf60ad809ce26db6fe33da21c8f08e694e32242a74381b3d0f063b741f53aff81",
        model_manifest_hash="0x723ee386a992a1d82496a7c7ff6a31869bfb3dfb9a1debfe49d8406601ddd245",
        assurance_class=1,
    )


def _commitment(task: TaskSpec):
    return commit_response(
        task=task,
        model=_model(),
        response_hash="0x653eb5647e0476cedf9191d6bdf7781db7fc4c2230a900388530e1a59fcd6bda",
        trace_root="0x493d875889d13fe46f729187823f07a16a6d3ad455742d028e80016b397dbe21",
        evidence_root="0x520f1d1215114bafb3a1b7792638a266b07e7fd87bc6ecc17e46c8a79026815a",
        artifact_root="0xd83aca0e722ad4365162d18e54db653a7a11e08f472ea12ec01bb035002ceabe",
        nonce=bytes.fromhex("7ab1577440dd7bedf920cb6de2f9fc6bf7ba98c78c85a3fa1f8311aac95e1759"),
    )


def _pending_receipt(task: TaskSpec, commitment_hash: str) -> Receipt:
    return Receipt(
        receipt_id=1,
        task_id=task.task_id,
        worker_id=task.worker_id,
        commitment_hash=commitment_hash,
        audit_id="0x" + "77" * 32,
        state=ReceiptState.PENDING,
        epoch_issued=task.epoch,
        challenge_deadline=6,
        nullifier="0x" + "66" * 32,
        audit_decision=None,
        audit_accepted=False,
        da_decision=None,
        data_availability_passed=False,
        activated_epoch=None,
        challenge_reason=None,
        slash_reason=None,
    )


def _active_receipt(receipt_id: int, nullifier: str) -> Receipt:
    task = _task()
    commitment = _commitment(task)
    return Receipt(
        receipt_id=receipt_id,
        task_id=task.task_id,
        worker_id=task.worker_id,
        commitment_hash=commitment.commitment_hash,
        audit_id="0x" + "77" * 32,
        state=ReceiptState.ACTIVE,
        epoch_issued=task.epoch,
        challenge_deadline=6,
        nullifier=nullifier,
        audit_decision=AuditDecision.ACCEPT,
        audit_accepted=True,
        da_decision=True,
        data_availability_passed=True,
        activated_epoch=2,
        challenge_reason=None,
        slash_reason=None,
    )


def _verify_foundry_vectors() -> None:
    subprocess.run(
        ["forge", "test", "--match-contract", "HashVectors", "-q"],
        cwd=CONTRACTS,
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> None:
    _verify_foundry_vectors()

    base_task = _task()
    late_task = _task(commitment_height=101)
    model = _model()
    base_commitment = _commitment(base_task)
    late_commitment = _commitment(late_task)
    pending = _pending_receipt(base_task, base_commitment.commitment_hash)
    active_one = _active_receipt(1, "0x" + "66" * 32)
    active_two = _active_receipt(2, "0x" + "88" * 32)

    allocation_one = allocate_credit(base_task, [active_one])
    allocation_two = allocate_credit(base_task, [active_one, active_two])

    payload = {
        "format": "POI_MPP_PROTOCOL_VECTORS_V1",
        "artifact_origin": "TEST_VECTOR_NON_EVIDENCE",
        "evidence_origin": "SYNTHETIC_NON_EVIDENCE",
        "generated_on": "2026-08-20",
        "domains": {
            "task": {"label": "POI_MPP_TASK", "version": 1},
            "model": {"label": "POI_MPP_MODEL", "version": 1},
            "response_commitment": {"label": "POI_MPP_RESPONSE_COMMITMENT", "version": 1},
        },
        "abi_layout": {
            "task_commitment": [
                {"name": "domain", "type": "bytes32"},
                {"name": "version", "type": "uint16"},
                {"name": "taskId", "type": "uint256"},
                {"name": "taskRoot", "type": "bytes32"},
                {"name": "worker", "type": "address"},
                {"name": "taskClass", "type": "uint8"},
                {"name": "creditBudget", "type": "uint256"},
                {"name": "epoch", "type": "uint64"},
                {"name": "deadline", "type": "uint64"},
            ],
            "model_commitment": [
                {"name": "domain", "type": "bytes32"},
                {"name": "version", "type": "uint16"},
                {"name": "modelRoot", "type": "bytes32"},
                {"name": "runtimeRoot", "type": "bytes32"},
                {"name": "modelManifestHash", "type": "bytes32"},
                {"name": "assuranceClass", "type": "uint8"},
            ],
            "response_commitment": [
                {"name": "domain", "type": "bytes32"},
                {"name": "version", "type": "uint16"},
                {"name": "taskCommitment", "type": "bytes32"},
                {"name": "modelCommitment", "type": "bytes32"},
                {"name": "responseHash", "type": "bytes32"},
                {"name": "traceRoot", "type": "bytes32"},
                {"name": "evidenceRoot", "type": "bytes32"},
                {"name": "artifactRoot", "type": "bytes32"},
                {"name": "nonce", "type": "bytes32"},
            ],
        },
        "enum_values": {
            "TaskClass": {"SERVICE": 0, "CONSENSUS": 1},
            "AuditDecision": {"NONE": 0, "ACCEPT": 1, "REJECT": 2, "ABSTAIN": 3},
            "ReceiptState": {
                "NONE": 0,
                "PENDING": 1,
                "ACTIVE": 2,
                "ABSTAINED": 3,
                "CHALLENGED": 4,
                "DA_FAILED": 5,
                "EXPIRED": 6,
                "REJECTED": 7,
                "SLASHED": 8,
            },
        },
        "commitment_vectors": [
            {
                "name": "baseline_commitment",
                "task": base_task.model_dump(mode="json"),
                "model": model.model_dump(mode="json"),
                "inputs": {
                    "response_hash": "0x653eb5647e0476cedf9191d6bdf7781db7fc4c2230a900388530e1a59fcd6bda",
                    "trace_root": "0x493d875889d13fe46f729187823f07a16a6d3ad455742d028e80016b397dbe21",
                    "evidence_root": "0x520f1d1215114bafb3a1b7792638a266b07e7fd87bc6ecc17e46c8a79026815a",
                    "artifact_root": "0xd83aca0e722ad4365162d18e54db653a7a11e08f472ea12ec01bb035002ceabe",
                    "nonce": "0x7ab1577440dd7bedf920cb6de2f9fc6bf7ba98c78c85a3fa1f8311aac95e1759",
                },
                "expected": {
                    "task_commitment": base_commitment.task_commitment,
                    "model_commitment": base_commitment.model_commitment,
                    "commitment_hash": base_commitment.commitment_hash,
                    "finalized_height": base_commitment.finalized_height,
                },
            },
            {
                "name": "height_invariant_commitment",
                "task": late_task.model_dump(mode="json"),
                "model": model.model_dump(mode="json"),
                "inputs": {
                    "response_hash": "0x653eb5647e0476cedf9191d6bdf7781db7fc4c2230a900388530e1a59fcd6bda",
                    "trace_root": "0x493d875889d13fe46f729187823f07a16a6d3ad455742d028e80016b397dbe21",
                    "evidence_root": "0x520f1d1215114bafb3a1b7792638a266b07e7fd87bc6ecc17e46c8a79026815a",
                    "artifact_root": "0xd83aca0e722ad4365162d18e54db653a7a11e08f472ea12ec01bb035002ceabe",
                    "nonce": "0x7ab1577440dd7bedf920cb6de2f9fc6bf7ba98c78c85a3fa1f8311aac95e1759",
                },
                "expected": {
                    "task_commitment": late_commitment.task_commitment,
                    "model_commitment": late_commitment.model_commitment,
                    "commitment_hash": late_commitment.commitment_hash,
                    "finalized_height": late_commitment.finalized_height,
                },
            },
        ],
        "state_vectors": [
            {
                "name": "activate_success",
                "receipt": pending.model_dump(mode="json"),
                "events": [
                    {"kind": "RecordAudit", "decision": 1},
                    {"kind": "RecordDataAvailability", "available": True},
                    {"kind": "ActivateReceipt"},
                ],
                "contexts": [
                    {"current_height": 6, "current_epoch": 2, "used_nullifiers": []},
                    {"current_height": 6, "current_epoch": 2, "used_nullifiers": []},
                    {"current_height": 6, "current_epoch": 2, "used_nullifiers": []},
                ],
                "expected": {"state": 2, "activated_epoch": 2},
            },
            {
                "name": "activate_before_gates_reverts",
                "receipt": pending.model_dump(mode="json"),
                "events": [{"kind": "ActivateReceipt"}],
                "contexts": [{"current_height": 5, "current_epoch": 1, "used_nullifiers": []}],
                "expected_error": {
                    "python": "receipt cannot activate before audit acceptance",
                    "solidity": "ReceiptManager__ActivationNotReady",
                },
            },
            {
                "name": "late_activation_reverts",
                "receipt": pending.model_copy(
                    update={
                        "audit_decision": AuditDecision.ACCEPT,
                        "audit_accepted": True,
                        "da_decision": True,
                        "data_availability_passed": True,
                    }
                ).model_dump(mode="json"),
                "events": [{"kind": "ActivateReceipt"}],
                "contexts": [{"current_height": 6, "current_epoch": 3, "used_nullifiers": []}],
                "expected_error": {
                    "python": "receipt activation window is closed",
                    "solidity": "ReceiptManager__ActivationWindowClosed",
                },
            },
        ],
        "credit_vectors": [
            {
                "name": "single_receipt_budget",
                "task": base_task.model_dump(mode="json"),
                "receipts": [active_one.model_dump(mode="json")],
                "expected": {
                    "ordered_receipt_ids": [1],
                    "by_receipt": {"1": 100},
                    "by_worker": {WORKER: 100},
                    "total_credit": 100,
                    "active_weight": {
                        "credit": 100,
                        "collateral": 1000,
                        "beta": 10,
                        "concentration_cap": 1000,
                        "weight": derive_active_weight(100, 1000, 10, 1000),
                    },
                },
            },
            {
                "name": "two_receipt_even_split",
                "task": base_task.model_dump(mode="json"),
                "receipts": [active_one.model_dump(mode="json"), active_two.model_dump(mode="json")],
                "expected": {
                    "ordered_receipt_ids": [1, 2],
                    "by_receipt": {"1": 50, "2": 50},
                    "by_worker": {WORKER: 100},
                    "total_credit": 100,
                },
            },
            {
                "name": "duplicate_receipt_id_rejected",
                "task": base_task.model_dump(mode="json"),
                "receipts": [
                    active_one.model_dump(mode="json"),
                    active_two.model_copy(update={"receipt_id": 1}).model_dump(mode="json"),
                ],
                "expected_error": {
                    "python": "duplicate receipt_id is not allowed",
                    "solidity": "CreditEngine__ReceiptIdsNotStrictlyAscending",
                },
            },
        ],
        "foundry_verified_examples": {
            "task_commitment": base_commitment.task_commitment,
            "model_commitment": base_commitment.model_commitment,
            "response_commitment": base_commitment.commitment_hash,
            "single_receipt_credit": allocation_one.model_dump(mode="json"),
            "two_receipt_credit": allocation_two.model_dump(mode="json"),
        },
    }

    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
