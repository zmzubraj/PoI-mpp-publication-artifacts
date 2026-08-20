"""Strict deterministic decode policy for worker execution."""

from __future__ import annotations

from pydantic import ValidationInfo, field_validator, model_validator

from poi_mpp.worker.model_manifest import _FrozenWorkerModel, _require_safe_text


class DeterministicDecodePolicy(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_DETERMINISTIC_DECODE_V1"
    seed: int
    max_new_tokens: int
    do_sample: bool = False
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    repetition_penalty: float = 1.0
    stop_sequences: tuple[str, ...] = ()

    @field_validator("seed", "max_new_tokens", "top_k")
    @classmethod
    def require_nonnegative(cls, value: int, info: ValidationInfo) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        if info.field_name == "max_new_tokens" and value == 0:
            raise ValueError("max_new_tokens must be positive")
        return value

    @field_validator("temperature", "top_p", "repetition_penalty")
    @classmethod
    def require_finite_float(cls, value: float, info: ValidationInfo) -> float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"{info.field_name} must be finite")
        return value

    @field_validator("stop_sequences")
    @classmethod
    def require_safe_stop_sequences(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_require_safe_text(item, "stop_sequences") for item in value)

    @model_validator(mode="after")
    def require_deterministic_configuration(self) -> "DeterministicDecodePolicy":
        if self.do_sample:
            raise ValueError("deterministic decode must not enable sampling")
        if self.temperature != 0.0:
            raise ValueError("deterministic decode requires temperature == 0.0")
        if self.top_p != 1.0:
            raise ValueError("deterministic decode requires top_p == 1.0")
        if self.top_k not in {0, 1}:
            raise ValueError("deterministic decode requires top_k in {0, 1}")
        if self.repetition_penalty <= 0:
            raise ValueError("repetition_penalty must be positive")
        return self
