"""Frozen protocol types for the Python reference machine."""

from __future__ import annotations

from contextvars import ContextVar
from enum import StrEnum
import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

from poi_mpp.evidence import digest


_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
_COMMITMENT_CONTEXT_SENTINEL = object()
_commitment_construction_context: ContextVar[object | None] = ContextVar(
    "poi_mpp_response_commitment_construction",
    default=None,
)


class _FrozenProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskClass(StrEnum):
    CONSENSUS = "CONSENSUS"
    SERVICE = "SERVICE"


class ReceiptState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    ABSTAINED = "ABSTAINED"
    CHALLENGED = "CHALLENGED"
    DA_FAILED = "DA_FAILED"
    EXPIRED = "EXPIRED"
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
    credit_budget: int = 0

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
        "credit_budget",
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
    task_epoch: int
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
    commitment_finality_depth: int
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
        if _commitment_construction_context.get() is not _COMMITMENT_CONTEXT_SENTINEL:
            raise ValueError(
                "ResponseCommitment must be issued via commit_response or trusted revalidation"
            )
        if self.task_epoch < 0:
            raise ValueError("task_epoch must be non-negative")
        if self.commitment_height < 0:
            raise ValueError("commitment_height must be non-negative")
        if self.commitment_finality_depth <= 0:
            raise ValueError("commitment_finality_depth must be positive")
        expected_finalized_height = self.commitment_height + self.commitment_finality_depth
        if self.finalized_height is not None and self.finalized_height != expected_finalized_height:
            raise ValueError(
                "finalized_height must equal commitment_height + commitment_finality_depth"
            )
        expected_hash = digest("RESPONSE_COMMITMENT", self.commitment_material())
        if self.commitment_hash != expected_hash:
            raise ValueError("commitment_hash does not match bound commitment material")
        return self

    def commitment_material(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "task_class": self.task_class.value,
            "task_epoch": self.task_epoch,
            "task_root": self.task_root,
            "model_id": self.model_id,
            "model_manifest_hash": self.model_manifest_hash,
            "response_hash": self.response_hash,
            "trace_root": self.trace_root,
            "evidence_root": self.evidence_root,
            "artifact_root": self.artifact_root,
            "nonce_hex": self.nonce_hex,
            "commitment_height": self.commitment_height,
            "commitment_finality_depth": self.commitment_finality_depth,
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
    audit_decision: Literal["ACCEPT", "REJECT", "ABSTAIN"] | None = None
    audit_accepted: bool
    da_decision: bool | None = None
    data_availability_passed: bool
    activated_epoch: int | None
    challenge_reason: str | None = None
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
        if self.audit_decision == "ACCEPT" and not self.audit_accepted:
            raise ValueError("audit_accepted must be true when audit_decision is ACCEPT")
        if self.audit_decision in {"REJECT", "ABSTAIN"} and self.audit_accepted:
            raise ValueError("only ACCEPT audit decisions may set audit_accepted")
        if self.da_decision is True and not self.data_availability_passed:
            raise ValueError("data_availability_passed must be true when da_decision is true")
        if self.da_decision is False and self.data_availability_passed:
            raise ValueError("da_decision=false cannot set data_availability_passed")
        if self.state is ReceiptState.ACTIVE and self.activated_epoch is None:
            raise ValueError("active receipts must record activated_epoch")
        if self.state is not ReceiptState.ACTIVE and self.activated_epoch is not None:
            raise ValueError("only active receipts may record activated_epoch")
        if self.state is ReceiptState.ABSTAINED and self.audit_decision != "ABSTAIN":
            raise ValueError("abstained receipts must record an ABSTAIN audit decision")
        if self.state is ReceiptState.CHALLENGED and not self.challenge_reason:
            raise ValueError("challenged receipts must record challenge_reason")
        if self.state is ReceiptState.DA_FAILED and self.da_decision is not False:
            raise ValueError("DA_FAILED receipts must record da_decision=false")
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


def response_commitment_material(value: ResponseCommitment | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, ResponseCommitment):
        return value.commitment_material()
    return {
        "task_id": value["task_id"],
        "worker_id": value["worker_id"],
        "task_class": (
            value["task_class"].value if isinstance(value["task_class"], TaskClass) else value["task_class"]
        ),
        "task_epoch": value["task_epoch"],
        "task_root": value["task_root"],
        "model_id": value["model_id"],
        "model_manifest_hash": value["model_manifest_hash"],
        "response_hash": value["response_hash"],
        "trace_root": value["trace_root"],
        "evidence_root": value["evidence_root"],
        "artifact_root": value["artifact_root"],
        "nonce_hex": value["nonce_hex"],
        "commitment_height": value["commitment_height"],
        "commitment_finality_depth": value["commitment_finality_depth"],
    }


def trusted_response_commitment(value: ResponseCommitment | Mapping[str, Any]) -> ResponseCommitment:
    payload = value.model_dump(mode="json") if isinstance(value, ResponseCommitment) else dict(value)
    token = _commitment_construction_context.set(_COMMITMENT_CONTEXT_SENTINEL)
    try:
        return ResponseCommitment.model_validate(payload)
    finally:
        _commitment_construction_context.reset(token)
