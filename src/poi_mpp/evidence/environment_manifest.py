"""Execution environment manifests for first-publication V2 task bindings."""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

from poi_mpp.evidence.canonical import digest


EXECUTION_ENVIRONMENT_MANIFEST_V1_SCHEMA = "POI_MPP_EXECUTION_ENVIRONMENT_MANIFEST_V1"
EXECUTION_ENVIRONMENT_MANIFEST_V1_DOMAIN = "EXECUTION_ENVIRONMENT_MANIFEST_V1"

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PINNED_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/+~-]{0,127}\Z")
_SAFE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_REQUIRED_SCRIPT_HASH_KEYS = frozenset({"runner", "artifact_exporter"})
_REQUIRED_CONFIG_HASH_KEYS = frozenset({"experiment_protocol", "generation_config"})


class _FrozenEnvironmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_nonblank_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _require_pattern(value: Any, *, field_name: str, pattern: re.Pattern[str]) -> str:
    normalized = _require_nonblank_string(value, field_name=field_name)
    if pattern.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} has an invalid format")
    return normalized


def _require_sha256(value: Any, *, field_name: str) -> str:
    normalized = _require_nonblank_string(value, field_name=field_name)
    if _SHA256.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return normalized


def _require_nonnegative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an exact integer")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _require_positive_int(value: Any, *, field_name: str) -> int:
    normalized = _require_nonnegative_int(value, field_name=field_name)
    if normalized <= 0:
        raise ValueError(f"{field_name} must be positive")
    return normalized


