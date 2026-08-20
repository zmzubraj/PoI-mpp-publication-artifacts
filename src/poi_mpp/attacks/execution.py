"""Frozen attack fixtures for deterministic post-commit tamper experiments."""

from __future__ import annotations

from enum import StrEnum
import math
import random
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.protocol import ModelManifest, ResponseCommitment, TaskSpec


_WORD_HEX = re.compile(r"0x[0-9a-f]{64}\Z")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AttackFamily(StrEnum):
    MODEL_ROOT_SUBSTITUTION = "MODEL_ROOT_SUBSTITUTION"
    WEIGHT_CORRUPTION = "WEIGHT_CORRUPTION"
    TRACE_NODE_MUTATION = "TRACE_NODE_MUTATION"
    TENSOR_PRODUCT_CORRUPTION = "TENSOR_PRODUCT_CORRUPTION"
    RESPONSE_BINDING_MISMATCH = "RESPONSE_BINDING_MISMATCH"
    IEC_EVIDENCE_INDEX_MUTATION = "IEC_EVIDENCE_INDEX_MUTATION"
    DECODE_POLICY_MUTATION = "DECODE_POLICY_MUTATION"
    CROSS_REQUEST_SPLICE = "CROSS_REQUEST_SPLICE"
    REPLAY_NULLIFIER = "REPLAY_NULLIFIER"
    UNSUPPORTED_KERNEL = "UNSUPPORTED_KERNEL"


class AttackAnalysisSurface(StrEnum):
    EXACT_MATCH = "EXACT_MATCH"
    EXACT_FIELD = "EXACT_FIELD_SOUNDNESS"
    EMPIRICAL_FLOAT = "EMPIRICAL_FLOAT_APPROXIMATION"
    UNSUPPORTED = "UNSUPPORTED_SURFACE"


class AttackNumericMode(StrEnum):
    EXACT_FIELD = "EXACT_FIELD"
    EMPIRICAL_FLOAT = "EMPIRICAL_FLOAT"


class AttackParameter(_FrozenModel):
    key: str
    value: str | int | float | bool

    @field_validator("key")
    @classmethod
    def require_nonblank_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("attack parameter keys must not be blank")
        return value

    @field_validator("value")
    @classmethod
    def reject_nonfinite_float(cls, value: str | int | float | bool) -> str | int | float | bool:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("attack parameter floats must be finite")
        return value


