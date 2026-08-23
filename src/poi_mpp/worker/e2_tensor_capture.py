"""Real E2 tensor-capture helpers for bounded publication-authorized runs."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from pydantic import ValidationInfo, field_validator

from poi_mpp.attacks.execution import ExecutionAuditBundle
from poi_mpp.evidence import RunConfig
from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e2_tamper import PUBLICATION_EVIDENCE_AUTHORIZED
from poi_mpp.protocol import TaskSpec, commit_response
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
from poi_mpp.worker.iec_schema import EvidenceItem
from poi_mpp.worker.inference import AdapterRunResult, ExecutionBundle, InferenceAdapter, execute_once
from poi_mpp.worker.model_manifest import PinnedModelManifest, _FrozenWorkerModel, bytes32_word
from poi_mpp.worker.real_transformers import (
    AuthorizedLocalTransformersSession,
    _response_binding,
    _trace_events,
)


_FIELD_MODULUS = 2_147_483_647


class TensorCaptureSpec(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_E2_TENSOR_CAPTURE_SPEC_V1"
    layer_path: str
    activation_token_index: int = 0
    input_width: int = 4
    output_width: int = 4
    fixed_point_scale: int = 1_000
    field_modulus: int = _FIELD_MODULUS

    @field_validator("layer_path")
    @classmethod
    def require_layer_path(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("layer_path must not be blank")
        return value.strip()

    @field_validator(
        "activation_token_index",
        "input_width",
        "output_width",
        "fixed_point_scale",
        "field_modulus",
    )
    @classmethod
    def require_positive_integers(cls, value: int, info: ValidationInfo) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{info.field_name} must be an integer")
        if info.field_name == "activation_token_index":
            if value < 0:
                raise ValueError("activation_token_index must be non-negative")
            return value
        if value <= 0:
            raise ValueError(f"{info.field_name} must be positive")
        return value


class TensorProductCapture(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_E2_TENSOR_PRODUCT_CAPTURE_V1"
    layer_path: str
    activation_token_index: int
    input_width: int
    output_width: int
    fixed_point_scale: int
    field_modulus: int
    source_input_width: int
    source_output_width: int
    float_matrix_a: tuple[tuple[float, ...], ...]
    float_matrix_b: tuple[tuple[float, ...], ...]
    float_matrix_c: tuple[tuple[float, ...], ...]
    field_matrix_a: tuple[tuple[int, ...], ...]
    field_matrix_b: tuple[tuple[int, ...], ...]
    field_matrix_c: tuple[tuple[int, ...], ...]
    weight_root: str
    capture_hash: str


def _field_project(value: float, *, scale: int, modulus: int) -> int:
    projected = int(round(float(value) * scale))
    return projected % modulus


def _float_product(
    left: tuple[tuple[float, ...], ...],
    right: tuple[tuple[float, ...], ...],
) -> tuple[tuple[float, ...], ...]:
    transpose = tuple(zip(*right, strict=True))
    return tuple(
        tuple(sum(lhs * rhs for lhs, rhs in zip(row, column, strict=True)) for column in transpose)
        for row in left
    )


def _field_product(
    left: tuple[tuple[int, ...], ...],
    right: tuple[tuple[int, ...], ...],
    *,
    modulus: int,
) -> tuple[tuple[int, ...], ...]:
    transpose = tuple(zip(*right, strict=True))
    rows: list[tuple[int, ...]] = []
    for row in left:
        current: list[int] = []
        for column in transpose:
            total = 0
            for lhs, rhs in zip(row, column, strict=True):
                total = (total + (lhs * rhs)) % modulus
            current.append(total)
        rows.append(tuple(current))
    return tuple(rows)


def derive_tensor_product_capture(
    *,
    activation_rows: tuple[tuple[float, ...], ...],
    weight_rows: tuple[tuple[float, ...], ...],
    spec: TensorCaptureSpec,
) -> TensorProductCapture:
    if not activation_rows or not activation_rows[0]:
        raise ValueError("activation_rows must not be empty")
    if not weight_rows or not weight_rows[0]:
        raise ValueError("weight_rows must not be empty")
    source_input_width = len(activation_rows[0])
    if any(len(row) != source_input_width for row in activation_rows):
        raise ValueError("activation_rows must be rectangular")
    source_output_width = len(weight_rows)
    weight_input_width = len(weight_rows[0])
    if any(len(row) != weight_input_width for row in weight_rows):
        raise ValueError("weight_rows must be rectangular")
    if source_input_width < spec.input_width or weight_input_width < spec.input_width:
        raise ValueError("captured activation/weight surfaces are narrower than spec.input_width")
    if source_output_width < spec.output_width:
        raise ValueError("captured weight surface is shorter than spec.output_width")

    float_matrix_a = tuple(
        tuple(float(cell) for cell in row[: spec.input_width])
        for row in activation_rows
    )
    float_matrix_b = tuple(
        tuple(float(weight_rows[row_index][column_index]) for row_index in range(spec.output_width))
        for column_index in range(spec.input_width)
    )
    float_matrix_c = _float_product(float_matrix_a, float_matrix_b)

    field_matrix_a = tuple(
        tuple(_field_project(cell, scale=spec.fixed_point_scale, modulus=spec.field_modulus) for cell in row)
        for row in float_matrix_a
    )
    field_matrix_b = tuple(
        tuple(_field_project(cell, scale=spec.fixed_point_scale, modulus=spec.field_modulus) for cell in row)
        for row in float_matrix_b
    )
    field_matrix_c = _field_product(field_matrix_a, field_matrix_b, modulus=spec.field_modulus)
    payload = {
        "layer_path": spec.layer_path,
        "activation_token_index": spec.activation_token_index,
        "input_width": spec.input_width,
        "output_width": spec.output_width,
        "fixed_point_scale": spec.fixed_point_scale,
        "field_modulus": spec.field_modulus,
        "float_matrix_a": float_matrix_a,
        "float_matrix_b": float_matrix_b,
        "float_matrix_c": float_matrix_c,
        "field_matrix_a": field_matrix_a,
        "field_matrix_b": field_matrix_b,
        "field_matrix_c": field_matrix_c,
    }
    return TensorProductCapture(
        layer_path=spec.layer_path,
        activation_token_index=spec.activation_token_index,
        input_width=spec.input_width,
        output_width=spec.output_width,
        fixed_point_scale=spec.fixed_point_scale,
        field_modulus=spec.field_modulus,
        source_input_width=source_input_width,
        source_output_width=source_output_width,
        float_matrix_a=float_matrix_a,
        float_matrix_b=float_matrix_b,
        float_matrix_c=float_matrix_c,
        field_matrix_a=field_matrix_a,
        field_matrix_b=field_matrix_b,
        field_matrix_c=field_matrix_c,
        weight_root=bytes32_word(
            "E2_CAPTURED_WEIGHT_ROOT",
            {
                "layer_path": spec.layer_path,
                "output_width": spec.output_width,
                "weight_rows": weight_rows[: spec.output_width],
            },
        ),
        capture_hash=bytes32_word("E2_TENSOR_CAPTURE", payload),
    )


def _nested_floats(value: Any) -> list[Any]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list):
        raise ValueError("captured tensor payload must be list-like")
    return value


def _select_activation_rows(value: Any, *, token_index: int) -> tuple[tuple[float, ...], ...]:
    rows = _nested_floats(value)
    if rows and isinstance(rows[0], list) and rows[0] and isinstance(rows[0][0], list):
        rows = rows[0]
    if rows and isinstance(rows[0], (int, float)):
        rows = [rows]
    if not rows or token_index >= len(rows):
        raise ValueError("captured activation rows do not contain the requested token index")
    selected = rows[token_index]
    if not isinstance(selected, list) or not selected:
        raise ValueError("captured activation row is invalid")
    return (tuple(float(cell) for cell in selected),)


def _select_weight_rows(value: Any) -> tuple[tuple[float, ...], ...]:
    rows = _nested_floats(value)
    if not rows or not isinstance(rows[0], list) or not rows[0]:
        raise ValueError("captured weight rows are invalid")
    return tuple(tuple(float(cell) for cell in row) for row in rows)


def _resolve_layer(root: object, dotted_path: str) -> object:
    current = root
    for segment in dotted_path.split("."):
        if segment.isdigit():
            current = current[int(segment)]  # type: ignore[index]
        else:
            current = getattr(current, segment)
    return current


class _StaticResultAdapter(InferenceAdapter):
    def __init__(self, result: AdapterRunResult) -> None:
        self._result = result

    def run(
        self,
        *,
        task: TaskSpec,
        manifest: PinnedModelManifest,
        policy: DeterministicDecodePolicy,
    ) -> AdapterRunResult:
        return self._result


@dataclass
class _HookCapture:
    activation_rows: tuple[tuple[float, ...], ...] | None = None
    weight_rows: tuple[tuple[float, ...], ...] | None = None


def _authorized_session_state(
    session: AuthorizedLocalTransformersSession,
) -> tuple[object, object, object, PinnedModelManifest]:
    runtime = getattr(session, "_runtime", None)
    loaded_model = getattr(session, "_loaded_model", None)
    loaded_tokenizer = getattr(session, "_loaded_tokenizer", None)
    loaded_manifest = getattr(session, "_loaded_manifest", None)
    if runtime is None or loaded_model is None or loaded_tokenizer is None or loaded_manifest is None:
        raise RuntimeError("authorized E2 capture requires a verified local transformers session")
    if not isinstance(loaded_manifest, PinnedModelManifest):
        raise RuntimeError("authorized E2 capture requires a typed pinned model manifest")
    return runtime, loaded_model, loaded_tokenizer, loaded_manifest


def build_real_e2_bundle(
    *,
    run_config: RunConfig,
    task: TaskSpec,
    manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
    model_path: str,
    tokenizer_path: str | None,
    capture_spec: TensorCaptureSpec,
    receipt_id: str,
    session_factory: Callable[[], AuthorizedLocalTransformersSession] = AuthorizedLocalTransformersSession,
    clock: Callable[[], float] = perf_counter,
) -> tuple[ExecutionAuditBundle, TensorProductCapture]:
    if run_config.origin is not EvidenceOrigin.REAL_MODEL_EXECUTION:
        raise ValueError("real E2 bundle builder requires REAL_MODEL_EXECUTION origin")
    if run_config.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        raise ValueError("real E2 bundle builder requires publication-authorized scope")

    session = session_factory()
    verified_result = session(
        model_path=model_path,
        tokenizer_path=tokenizer_path or model_path,
        local_files_only=True,
        manifest=manifest,
        policy=policy,
        task=task,
    )
    runtime, loaded_model, loaded_tokenizer, loaded_manifest = _authorized_session_state(session)

    capture = _HookCapture()
    module = _resolve_layer(loaded_model, capture_spec.layer_path)

    def _hook(mod: object, inputs: tuple[Any, ...], output: Any) -> None:
        del output
        if capture.activation_rows is not None:
            return
        if not inputs:
            raise ValueError("captured layer hook did not receive inputs")
        capture.activation_rows = _select_activation_rows(
            inputs[0],
            token_index=capture_spec.activation_token_index,
        )
        capture.weight_rows = _select_weight_rows(getattr(mod, "weight", None))

    handle = module.register_forward_hook(_hook)
    try:
        inference_start = clock()
        prompt_token_ids = tuple(int(token_id) for token_id in runtime.encode_task(loaded_tokenizer, task))
        generated_token_ids = tuple(int(token_id) for token_id in runtime.generate(loaded_model, prompt_token_ids, policy))
        response = runtime.decode(loaded_tokenizer, generated_token_ids).strip()
        after_inference = clock()
    finally:
        handle.remove()

    if capture.activation_rows is None or capture.weight_rows is None:
        raise RuntimeError(f"did not capture a bounded tensor product from {capture_spec.layer_path}")
    if response != verified_result.response:
        raise RuntimeError("authorized E2 capture replay drifted from the verified deterministic session response")

    response_binding = _response_binding(response)
    result = AdapterRunResult(
        loaded_manifest=loaded_manifest,
        response=response,
        claim_texts=(f"Exact UTF8 transcript bound by {response_binding}",),
        trace_events=_trace_events(
            task=task,
            policy=policy,
            prompt_token_ids=prompt_token_ids,
            generated_token_ids=generated_token_ids,
            response=response,
        ),
        evidence_items=(
            EvidenceItem(
                evidence_id="REAL-MODEL-EXECUTION-TRANSCRIPT",
                artifact_label="execution-transcript-binding",
                content=response_binding,
                keywords=("response", "hash", "utf8-transcript"),
                origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
                confidence=None,
            ),
        ),
        warmup_ms=verified_result.warmup_ms,
        inference_ms=(after_inference - inference_start) * 1000.0,
    )
    execution_bundle = execute_once(
        task,
        manifest,
        policy,
        adapter=_StaticResultAdapter(result),
    )
    tensor_capture = derive_tensor_product_capture(
        activation_rows=capture.activation_rows,
        weight_rows=capture.weight_rows,
        spec=capture_spec,
    )
    return (
        build_execution_audit_bundle(
            run_config=run_config,
            task=task,
            model_manifest=manifest,
            policy=policy,
            execution_bundle=execution_bundle,
            capture=tensor_capture,
            receipt_id=receipt_id,
        ),
        tensor_capture,
    )


def build_execution_audit_bundle(
    *,
    run_config: RunConfig,
    task: TaskSpec,
    model_manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
    execution_bundle: ExecutionBundle,
    capture: TensorProductCapture,
    receipt_id: str,
) -> ExecutionAuditBundle:
    nonce = bytes.fromhex(
        digest(
            "E2_REAL_EXECUTION_NONCE",
            {
                "run_id": run_config.run_id,
                "receipt_id": receipt_id,
                "response_hash": execution_bundle.response_hash,
                "trace_root": execution_bundle.trace_root,
                "evidence_root": execution_bundle.evidence_root,
                "artifact_root": execution_bundle.artifact_root,
                "capture_hash": capture.capture_hash,
            },
        )
    )
    commitment = commit_response(
        task,
        execution_bundle.protocol_model_manifest,
        execution_bundle.response_hash,
        execution_bundle.trace_root,
        execution_bundle.evidence_root,
        execution_bundle.artifact_root,
        nonce,
    )
    decode_policy_hash = bytes32_word("E2_REAL_DECODE_POLICY", policy.model_dump(mode="json"))
    iec_index_hash = bytes32_word(
        "E2_REAL_IEC_INDEX",
        {
            "evidence_root": execution_bundle.iec.evidence_root,
            "claim_ids": [claim.claim_id for claim in execution_bundle.iec.claims],
            "evidence_ids": [item.evidence_id for item in execution_bundle.iec.evidence_items],
        },
    )
    nullifier = bytes32_word(
        "E2_REAL_NULLIFIER",
        {
            "run_id": run_config.run_id,
            "receipt_id": receipt_id,
            "response_hash": execution_bundle.response_hash,
            "trace_root": execution_bundle.trace_root,
            "model_manifest_hash": model_manifest.manifest_hash(policy),
        },
    )
    return ExecutionAuditBundle(
        bundle_id=f"{run_config.run_id}:{receipt_id}",
        run_id=run_config.run_id,
        experiment_id=run_config.experiment_id,
        receipt_id=receipt_id,
        origin=run_config.origin,
        run_config=run_config,
        task=task,
        model_manifest=execution_bundle.protocol_model_manifest,
        commitment=commitment,
        response_hash=execution_bundle.response_hash,
        trace_root=execution_bundle.trace_root,
        evidence_root=execution_bundle.evidence_root,
        artifact_root=execution_bundle.artifact_root,
        model_root=execution_bundle.protocol_model_manifest.model_root,
        committed_weight_root=capture.weight_root,
        weight_root=capture.weight_root,
        committed_decode_policy_hash=decode_policy_hash,
        decode_policy_hash=decode_policy_hash,
        committed_iec_index_hash=iec_index_hash,
        iec_index_hash=iec_index_hash,
        committed_nullifier=nullifier,
        nullifier=nullifier,
        committed_field_matrix_c=capture.field_matrix_c,
        field_matrix_a=capture.field_matrix_a,
        field_matrix_b=capture.field_matrix_b,
        field_matrix_c=capture.field_matrix_c,
        committed_float_matrix_c=capture.float_matrix_c,
        float_matrix_a=capture.float_matrix_a,
        float_matrix_b=capture.float_matrix_b,
        float_matrix_c=capture.float_matrix_c,
    )


__all__ = [
    "TensorCaptureSpec",
    "TensorProductCapture",
    "build_execution_audit_bundle",
    "build_real_e2_bundle",
    "derive_tensor_product_capture",
]
