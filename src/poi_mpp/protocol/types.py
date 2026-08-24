"""Frozen protocol types and EVM-compatible hashing helpers."""

from __future__ import annotations

from contextvars import ContextVar
from enum import IntEnum
from functools import lru_cache
import re
import subprocess
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator


_WORD_HEX = re.compile(r"(?:0x)?[0-9a-f]{64}\Z")
_ADDRESS_HEX = re.compile(r"0x[0-9a-f]{40}\Z")
_COMMITMENT_CONTEXT_SENTINEL = object()
_commitment_construction_context: ContextVar[object | None] = ContextVar(
    "poi_mpp_response_commitment_construction",
    default=None,
)

_TASK_DOMAIN = "POI_MPP_TASK"
_MODEL_DOMAIN = "POI_MPP_MODEL"
_RESPONSE_DOMAIN = "POI_MPP_RESPONSE_COMMITMENT"
_DOMAIN_VERSION = 1


class _FrozenProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskClass(IntEnum):
    SERVICE = 0
    CONSENSUS = 1


class AuditDecision(IntEnum):
    NONE = 0
    ACCEPT = 1
    REJECT = 2
    ABSTAIN = 3


class ReceiptState(IntEnum):
    NONE = 0
    PENDING = 1
    ACTIVE = 2
    ABSTAINED = 3
    CHALLENGED = 4
    DA_FAILED = 5
    EXPIRED = 6
    REJECTED = 7
    SLASHED = 8


class ReceiptVerificationMode(IntEnum):
    LEGACY_PROTOCOL = 0
    SEMANTIC_PUBLICATION = 1