class AttackManifest(_FrozenModel):
    schema_version: str = "POI_MPP_E2_ATTACK_MANIFEST_V1"
    family: AttackFamily
    analysis_surface: AttackAnalysisSurface
    numeric_mode: AttackNumericMode | None = None
    location: str
    seed: int = Field(ge=0)
    origin: EvidenceOrigin
    original_commitment: str
    original_target_hash: str
    attacked_target_hash: str
    parameters: tuple[AttackParameter, ...] = ()

    @field_validator("location")
    @classmethod
    def require_nonblank_location(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("attack location must not be blank")
        return value

    @field_validator("original_commitment", "original_target_hash", "attacked_target_hash")
    @classmethod
    def require_word_hex(cls, value: str) -> str:
        if not _WORD_HEX.fullmatch(value):
            raise ValueError("attack manifest hashes must be 32-byte hex words")
        return value

    @model_validator(mode="after")
    def validate_canonical_surface(self) -> "AttackManifest":
        expected = canonical_attack_surface(self.family, numeric_mode=self.numeric_mode)
        if self.analysis_surface is not expected:
            raise ValueError("analysis_surface must equal the canonical surface for family/numeric_mode")
        if self.family is AttackFamily.TENSOR_PRODUCT_CORRUPTION:
            if self.numeric_mode is None:
                raise ValueError("tensor corruption attacks require numeric_mode")
        elif self.numeric_mode is not None:
            raise ValueError("numeric_mode is only valid for tensor corruption attacks")
        return self


class ExecutionAuditBundle(_FrozenModel):
    schema_version: str = "POI_MPP_E2_EXECUTION_BUNDLE_V1"
    bundle_id: str
    run_id: str
    experiment_id: str
    receipt_id: str
    origin: EvidenceOrigin
    run_config: Any
    task: TaskSpec
    model_manifest: ModelManifest
    commitment: Any
    response_hash: str
    trace_root: str
    evidence_root: str
    artifact_root: str
    model_root: str
    committed_weight_root: str
    weight_root: str
    committed_decode_policy_hash: str
    decode_policy_hash: str
    committed_iec_index_hash: str
    iec_index_hash: str
    committed_nullifier: str
    nullifier: str
    committed_field_matrix_c: tuple[tuple[int, ...], ...]
    field_matrix_a: tuple[tuple[int, ...], ...]
    field_matrix_b: tuple[tuple[int, ...], ...]
    field_matrix_c: tuple[tuple[int, ...], ...]
    committed_float_matrix_c: tuple[tuple[float, ...], ...]
    float_matrix_a: tuple[tuple[float, ...], ...]
    float_matrix_b: tuple[tuple[float, ...], ...]
    float_matrix_c: tuple[tuple[float, ...], ...]
    committed_kernel_label: str = "SUPPORTED_KERNEL"
    kernel_label: str = "SUPPORTED_KERNEL"

    def model_copy(
        self,
        *,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> "ExecutionAuditBundle":
        if not update:
            return super().model_copy(deep=deep)
        merged = {
            field_name: getattr(self, field_name)
            for field_name in type(self).model_fields
        }
        merged.update(update)
        return type(self).model_validate(merged)

    @field_validator(
        "bundle_id",
        "run_id",
        "experiment_id",
        "receipt_id",
        "committed_kernel_label",
        "kernel_label",
    )
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("bundle text fields must not be blank")
        return value

    @field_validator(
        "response_hash",
        "trace_root",
        "evidence_root",
        "artifact_root",
        "model_root",
        "committed_weight_root",
        "weight_root",
        "committed_decode_policy_hash",
        "decode_policy_hash",
        "committed_iec_index_hash",
        "iec_index_hash",
        "committed_nullifier",
        "nullifier",
    )
    @classmethod
    def require_word_hex(cls, value: str) -> str:
        if not _WORD_HEX.fullmatch(value):
            raise ValueError("bundle roots must be 32-byte hex words")
        return value

    @field_validator(
        "committed_field_matrix_c",
        "field_matrix_a",
        "field_matrix_b",
        "field_matrix_c",
    )
    @classmethod
    def require_int_matrix(cls, value: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, ...], ...]:
        return _validate_int_matrix(value)

    @field_validator(
        "committed_float_matrix_c",
        "float_matrix_a",
        "float_matrix_b",
        "float_matrix_c",
    )
    @classmethod
    def require_float_matrix(
        cls, value: tuple[tuple[float, ...], ...]
    ) -> tuple[tuple[float, ...], ...]:
        return _validate_float_matrix(value)

    @model_validator(mode="after")
    def validate_commitment_alignment(self) -> "ExecutionAuditBundle":
        if not isinstance(self.commitment, ResponseCommitment):
            raise ValueError("bundle commitment must be a ResponseCommitment")
        if self.commitment.task_id != self.task.task_id:
            raise ValueError("bundle commitment must bind the supplied task")
        if self.task.task_id < 0:
            raise ValueError("task_id must be non-negative")
        return self


def _validate_int_matrix(value: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, ...], ...]:
    if not value:
        raise ValueError("exact matrices must not be empty")
    width = len(value[0])
    if width == 0:
        raise ValueError("exact matrices must not contain empty rows")
    for row in value:
        if len(row) != width:
            raise ValueError("exact matrices must be rectangular")
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, int):
                raise ValueError("exact matrices must contain integers")
    return value


def _validate_float_matrix(value: tuple[tuple[float, ...], ...]) -> tuple[tuple[float, ...], ...]:
    if not value:
        raise ValueError("float matrices must not be empty")
    width = len(value[0])
    if width == 0:
        raise ValueError("float matrices must not contain empty rows")
    for row in value:
        if len(row) != width:
            raise ValueError("float matrices must be rectangular")
        for cell in row:
            if not math.isfinite(float(cell)):
                raise ValueError("float matrices must contain only finite values")
    return value


