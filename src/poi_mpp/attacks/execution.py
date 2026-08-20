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


class AttackReplayProof(_FrozenModel):
    schema_version: str = "POI_MPP_E2_ATTACK_REPLAY_PROOF_V1"
    attack_instance_id: str
    proof_hash: str
    seed_sensitive: bool
    original_material: dict[str, Any]
    attacked_material: dict[str, Any]
    peer_material: dict[str, Any] | None = None

    @field_validator("attack_instance_id", "proof_hash")
    @classmethod
    def require_word_hex(cls, value: str) -> str:
        if not _WORD_HEX.fullmatch(value):
            raise ValueError("replay proof digests must be 32-byte hex words")
        return value

    @field_validator("original_material", "attacked_material", "peer_material")
    @classmethod
    def require_canonical_material(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("replay proof materials must not be empty")
        return _canonicalize_material_mapping(value)


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
    replay_proof: AttackReplayProof
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
        replay_contract = validated_attack_replay_contract(self)
        if self.original_target_hash != replay_contract["original_target_hash"]:
            raise ValueError("original_target_hash does not match canonical replay witness material")
        if self.attacked_target_hash != replay_contract["attacked_target_hash"]:
            raise ValueError("attacked_target_hash does not match canonical replay witness material")
        if self.replay_proof.seed_sensitive is not replay_contract["seed_sensitive"]:
            raise ValueError("replay_proof.seed_sensitive does not match canonical attack sensitivity")
        if self.replay_proof.attack_instance_id != replay_contract["attack_instance_id"]:
            raise ValueError("replay_proof.attack_instance_id does not match canonical replay contract")
        if self.replay_proof.proof_hash != replay_contract["proof_hash"]:
            raise ValueError("replay_proof.proof_hash does not match canonical replay contract")
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


def _canonicalize_material(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonicalize_material(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {key: _canonicalize_material(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_material(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("replay proof materials must be finite")
        return value
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("replay proof string materials must not be blank")
        return value
    raise TypeError(f"unsupported replay proof material: {type(value)!r}")


def _canonicalize_material_mapping(value: dict[str, Any]) -> dict[str, Any]:
    canonical = _canonicalize_material(value)
    if not isinstance(canonical, dict):
        raise TypeError("replay proof materials must be mappings")
    return canonical


def _proof_word(label: str, payload: object) -> str:
    return "0x" + digest(label, payload)


def _normalize_word(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not _WORD_HEX.fullmatch(value):
        raise ValueError(f"{field_name} must be a 32-byte hex word")
    return value


def _normalize_int_matrix_material(value: Any, *, field_name: str) -> tuple[tuple[int, ...], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a rectangular integer matrix")
    rows: list[tuple[int, ...]] = []
    width: int | None = None
    for row in value:
        if not isinstance(row, list):
            raise ValueError(f"{field_name} must be a rectangular integer matrix")
        normalized_row: list[int] = []
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, int):
                raise ValueError(f"{field_name} must contain integers")
            normalized_row.append(cell)
        if width is None:
            width = len(normalized_row)
        elif len(normalized_row) != width:
            raise ValueError(f"{field_name} must be rectangular")
        rows.append(tuple(normalized_row))
    return _validate_int_matrix(tuple(rows))


def _normalize_float_matrix_material(value: Any, *, field_name: str) -> tuple[tuple[float, ...], ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a rectangular float matrix")
    rows: list[tuple[float, ...]] = []
    width: int | None = None
    for row in value:
        if not isinstance(row, list):
            raise ValueError(f"{field_name} must be a rectangular float matrix")
        normalized_row: list[float] = []
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, (int, float)):
                raise ValueError(f"{field_name} must contain numeric entries")
            numeric = float(cell)
            if not math.isfinite(numeric):
                raise ValueError(f"{field_name} must contain finite numeric entries")
            normalized_row.append(numeric)
        if width is None:
            width = len(normalized_row)
        elif len(normalized_row) != width:
            raise ValueError(f"{field_name} must be rectangular")
        rows.append(tuple(normalized_row))
    return _validate_float_matrix(tuple(rows))


def _seed_sensitive_attack(family: AttackFamily) -> bool:
    return family not in {
        AttackFamily.CROSS_REQUEST_SPLICE,
        AttackFamily.REPLAY_NULLIFIER,
        AttackFamily.UNSUPPORTED_KERNEL,
    }


def _original_attack_material(
    bundle: ExecutionAuditBundle,
    family: AttackFamily,
    *,
    numeric_mode: AttackNumericMode | None = None,
) -> dict[str, Any]:
    if family is AttackFamily.MODEL_ROOT_SUBSTITUTION:
        return {"model_root": bundle.model_root}
    if family is AttackFamily.WEIGHT_CORRUPTION:
        return {"weight_root": bundle.weight_root}
    if family is AttackFamily.TRACE_NODE_MUTATION:
        return {"trace_root": bundle.trace_root}
    if family is AttackFamily.TENSOR_PRODUCT_CORRUPTION:
        if numeric_mode is AttackNumericMode.EMPIRICAL_FLOAT:
            return {"float_matrix_c": bundle.float_matrix_c}
        return {"field_matrix_c": bundle.field_matrix_c}
    if family is AttackFamily.RESPONSE_BINDING_MISMATCH:
        return {"response_hash": bundle.response_hash, "trace_root": bundle.trace_root}
    if family is AttackFamily.IEC_EVIDENCE_INDEX_MUTATION:
        return {"iec_index_hash": bundle.iec_index_hash}
    if family is AttackFamily.DECODE_POLICY_MUTATION:
        return {"decode_policy_hash": bundle.decode_policy_hash}
    if family is AttackFamily.CROSS_REQUEST_SPLICE:
        return {"response_hash": bundle.response_hash, "trace_root": bundle.trace_root}
    if family is AttackFamily.REPLAY_NULLIFIER:
        return {"nullifier": bundle.nullifier}
    if family is AttackFamily.UNSUPPORTED_KERNEL:
        return {"kernel_label": bundle.kernel_label}
    raise ValueError(f"unsupported attack family: {family}")


def _attacked_attack_material(
    bundle: ExecutionAuditBundle,
    family: AttackFamily,
    *,
    numeric_mode: AttackNumericMode | None = None,
) -> dict[str, Any]:
    if family is AttackFamily.MODEL_ROOT_SUBSTITUTION:
        return {"model_root": bundle.model_root}
    if family is AttackFamily.WEIGHT_CORRUPTION:
        return {"weight_root": bundle.weight_root}
    if family is AttackFamily.TRACE_NODE_MUTATION:
        return {"trace_root": bundle.trace_root}
    if family is AttackFamily.TENSOR_PRODUCT_CORRUPTION:
        if numeric_mode is AttackNumericMode.EMPIRICAL_FLOAT:
            return {"float_matrix_c": bundle.float_matrix_c}
        return {"field_matrix_c": bundle.field_matrix_c}
    if family is AttackFamily.RESPONSE_BINDING_MISMATCH:
        return {"response_hash": bundle.response_hash, "trace_root": bundle.trace_root}
    if family is AttackFamily.IEC_EVIDENCE_INDEX_MUTATION:
        return {"iec_index_hash": bundle.iec_index_hash}
    if family is AttackFamily.DECODE_POLICY_MUTATION:
        return {"decode_policy_hash": bundle.decode_policy_hash}
    if family is AttackFamily.CROSS_REQUEST_SPLICE:
        return {"response_hash": bundle.response_hash, "trace_root": bundle.trace_root}
    if family is AttackFamily.REPLAY_NULLIFIER:
        return {"nullifier": bundle.nullifier}
    if family is AttackFamily.UNSUPPORTED_KERNEL:
        return {"kernel_label": bundle.kernel_label}
    raise ValueError(f"unsupported attack family: {family}")


def _peer_attack_material(
    peer_bundle: ExecutionAuditBundle | None,
    family: AttackFamily,
) -> dict[str, Any] | None:
    if peer_bundle is None:
        return None
    if family is AttackFamily.CROSS_REQUEST_SPLICE:
        return {
            "peer_receipt_id": peer_bundle.receipt_id,
            "response_hash": peer_bundle.response_hash,
            "trace_root": peer_bundle.trace_root,
        }
    if family is AttackFamily.REPLAY_NULLIFIER:
        return {
            "peer_receipt_id": peer_bundle.receipt_id,
            "nullifier": peer_bundle.nullifier,
        }
    return None


def _replayed_attacked_material_from_proof(manifest: AttackManifest) -> dict[str, Any]:
    original = manifest.replay_proof.original_material
    peer = manifest.replay_proof.peer_material
    seed = manifest.seed
    family = manifest.family
    if family is AttackFamily.MODEL_ROOT_SUBSTITUTION:
        return {"model_root": _mutate_word(_normalize_word(original.get("model_root"), field_name="model_root"), seed=seed, label="model_root")}
    if family is AttackFamily.WEIGHT_CORRUPTION:
        return {"weight_root": _mutate_word(_normalize_word(original.get("weight_root"), field_name="weight_root"), seed=seed, label="weights")}
    if family is AttackFamily.TRACE_NODE_MUTATION:
        return {"trace_root": _mutate_word(_normalize_word(original.get("trace_root"), field_name="trace_root"), seed=seed, label="trace")}
    if family is AttackFamily.TENSOR_PRODUCT_CORRUPTION:
        if manifest.numeric_mode is AttackNumericMode.EMPIRICAL_FLOAT:
            matrix = _normalize_float_matrix_material(original.get("float_matrix_c"), field_name="float_matrix_c")
            return {"float_matrix_c": _mutate_float_product(matrix, seed=seed)}
        matrix = _normalize_int_matrix_material(original.get("field_matrix_c"), field_name="field_matrix_c")
        return {"field_matrix_c": _mutate_int_product(matrix, seed=seed)}
    if family is AttackFamily.RESPONSE_BINDING_MISMATCH:
        return {
            "response_hash": _mutate_word(
                _normalize_word(original.get("response_hash"), field_name="response_hash"),
                seed=seed,
                label="response_binding",
            ),
            "trace_root": _normalize_word(original.get("trace_root"), field_name="trace_root"),
        }
    if family is AttackFamily.IEC_EVIDENCE_INDEX_MUTATION:
        return {
            "iec_index_hash": _mutate_word(
                _normalize_word(original.get("iec_index_hash"), field_name="iec_index_hash"),
                seed=seed,
                label="iec_index",
            )
        }
    if family is AttackFamily.DECODE_POLICY_MUTATION:
        return {
            "decode_policy_hash": _mutate_word(
                _normalize_word(original.get("decode_policy_hash"), field_name="decode_policy_hash"),
                seed=seed,
                label="decode_policy",
            )
        }
    if family is AttackFamily.CROSS_REQUEST_SPLICE:
        if peer is None:
            raise ValueError("cross-request splice replay proof requires peer material")
        return {
            "response_hash": _normalize_word(peer.get("response_hash"), field_name="peer.response_hash"),
            "trace_root": _normalize_word(peer.get("trace_root"), field_name="peer.trace_root"),
        }
    if family is AttackFamily.REPLAY_NULLIFIER:
        if peer is None:
            raise ValueError("replay-nullifier proof requires peer material")
        return {"nullifier": _normalize_word(peer.get("nullifier"), field_name="peer.nullifier")}
    if family is AttackFamily.UNSUPPORTED_KERNEL:
        return {"kernel_label": "UNSUPPORTED_KERNEL"}
    raise ValueError(f"unsupported attack family: {family}")


def _target_hash_from_material(
    family: AttackFamily,
    material: dict[str, Any],
    *,
    numeric_mode: AttackNumericMode | None = None,
) -> str:
    if family is AttackFamily.MODEL_ROOT_SUBSTITUTION:
        return _normalize_word(material.get("model_root"), field_name="model_root")
    if family is AttackFamily.WEIGHT_CORRUPTION:
        return _normalize_word(material.get("weight_root"), field_name="weight_root")
    if family is AttackFamily.TRACE_NODE_MUTATION:
        return _normalize_word(material.get("trace_root"), field_name="trace_root")
    if family is AttackFamily.TENSOR_PRODUCT_CORRUPTION:
        if numeric_mode is AttackNumericMode.EMPIRICAL_FLOAT:
            return _matrix_hash(
                "E2_FLOAT_PRODUCT",
                _normalize_float_matrix_material(material.get("float_matrix_c"), field_name="float_matrix_c"),
            )
        return _matrix_hash(
            "E2_FIELD_PRODUCT",
            _normalize_int_matrix_material(material.get("field_matrix_c"), field_name="field_matrix_c"),
        )
    if family in {AttackFamily.RESPONSE_BINDING_MISMATCH, AttackFamily.CROSS_REQUEST_SPLICE}:
        return _binding_hash(
            _normalize_word(material.get("response_hash"), field_name="response_hash"),
            _normalize_word(material.get("trace_root"), field_name="trace_root"),
        )
    if family is AttackFamily.IEC_EVIDENCE_INDEX_MUTATION:
        return _normalize_word(material.get("iec_index_hash"), field_name="iec_index_hash")
    if family is AttackFamily.DECODE_POLICY_MUTATION:
        return _normalize_word(material.get("decode_policy_hash"), field_name="decode_policy_hash")
    if family is AttackFamily.REPLAY_NULLIFIER:
        return _normalize_word(material.get("nullifier"), field_name="nullifier")
    if family is AttackFamily.UNSUPPORTED_KERNEL:
        kernel_label = material.get("kernel_label")
        if not isinstance(kernel_label, str) or not kernel_label.strip():
            raise ValueError("kernel_label must be a non-blank string")
        return _proof_word("E2_KERNEL_PATH", {"kernel_label": kernel_label})
    raise ValueError(f"unsupported attack family: {family}")


def _attack_instance_payload(manifest: AttackManifest) -> dict[str, Any]:
    return {
        "family": manifest.family.value,
        "location": manifest.location,
        "seed": manifest.seed,
        "numeric_mode": manifest.numeric_mode.value if manifest.numeric_mode is not None else None,
        "parameters": [parameter.model_dump(mode="json") for parameter in manifest.parameters],
        "original_material": manifest.replay_proof.original_material,
        "attacked_material": manifest.replay_proof.attacked_material,
        "peer_material": manifest.replay_proof.peer_material,
    }


def _build_replay_proof(
    *,
    family: AttackFamily,
    location: str,
    seed: int,
    numeric_mode: AttackNumericMode | None,
    parameters: tuple[AttackParameter, ...],
    original_material: dict[str, Any],
    attacked_material: dict[str, Any],
    peer_material: dict[str, Any] | None,
    original_target_hash: str,
    attacked_target_hash: str,
) -> AttackReplayProof:
    attack_instance_id = _proof_word(
        "E2_ATTACK_INSTANCE",
        {
            "family": family.value,
            "location": location,
            "seed": seed,
            "numeric_mode": numeric_mode.value if numeric_mode is not None else None,
            "parameters": [parameter.model_dump(mode="json") for parameter in parameters],
            "original_material": original_material,
            "attacked_material": attacked_material,
            "peer_material": peer_material,
        },
    )
    return AttackReplayProof(
        attack_instance_id=attack_instance_id,
        proof_hash=_proof_word(
            "E2_ATTACK_REPLAY_PROOF",
            {
                "attack_instance_id": attack_instance_id,
                "seed_sensitive": _seed_sensitive_attack(family),
                "original_target_hash": original_target_hash,
                "attacked_target_hash": attacked_target_hash,
            },
        ),
        seed_sensitive=_seed_sensitive_attack(family),
        original_material=original_material,
        attacked_material=attacked_material,
        peer_material=peer_material,
    )


def validated_attack_replay_contract(manifest: AttackManifest) -> dict[str, Any]:
    replayed_attacked_material = _canonicalize_material_mapping(
        _replayed_attacked_material_from_proof(manifest)
    )
    if replayed_attacked_material != manifest.replay_proof.attacked_material:
        raise ValueError("replay proof attacked material does not match deterministic family replay")
    original_target_hash = _target_hash_from_material(
        manifest.family,
        manifest.replay_proof.original_material,
        numeric_mode=manifest.numeric_mode,
    )
    attacked_target_hash = _target_hash_from_material(
        manifest.family,
        replayed_attacked_material,
        numeric_mode=manifest.numeric_mode,
    )
    attack_instance_id = _proof_word("E2_ATTACK_INSTANCE", _attack_instance_payload(manifest))
    proof_hash = _proof_word(
        "E2_ATTACK_REPLAY_PROOF",
        {
            "attack_instance_id": attack_instance_id,
            "seed_sensitive": _seed_sensitive_attack(manifest.family),
            "original_target_hash": original_target_hash,
            "attacked_target_hash": attacked_target_hash,
        },
    )
    return {
        "seed_sensitive": _seed_sensitive_attack(manifest.family),
        "original_target_hash": original_target_hash,
        "attacked_target_hash": attacked_target_hash,
        "attack_instance_id": attack_instance_id,
        "proof_hash": proof_hash,
    }

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
    original_material = _canonicalize_material_mapping(
        _original_attack_material(bundle, family, numeric_mode=numeric_mode)
    )
    attacked_material = _canonicalize_material_mapping(
        _attacked_attack_material(attacked, family, numeric_mode=numeric_mode)
    )
    peer_material = _peer_attack_material(peer_bundle, family)
    canonical_peer_material = (
        _canonicalize_material_mapping(peer_material)
        if peer_material is not None
        else None
    )
    parameter_items = _parameter_items(parameters)
    original_target_hash = committed_target_hash(
        bundle,
        family,
        numeric_mode=numeric_mode,
    )
    attacked_target_hash = observed_target_hash(
        attacked,
        family,
        numeric_mode=numeric_mode,
    )
    proof = _build_replay_proof(
        family=family,
        location=location,
        seed=seed,
        numeric_mode=numeric_mode,
        parameters=parameter_items,
        original_material=original_material,
        attacked_material=attacked_material,
        peer_material=canonical_peer_material,
        original_target_hash=original_target_hash,
        attacked_target_hash=attacked_target_hash,
    )
    manifest = AttackManifest(
        family=family,
        analysis_surface=support,
        numeric_mode=numeric_mode,
        location=location,
        seed=seed,
        origin=bundle.origin,
        original_commitment=bundle.commitment.commitment_hash,
        original_target_hash=original_target_hash,
        attacked_target_hash=attacked_target_hash,
        replay_proof=proof,
        parameters=parameter_items,
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
    parameters = _parameter_items({"index": index})
    replay_proof = _build_replay_proof(
        family=manifest.family,
        location=f"trace.nodes[{index}]",
        seed=manifest.seed,
        numeric_mode=manifest.numeric_mode,
        parameters=parameters,
        original_material=manifest.replay_proof.original_material,
        attacked_material=manifest.replay_proof.attacked_material,
        peer_material=manifest.replay_proof.peer_material,
        original_target_hash=manifest.original_target_hash,
        attacked_target_hash=manifest.attacked_target_hash,
    )
    updated_manifest = manifest.model_copy(
        update={
            "location": f"trace.nodes[{index}]",
            "parameters": parameters,
            "replay_proof": replay_proof,
        }
    )
    return attacked, updated_manifest
