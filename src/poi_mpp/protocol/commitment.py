"""Deterministic commitment construction for the Python protocol kernel."""

from __future__ import annotations

from poi_mpp.evidence import digest
from poi_mpp.protocol.types import ModelManifest, ResponseCommitment, TaskSpec


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
    material = {
        "task_root": task_root,
        "model_manifest_hash": model_manifest_hash,
        "response_hash": response_hash,
        "trace_root": trace_root,
        "evidence_root": evidence_root,
        "artifact_root": artifact_root,
        "nonce_hex": nonce.hex(),
    }
    return ResponseCommitment(
        task_id=task.task_id,
        worker_id=task.worker_id,
        task_class=task.task_class,
        task_root=task_root,
        model_id=model.model_id,
        model_manifest_hash=model_manifest_hash,
        response_hash=response_hash,
        trace_root=trace_root,
        evidence_root=evidence_root,
        artifact_root=artifact_root,
        nonce_hex=nonce.hex(),
        commitment_hash=digest("RESPONSE_COMMITMENT", material),
        commitment_height=task.commitment_height,
        finalized_height=task.commitment_height + task.commitment_finality_depth,
    )