def _parameter_items(parameters: dict[str, str | int | float | bool]) -> tuple[AttackParameter, ...]:
    return tuple(AttackParameter(key=key, value=value) for key, value in sorted(parameters.items()))


def canonical_attack_surface(
    family: AttackFamily,
    *,
    numeric_mode: AttackNumericMode | None = None,
) -> AttackAnalysisSurface:
    if family is AttackFamily.TENSOR_PRODUCT_CORRUPTION:
        if numeric_mode is AttackNumericMode.EXACT_FIELD:
            return AttackAnalysisSurface.EXACT_FIELD
        if numeric_mode is AttackNumericMode.EMPIRICAL_FLOAT:
            return AttackAnalysisSurface.EMPIRICAL_FLOAT
        raise ValueError("tensor corruption attacks require a canonical numeric_mode")
    if family is AttackFamily.UNSUPPORTED_KERNEL:
        if numeric_mode is not None:
            raise ValueError("unsupported kernel attacks cannot declare numeric_mode")
        return AttackAnalysisSurface.UNSUPPORTED
    if numeric_mode is not None:
        raise ValueError("numeric_mode is only valid for tensor corruption attacks")
    return AttackAnalysisSurface.EXACT_MATCH


def _mutate_word(value: str, *, seed: int, label: str) -> str:
    raw = bytearray(bytes.fromhex(value[2:]))
    rng = random.Random(f"{label}:{seed}:{value}")
    index = rng.randrange(len(raw))
    raw[index] ^= 0x01 | (rng.randrange(1, 255) & 0xFE)
    return "0x" + bytes(raw).hex()


def _mutate_int_product(
    matrix: tuple[tuple[int, ...], ...],
    *,
    seed: int,
) -> tuple[tuple[int, ...], ...]:
    rows = [list(row) for row in matrix]
    rng = random.Random(f"field:{seed}:{matrix}")
    row_index = rng.randrange(len(rows))
    col_index = rng.randrange(len(rows[row_index]))
    rows[row_index][col_index] = rows[row_index][col_index] + 1
    return tuple(tuple(row) for row in rows)


def _mutate_float_product(
    matrix: tuple[tuple[float, ...], ...],
    *,
    seed: int,
) -> tuple[tuple[float, ...], ...]:
    rows = [list(row) for row in matrix]
    rng = random.Random(f"float:{seed}:{matrix}")
    row_index = rng.randrange(len(rows))
    col_index = rng.randrange(len(rows[row_index]))
    rows[row_index][col_index] = float(rows[row_index][col_index]) + (1.0 + rng.random())
    return tuple(tuple(row) for row in rows)


def _binding_hash(response_hash: str, trace_root: str) -> str:
    return "0x" + digest(
        "E2_RESPONSE_BINDING",
        {"response_hash": response_hash, "trace_root": trace_root},
    )


def _matrix_hash(label: str, matrix: tuple[tuple[int, ...], ...] | tuple[tuple[float, ...], ...]) -> str:
    return "0x" + digest(label, {"matrix": matrix})


def committed_target_hash(
    bundle: ExecutionAuditBundle,
    family: AttackFamily,
    *,
    numeric_mode: AttackNumericMode | None = None,
) -> str:
    if family is AttackFamily.MODEL_ROOT_SUBSTITUTION:
        return bundle.model_manifest.model_root
    if family is AttackFamily.WEIGHT_CORRUPTION:
        return bundle.committed_weight_root
    if family is AttackFamily.TRACE_NODE_MUTATION:
        return bundle.commitment.trace_root
    if family is AttackFamily.TENSOR_PRODUCT_CORRUPTION:
        support = canonical_attack_surface(family, numeric_mode=numeric_mode)
        if support is AttackAnalysisSurface.EMPIRICAL_FLOAT:
            return _matrix_hash("E2_FLOAT_PRODUCT", bundle.committed_float_matrix_c)
        return _matrix_hash("E2_FIELD_PRODUCT", bundle.committed_field_matrix_c)
    if family is AttackFamily.RESPONSE_BINDING_MISMATCH:
        return _binding_hash(bundle.commitment.response_hash, bundle.commitment.trace_root)
    if family is AttackFamily.IEC_EVIDENCE_INDEX_MUTATION:
        return bundle.committed_iec_index_hash
    if family is AttackFamily.DECODE_POLICY_MUTATION:
        return bundle.committed_decode_policy_hash
    if family is AttackFamily.CROSS_REQUEST_SPLICE:
        return _binding_hash(bundle.commitment.response_hash, bundle.commitment.trace_root)
    if family is AttackFamily.REPLAY_NULLIFIER:
        return bundle.committed_nullifier
    if family is AttackFamily.UNSUPPORTED_KERNEL:
        return "0x" + digest("E2_KERNEL_PATH", {"kernel_label": bundle.committed_kernel_label})
    raise ValueError(f"unsupported attack family: {family}")


