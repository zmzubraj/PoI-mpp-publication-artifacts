"""Receipt events and transition helpers."""

from __future__ import annotations

from pydantic import field_validator, model_validator

from poi_mpp.protocol.types import AuditDecision, _FrozenProtocolModel


class RecordAudit(_FrozenProtocolModel):
    decision: AuditDecision
    verification_result_digest: str | None = None
    semantic_task_root: str | None = None
    semantic_response_hash: str | None = None
    semantic_commitment_hash: str | None = None

    @model_validator(mode="after")
    def require_complete_semantic_binding(self) -> "RecordAudit":
        bindings = (
            self.verification_result_digest,
            self.semantic_task_root,
            self.semantic_response_hash,
            self.semantic_commitment_hash,
        )
        if any(value is not None for value in bindings) and not all(
            value is not None for value in bindings
        ):
            raise ValueError("semantic audit binding fields must be supplied together")
        return self


class RecordDataAvailability(_FrozenProtocolModel):
    available: bool


class OpenChallenge(_FrozenProtocolModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


class ActivateReceipt(_FrozenProtocolModel):
    pass


class ExpireReceipt(_FrozenProtocolModel):
    pass


class SlashReceipt(_FrozenProtocolModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


ProtocolEvent = (
    RecordAudit
    | RecordDataAvailability
    | OpenChallenge
    | ActivateReceipt
    | ExpireReceipt
    | SlashReceipt
)
