"""Deterministic commitment construction for the Python protocol kernel."""

from __future__ import annotations

from poi_mpp.evidence import digest
from poi_mpp.protocol.types import (
    ModelManifest,
    TaskSpec,
    response_commitment_material,
    trusted_response_commitment,
)


def commit_response(
    task: TaskSpec,
    model: ModelManifest,
    response_hash: str,
    trace_root: str,
    evidence_root: str,
    artifact_root: str,
    nonce: bytes,
) -> ResponseCommitment:
    task_root = digest("TASK_SPEC", task)
    model_manifest_hash = digest("MODEL_MANIFEST", model)
    payload = {
        "task_id": task.task_id,
        "worker_id": task.worker_id,
        "task_class": task.task_class.value,
        "task_epoch": task.epoch,
        "task_root": task_root,
        "model_id": model.model_id,
        "model_manifest_hash": model_manifest_hash,
        "response_hash": response_hash,
        "trace_root": trace_root,
        "evidence_root": evidence_root,
        "artifact_root": artifact_root,
        "nonce_hex": nonce.hex(),
        "commitment_height": task.commitment_height,
        "commitment_finality_depth": task.commitment_finality_depth,
        "finalized_height": task.commitment_height + task.commitment_finality_depth,
    }
    return trusted_response_commitment(
        {
            **payload,
            "commitment_hash": digest("RESPONSE_COMMITMENT", response_commitment_material(payload)),
        }
    )
