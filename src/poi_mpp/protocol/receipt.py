"""Receipt events and transition helpers."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator

from poi_mpp.protocol.types import _FrozenProtocolModel


class RecordAudit(_FrozenProtocolModel):
    decision: Literal["ACCEPT", "REJECT", "ABSTAIN"]


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