def observed_target_hash(
    bundle: ExecutionAuditBundle,
    family: AttackFamily,
    *,
    numeric_mode: AttackNumericMode | None = None,
) -> str:
    if family is AttackFamily.MODEL_ROOT_SUBSTITUTION:
        return bundle.model_root
    if family is AttackFamily.WEIGHT_CORRUPTION:
        return bundle.weight_root
    if family is AttackFamily.TRACE_NODE_MUTATION:
        return bundle.trace_root
    if family is AttackFamily.TENSOR_PRODUCT_CORRUPTION:
        support = canonical_attack_surface(family, numeric_mode=numeric_mode)
        if support is AttackAnalysisSurface.EMPIRICAL_FLOAT:
            return _matrix_hash("E2_FLOAT_PRODUCT", bundle.float_matrix_c)
        return _matrix_hash("E2_FIELD_PRODUCT", bundle.field_matrix_c)
    if family is AttackFamily.RESPONSE_BINDING_MISMATCH:
        return _binding_hash(bundle.response_hash, bundle.trace_root)
    if family is AttackFamily.IEC_EVIDENCE_INDEX_MUTATION:
        return bundle.iec_index_hash
    if family is AttackFamily.DECODE_POLICY_MUTATION:
        return bundle.decode_policy_hash
    if family is AttackFamily.CROSS_REQUEST_SPLICE:
        return _binding_hash(bundle.response_hash, bundle.trace_root)
    if family is AttackFamily.REPLAY_NULLIFIER:
        return bundle.nullifier
    if family is AttackFamily.UNSUPPORTED_KERNEL:
        return "0x" + digest("E2_KERNEL_PATH", {"kernel_label": bundle.kernel_label})
    raise ValueError(f"unsupported attack family: {family}")


