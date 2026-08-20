"""Frozen protocol types for the Python reference machine."""

from __future__ import annotations

from enum import StrEnum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator


_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX_40 = re.compile(r"[0-9a-f]{40}\Z")


class _FrozenProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskClass(StrEnum):
    CONSENSUS = "CONSENSUS"
    SERVICE = "SERVICE"


class ReceiptState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SLASHED = "SLASHED"


class TaskSpec(_FrozenProtocolModel):
    task_id: str
    worker_id: str
    task_class: TaskClass
    registered: bool
    epoch: int
    commitment_height: int
    commitment_finality_depth: int
    challenge_window_blocks: int
    audit_domain_size: int

    @field_validator("task_id", "worker_id")
    @classmethod
    def require_nonblank_identifier(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator(
        "epoch",
        "commitment_height",
        "commitment_finality_depth",
        "challenge_window_blocks",
        "audit_domain_size",
    )
    @classmethod
    def require_nonnegative_integer(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        if info.field_name in {
            "commitment_finality_depth",
            "challenge_window_blocks",
            "audit_domain_size",
        } and value == 0:
            raise ValueError(f"{info.field_name} must be positive")
        return value


class ModelManifest(_FrozenProtocolModel):
    model_id: str
    model_root: str
    revision: str
    parameter_count: int

    @field_validator("model_id")
    @classmethod
    def require_nonblank_model_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model_id must not be blank")
        return value

    @field_validator("model_root")
    @classmethod
    def require_model_root(cls, value: str) -> str:
        if not _HEX_64.fullmatch(value):
            raise ValueError("model_root must be a lowercase SHA-256 digest")
        return value

    @field_validator("revision")
    @classmethod
    def require_revision(cls, value: str) -> str:
        if not _HEX_40.fullmatch(value):
            raise ValueError("revision must be a lowercase 40-character git revision")
        return value

    @field_validator("parameter_count")
    @classmethod
    def require_parameter_count(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("parameter_count must be positive")
        return value


class ResponseCommitment(_FrozenProtocolModel):
    task_id: str
    worker_id: str
    task_class: TaskClass
    task_root: str
    model_id: str
    model_manifest_hash: str
    response_hash: str
    trace_root: str
    evidence_root: str
    artifact_root: str
    nonce_hex: str
    commitment_hash: str
    commitment_height: int
    finalized_height: int | None

    @field_validator(
        "task_root",
        "model_manifest_hash",
        "response_hash",
        "trace_root",
        "evidence_root",
        "artifact_root",
        "commitment_hash",
    )
    @classmethod
    def require_sha256_hex(cls, value: str, info: ValidationInfo) -> str:
        if not _HEX_64.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 digest")
        return value

    @field_validator("nonce_hex")
    @classmethod
    def require_nonce_hex(cls, value: str) -> str:
        if not value or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("nonce_hex must be lowercase hexadecimal")
        return value

    @model_validator(mode="after")
    def validate_finality(self) -> "ResponseCommitment":
        if self.finalized_height is not None and self.finalized_height < self.commitment_height:
            raise ValueError("finalized_height cannot precede commitment_height")
        return self


class AuditPlan(_FrozenProtocolModel):
    audit_id: str
    commitment_hash: str
    seed_hash: str
    round_index: int
    sample_count: int
    sample_indices: tuple[int, ...]

    @field_validator("audit_id", "commitment_hash", "seed_hash")
    @classmethod
    def require_digest(cls, value: str, info: ValidationInfo) -> str:
        if not _HEX_64.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 digest")
        return value

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
    receipt_id: str
    task_id: str
    worker_id: str
    commitment_hash: str
    audit_id: str
    state: ReceiptState
    epoch_issued: int
    challenge_deadline: int
    nullifier: str
    audit_accepted: bool
    data_availability_passed: bool
    activated_epoch: int | None
    slash_reason: str | None

    @field_validator("receipt_id", "task_id", "worker_id", "audit_id")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("commitment_hash", "nullifier")
    @classmethod
    def require_hash(cls, value: str, info: ValidationInfo) -> str:
        if not _HEX_64.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> "Receipt":
        if self.epoch_issued < 0:
            raise ValueError("epoch_issued must be non-negative")
        if self.challenge_deadline < 0:
            raise ValueError("challenge_deadline must be non-negative")
        if self.state is ReceiptState.ACTIVE and self.activated_epoch is None:
            raise ValueError("active receipts must record activated_epoch")
        if self.state is not ReceiptState.ACTIVE and self.activated_epoch is not None:
            raise ValueError("only active receipts may record activated_epoch")
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
        for value in values:
            if not _HEX_64.fullmatch(value):
                raise ValueError("used_nullifiers must contain lowercase SHA-256 digests")
        return values
