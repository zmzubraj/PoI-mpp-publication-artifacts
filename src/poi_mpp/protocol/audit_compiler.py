"""Deterministic audit-plan derivation after commitment finality."""

from __future__ import annotations

import hashlib

from pydantic import field_validator

from poi_mpp.evidence import digest
from poi_mpp.protocol.reference_machine import InvalidTransition
from poi_mpp.protocol.types import (
    AuditPlan,
    ResponseCommitment,
    TaskSpec,
    trusted_response_commitment,
    _FrozenProtocolModel,
    task_commitment_hash,
)


class AuditPolicy(_FrozenProtocolModel):
    sample_count: int
    replacement: bool = False

    @field_validator("sample_count")
    @classmethod
    def require_positive_sample_count(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("sample_count must be positive")
        return value


def _sample_indices(seed_material: bytes, *, domain_size: int, sample_count: int, replacement: bool) -> tuple[int, ...]:
    indices: list[int] = []
    counter = 0
    while len(indices) < sample_count:
        block = hashlib.sha256(seed_material + counter.to_bytes(8, "big")).digest()
        index = int.from_bytes(block, "big") % domain_size
        counter += 1
        if replacement or index not in indices:
            indices.append(index)
    return tuple(indices)


def _word_digest(domain: str, value: object) -> str:
    return f"0x{digest(domain, value)}"


def compile_audit(
    policy: AuditPolicy,
    task: TaskSpec,
    finalized_commitment: ResponseCommitment,
    epoch_beacon: bytes,
    round_index: int,
) -> AuditPlan:
    try:
        commitment = trusted_response_commitment(finalized_commitment)
    except ValueError as error:
        raise InvalidTransition("commitment is invalid") from error
    if commitment.finalized_height is None:
        raise InvalidTransition("commitment is not finalized")
    if round_index < 0:
        raise InvalidTransition("round_index must be non-negative")
    expected_task_commitment = task_commitment_hash(task)
    if (
        commitment.task_id != task.task_id
        or commitment.worker_id != task.worker_id
        or commitment.task_class is not task.task_class
        or commitment.task_epoch != task.epoch
        or commitment.task_commitment != expected_task_commitment
        or commitment.committed_height != task.commitment_height
        or commitment.commitment_finality_depth != task.commitment_finality_depth
        or commitment.finalized_height
        != task.commitment_height + task.commitment_finality_depth
    ):
        raise InvalidTransition("commitment does not match task specification")
    if round_index < 0:
        raise InvalidTransition("round_index must be non-negative")
    if not task.registered:
        raise InvalidTransition("unregistered tasks cannot derive audit plans")
    if not policy.replacement and policy.sample_count > task.audit_domain_size:
        raise InvalidTransition("sample_count exceeds audit domain without replacement")
    policy_hash = _word_digest("AUDIT_POLICY", policy)
    seed_material = {
        "task_id": task.task_id,
        "worker_id": commitment.worker_id,
        "task_class": int(commitment.task_class),
        "task_epoch": commitment.task_epoch,
        "task_commitment": commitment.task_commitment,
        "model_commitment": commitment.model_commitment,
        "commitment_hash": commitment.commitment_hash,
        "response_hash": commitment.response_hash,
        "trace_root": commitment.trace_root,
        "evidence_root": commitment.evidence_root,
        "artifact_root": commitment.artifact_root,
        "policy_hash": policy_hash,
        "epoch_beacon": epoch_beacon.hex(),
        "round_index": round_index,
        "finalized_height": commitment.finalized_height,
    }
    seed_hash = _word_digest("AUDIT_SEED", seed_material)
    sample_indices = _sample_indices(
        bytes.fromhex(seed_hash[2:]),
        domain_size=task.audit_domain_size,
        sample_count=policy.sample_count,
        replacement=policy.replacement,
    )
    audit_id = _word_digest(
        "AUDIT_PLAN",
        {
            "commitment_hash": commitment.commitment_hash,
            "seed_hash": seed_hash,
            "policy_hash": policy_hash,
            "round_index": round_index,
            "sample_indices": sample_indices,
        },
    )
    return AuditPlan(
        audit_id=audit_id,
        commitment_hash=commitment.commitment_hash,
        seed_hash=seed_hash,
        policy_hash=policy_hash,
        round_index=round_index,
        sample_count=policy.sample_count,
        sample_indices=sample_indices,
    )
