"""Deterministic next-epoch committee sampling from active weights."""

from __future__ import annotations

import hashlib
from typing import Mapping


def sample_committee(weights: Mapping[str, int], *, committee_size: int, seed: bytes) -> tuple[str, ...]:
    if committee_size <= 0:
        raise ValueError("committee_size must be positive")
    negative = [worker for worker, weight in weights.items() if weight < 0]
    if negative:
        raise ValueError("negative active weight is not allowed")
    remaining = {worker: weight for worker, weight in weights.items() if weight > 0}
    if not remaining:
        raise ValueError("total active weight must be positive")
    if committee_size > len(remaining):
        raise ValueError("committee_size cannot exceed the number of positive-weight workers")
    selected: list[str] = []
    counter = 0
    while len(selected) < committee_size:
        total_weight = sum(remaining.values())
        if total_weight <= 0:
            raise ValueError("total active weight must be positive")
        roll = int.from_bytes(
            hashlib.sha256(seed + counter.to_bytes(8, "big")).digest(),
            "big",
        ) % total_weight
        counter += 1
        cumulative = 0
        chosen = None
        for worker, weight in sorted(remaining.items()):
            cumulative += weight
            if roll < cumulative:
                chosen = worker
                break
        assert chosen is not None
        selected.append(chosen)
        remaining.pop(chosen)
    return tuple(selected)
