"""E1 single-pass cost experiment with fail-closed publication gating."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
import os
from pathlib import Path
import secrets
import time

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence import (
    ARTIFACT_RECORD_SCHEMA_VERSION,
    ArtifactRegistry,
    ArtifactStage,
    EvidenceOrigin,
    GateDecision,
    ProvenanceBundle,
    RunConfig,
    artifact_content_material,
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
from poi_mpp.reporting.e1 import E1Summary, E1Variant, summarize_e1_rows


MIN_E1_SUPPORTED_PAIRS = 2
PUBLICATION_EVIDENCE_AUTHORIZED = "PUBLICATION_EVIDENCE_AUTHORIZED"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MeasurementClock(StrEnum):
    MONOTONIC_EXTERNAL = "MONOTONIC_EXTERNAL"
    FIXTURE_SYNTHETIC = "FIXTURE_SYNTHETIC"


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
    run_id: str
    experiment_id: str
    task_id: int = Field(ge=0)
    pair_id: str
    variant: E1Variant
    is_warmup: bool
    origin: EvidenceOrigin
    measurement_clock: MeasurementClock
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

    @field_validator("run_id", "experiment_id", "pair_id")
    @classmethod
    def require_nonblank_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("row identifiers must not be blank")
        return value

    @model_validator(mode="after")
    def validate_measurement_boundary(self) -> "E1MeasurementRow":
        if self.origin is EvidenceOrigin.REAL_MODEL_EXECUTION:
            if self.measurement_clock is not MeasurementClock.MONOTONIC_EXTERNAL:
                raise ValueError("real-origin rows require external monotonic measurement")
            if self.measured_ms <= 0.0:
                raise ValueError("real-origin rows require positive external measured_ms")
        return self


class _RowsResult(_FrozenModel):
    measured_rows: tuple[E1MeasurementRow, ...]
    raw_rows: tuple[E1MeasurementRow, ...]


class E1ExperimentResult(_FrozenModel):
    schema_version: str = "POI_MPP_E1_EXPERIMENT_RESULT_V1"
    raw_rows_path: Path
    measured_rows: tuple[E1MeasurementRow, ...]
    summary: E1Summary
    publication_record: dict[str, object]
    publication_decision: GateDecision
    frozen_artifact_path: Path | None = None


def _default_clock_ns() -> int:
    return time.perf_counter_ns()


def _measurement_clock(clock_ns: Callable[[], int] | None) -> MeasurementClock:
    return (
        MeasurementClock.FIXTURE_SYNTHETIC
        if clock_ns is not None
        else MeasurementClock.MONOTONIC_EXTERNAL
    )


def _elapsed_ms(start_ns: int, end_ns: int) -> float:
    if end_ns < start_ns:
        raise ValueError("external clock must be monotonic")
    return (end_ns - start_ns) / 1_000_000.0


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
    audit_plan = compile_audit(
        AuditPolicy(sample_count=min(4, task.audit_domain_size)),
        task,
        commitment,
        b"e1-beacon",
        pair_index,
    )
    receipt = _pending_receipt(
        task,
        commitment_hash=commitment.commitment_hash,
        audit_id=audit_plan.audit_id,
        pair_index=pair_index,
    )
    accepted = transition(
        receipt,
        RecordAudit(decision=AuditDecision.ACCEPT),
        TransitionContext(
            current_height=task.commitment_height,
            current_epoch=task.epoch,
            used_nullifiers=frozenset(),
        ),
    )
    available = transition(
        accepted,
        RecordDataAvailability(available=True),
        TransitionContext(
            current_height=task.commitment_height,
            current_epoch=task.epoch,
            used_nullifiers=frozenset(),
        ),
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
    run_id: str,
    experiment_id: str,
    task: TaskSpec,
    pair_id: str,
    variant: E1Variant,
    is_warmup: bool,
    measured_ms: float,
    measurement_clock: MeasurementClock,
    receipt: Receipt | None = None,
) -> E1MeasurementRow:
    return E1MeasurementRow(
        run_id=run_id,
        experiment_id=experiment_id,
        task_id=task.task_id,
        pair_id=pair_id,
        variant=variant,
        is_warmup=is_warmup,
        origin=sample.origin,
        measurement_clock=measurement_clock,
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


def _measure_runner_call(
    runner,
    task: TaskSpec,
    *,
    clock_ns: Callable[[], int] | None = None,
) -> tuple[E1ExecutionSample, float]:
    timer = clock_ns or _default_clock_ns
    start_ns = timer()
    sample = runner.run(task)
    end_ns = timer()
    measured_ms = _elapsed_ms(start_ns, end_ns)
    if clock_ns is not None and sample.origin is not EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
        raise ValueError("fixture clock injection is only permitted for synthetic non-evidence samples")
    return sample, measured_ms


def run_two_run_baseline(
    runner,
    task: TaskSpec,
    *,
    run_id: str,
    experiment_id: str,
    pair_id: str,
    is_warmup: bool = False,
    clock_ns: Callable[[], int] | None = None,
) -> _RowsResult:
    timer = clock_ns or _default_clock_ns
    start_ns = timer()
    first = runner.run(task)
    second = runner.run(task)
    end_ns = timer()
    if first.origin is not second.origin:
        raise ValueError("two-run baseline requires a stable evidence origin across both invocations")
    if clock_ns is not None and second.origin is not EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
        raise ValueError("fixture clock injection is only permitted for synthetic non-evidence samples")
    row = _row_from_sample(
        second,
        run_id=run_id,
        experiment_id=experiment_id,
        task=task,
        pair_id=pair_id,
        variant=E1Variant.TWO_RUN_BASELINE,
        is_warmup=is_warmup,
        measured_ms=_elapsed_ms(start_ns, end_ns),
        measurement_clock=_measurement_clock(clock_ns),
    )
    return _split_rows([row])


def _run_native_single(
    runner,
    task: TaskSpec,
    *,
    run_id: str,
    experiment_id: str,
    pair_id: str,
    is_warmup: bool,
    clock_ns: Callable[[], int] | None,
) -> E1MeasurementRow:
    sample, measured_ms = _measure_runner_call(runner, task, clock_ns=clock_ns)
    return _row_from_sample(
        sample,
        run_id=run_id,
        experiment_id=experiment_id,
        task=task,
        pair_id=pair_id,
        variant=E1Variant.NATIVE_SINGLE,
        is_warmup=is_warmup,
        measured_ms=measured_ms,
        measurement_clock=_measurement_clock(clock_ns),
    )


def _run_mpp_single_pass(
    runner,
    task: TaskSpec,
    *,
    run_id: str,
    experiment_id: str,
    pair_id: str,
    pair_index: int,
    is_warmup: bool,
    clock_ns: Callable[[], int] | None,
) -> E1MeasurementRow:
    timer = clock_ns or _default_clock_ns
    start_ns = timer()
    sample = runner.run(task)
    receipt = _active_receipt(sample, task, pair_index=pair_index)
    end_ns = timer()
    if clock_ns is not None and sample.origin is not EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
        raise ValueError("fixture clock injection is only permitted for synthetic non-evidence samples")
    return _row_from_sample(
        sample,
        run_id=run_id,
        experiment_id=experiment_id,
        task=task,
        pair_id=pair_id,
        variant=E1Variant.MPP_SINGLE_PASS,
        is_warmup=is_warmup,
        measured_ms=_elapsed_ms(start_ns, end_ns),
        measurement_clock=_measurement_clock(clock_ns),
        receipt=receipt,
    )


def _write_rows_parquet_atomic(rows: list[E1MeasurementRow], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([row.model_dump(mode="json") for row in rows])
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    pq.write_table(table, temporary)
    os.replace(temporary, path)
    return path


def _record_origin(rows: list[E1MeasurementRow]) -> str:
    origins = {row.origin.value for row in rows}
    if len(origins) == 1:
        return next(iter(origins))
    return "MIXED_ROW_ORIGINS"


def _publication_precheck_reasons(
    *,
    rows: list[E1MeasurementRow],
    run_config: RunConfig,
    task: TaskSpec,
    provenance_bundle: ProvenanceBundle | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    row_run_ids = {row.run_id for row in rows}
    row_experiment_ids = {row.experiment_id for row in rows}
    row_task_ids = {row.task_id for row in rows}
    row_origins = {row.origin.value for row in rows}
    if row_run_ids != {run_config.run_id}:
        reasons.append("rows.run_id must equal run_config.run_id")
    if row_experiment_ids != {run_config.experiment_id}:
        reasons.append("rows.experiment_id must equal run_config.experiment_id")
    if row_task_ids != {task.task_id}:
        reasons.append("rows.task_id must equal task.task_id")
    if row_origins != {run_config.origin.value}:
        reasons.append("rows.origin must equal run_config.origin")
    if provenance_bundle is None:
        return tuple(reasons)
    manifest = provenance_bundle.manifest
    if run_config.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        reasons.append(
            f"run_config.authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
        )
    if manifest.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        reasons.append(
            f"provenance.authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
        )
    if manifest.run_id != run_config.run_id:
        reasons.append("provenance.run_id must equal run_config.run_id")
    if manifest.experiment_id != run_config.experiment_id:
        reasons.append("provenance.experiment_id must equal run_config.experiment_id")
    if manifest.origin.value != run_config.origin.value:
        reasons.append("provenance.origin must equal run_config.origin")
    if row_origins != {manifest.origin.value}:
        reasons.append("rows.origin must equal provenance.origin")
    return tuple(dict.fromkeys(reasons))


def _publication_record(
    *,
    summary: E1Summary,
    rows: list[E1MeasurementRow],
    run_config: RunConfig,
    provenance_bundle: ProvenanceBundle | None,
    publication_authorized: bool,
) -> dict[str, object]:
    origin = _record_origin(rows)
    stage = (
        ArtifactStage.SEMANTICALLY_VALID.value
        if provenance_bundle is None or not publication_authorized
        else ArtifactStage.FROZEN.value
    )
    payload = {
        "paired_count": summary.paired_count,
        "minimum_pairs_required": summary.minimum_pairs_required,
        "mean_two_run_ms": summary.mean_two_run_ms,
        "mean_mpp_ms": summary.mean_mpp_ms,
        "mean_delta_ms": summary.mean_delta_ms,
    }
    record: dict[str, object] = {
        "schema_version": ARTIFACT_RECORD_SCHEMA_VERSION,
        "artifact_id": f"{run_config.experiment_id}-E1-SUMMARY",
        "run_id": run_config.run_id,
        "experiment_id": run_config.experiment_id,
        "origin": origin,
        "stage": stage,
        "parent_hashes": list(run_config.parent_hashes),
        "payload": payload,
        "denominator": summary.denominator,
        "ci_required": True,
        "confidence_interval": list(summary.delta_ci),
        "claim_id": summary.claim_id,
        "claim_disposition": summary.claim_disposition,
        "provenance": (
            provenance_bundle.manifest.model_dump(mode="json")
            if provenance_bundle is not None
            else {"status": "UNVERIFIED_LOCAL_ONLY"}
        ),
    }
    record["content_hash"] = digest("ARTIFACT_CONTENT", artifact_content_material(record))
    return record


def run_e1_cost_experiment(
    *,
    runner,
    run_config: RunConfig,
    task: TaskSpec,
    output_dir: str | Path,
    warmup_pairs: int = 0,
    provenance_bundle: ProvenanceBundle | None = None,
    registry: ArtifactRegistry | None = None,
    clock_ns: Callable[[], int] | None = None,
) -> E1ExperimentResult:
    rows: list[E1MeasurementRow] = []
    pair_sequence_index = 0
    for warmup_index in range(warmup_pairs):
        pair_id = f"warmup-{warmup_index:04d}"
        rows.append(
            _run_native_single(
                runner,
                task,
                run_id=run_config.run_id,
                experiment_id=run_config.experiment_id,
                pair_id=pair_id,
                is_warmup=True,
                clock_ns=clock_ns,
            )
        )
        rows.extend(
            run_two_run_baseline(
                runner,
                task,
                run_id=run_config.run_id,
                experiment_id=run_config.experiment_id,
                pair_id=pair_id,
                is_warmup=True,
                clock_ns=clock_ns,
            ).raw_rows
        )
        rows.append(
            _run_mpp_single_pass(
                runner,
                task,
                run_id=run_config.run_id,
                experiment_id=run_config.experiment_id,
                pair_id=pair_id,
                pair_index=pair_sequence_index,
                is_warmup=True,
                clock_ns=clock_ns,
            )
        )
        pair_sequence_index += 1

    for measured_index in range(run_config.data_availability.samples):
        pair_id = f"pair-{measured_index:04d}"
        rows.append(
            _run_native_single(
                runner,
                task,
                run_id=run_config.run_id,
                experiment_id=run_config.experiment_id,
                pair_id=pair_id,
                is_warmup=False,
                clock_ns=clock_ns,
            )
        )
        rows.extend(
            run_two_run_baseline(
                runner,
                task,
                run_id=run_config.run_id,
                experiment_id=run_config.experiment_id,
                pair_id=pair_id,
                is_warmup=False,
                clock_ns=clock_ns,
            ).raw_rows
        )
        rows.append(
            _run_mpp_single_pass(
                runner,
                task,
                run_id=run_config.run_id,
                experiment_id=run_config.experiment_id,
                pair_id=pair_id,
                pair_index=pair_sequence_index,
                is_warmup=False,
                clock_ns=clock_ns,
            )
        )
        pair_sequence_index += 1

    raw_rows_path = _write_rows_parquet_atomic(
        rows,
        Path(output_dir) / f"{run_config.experiment_id.lower()}_cost_rows.parquet",
    )
    measured_json = [row.model_dump(mode="json") for row in rows if not row.is_warmup]
    measured_rows = [row for row in rows if not row.is_warmup]
    summary = summarize_e1_rows(
        measured_json,
        minimum_pairs_required=MIN_E1_SUPPORTED_PAIRS,
    )
    precheck_reasons = _publication_precheck_reasons(
        rows=measured_rows,
        run_config=run_config,
        task=task,
        provenance_bundle=provenance_bundle,
    )
    record = _publication_record(
        summary=summary,
        rows=measured_rows,
        run_config=run_config,
        provenance_bundle=provenance_bundle,
        publication_authorized=provenance_bundle is not None and not precheck_reasons,
    )
    bundles = [provenance_bundle] if provenance_bundle is not None else None
    publication_decision = evaluate_publication_gate(
        summary.claim_id,
        [record],
        provenance_bundles=bundles,
    )
    if precheck_reasons:
        publication_decision = GateDecision(
            publication_decision.claim_id,
            "INCOMPLETE",
            "INCONCLUSIVE",
            tuple(dict.fromkeys((*precheck_reasons, *publication_decision.reasons))),
        )
    frozen_artifact_path: Path | None = None
    if (
        registry is not None
        and provenance_bundle is not None
        and not precheck_reasons
        and publication_decision.completeness == "COMPLETE"
    ):
        frozen_artifact_path = registry.write_atomic(record, provenance_bundle=provenance_bundle)
    return E1ExperimentResult(
        raw_rows_path=raw_rows_path,
        measured_rows=tuple(measured_rows),
        summary=summary,
        publication_record=record,
        publication_decision=publication_decision,
        frozen_artifact_path=frozen_artifact_path,
    )
