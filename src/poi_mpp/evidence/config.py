"""Strict, hash-bound run configuration loading.

The loader intentionally accepts only the small run contract used by the
evidence pipeline.  It does not merge profiles, supply operational defaults,
or coerce invalid values: a frozen run must be reproducible from the exact
configuration supplied to it.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import EvidenceOrigin


RUN_CONFIG_SCHEMA_VERSION = "POI_MPP_RUN_CONFIG_V1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "schema_hash",
        "run_id",
        "experiment_id",
        "origin",
        "authorization_scope",
        "model_hash",
        "dataset_hash",
        "parent_hashes",
        "data_availability",
    }
)
_DA_FIELDS = frozenset({"total_shards", "samples", "replacement"})


class _FrozenConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DataAvailabilityConfig(_FrozenConfigModel):
    """DA sampling policy, including the without-replacement hard bound."""

    total_shards: int
    samples: int
    replacement: bool

    @field_validator("total_shards", "samples", mode="before")
    @classmethod
    def require_plain_positive_integers(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("replacement", mode="before")
    @classmethod
    def require_boolean_replacement(cls, value: object) -> object:
        if not isinstance(value, bool):
            raise ValueError("replacement must be a boolean")
        return value

    @model_validator(mode="after")
    def reject_impossible_without_replacement_sample(self) -> "DataAvailabilityConfig":
        if not self.replacement and self.samples > self.total_shards:
            raise ValueError("samples cannot exceed total_shards when replacement is false")
        return self


class RunConfig(_FrozenConfigModel):
    """Immutable run inputs that must be bound before evidence is generated."""

    schema_version: Literal[RUN_CONFIG_SCHEMA_VERSION]
    schema_hash: str
    run_id: str
    experiment_id: str
    origin: EvidenceOrigin
    authorization_scope: str
    model_hash: str
    dataset_hash: str
    parent_hashes: tuple[str, ...] = ()
    data_availability: DataAvailabilityConfig

    @field_validator("schema_hash", "model_hash", "dataset_hash")
    @classmethod
    def require_sha256(cls, value: str, info: ValidationInfo) -> str:
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 hex digest")
        if info.field_name == "schema_hash" and value != approved_schema_hash():
            raise ValueError("schema_hash must match the approved run configuration schema")
        return value

    @field_validator("parent_hashes")
    @classmethod
    def require_parent_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not _SHA256.fullmatch(value):
                raise ValueError("parent_hashes must contain lowercase SHA-256 hex digests")
        return values

    @field_validator("run_id", "experiment_id", "authorization_scope")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[3] / "configs" / "schema" / "run-config-v1.json"


def schema_hash(schema_path: str | Path | None = None) -> str:
    """Return a schema digest for diagnostics, not freeze authorization.

    Passing a path is intentionally limited to diagnostics and tests.  Only
    :func:`approved_schema_hash` identifies the bundled v1 schema accepted by
    ``RunConfig`` and the public ``freeze_run`` authority path.
    """

    path = Path(schema_path) if schema_path is not None else _schema_path()
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"unable to load run configuration schema: {path}") from error
    if not isinstance(loaded, dict):
        raise ValueError("run configuration schema must be a JSON object")
    return digest("RUN_CONFIG_SCHEMA", loaded)


def approved_schema_hash() -> str:
    """Return the sole schema digest authorized for v1 frozen runs."""

    return schema_hash(_schema_path())


def require_approved_run_config(config: RunConfig) -> None:
    """Recheck schema authority at public freeze boundaries.

    ``BaseModel.model_construct`` deliberately bypasses Pydantic validation;
    this defense-in-depth check ensures such an unsafe in-memory object cannot
    acquire a frozen run manifest.
    """

    if not isinstance(config, RunConfig):
        raise ValueError("freeze_run requires a RunConfig")
    if (
        config.schema_version != RUN_CONFIG_SCHEMA_VERSION
        or config.schema_hash != approved_schema_hash()
    ):
        raise ValueError("RunConfig must bind the approved run configuration schema")


def config_hash(config: RunConfig) -> str:
    """Return the domain-separated canonical digest of a frozen configuration."""

    return digest("RUN_CONFIG", config)


def _reject_unknown_fields(raw: dict[str, Any]) -> None:
    unexpected_root = sorted(set(raw) - _ROOT_FIELDS)
    data_availability = raw.get("data_availability")
    unexpected_da = (
        sorted(set(data_availability) - _DA_FIELDS)
        if isinstance(data_availability, dict)
        else []
    )
    if unexpected_root or unexpected_da:
        locations = [*unexpected_root, *(f"data_availability.{key}" for key in unexpected_da)]
        raise ValueError(f"unknown configuration fields: {', '.join(locations)}")


def load_run_config(path: str | Path) -> RunConfig:
    """Load one YAML/JSON config and bind it to the exact approved schema.

    This function never merges a base profile or writes a normalized copy.  The
    returned frozen object preserves all allowed values and rejects everything
    else before any run can be frozen.
    """

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"unable to load run configuration: {config_path}") from error
    if not isinstance(raw, dict):
        raise ValueError("run configuration must be a mapping")

    _reject_unknown_fields(raw)
    actual_schema_hash = approved_schema_hash()
    supplied_schema_hash = raw.get("schema_hash")
    if supplied_schema_hash is not None and supplied_schema_hash != actual_schema_hash:
        raise ValueError("schema_hash does not match the approved run configuration schema")
    return RunConfig.model_validate({**raw, "schema_hash": actual_schema_hash})
