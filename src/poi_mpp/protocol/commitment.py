"""Deterministic EVM-compatible commitment construction."""

from __future__ import annotations

from poi_mpp.protocol.types import (
    ModelManifest,
    TaskSpec,
    model_commitment_hash,
    response_commitment_hash,
    trusted_response_commitment,
    task_commitment_hash,
)


def _nonce_word(nonce: bytes) -> str:
    if len(nonce) != 32:
        raise ValueError("nonce must be exactly 32 bytes")
    return f"0x{nonce.hex()}"


def commit_response(
    task: TaskSpec,
    model: ModelManifest,
    response_hash: str,
    trace_root: str,
    evidence_root: str,
    artifact_root: str,
    nonce: bytes,
) -> ResponseCommitment:
    task_commitment = task_commitment_hash(task)
    model_commitment = model_commitment_hash(model)
    nonce_word = _nonce_word(nonce)
    payload = {
        "task_id": task.task_id,
        "worker_id": task.worker_id,
        "task_class": task.task_class,
        "task_epoch": task.epoch,
        "task_commitment": task_commitment,
        "model_commitment": model_commitment,
        "response_hash": response_hash,
        "trace_root": trace_root,
        "evidence_root": evidence_root,
        "artifact_root": artifact_root,
        "nonce": nonce_word,
        "committed_height": task.commitment_height,
        "commitment_finality_depth": task.commitment_finality_depth,
        "finalized_height": task.commitment_height + task.commitment_finality_depth,
    }
    return trusted_response_commitment(
        {
            **payload,
            "commitment_hash": response_commitment_hash(
                task_commitment=task_commitment,
                model_commitment=model_commitment,
                response_hash=response_hash,
                trace_root=trace_root,
                evidence_root=evidence_root,
                artifact_root=artifact_root,
                nonce=nonce_word,
            ),
        }
    )