def apply_attack(
    bundle: ExecutionAuditBundle,
    family: AttackFamily,
    *,
    seed: int,
    peer_bundle: ExecutionAuditBundle | None = None,
    analysis_surface: AttackAnalysisSurface | None = None,
) -> tuple[ExecutionAuditBundle, AttackManifest]:
    numeric_mode: AttackNumericMode | None = None
    if family is AttackFamily.TENSOR_PRODUCT_CORRUPTION:
        if analysis_surface is None:
            numeric_mode = AttackNumericMode.EXACT_FIELD
        elif analysis_surface is AttackAnalysisSurface.EXACT_FIELD:
            numeric_mode = AttackNumericMode.EXACT_FIELD
        elif analysis_surface is AttackAnalysisSurface.EMPIRICAL_FLOAT:
            numeric_mode = AttackNumericMode.EMPIRICAL_FLOAT
        else:
            raise ValueError("tensor corruption attacks only support exact-field or empirical-float surfaces")
    elif analysis_surface is not None:
        expected_surface = canonical_attack_surface(family)
        if analysis_surface is not expected_surface:
            raise ValueError("analysis_surface cannot relabel the canonical attack surface")
    support = canonical_attack_surface(family, numeric_mode=numeric_mode)
    parameters: dict[str, str | int | float | bool] = {}
    updates: dict[str, Any]
    location: str

    if family is AttackFamily.MODEL_ROOT_SUBSTITUTION:
        location = "model_manifest.model_root"
        updates = {"model_root": _mutate_word(bundle.model_root, seed=seed, label="model_root")}
    elif family is AttackFamily.WEIGHT_CORRUPTION:
        location = "weights.root"
        updates = {"weight_root": _mutate_word(bundle.weight_root, seed=seed, label="weights")}
    elif family is AttackFamily.TRACE_NODE_MUTATION:
        location = "trace.nodes[0]"
        updates = {"trace_root": _mutate_word(bundle.trace_root, seed=seed, label="trace")}
    elif family is AttackFamily.TENSOR_PRODUCT_CORRUPTION:
        if support is AttackAnalysisSurface.EMPIRICAL_FLOAT:
            location = "float_product"
            updates = {
                "float_matrix_c": _mutate_float_product(bundle.float_matrix_c, seed=seed)
            }
        else:
            location = "field_product"
            support = AttackAnalysisSurface.EXACT_FIELD
            updates = {
                "field_matrix_c": _mutate_int_product(bundle.field_matrix_c, seed=seed)
            }
        assert numeric_mode is not None
        parameters["numeric_mode"] = numeric_mode.value
    elif family is AttackFamily.RESPONSE_BINDING_MISMATCH:
        location = "response.binding"
        updates = {
            "response_hash": _mutate_word(
                bundle.response_hash,
                seed=seed,
                label="response_binding",
            )
        }
    elif family is AttackFamily.IEC_EVIDENCE_INDEX_MUTATION:
        location = "evidence.indices"
        updates = {
            "iec_index_hash": _mutate_word(bundle.iec_index_hash, seed=seed, label="iec_index")
        }
    elif family is AttackFamily.DECODE_POLICY_MUTATION:
        location = "decode.policy"
        updates = {
            "decode_policy_hash": _mutate_word(
                bundle.decode_policy_hash,
                seed=seed,
                label="decode_policy",
            )
        }
    elif family is AttackFamily.CROSS_REQUEST_SPLICE:
        if peer_bundle is None:
            raise ValueError("cross-request splice requires peer_bundle")
        location = "cross_request.splice"
        updates = {
            "response_hash": peer_bundle.response_hash,
            "trace_root": peer_bundle.trace_root,
        }
        parameters["peer_receipt_id"] = peer_bundle.receipt_id
    elif family is AttackFamily.REPLAY_NULLIFIER:
        if peer_bundle is None:
            raise ValueError("replay attack requires peer_bundle")
        location = "receipt.nullifier"
        updates = {"nullifier": peer_bundle.nullifier}
        parameters["peer_receipt_id"] = peer_bundle.receipt_id
    elif family is AttackFamily.UNSUPPORTED_KERNEL:
        location = "runtime.kernel"
        updates = {"kernel_label": "UNSUPPORTED_KERNEL"}
    else:
        raise ValueError(f"unsupported attack family: {family}")

    attacked = bundle.model_copy(update=updates)
    manifest = AttackManifest(
        family=family,
        analysis_surface=support,
        numeric_mode=numeric_mode,
        location=location,
        seed=seed,
        origin=bundle.origin,
        original_commitment=bundle.commitment.commitment_hash,
        original_target_hash=committed_target_hash(
            bundle,
            family,
            numeric_mode=numeric_mode,
        ),
        attacked_target_hash=observed_target_hash(
            attacked,
            family,
            numeric_mode=numeric_mode,
        ),
        parameters=_parameter_items(parameters),
    )
    return attacked, manifest


def corrupt_trace_node(
    bundle: ExecutionAuditBundle,
    *,
    index: int,
    seed: int = 1,
) -> tuple[ExecutionAuditBundle, AttackManifest]:
    attacked, manifest = apply_attack(
        bundle,
        AttackFamily.TRACE_NODE_MUTATION,
        seed=seed,
    )
    updated_manifest = manifest.model_copy(
        update={
            "location": f"trace.nodes[{index}]",
            "parameters": _parameter_items({"index": index}),
        }
    )
    return attacked, updated_manifest