def _require_finite_float(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _normalize_hash_mapping(value: Any, *, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a mapping")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        binding_key = _require_pattern(key, field_name=field_name, pattern=_SAFE_KEY)
        if binding_key in normalized:
            raise ValueError(f"{field_name} must not contain duplicate keys")
        normalized[binding_key] = _require_sha256(item, field_name=f"{field_name}.{binding_key}")
    return dict(sorted(normalized.items()))


class ExecutionModelBindingV1(_FrozenEnvironmentModel):
    model_id: str
    model_revision: str
    model_weights_hash: str
    tokenizer_id: str
    tokenizer_revision: str
    tokenizer_hash: str
    weight_access: Literal["OPEN_WEIGHT"] = "OPEN_WEIGHT"
    parameter_count_billions: float

    @field_validator("model_id", "tokenizer_id", mode="before")
    @classmethod
    def normalize_ids(cls, value: Any, info: ValidationInfo) -> str:
        return _require_pattern(value, field_name=info.field_name, pattern=_SAFE_TOKEN)

    @field_validator("model_revision", "tokenizer_revision", mode="before")
    @classmethod
    def normalize_revisions(cls, value: Any, info: ValidationInfo) -> str:
        normalized = _require_nonblank_string(value, field_name=info.field_name)
        if _PINNED_REVISION.fullmatch(normalized) is None:
            raise ValueError(f"{info.field_name} must be a pinned 40- or 64-hex revision")
        return normalized

    @field_validator("model_weights_hash", "tokenizer_hash", mode="before")
    @classmethod
    def normalize_hashes(cls, value: Any, info: ValidationInfo) -> str:
        return _require_sha256(value, field_name=info.field_name)

    @field_validator("parameter_count_billions", mode="before")
    @classmethod
    def normalize_parameter_count(cls, value: Any) -> float:
        normalized = _require_finite_float(value, field_name="parameter_count_billions")
        if normalized < 1.0 or normalized > 8.0:
            raise ValueError("parameter_count_billions must stay within the 1B-8B publication scope")
        return normalized


class ExecutionRuntimeBindingV1(_FrozenEnvironmentModel):
    python_version: str
    framework_name: str
    framework_version: str
    dependency_lock_hash: str
    environment_sbom_digest: str

    @field_validator("python_version", "framework_name", "framework_version", mode="before")
    @classmethod
    def normalize_runtime_text(cls, value: Any, info: ValidationInfo) -> str:
        return _require_nonblank_string(value, field_name=info.field_name)

    @field_validator("dependency_lock_hash", "environment_sbom_digest", mode="before")
    @classmethod
    def normalize_runtime_hashes(cls, value: Any, info: ValidationInfo) -> str:
        return _require_sha256(value, field_name=info.field_name)


class ExecutionHardwareInventoryV1(_FrozenEnvironmentModel):
    accelerator_label: str
    accelerator_count: int
    driver_version: str

    @field_validator("accelerator_label", "driver_version", mode="before")
    @classmethod
    def normalize_hardware_text(cls, value: Any, info: ValidationInfo) -> str:
        return _require_nonblank_string(value, field_name=info.field_name)

    @field_validator("accelerator_count", mode="before")
    @classmethod
    def normalize_accelerator_count(cls, value: Any) -> int:
        return _require_positive_int(value, field_name="accelerator_count")


class DeterministicExecutionSettingsV1(_FrozenEnvironmentModel):
    global_seed: int
    inference_seed: int
    local_files_only: bool
    hash_check_enforced: bool

    @field_validator("global_seed", "inference_seed", mode="before")
    @classmethod
    def normalize_seeds(cls, value: Any, info: ValidationInfo) -> int:
        return _require_nonnegative_int(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_local_determinism_contract(self) -> "DeterministicExecutionSettingsV1":
        if not self.local_files_only:
            raise ValueError("local_files_only must be true for the first-publication environment")
        if not self.hash_check_enforced:
            raise ValueError("hash_check_enforced must be true for the first-publication environment")
        return self


class GenerationParametersV1(_FrozenEnvironmentModel):
    do_sample: bool
    temperature: float
    top_p: float
    max_new_tokens: int

    @field_validator("temperature", "top_p", mode="before")
    @classmethod
    def normalize_generation_floats(cls, value: Any, info: ValidationInfo) -> float:
        return _require_finite_float(value, field_name=info.field_name)

    @field_validator("max_new_tokens", mode="before")
    @classmethod
    def normalize_max_new_tokens(cls, value: Any) -> int:
        return _require_positive_int(value, field_name="max_new_tokens")

    @model_validator(mode="after")
    def validate_deterministic_generation(self) -> "GenerationParametersV1":
        if self.do_sample:
            raise ValueError("do_sample must be false for the first-publication deterministic environment")
        if self.temperature != 0.0:
            raise ValueError("temperature must be 0.0 for deterministic first-publication execution")
        if self.top_p != 1.0:
            raise ValueError("top_p must be 1.0 for deterministic first-publication execution")
        return self


class ExecutionEnvironmentManifestV1(_FrozenEnvironmentModel):
    schema_version: Literal[EXECUTION_ENVIRONMENT_MANIFEST_V1_SCHEMA] = (
        EXECUTION_ENVIRONMENT_MANIFEST_V1_SCHEMA
    )
    environment_id: str
    model: ExecutionModelBindingV1
    runtime: ExecutionRuntimeBindingV1
    hardware: ExecutionHardwareInventoryV1
    deterministic: DeterministicExecutionSettingsV1
    generation: GenerationParametersV1
    script_hashes: dict[str, str]
    config_hashes: dict[str, str]
    network_access: Literal["LOCAL_ONLY"] = "LOCAL_ONLY"
    external_services: tuple[str, ...] = ()

    @field_validator("environment_id", mode="before")
    @classmethod
    def normalize_environment_id(cls, value: Any) -> str:
        return _require_pattern(value, field_name="environment_id", pattern=_SAFE_TOKEN)

    @field_validator("script_hashes", "config_hashes", mode="before")
    @classmethod
    def normalize_hash_mappings(cls, value: Any, info: ValidationInfo) -> dict[str, str]:
        return _normalize_hash_mapping(value, field_name=info.field_name)

    @field_validator("external_services", mode="before")
    @classmethod
    def normalize_external_services(cls, value: Any) -> tuple[str, ...]:
        if value in (None, (), []):
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("external_services must be a sequence")
        normalized = tuple(
            _require_pattern(item, field_name="external_services", pattern=_SAFE_TOKEN)
            for item in value
        )
        if len(set(normalized)) != len(normalized):
            raise ValueError("external_services must not contain duplicates")
        return tuple(sorted(normalized))

    @model_validator(mode="after")
    def validate_local_scope(self) -> "ExecutionEnvironmentManifestV1":
        if self.network_access != "LOCAL_ONLY":
            raise ValueError("network_access must remain LOCAL_ONLY for the first-publication environment")
        if self.external_services:
            raise ValueError("external_services must be empty for the first-publication local environment")
        missing_scripts = sorted(_REQUIRED_SCRIPT_HASH_KEYS.difference(self.script_hashes))
        if missing_scripts:
            raise ValueError(
                "required script hash binding is absent: " + ", ".join(missing_scripts)
            )
        missing_configs = sorted(_REQUIRED_CONFIG_HASH_KEYS.difference(self.config_hashes))
        if missing_configs:
            raise ValueError(
                "required config hash binding is absent: " + ", ".join(missing_configs)
            )
        if self.model.model_id == self.model.tokenizer_id and (
            self.model.model_revision != self.model.tokenizer_revision
        ):
            raise ValueError("model and tokenizer revisions must match when model_id and tokenizer_id match")
        return self

    def canonical_material(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def environment_manifest_hash(self) -> str:
        return digest(EXECUTION_ENVIRONMENT_MANIFEST_V1_DOMAIN, self.canonical_material())
