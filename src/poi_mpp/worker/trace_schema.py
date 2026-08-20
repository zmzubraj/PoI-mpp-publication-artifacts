"""Trace event schema for worker sidecars."""

from __future__ import annotations

import re

from pydantic import ValidationInfo, field_validator

from poi_mpp.worker.model_manifest import _FrozenWorkerModel, validate_public_json


_WORD_HEX = re.compile(r"0x[0-9a-f]{64}\Z")


class TraceEvent(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_TRACE_EVENT_V1"
    event_index: int
    op_name: str
    input_hashes: tuple[str, ...]
    output_hash: str
    metadata: dict[str, object] = {}

    @field_validator("event_index")
    @classmethod
    def require_nonnegative_index(cls, value: int) -> int:
        if value < 0:
            raise ValueError("event_index must be non-negative")
        return value

    @field_validator("op_name")
    @classmethod
    def require_op_name(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("op_name must not be blank")
        return value.strip()

    @field_validator("input_hashes")
    @classmethod
    def require_input_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("input_hashes must not be empty")
        for value in values:
            if not _WORD_HEX.fullmatch(value):
                raise ValueError("input_hashes must contain lowercase bytes32 words")
        return values

    @field_validator("output_hash")
    @classmethod
    def require_output_hash(cls, value: str) -> str:
        if not _WORD_HEX.fullmatch(value):
            raise ValueError("output_hash must be a lowercase bytes32 word")
        return value

    @field_validator("metadata")
    @classmethod
    def require_safe_metadata(cls, value: dict[str, object]) -> dict[str, object]:
        normalized = validate_public_json(value, field_name="safe public metadata")
        assert isinstance(normalized, dict)
        return normalized
