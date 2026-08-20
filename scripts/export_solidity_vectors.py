from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
OUTPUT = ROOT / "tests" / "fixtures" / "protocol_vectors.json"
WITNESS = CONTRACTS / "out" / "protocol_witnesses.json"

WORKER = "0x0000000000000000000000000000000000002001"
ALT_WORKER = "0x0000000000000000000000000000000000002002"

WORD = re.compile(r"0x[0-9a-f]{64}\Z")
SELECTOR_PADDED = re.compile(r"0x[0-9a-f]{64}\Z")


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)


def _keccak_label(label: str) -> str:
    result = _run(["cast", "keccak", label], cwd=CONTRACTS)
    return result.stdout.strip()


def _verify_foundry_vectors() -> None:
    _run(["forge", "test", "--match-contract", "HashVectors", "-q"], cwd=CONTRACTS)


def _materialize_solidity_witnesses() -> None:
    if WITNESS.exists():
        WITNESS.unlink()
    _run(["forge", "script", "script/ProtocolVectorWitness.s.sol:ProtocolVectorWitness", "--via-ir", "-q"], cwd=CONTRACTS)
    if not WITNESS.is_file():
        raise RuntimeError("Solidity witness file was not produced by forge script")


def _normalize_word(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not WORD.fullmatch(value):
        raise ValueError(f"{field_name} must be a 32-byte lowercase hex word")
    return value


def _normalize_selector(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not SELECTOR_PADDED.fullmatch(value):
        raise ValueError(f"{field_name} must be a padded 32-byte selector word")
    return value[:10]


def _load_witnesses() -> dict[str, object]:
    payload = json.loads(WITNESS.read_text())
    if payload.get("schema") != "POI_MPP_SOLIDITY_WITNESSES_V1":
        raise ValueError("Unexpected Solidity witness schema")
    for key in ("commitment", "state", "credit"):
        if key not in payload:
            raise ValueError(f"Missing witness section: {key}")
    return payload


def _task(
    *,
    task_id: int,
    task_root: str,
    worker_id: str,
    task_class: int,
    active: bool = True,
    registered: bool = True,
    credit_budget: int = 100,
    epoch: int = 1,
    deadline: int = 500,
    commitment_height: int = 1,
    commitment_finality_depth: int = 2,
    challenge_window_blocks: int = 5,
    audit_domain_size: int = 16,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "task_root": task_root,
        "worker_id": worker_id,
        "task_class": task_class,
        "active": active,
        "registered": registered,
        "credit_budget": credit_budget,
        "epoch": epoch,
        "deadline": deadline,
        "commitment_height": commitment_height,
        "commitment_finality_depth": commitment_finality_depth,
        "challenge_window_blocks": challenge_window_blocks,
        "audit_domain_size": audit_domain_size,
    }


def _model() -> dict[str, object]:
    return {
        "model_root": "0x44a56b126c2f006b1dd376d118236897abc703751abb78eaac730e554dd49f77",
        "runtime_root": "0xf60ad809ce26db6fe33da21c8f08e694e32242a74381b3d0f063b741f53aff81",
        "model_manifest_hash": "0x723ee386a992a1d82496a7c7ff6a31869bfb3dfb9a1debfe49d8406601ddd245",
        "assurance_class": 1,
    }


def _pending_receipt(*, task_id: int, worker_id: str, commitment_hash: str) -> dict[str, object]:
    return {
        "receipt_id": 1,
        "task_id": task_id,
        "worker_id": worker_id,
        "commitment_hash": commitment_hash,
        "audit_id": "0x" + "77" * 32,
        "state": 1,
        "epoch_issued": 1,
        "challenge_deadline": 6,
        "nullifier": "0x" + "66" * 32,
        "audit_decision": None,
        "audit_accepted": False,
        "da_decision": None,
        "data_availability_passed": False,
        "activated_epoch": None,
        "challenge_reason": None,
        "slash_reason": None,
    }


def _active_receipt(
    *,
    receipt_id: int,
    task_id: int,
    worker_id: str,
    commitment_hash: str,
    nullifier: str,
    activated_epoch: int = 2,
) -> dict[str, object]:
    return {
        "receipt_id": receipt_id,
        "task_id": task_id,
        "worker_id": worker_id,
        "commitment_hash": commitment_hash,
        "audit_id": "0x" + "77" * 32,
        "state": 2,
        "epoch_issued": 1,
        "challenge_deadline": 6,
        "nullifier": nullifier,
        "audit_decision": 1,
        "audit_accepted": True,
        "da_decision": True,
        "data_availability_passed": True,
        "activated_epoch": activated_epoch,
        "challenge_reason": None,
        "slash_reason": None,
    }


def _validate_case_names(vectors: list[dict[str, object]], *, field_name: str) -> None:
    names = [str(vector["name"]) for vector in vectors]
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate {field_name} names detected")


def _fixture_from_witnesses(witnesses: dict[str, object]) -> dict[str, object]:
    commitment = witnesses["commitment"]
    state = witnesses["state"]
    credit = witnesses["credit"]

    baseline = commitment["baseline"]
    height_invariant = commitment["height_invariant"]

    baseline_task = _task(
        task_id=1,
        task_root="0x04838d077a606ff8949dbe7f0d79f9095388b6c5dd49a0c8fa4b1e74ce1cdba9",
        worker_id=WORKER,
        task_class=1,
    )
    late_task = _task(
        task_id=1,
        task_root="0x04838d077a606ff8949dbe7f0d79f9095388b6c5dd49a0c8fa4b1e74ce1cdba9",
        worker_id=WORKER,
        task_class=1,
        commitment_height=101,
    )
    service_task = _task(
        task_id=2,
        task_root=_keccak_label("service-task-root"),
        worker_id=ALT_WORKER,
        task_class=0,
    )
    zero_budget_task = _task(
        task_id=3,
        task_root=_keccak_label("zero-budget-task-root"),
        worker_id=WORKER,
        task_class=1,
        credit_budget=0,
    )
    inactive_task = _task(
        task_id=3,
        task_root=_keccak_label("inactive-task-root"),
        worker_id=WORKER,
        task_class=1,
        active=False,
    )
    canonical_model = _model()

    response_inputs = {
        "response_hash": "0x653eb5647e0476cedf9191d6bdf7781db7fc4c2230a900388530e1a59fcd6bda",
        "trace_root": "0x493d875889d13fe46f729187823f07a16a6d3ad455742d028e80016b397dbe21",
        "evidence_root": "0x520f1d1215114bafb3a1b7792638a266b07e7fd87bc6ecc17e46c8a79026815a",
        "artifact_root": "0xd83aca0e722ad4365162d18e54db653a7a11e08f472ea12ec01bb035002ceabe",
        "nonce": "0x7ab1577440dd7bedf920cb6de2f9fc6bf7ba98c78c85a3fa1f8311aac95e1759",
    }

    baseline_commitment_hash = _normalize_word(baseline["commitment_hash"], field_name="baseline commitment hash")

    commitment_vectors = [
        {
            "name": "baseline_commitment",
            "task": baseline_task,
            "model": canonical_model,
            "inputs": response_inputs,
            "expected": {
                "task_commitment": _normalize_word(
                    baseline["task_commitment"], field_name="baseline task commitment"
                ),
                "model_commitment": _normalize_word(
                    baseline["model_commitment"], field_name="baseline model commitment"
                ),
                "commitment_hash": baseline_commitment_hash,
            },
        },
        {
            "name": "height_invariant_commitment",
            "task": late_task,
            "model": canonical_model,
            "inputs": response_inputs,
            "expected": {
                "task_commitment": _normalize_word(
                    height_invariant["task_commitment"], field_name="height-invariant task commitment"
                ),
                "model_commitment": _normalize_word(
                    height_invariant["model_commitment"], field_name="height-invariant model commitment"
                ),
                "commitment_hash": _normalize_word(
                    height_invariant["commitment_hash"], field_name="height-invariant response commitment"
                ),
            },
        },
    ]

    state_vectors = [
        {
            "name": "activate_success",
            "receipt": _pending_receipt(task_id=1, worker_id=WORKER, commitment_hash=baseline_commitment_hash),
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
            "expected": {
                "state": int(state["activate_success"]["state"]),
                "activated_epoch": int(state["activate_success"]["activated_epoch"]),
            },
        },
        {
            "name": "activate_before_gates_reverts",
            "receipt": _pending_receipt(task_id=1, worker_id=WORKER, commitment_hash=baseline_commitment_hash),
            "events": [{"kind": "ActivateReceipt"}],
            "contexts": [{"current_height": 5, "current_epoch": 1, "used_nullifiers": []}],
            "expected_error": {
                "python": "receipt cannot activate before audit acceptance",
                "solidity_selector": _normalize_selector(
                    state["premature_activation_revert"], field_name="premature activation selector"
                ),
            },
        },
        {
            "name": "late_activation_reverts",
            "receipt": {
                **_pending_receipt(task_id=1, worker_id=WORKER, commitment_hash=baseline_commitment_hash),
                "audit_decision": 1,
                "audit_accepted": True,
                "da_decision": True,
                "data_availability_passed": True,
            },
            "events": [{"kind": "ActivateReceipt"}],
            "contexts": [{"current_height": 6, "current_epoch": 3, "used_nullifiers": []}],
            "expected_error": {
                "python": "receipt activation window is closed",
                "solidity_selector": _normalize_selector(
                    state["late_activation_revert"], field_name="late activation selector"
                ),
            },
        },
    ]

    credit_vectors = [
        {
            "name": "single_receipt_budget",
            "task": baseline_task,
            "receipts": [_active_receipt(
                receipt_id=1,
                task_id=1,
                worker_id=WORKER,
                commitment_hash=baseline_commitment_hash,
                nullifier="0x" + "66" * 32,
            )],
            "expected": {
                "ordered_receipt_ids": [1],
                "by_receipt": {"1": int(credit["single_receipt_budget"]["receipt_1"])},
                "by_worker": {WORKER: int(credit["single_receipt_budget"]["allocated"])},
                "total_credit": int(credit["single_receipt_budget"]["allocated"]),
                "active_weight": {
                    "credit": int(credit["single_receipt_budget"]["allocated"]),
                    "collateral": 1000,
                    "beta": 10,
                    "concentration_cap": 1000,
                    "weight": int(credit["single_receipt_budget"]["active_weight"]),
                },
            },
        },
        {
            "name": "two_receipt_even_split",
            "task": baseline_task,
            "receipts": [
                _active_receipt(
                    receipt_id=1,
                    task_id=1,
                    worker_id=WORKER,
                    commitment_hash=baseline_commitment_hash,
                    nullifier="0x" + "66" * 32,
                ),
                _active_receipt(
                    receipt_id=2,
                    task_id=1,
                    worker_id=WORKER,
                    commitment_hash=baseline_commitment_hash,
                    nullifier="0x" + "88" * 32,
                ),
            ],
            "expected": {
                "ordered_receipt_ids": [1, 2],
                "by_receipt": {
                    "1": int(credit["two_receipt_even_split"]["receipt_1"]),
                    "2": int(credit["two_receipt_even_split"]["receipt_2"]),
                },
                "by_worker": {WORKER: int(credit["two_receipt_even_split"]["allocated"])},
                "total_credit": int(credit["two_receipt_even_split"]["allocated"]),
            },
        },
        {
            "name": "service_task_noop",
            "task": service_task,
            "receipts": [
                _active_receipt(
                    receipt_id=1,
                    task_id=2,
                    worker_id=ALT_WORKER,
                    commitment_hash=baseline_commitment_hash,
                    nullifier="0x" + "99" * 32,
                )
            ],
            "expected": {"ordered_receipt_ids": [], "by_receipt": {}, "by_worker": {}, "total_credit": 0},
            "solidity_witness": {
                "allocated": int(credit["service_task_noop"]["allocated"]),
                "receipt_credit": int(credit["service_task_noop"]["receipt_credit"]),
                "epoch_credit": int(credit["service_task_noop"]["epoch_credit"]),
                "consumed": bool(credit["service_task_noop"]["consumed"]),
            },
        },
        {
            "name": "zero_budget_noop",
            "task": zero_budget_task,
            "receipts": [
                _active_receipt(
                    receipt_id=1,
                    task_id=3,
                    worker_id=WORKER,
                    commitment_hash=baseline_commitment_hash,
                    nullifier="0x" + "aa" * 32,
                )
            ],
            "expected": {"ordered_receipt_ids": [], "by_receipt": {}, "by_worker": {}, "total_credit": 0},
            "solidity_witness": {
                "allocated": int(credit["zero_budget_noop"]["allocated"]),
                "receipt_credit": int(credit["zero_budget_noop"]["receipt_credit"]),
                "epoch_credit": int(credit["zero_budget_noop"]["epoch_credit"]),
                "consumed": bool(credit["zero_budget_noop"]["consumed"]),
            },
        },
        {
            "name": "inactive_task_noop",
            "task": inactive_task,
            "receipts": [
                _active_receipt(
                    receipt_id=1,
                    task_id=3,
                    worker_id=WORKER,
                    commitment_hash=baseline_commitment_hash,
                    nullifier="0x" + "ab" * 32,
                )
            ],
            "expected": {"ordered_receipt_ids": [], "by_receipt": {}, "by_worker": {}, "total_credit": 0},
            "solidity_witness": {
                "allocated": int(credit["inactive_task_noop"]["allocated"]),
                "receipt_credit": int(credit["inactive_task_noop"]["receipt_credit"]),
                "epoch_credit": int(credit["inactive_task_noop"]["epoch_credit"]),
                "consumed": bool(credit["inactive_task_noop"]["consumed"]),
            },
        },
        {
            "name": "empty_batch_rejected",
            "task": baseline_task,
            "receipts": [],
            "expected_error": {
                "python": "no active receipt eligible for allocation",
                "solidity_selector": _normalize_selector(
                    credit["empty_batch_revert"], field_name="empty batch selector"
                ),
            },
        },
        {
            "name": "wrong_epoch_rejected",
            "task": baseline_task,
            "receipts": [
                _active_receipt(
                    receipt_id=1,
                    task_id=1,
                    worker_id=WORKER,
                    commitment_hash=baseline_commitment_hash,
                    nullifier="0x" + "66" * 32,
                    activated_epoch=3,
                )
            ],
            "expected_error": {
                "python": "active receipts must mature in the exact next epoch",
                "solidity_selector": _normalize_selector(
                    credit["wrong_epoch_revert"], field_name="wrong epoch selector"
                ),
            },
        },
        {
            "name": "duplicate_receipt_id_rejected",
            "task": baseline_task,
            "receipts": [
                _active_receipt(
                    receipt_id=1,
                    task_id=1,
                    worker_id=WORKER,
                    commitment_hash=baseline_commitment_hash,
                    nullifier="0x" + "66" * 32,
                ),
                _active_receipt(
                    receipt_id=1,
                    task_id=1,
                    worker_id=WORKER,
                    commitment_hash=baseline_commitment_hash,
                    nullifier="0x" + "88" * 32,
                ),
            ],
            "expected_error": {
                "python": "duplicate receipt_id is not allowed",
                "solidity_selector": _normalize_selector(
                    credit["duplicate_receipt_batch_revert"], field_name="duplicate batch selector"
                ),
            },
        },
        {
            "name": "replay_rejected",
            "task": baseline_task,
            "receipts": [
                _active_receipt(
                    receipt_id=1,
                    task_id=1,
                    worker_id=WORKER,
                    commitment_hash=baseline_commitment_hash,
                    nullifier="0x" + "66" * 32,
                )
            ],
            "previously_credited_receipt_ids": [1],
            "expected_error": {
                "python": "receipt already credited",
                "solidity_selector": _normalize_selector(credit["replay_revert"], field_name="replay selector"),
            },
        },
    ]

    _validate_case_names(commitment_vectors, field_name="commitment vector")
    _validate_case_names(state_vectors, field_name="state vector")
    _validate_case_names(credit_vectors, field_name="credit vector")

    for noop_case in ("service_task_noop", "zero_budget_noop", "inactive_task_noop"):
        witness_case = next(vector for vector in credit_vectors if vector["name"] == noop_case)
        if witness_case["solidity_witness"]["allocated"] != 0:
            raise ValueError(f"{noop_case} witness allocated non-zero credit")
        if witness_case["solidity_witness"]["receipt_credit"] != 0:
            raise ValueError(f"{noop_case} witness mutated per-receipt credit")
        if witness_case["solidity_witness"]["epoch_credit"] != 0:
            raise ValueError(f"{noop_case} witness mutated epoch credit")
        if witness_case["solidity_witness"]["consumed"] is not False:
            raise ValueError(f"{noop_case} witness consumed a receipt")

    return {
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
        "solidity_witness_source": {
            "contract": "HashVectors",
            "script": "contracts/script/ProtocolVectorWitness.s.sol",
            "witness_path": "contracts/out/protocol_witnesses.json",
        },
        "commitment_vectors": commitment_vectors,
        "state_vectors": state_vectors,
        "credit_vectors": credit_vectors,
    }


def main() -> None:
    _verify_foundry_vectors()
    _materialize_solidity_witnesses()
    fixture = _fixture_from_witnesses(_load_witnesses())
    OUTPUT.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
