"""Merkle-style trace hashing for immutable sidecars."""

from __future__ import annotations

import hashlib

from poi_mpp.evidence.canonical import canonical_bytes, digest
from poi_mpp.worker.trace_schema import TraceEvent


def trace_leaf_hash(event: TraceEvent) -> str:
    return f"0x{digest('WORKER_TRACE_EVENT', event)}"


def _hash_pair(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(left + right).digest()


def trace_root(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> str:
    sequence = tuple(events)
    if not sequence:
        return f"0x{digest('WORKER_TRACE_EMPTY', {'events': []})}"

    level = [bytes.fromhex(trace_leaf_hash(event)[2:]) for event in sequence]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_hash_pair(level[index], level[index + 1]) for index in range(0, len(level), 2)]
    return f"0x{level[0].hex()}"


def trace_commitment_bytes(events: tuple[TraceEvent, ...]) -> bytes:
    return canonical_bytes("WORKER_TRACE_SIDE_CAR", {"events": [event.model_dump(mode="json") for event in events]})
