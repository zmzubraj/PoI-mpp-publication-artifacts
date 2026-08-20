"""Deterministic audit-plan derivation after commitment finality."""

from __future__ import annotations

import hashlib

from pydantic import field_validator

from poi_mpp.evidence import digest
from poi_mpp.protocol.reference_machine import InvalidTransition
from poi_mpp.protocol.types import AuditPlan, ResponseCommitment, TaskSpec, _FrozenProtocolModel


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


def compile_audit(
    policy: AuditPolicy,
    task: TaskSpec,
    finalized_commitment: ResponseCommitment,
    epoch_beacon: bytes,
    round_index: int,
) -> AuditPlan:
    if finalized_commitment.finalized_height is None:
        raise InvalidTransition("commitment is not finalized")
    if finalized_commitment.task_id != task.task_id:
        raise InvalidTransition("commitment task does not match task specification")
    if round_index < 0:
        raise InvalidTransition("round_index must be non-negative")
    if not task.registered:
        raise InvalidTransition("unregistered tasks cannot derive audit plans")
    if not policy.replacement and policy.sample_count > task.audit_domain_size:
        raise InvalidTransition("sample_count exceeds audit domain without replacement")
    seed_material = {
        "task_id": task.task_id,
        "commitment_hash": finalized_commitment.commitment_hash,
        "epoch_beacon": epoch_beacon.hex(),
        "round_index": round_index,
        "finalized_height": finalized_commitment.finalized_height,
    }
    seed_hash = digest("AUDIT_SEED", seed_material)
    sample_indices = _sample_indices(
        bytes.fromhex(seed_hash),
        domain_size=task.audit_domain_size,
        sample_count=policy.sample_count,
        replacement=policy.replacement,
    )
    audit_id = digest(
        "AUDIT_PLAN",
        {
            "commitment_hash": finalized_commitment.commitment_hash,
            "seed_hash": seed_hash,
            "round_index": round_index,
            "sample_indices": sample_indices,
        },
    )
    return AuditPlan(
        audit_id=audit_id,
        commitment_hash=finalized_commitment.commitment_hash,
        seed_hash=seed_hash,
        round_index=round_index,
        sample_count=policy.sample_count,
        sample_indices=sample_indices,
    )