def _normalize_word_hex(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _WORD_HEX.fullmatch(value):
        raise ValueError(f"{field_name} must be a 32-byte lowercase hex word")
    return value if value.startswith("0x") else f"0x{value}"


def _normalize_address(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a lowercase EVM address")
    lowered = value.lower()
    if not _ADDRESS_HEX.fullmatch(lowered):
        raise ValueError(f"{field_name} must be a lowercase EVM address")
    return lowered


def _hex_bytes(value: str) -> bytes:
    normalized = value[2:] if value.startswith("0x") else value
    return bytes.fromhex(normalized)


def _abi_word_uint(value: int, bits: int, field_name: str) -> bytes:
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    if value >= 1 << bits:
        raise ValueError(f"{field_name} exceeds uint{bits}")
    return value.to_bytes(32, "big")


def _abi_word_bytes32(value: str, field_name: str) -> bytes:
    return _hex_bytes(_normalize_word_hex(value, field_name))


def _abi_word_address(value: str, field_name: str) -> bytes:
    return b"\x00" * 12 + _hex_bytes(_normalize_address(value, field_name))


def _abi_word_domain(label: str) -> bytes:
    encoded = label.encode("ascii")
    if len(encoded) > 32:
        raise ValueError("domain label exceeds bytes32 width")
    return encoded.ljust(32, b"\x00")


def _abi_encode_static(*words: bytes) -> bytes:
    for word in words:
        if len(word) != 32:
            raise ValueError("all ABI words must be exactly 32 bytes")
    return b"".join(words)


@lru_cache(maxsize=2048)
def _cast_keccak(hex_input: str) -> str:
    result = subprocess.run(
        ["cast", "keccak", hex_input],
        check=True,
        capture_output=True,
        text=True,
    )
    return _normalize_word_hex(result.stdout.strip(), "keccak output")


def _keccak_bytes(payload: bytes) -> str:
    return _cast_keccak(f"0x{payload.hex()}")


class TaskSpec(_FrozenProtocolModel):
    task_id: int
    task_root: str
    worker_id: str
    task_class: TaskClass
    active: bool = True
    registered: bool
    credit_budget: int = 0
    epoch: int
    deadline: int
    commitment_height: int
    commitment_finality_depth: int
    challenge_window_blocks: int
    audit_domain_size: int

    @field_validator("task_root")
    @classmethod
    def require_task_root(cls, value: str) -> str:
        return _normalize_word_hex(value, "task_root")

    @field_validator("worker_id")
    @classmethod
    def require_worker_address(cls, value: str) -> str:
        return _normalize_address(value, "worker_id")

    @field_validator(
        "task_id",
        "credit_budget",
        "epoch",
        "deadline",
        "commitment_height",
        "commitment_finality_depth",
        "challenge_window_blocks",
        "audit_domain_size",
    )
    @classmethod
    def require_nonnegative_integer(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        if info.field_name in {"deadline", "commitment_finality_depth", "challenge_window_blocks", "audit_domain_size"} and value == 0:
            raise ValueError(f"{info.field_name} must be positive")
        return value


class ModelManifest(_FrozenProtocolModel):
    model_root: str
    runtime_root: str
    model_manifest_hash: str
    assurance_class: int

    @field_validator("model_root", "runtime_root", "model_manifest_hash")
    @classmethod
    def require_word_hex(cls, value: str, info: ValidationInfo) -> str:
        return _normalize_word_hex(value, info.field_name)

    @field_validator("assurance_class")
    @classmethod
    def require_assurance_class(cls, value: int) -> int:
        if value < 0 or value > 255:
            raise ValueError("assurance_class must fit uint8")
        return value


class ResponseCommitment(_FrozenProtocolModel):
    task_id: int
    worker_id: str
    task_class: TaskClass
    task_epoch: int
    task_commitment: str
    model_commitment: str
    response_hash: str
    trace_root: str
    evidence_root: str
    artifact_root: str
    nonce: str
    commitment_hash: str
    committed_height: int
    commitment_finality_depth: int
    finalized_height: int | None

    @field_validator(
        "task_commitment",
        "model_commitment",
        "response_hash",
        "trace_root",
        "evidence_root",
        "artifact_root",
        "nonce",
        "commitment_hash",
    )
    @classmethod
    def require_sha3_word(cls, value: str, info: ValidationInfo) -> str:
        return _normalize_word_hex(value, info.field_name)

    @field_validator("worker_id")
    @classmethod
    def require_worker_address(cls, value: str) -> str:
        return _normalize_address(value, "worker_id")

    @field_validator("task_id", "task_epoch", "committed_height", "commitment_finality_depth")
    @classmethod
    def require_nonnegative(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        if info.field_name == "commitment_finality_depth" and value == 0:
            raise ValueError("commitment_finality_depth must be positive")
        return value

    @model_validator(mode="after")
    def validate_finality(self) -> "ResponseCommitment":
        if _commitment_construction_context.get() is not _COMMITMENT_CONTEXT_SENTINEL:
            raise ValueError(
                "ResponseCommitment must be issued via commit_response or trusted revalidation"
            )
        expected_finalized_height = self.committed_height + self.commitment_finality_depth
        if self.finalized_height is not None and self.finalized_height != expected_finalized_height:
            raise ValueError(
                "finalized_height must equal committed_height + commitment_finality_depth"
            )
        expected_hash = response_commitment_hash(
            task_commitment=self.task_commitment,
            model_commitment=self.model_commitment,
            response_hash=self.response_hash,
            trace_root=self.trace_root,
            evidence_root=self.evidence_root,
            artifact_root=self.artifact_root,
            nonce=self.nonce,
        )
        if self.commitment_hash != expected_hash:
            raise ValueError("commitment_hash does not match bound commitment material")
        return self

    def commitment_material(self) -> dict[str, Any]:
        return {
            "task_commitment": self.task_commitment,
            "model_commitment": self.model_commitment,
            "response_hash": self.response_hash,
            "trace_root": self.trace_root,
            "evidence_root": self.evidence_root,
            "artifact_root": self.artifact_root,
            "nonce": self.nonce,
        }


class AuditPlan(_FrozenProtocolModel):
    audit_id: str
    commitment_hash: str
    seed_hash: str
    policy_hash: str
    round_index: int
    sample_count: int
    sample_indices: tuple[int, ...]

    @field_validator("audit_id", "commitment_hash", "seed_hash", "policy_hash")
    @classmethod
    def require_digest(cls, value: str, info: ValidationInfo) -> str:
        return _normalize_word_hex(value, info.field_name)

    @model_validator(mode="after")
    def validate_samples(self) -> "AuditPlan":
        if self.round_index < 0:
            raise ValueError("round_index must be non-negative")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if len(self.sample_indices) != self.sample_count:
            raise ValueError("sample_indices length must match sample_count")
        if any(index < 0 for index in self.sample_indices):
            raise ValueError("sample_indices must be non-negative")
        return self


class Receipt(_FrozenProtocolModel):
    receipt_id: int
    task_id: int
    worker_id: str
    commitment_hash: str
    audit_id: str
    state: ReceiptState
    epoch_issued: int
    challenge_deadline: int
    nullifier: str
    audit_decision: AuditDecision | None = None
    audit_accepted: bool
    da_decision: bool | None = None
    data_availability_passed: bool
    activated_epoch: int | None
    challenge_reason: str | None = None
    slash_reason: str | None
    semantic_task_root: str | None = None
    semantic_response_hash: str | None = None
    audit_verification_result_digest: str | None = None
    verification_mode: ReceiptVerificationMode = ReceiptVerificationMode.LEGACY_PROTOCOL

    @field_validator("worker_id")
    @classmethod
    def require_worker_address(cls, value: str) -> str:
        return _normalize_address(value, "worker_id")

    @field_validator("commitment_hash", "audit_id", "nullifier")
    @classmethod
    def require_word_hash(cls, value: str, info: ValidationInfo) -> str:
        return _normalize_word_hex(value, info.field_name)

    @field_validator(
        "semantic_task_root",
        "semantic_response_hash",
        "audit_verification_result_digest",
    )
    @classmethod
    def require_optional_word_hash(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        if value is None:
            return None
        return _normalize_word_hex(value, info.field_name)

    @field_validator("receipt_id", "task_id", "epoch_issued", "challenge_deadline")
    @classmethod
    def require_nonnegative_int(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> "Receipt":
        semantic_bindings = (self.semantic_task_root, self.semantic_response_hash)
        if self.verification_mode is ReceiptVerificationMode.SEMANTIC_PUBLICATION:
            if not all(value is not None for value in semantic_bindings):
                raise ValueError(
                    "semantic publication receipts require task and response bindings"
                )
        elif any(value is not None for value in semantic_bindings):
            raise ValueError("legacy receipts cannot carry semantic bindings")
        if (
            self.verification_mode is ReceiptVerificationMode.LEGACY_PROTOCOL
            and self.audit_verification_result_digest is not None
        ):
            raise ValueError("legacy receipts cannot carry a semantic verification digest")
        if (
            self.verification_mode is ReceiptVerificationMode.SEMANTIC_PUBLICATION
            and self.audit_decision is not None
            and self.audit_verification_result_digest is None
        ):
            raise ValueError("semantic audit decisions require a verification result digest")
        if self.audit_decision is AuditDecision.ACCEPT and not self.audit_accepted:
            raise ValueError("audit_accepted must be true when audit_decision is ACCEPT")
        if self.audit_decision in {AuditDecision.REJECT, AuditDecision.ABSTAIN} and self.audit_accepted:
            raise ValueError("only ACCEPT audit decisions may set audit_accepted")
        if self.da_decision is True and not self.data_availability_passed:
            raise ValueError("data_availability_passed must be true when da_decision is true")
        if self.da_decision is False and self.data_availability_passed:
            raise ValueError("da_decision=false cannot set data_availability_passed")
        if self.state is ReceiptState.ACTIVE and self.activated_epoch is None:
            raise ValueError("active receipts must record activated_epoch")
        if self.state is not ReceiptState.ACTIVE and self.activated_epoch is not None:
            raise ValueError("only active receipts may record activated_epoch")
        if self.state is ReceiptState.ABSTAINED and self.audit_decision is not AuditDecision.ABSTAIN:
            raise ValueError("abstained receipts must record an ABSTAIN audit decision")
        if self.state is ReceiptState.CHALLENGED and not self.challenge_reason:
            raise ValueError("challenged receipts must record challenge_reason")
        if self.state is ReceiptState.DA_FAILED and self.da_decision is not False:
            raise ValueError("DA_FAILED receipts must record da_decision=false")
        if self.state is ReceiptState.REJECTED and self.audit_decision is not AuditDecision.REJECT:
            raise ValueError("rejected receipts must record a REJECT audit decision")
        if self.state is ReceiptState.SLASHED and not self.slash_reason:
            raise ValueError("slashed receipts must record slash_reason")
        return self


class TransitionContext(_FrozenProtocolModel):
    current_height: int
    current_epoch: int
    used_nullifiers: frozenset[str]

    @field_validator("current_height", "current_epoch")
    @classmethod
    def require_nonnegative(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value

    @field_validator("used_nullifiers")
    @classmethod
    def require_nullifier_hashes(cls, values: frozenset[str]) -> frozenset[str]:
        return frozenset(_normalize_word_hex(value, "used_nullifiers") for value in values)


def task_commitment_hash(task: TaskSpec) -> str:
    payload = _abi_encode_static(
        _abi_word_domain(_TASK_DOMAIN),
        _abi_word_uint(_DOMAIN_VERSION, 16, "task_version"),
        _abi_word_uint(task.task_id, 256, "task_id"),
        _abi_word_bytes32(task.task_root, "task_root"),
        _abi_word_address(task.worker_id, "worker_id"),
        _abi_word_uint(int(task.task_class), 8, "task_class"),
        _abi_word_uint(task.credit_budget, 256, "credit_budget"),
        _abi_word_uint(task.epoch, 64, "epoch"),
        _abi_word_uint(task.deadline, 64, "deadline"),
    )
    return _keccak_bytes(payload)


def model_commitment_hash(model: ModelManifest) -> str:
    payload = _abi_encode_static(
        _abi_word_domain(_MODEL_DOMAIN),
        _abi_word_uint(_DOMAIN_VERSION, 16, "model_version"),
        _abi_word_bytes32(model.model_root, "model_root"),
        _abi_word_bytes32(model.runtime_root, "runtime_root"),
        _abi_word_bytes32(model.model_manifest_hash, "model_manifest_hash"),
        _abi_word_uint(model.assurance_class, 8, "assurance_class"),
    )
    return _keccak_bytes(payload)


def response_commitment_hash(
    *,
    task_commitment: str,
    model_commitment: str,
    response_hash: str,
    trace_root: str,
    evidence_root: str,
    artifact_root: str,
    nonce: str,
) -> str:
    payload = _abi_encode_static(
        _abi_word_domain(_RESPONSE_DOMAIN),
        _abi_word_uint(_DOMAIN_VERSION, 16, "response_version"),
        _abi_word_bytes32(task_commitment, "task_commitment"),
        _abi_word_bytes32(model_commitment, "model_commitment"),
        _abi_word_bytes32(response_hash, "response_hash"),
        _abi_word_bytes32(trace_root, "trace_root"),
        _abi_word_bytes32(evidence_root, "evidence_root"),
        _abi_word_bytes32(artifact_root, "artifact_root"),
        _abi_word_bytes32(nonce, "nonce"),
    )
    return _keccak_bytes(payload)


def response_commitment_material(value: ResponseCommitment | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, ResponseCommitment):
        return value.commitment_material()
    return {
        "task_commitment": value["task_commitment"],
        "model_commitment": value["model_commitment"],
        "response_hash": value["response_hash"],
        "trace_root": value["trace_root"],
        "evidence_root": value["evidence_root"],
        "artifact_root": value["artifact_root"],
        "nonce": value["nonce"],
    }


def trusted_response_commitment(value: ResponseCommitment | Mapping[str, Any]) -> ResponseCommitment:
    payload = value.model_dump(mode="json") if isinstance(value, ResponseCommitment) else dict(value)
    token = _commitment_construction_context.set(_COMMITMENT_CONTEXT_SENTINEL)
    try:
        return ResponseCommitment.model_validate(payload)
    finally:
        _commitment_construction_context.reset(token)
