"""Canonical V2 task-root envelope binding scientific execution inputs."""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationInfo, field_validator, model_validator

from poi_mpp.evidence.canonical import canonical_bytes as _canonical_bytes
from poi_mpp.evidence.canonical import digest
from poi_mpp.protocol.types import TaskClass, _FrozenProtocolModel, _normalize_word_hex


TASK_ENVELOPE_V2_SCHEMA = "POI_MPP_TASK_ENVELOPE_V2"
TASK_ENVELOPE_V2_DOMAIN = "TASK_ENVELOPE_V2"


class TaskEnvelopeScopeV2(_FrozenProtocolModel):
    publication_scope: str
    authorization_scope: str
    evidence_origin: str
    task_class: TaskClass

    @field_validator("publication_scope", "authorization_scope", "evidence_origin")
    @classmethod
    def require_nonblank_scope_text(cls, value: str, info: ValidationInfo) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def require_unambiguous_bindings(self) -> "TaskEnvelopeScopeV2":
        labels = (
            self.publication_scope,
            self.authorization_scope,
            self.evidence_origin,
        )
        if len(set(labels)) != len(labels):
            raise ValueError("scope bindings must be pairwise distinct")
        return self


class TaskEnvelopeV2(_FrozenProtocolModel):
    schema_version: Literal[TASK_ENVELOPE_V2_SCHEMA] = TASK_ENVELOPE_V2_SCHEMA
    claim_spec_hash: str
    task_payload_hash: str
    semantic_policy_hash: str
    dataset_manifest_hash: str
    authority_registry_snapshot_hash: str
    model_manifest_hash: str
    runtime_environment_hash: str
    evidence_origin_policy_hash: str
    experiment_protocol_hash: str
    epoch: int
    expiry: int
    scope: TaskEnvelopeScopeV2

    @field_validator(
        "claim_spec_hash",
        "task_payload_hash",
        "semantic_policy_hash",
        "dataset_manifest_hash",
        "authority_registry_snapshot_hash",
        "model_manifest_hash",
        "runtime_environment_hash",
        "evidence_origin_policy_hash",
        "experiment_protocol_hash",
    )
    @classmethod
    def require_word_hash(cls, value: str, info: ValidationInfo) -> str:
        return _normalize_word_hex(value, info.field_name)

    @field_validator("epoch")
    @classmethod
    def require_nonnegative_epoch(cls, value: int) -> int:
        if value < 0:
            raise ValueError("epoch must be non-negative")
        return value

    @field_validator("expiry")
    @classmethod
    def require_positive_expiry(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("expiry must be positive")
        return value

    @model_validator(mode="after")
    def require_live_epoch_window(self) -> "TaskEnvelopeV2":
        if self.expiry <= self.epoch:
            raise ValueError("expiry must exceed epoch")
        return self

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(TASK_ENVELOPE_V2_DOMAIN, self.canonical_payload())

    @property
    def task_root(self) -> str:
        return f"0x{digest(TASK_ENVELOPE_V2_DOMAIN, self.canonical_payload())}"
