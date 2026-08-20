"""Deterministic worker execution and optional local-model adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from pydantic import ValidationInfo, field_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import ArtifactRecord, ArtifactStage, EvidenceOrigin
from poi_mpp.protocol.types import TaskSpec
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
from poi_mpp.worker.iec_builder import build_iec
from poi_mpp.worker.iec_schema import EvidenceItem, IntelligenceEvidenceCapsule
from poi_mpp.worker.model_manifest import PinnedModelManifest, _FrozenWorkerModel, bytes32_word
from poi_mpp.worker.trace_capture import TraceSidecar, build_trace_sidecar
from poi_mpp.worker.trace_schema import TraceEvent


class ExecutionTimings(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_EXECUTION_TIMINGS_V1"
    warmup_ms: float
    inference_ms: float
    total_ms: float

    @field_validator("warmup_ms", "inference_ms", "total_ms")
    @classmethod
    def require_finite_nonnegative(cls, value: float, info: ValidationInfo) -> float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"{info.field_name} must be finite")
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value


class ArtifactRef(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_WORKER_ARTIFACT_REF_V1"
    artifact_name: str
    record: ArtifactRecord
    root: str


class ExecutionBundle(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_EXECUTION_BUNDLE_V1"
    response: str
    response_hash: str
    trace_root: str
    evidence_root: str
    artifact_root: str
    timings: ExecutionTimings
    retained_artifacts: tuple[ArtifactRef, ...]
    trace_sidecar: TraceSidecar
    iec: IntelligenceEvidenceCapsule
    protocol_model_manifest: Any


class AdapterRunResult(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_ADAPTER_RUN_RESULT_V1"
    loaded_manifest: PinnedModelManifest
    response: str
    trace_events: tuple[TraceEvent, ...]
    evidence_items: tuple[EvidenceItem, ...]
    claim_texts: tuple[str, ...] | None = None
    task_requirements: tuple[str, ...] = ()
    warmup_ms: float = 0.0
    inference_ms: float = 0.0

    @field_validator("response")
    @classmethod
    def require_nonblank_response(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("response must not be blank")
        return value


class InferenceAdapter(Protocol):
    def run(
        self,
        *,
        task: TaskSpec,
        manifest: PinnedModelManifest,
        policy: DeterministicDecodePolicy,
    ) -> AdapterRunResult: ...


@dataclass(frozen=True)
class FixtureInferenceAdapter:
    response: str
    trace_token_ids: tuple[int, ...]
    evidence_texts: tuple[str, ...]
    loaded_revision: str | None = None

    @classmethod
    def synthetic(
        cls,
        *,
        response: str,
        trace_token_ids: tuple[int, ...],
        evidence_texts: tuple[str, ...],
        loaded_revision: str | None = None,
    ) -> "FixtureInferenceAdapter":
        return cls(
            response=response,
            trace_token_ids=trace_token_ids,
            evidence_texts=evidence_texts,
            loaded_revision=loaded_revision,
        )

    def run(
        self,
        *,
        task: TaskSpec,
        manifest: PinnedModelManifest,
        policy: DeterministicDecodePolicy,
    ) -> AdapterRunResult:
        loaded = manifest.model_copy(
            update={"revision": self.loaded_revision or manifest.revision}
        )
        trace_events = tuple(
            TraceEvent(
                event_index=index,
                op_name="decode_step",
                input_hashes=(
                    bytes32_word(
                        "WORKER_TRACE_INPUT",
                        {"task_id": task.task_id, "seed": policy.seed, "token_id": token_id},
                    ),
                ),
                output_hash=bytes32_word(
                    "WORKER_TRACE_OUTPUT",
                    {"task_id": task.task_id, "seed": policy.seed, "token_id": token_id},
                ),
                metadata={"token_id": token_id, "surface": "SYNTHETIC_NON_EVIDENCE"},
            )
            for index, token_id in enumerate(self.trace_token_ids)
        )
        evidence_items = tuple(
            EvidenceItem(
                evidence_id=f"E-{index + 1:03d}",
                artifact_label=f"synthetic-evidence-{index + 1}",
                content=text,
                keywords=tuple(word.lower().strip(".,") for word in text.split()[:3] if word),
                origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                confidence=1.0,
            )
            for index, text in enumerate(self.evidence_texts)
        )
        return AdapterRunResult(
            loaded_manifest=loaded,
            response=self.response,
            trace_events=trace_events,
            evidence_items=evidence_items,
            warmup_ms=0.0,
            inference_ms=0.0,
        )


@dataclass(frozen=True)
class TransformersCausalLMAdapter:
    model_path: str
    tokenizer_path: str | None = None
    local_files_only: bool = True
    loader: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        if not self.local_files_only:
            raise ValueError("TransformersCausalLMAdapter requires local_files_only=True")

    def run(
        self,
        *,
        task: TaskSpec,
        manifest: PinnedModelManifest,
        policy: DeterministicDecodePolicy,
    ) -> AdapterRunResult:
        if self.loader is None:
            raise RuntimeError("authorized transformers loader is required for real execution")
        loaded = self.loader(
            model_path=self.model_path,
            tokenizer_path=self.tokenizer_path or self.model_path,
            local_files_only=self.local_files_only,
            manifest=manifest,
            policy=policy,
            task=task,
        )
        if not isinstance(loaded, AdapterRunResult):
            raise TypeError("loader must return AdapterRunResult")
        return loaded


def _response_hash(response: str) -> str:
    return bytes32_word("WORKER_RESPONSE_TEXT", {"response": response})


def _artifact_record(
    *,
    artifact_id: str,
    run_id: str,
    experiment_id: str,
    origin: EvidenceOrigin,
    content_hash: str,
    parent_hashes: tuple[str, ...] = (),
) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        run_id=run_id,
        experiment_id=experiment_id,
        origin=origin,
        stage=ArtifactStage.GENERATED,
        content_hash=content_hash,
        parent_hashes=parent_hashes,
    )


def _artifact_root(refs: tuple[ArtifactRef, ...]) -> str:
    return bytes32_word(
        "WORKER_ARTIFACT_ROOT",
        {
            "artifacts": [
                {
                    "artifact_name": ref.artifact_name,
                    "root": ref.root,
                    "record": ref.record.model_dump(mode="json"),
                }
                for ref in refs
            ]
        },
    )


def execute_once(
    task: TaskSpec,
    model_manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
    *,
    adapter: InferenceAdapter,
) -> ExecutionBundle:
    """Execute one deterministic worker run behind an explicit adapter boundary."""

    run_result = adapter.run(task=task, manifest=model_manifest, policy=policy)
    model_manifest.assert_matches_loaded(run_result.loaded_manifest)

    trace_sidecar = build_trace_sidecar(run_result.trace_events)
    response_hash = _response_hash(run_result.response)
    iec = build_iec(
        response=run_result.response,
        response_hash=response_hash,
        evidence_items=run_result.evidence_items,
        task_requirements=run_result.task_requirements,
        claim_texts=run_result.claim_texts,
    )
    origins = {item.origin for item in run_result.evidence_items}
    if len(origins) != 1:
        raise ValueError("evidence items must share one origin per execution")
    origin = next(iter(origins))
    response_content_hash = digest("WORKER_RESPONSE_ARTIFACT", {"response": run_result.response})
    trace_content_hash = digest(
        "WORKER_TRACE_ARTIFACT",
        {"trace_root": trace_sidecar.trace_root, "events": [event.model_dump(mode="json") for event in trace_sidecar.events]},
    )
    iec_content_hash = digest("WORKER_IEC_ARTIFACT", iec)

    response_ref = ArtifactRef(
        artifact_name="response",
        root=response_hash,
        record=_artifact_record(
            artifact_id=f"TASK-{task.task_id:06d}-RESPONSE",
            run_id=f"TASK-{task.task_id:06d}",
            experiment_id=f"TASK-{task.task_id:06d}",
            origin=origin,
            content_hash=response_content_hash,
        ),
    )
    trace_ref = ArtifactRef(
        artifact_name="trace",
        root=trace_sidecar.trace_root,
        record=_artifact_record(
            artifact_id=f"TASK-{task.task_id:06d}-TRACE",
            run_id=f"TASK-{task.task_id:06d}",
            experiment_id=f"TASK-{task.task_id:06d}",
            origin=origin,
            content_hash=trace_content_hash,
            parent_hashes=(response_content_hash,),
        ),
    )
    iec_ref = ArtifactRef(
        artifact_name="iec",
        root=iec.evidence_root,
        record=_artifact_record(
            artifact_id=f"TASK-{task.task_id:06d}-IEC",
            run_id=f"TASK-{task.task_id:06d}",
            experiment_id=f"TASK-{task.task_id:06d}",
            origin=origin,
            content_hash=iec_content_hash,
            parent_hashes=(response_content_hash, trace_content_hash),
        ),
    )
    retained_artifacts = (response_ref, trace_ref, iec_ref)
    artifact_root = _artifact_root(retained_artifacts)
    timings = ExecutionTimings(
        warmup_ms=run_result.warmup_ms,
        inference_ms=run_result.inference_ms,
        total_ms=run_result.warmup_ms + run_result.inference_ms,
    )
    protocol_model_manifest = model_manifest.to_protocol_manifest(policy)
    return ExecutionBundle(
        response=run_result.response,
        response_hash=response_hash,
        trace_root=trace_sidecar.trace_root,
        evidence_root=iec.evidence_root,
        artifact_root=artifact_root,
        timings=timings,
        retained_artifacts=retained_artifacts,
        trace_sidecar=trace_sidecar,
        iec=iec,
        protocol_model_manifest=protocol_model_manifest,
    )
