"""E1 single-pass cost experiment with fail-closed publication gating."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
import secrets

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, field_validator

from poi_mpp.evidence import (
    ARTIFACT_RECORD_SCHEMA_VERSION,
    ArtifactRegistry,
    ArtifactStage,
    EvidenceOrigin,
    GateDecision,
    ProvenanceBundle,
    digest,
    evaluate_publication_gate,
)
from poi_mpp.protocol import (
    ActivateReceipt,
    AuditDecision,
    AuditPolicy,
    Receipt,
    ReceiptState,
    RecordAudit,
    RecordDataAvailability,
    TaskSpec,
    TransitionContext,
    commit_response,
    compile_audit,
    transition,
)
from poi_mpp.protocol.types import ModelManifest
from poi_mpp.reporting.e1 import E1Variant, summarize_e1_rows


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class E1ExecutionSample(_FrozenModel):
    schema_version: str = "POI_MPP_E1_EXECUTION_SAMPLE_V1"
    origin: EvidenceOrigin
    response_hash: str
    trace_root: str
    evidence_root: str
    artifact_root: str
    total_ms: float = Field(ge=0.0)
    inference_ms: float = Field(ge=0.0)
    audit_ms: float = Field(ge=0.0)
    retained_trace_bytes: int = Field(ge=0)
    expected_dispute_cost: float = Field(ge=0.0)
    protocol_model_manifest: ModelManifest

    @field_validator("response_hash", "trace_root", "evidence_root", "artifact_root")
    @classmethod
    def require_word_hashes(cls, value: str) -> str:
        if not isinstance(value, str) or not value.startswith("0x") or len(value) != 66:
            raise ValueError("execution roots must be 32-byte hex words")
        return value


class E1MeasurementRow(_FrozenModel):
    schema_version: str = "POI_MPP_E1_MEASUREMENT_ROW_V1"
    pair_id: str
    variant: E1Variant
    is_warmup: bool
    origin: EvidenceOrigin
    measured_ms: float = Field(ge=0.0)
    inference_ms: float = Field(ge=0.0)
    audit_ms: float = Field(ge=0.0)
    retained_trace_bytes: int = Field(ge=0)
    expected_dispute_cost: float = Field(ge=0.0)
    response_hash: str
    trace_root: str
    evidence_root: str
    artifact_root: str
    receipt_state: str | None = None
    receipt_id: int | None = None

    @field_validator("pair_id")
    @classmethod
    def require_pair_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("pair_id must not be blank")
        return value


class _RowsResult(_FrozenModel):
    measured_rows: tuple[E1MeasurementRow, ...]
    raw_rows: tuple[E1MeasurementRow, ...]


class E1ExperimentResult(_FrozenModel):
    schema_version: str = "POI_MPP_E1_EXPERIMENT_RESULT_V1"
    raw_rows_path: Path
    measured_rows: tuple[E1MeasurementRow, ...]
    publication_decision: GateDecision


def _pending_receipt(task: TaskSpec, *, commitment_hash: str, audit_id: str, pair_index: int) -> Receipt:
    return Receipt(
        receipt_id=pair_index + 1,
        task_id=task.task_id,
        worker_id=task.worker_id,
        commitment_hash=commitment_hash,
        audit_id=audit_id,
        state=ReceiptState.PENDING,
        epoch_issued=task.epoch,
        challenge_deadline=task.commitment_height + task.challenge_window_blocks,
        nullifier="0x" + digest("E1_RECEIPT_NULLIFIER", {"task_id": task.task_id, "pair_index": pair_index}),
        audit_decision=None,
        audit_accepted=False,
        da_decision=None,
        data_availability_passed=False,
        activated_epoch=None,
        challenge_reason=None,
        slash_reason=None,
    )


def _active_receipt(sample: E1ExecutionSample, task: TaskSpec, *, pair_index: int) -> Receipt:
    commitment = commit_response(
        task=task,
        model=sample.protocol_model_manifest,
        response_hash=sample.response_hash,
        trace_root=sample.trace_root,
        evidence_root=sample.evidence_root,
        artifact_root=sample.artifact_root,
        nonce=bytes.fromhex(digest("E1_COMMIT_NONCE", {"task_id": task.task_id, "pair_index": pair_index})),
    )
    audit_plan = compile_audit(AuditPolicy(sample_count=min(4, task.audit_domain_size)), task, commitment, b"e1-beacon", pair_index)
    receipt = _pending_receipt(task, commitment_hash=commitment.commitment_hash, audit_id=audit_plan.audit_id, pair_index=pair_index)
    accepted = transition(
        receipt,
        RecordAudit(decision=AuditDecision.ACCEPT),
        TransitionContext(current_height=task.commitment_height, current_epoch=task.epoch, used_nullifiers=frozenset()),
    )
    available = transition(
        accepted,
        RecordDataAvailability(available=True),
        TransitionContext(current_height=task.commitment_height, current_epoch=task.epoch, used_nullifiers=frozenset()),
    )
    return transition(
        available,
        ActivateReceipt(),
        TransitionContext(
            current_height=task.commitment_height + task.challenge_window_blocks,
            current_epoch=task.epoch + 1,
            used_nullifiers=frozenset(),
        ),
    )


def _row_from_sample(
    sample: E1ExecutionSample,
    *,
    pair_id: str,
    variant: E1Variant,
    is_warmup: bool,
    measured_ms: float,
    receipt: Receipt | None = None,
) -> E1MeasurementRow:
    return E1MeasurementRow(
        pair_id=pair_id,
        variant=variant,
        is_warmup=is_warmup,
        origin=sample.origin,
        measured_ms=measured_ms,
        inference_ms=sample.inference_ms,
        audit_ms=sample.audit_ms,
        retained_trace_bytes=sample.retained_trace_bytes,
        expected_dispute_cost=sample.expected_dispute_cost,
        response_hash=sample.response_hash,
        trace_root=sample.trace_root,
        evidence_root=sample.evidence_root,
        artifact_root=sample.artifact_root,
        receipt_state=receipt.state.name if receipt is not None else None,
        receipt_id=receipt.receipt_id if receipt is not None else None,
    )


def _split_rows(rows: list[E1MeasurementRow]) -> _RowsResult:
    measured = tuple(row for row in rows if not row.is_warmup)
    return _RowsResult(measured_rows=measured, raw_rows=tuple(rows))


def run_two_run_baseline(runner, task: TaskSpec, *, pair_id: str, is_warmup: bool = False) -> _RowsResult:
    first = runner.run(task)
    second = runner.run(task)
    row = _row_from_sample(
        second,
        pair_id=pair_id,
        variant=E1Variant.TWO_RUN_BASELINE,
        is_warmup=is_warmup,
        measured_ms=first.total_ms + second.total_ms,
    )
    return _split_rows([row])


def _run_native_single(runner, task: TaskSpec, *, pair_id: str, is_warmup: bool) -> E1MeasurementRow:
    sample = runner.run(task)
    return _row_from_sample(
        sample,
        pair_id=pair_id,
        variant=E1Variant.NATIVE_SINGLE,
        is_warmup=is_warmup,
        measured_ms=sample.total_ms,
    )


def _run_mpp_single_pass(runner, task: TaskSpec, *, pair_id: str, pair_index: int, is_warmup: bool) -> E1MeasurementRow:
    sample = runner.run(task)
    receipt = _active_receipt(sample, task, pair_index=pair_index)
    return _row_from_sample(
        sample,
        pair_id=pair_id,
        variant=E1Variant.MPP_SINGLE_PASS,
        is_warmup=is_warmup,
        measured_ms=sample.total_ms + sample.audit_ms,
        receipt=receipt,
    )


def _write_rows_parquet(rows: list[E1MeasurementRow], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([row.model_dump(mode="json") for row in rows])
    pq.write_table(table, path)
    return path


def _publication_record(
    *,
    summary,
    rows: list[E1MeasurementRow],
    run_id: str,
    experiment_id: str,
    provenance_bundle: ProvenanceBundle | None,
) -> dict[str, object]:
    synthetic = any(row.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE for row in rows)
    origin = (
        EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value
        if synthetic
        else rows[0].origin.value
    )
    stage = (
        ArtifactStage.SEMANTICALLY_VALID.value
        if synthetic or provenance_bundle is None
        else ArtifactStage.FROZEN.value
    )
    payload = {
        "paired_count": summary.paired_count,
        "mean_two_run_ms": summary.mean_two_run_ms,
        "mean_mpp_ms": summary.mean_mpp_ms,
        "mean_delta_ms": summary.mean_delta_ms,
    }
    material = {
        "schema_version": ARTIFACT_RECORD_SCHEMA_VERSION,
        "artifact_id": f"{experiment_id}-E1-SUMMARY",
        "run_id": run_id,
        "experiment_id": experiment_id,
        "origin": origin,
        "parent_hashes": [],
        "payload": payload,
        "denominator": summary.paired_count,
        "ci_required": True,
        "confidence_interval": list(summary.delta_ci),
        "claim_id": summary.claim_id,
        "claim_disposition": summary.claim_disposition,
    }
    return {
        **material,
        "stage": stage,
        "content_hash": digest("ARTIFACT_CONTENT", material),
        "provenance": (
            provenance_bundle.manifest.model_dump(mode="json")
            if provenance_bundle is not None
            else {"status": "UNVERIFIED_LOCAL_ONLY"}
        ),
    }


def run_e1_cost_experiment(
    *,
    runner,
    task: TaskSpec,
    output_dir: str | Path,
    run_id: str,
    experiment_id: str,
    warmup_pairs: int = 0,
    provenance_bundle: ProvenanceBundle | None = None,
    registry: ArtifactRegistry | None = None,
) -> E1ExperimentResult:
    rows: list[E1MeasurementRow] = []
    pair_index = 0
    for is_warmup in (True,) * warmup_pairs + (False,):
        pair_id = f"pair-{pair_index}"
        rows.append(_run_native_single(runner, task, pair_id=pair_id, is_warmup=is_warmup))
        rows.extend(run_two_run_baseline(runner, task, pair_id=pair_id, is_warmup=is_warmup).raw_rows)
        rows.append(_run_mpp_single_pass(runner, task, pair_id=pair_id, pair_index=pair_index, is_warmup=is_warmup))
        pair_index += 1

    raw_rows_path = _write_rows_parquet(rows, Path(output_dir) / f"{experiment_id.lower()}_cost_rows.parquet")
    measured_json = [row.model_dump(mode="json") for row in rows if not row.is_warmup]
    summary = summarize_e1_rows(measured_json)
    record = _publication_record(
        summary=summary,
        rows=rows,
        run_id=run_id,
        experiment_id=experiment_id,
        provenance_bundle=provenance_bundle,
    )
    bundles = [provenance_bundle] if provenance_bundle is not None else None
    publication_decision = evaluate_publication_gate(summary.claim_id, [record], provenance_bundles=bundles)
    if (
        registry is not None
        and provenance_bundle is not None
        and publication_decision.completeness == "COMPLETE"
    ):
        registry.write_atomic(record, provenance_bundle=provenance_bundle)
    return E1ExperimentResult(
        raw_rows_path=raw_rows_path,
        measured_rows=tuple(row for row in rows if not row.is_warmup),
        publication_decision=publication_decision,
    )
