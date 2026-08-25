"""Shared fail-closed mechanics for E5/E6 multi-seed sensitivity runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import yaml

from poi_mpp.evidence.models import EvidenceOrigin


CLAIM_SCOPE = "SCENARIO_SPECIFIC_SENSITIVITY_ONLY"
NO_UPGRADE_DISPOSITION = "SENSITIVITY_ONLY_NO_CLAIM_UPGRADE"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MultiSeedConfig(FrozenModel):
    schema_version: str
    experiment_id: str
    evidence_origin: EvidenceOrigin
    claim_scope: str
    failure_disposition: str
    required_model_version: str
    simulations_per_seed: int = Field(ge=1)
    seeds: tuple[int, ...] = Field(min_length=3, max_length=9)
    expected_scenario_ids: tuple[str, ...] = Field(min_length=1)
    source_contract_path: Path
    source_contract_sha256: str
    source_plan_path: Path
    source_plan_sha256: str
    source_run_config_path: Path
    source_run_config_sha256: str

    @field_validator(
        "source_contract_sha256",
        "source_plan_sha256",
        "source_run_config_sha256",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("source hashes must be lowercase SHA-256 hex digests")
        return value

    @model_validator(mode="after")
    def validate_frozen_scope(self) -> "MultiSeedConfig":
        if self.evidence_origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
            raise ValueError("evidence_origin must equal REPRODUCIBLE_SIMULATION")
        if self.claim_scope != CLAIM_SCOPE:
            raise ValueError(f"claim_scope must equal {CLAIM_SCOPE}")
        if self.failure_disposition != "INCONCLUSIVE":
            raise ValueError("failure_disposition must equal INCONCLUSIVE")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be unique")
        if any(seed < 0 for seed in self.seeds):
            raise ValueError("seeds must be non-negative")
        if len(set(self.expected_scenario_ids)) != len(self.expected_scenario_ids):
            raise ValueError("expected_scenario_ids must be unique")
        return self


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": ")) + "\n").encode("utf-8")


def _reject_symlink(path: Path, *, label: str) -> None:
    candidate = path.absolute()
    for item in (candidate, *candidate.parents):
        if item.is_symlink():
            raise ValueError(f"{label} must not be a symlink or traverse a symlink")


def resolve_repo_file(path: Path, *, repo_root: Path, label: str) -> Path:
    root = repo_root.resolve()
    candidate = path if path.is_absolute() else root / path
    _reject_symlink(candidate, label=label)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} must stay within the repository") from error
    if not resolved.is_file():
        raise ValueError(f"{label} must be a regular file")
    return resolved


def load_canonical_multiseed_config(
    path: str | Path,
    *,
    repo_root: str | Path,
    expected_experiment_id: str,
    expected_schema_version: str,
) -> tuple[MultiSeedConfig, str]:
    root = Path(repo_root)
    config_path = Path(path)
    _reject_symlink(config_path, label="multi-seed config")
    try:
        raw_bytes = config_path.read_bytes()
        raw = yaml.safe_load(raw_bytes)
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"unable to load multi-seed config: {config_path}") from error
    if not isinstance(raw, Mapping):
        raise ValueError("multi-seed config must be a mapping")
    canonical = yaml.safe_dump(
        dict(raw), allow_unicode=True, default_flow_style=False, sort_keys=True
    ).encode("utf-8")
    if raw_bytes != canonical:
        raise ValueError("multi-seed config must use canonical YAML encoding")
    config = MultiSeedConfig.model_validate(dict(raw))
    if config.experiment_id != expected_experiment_id:
        raise ValueError(f"experiment_id must equal {expected_experiment_id}")
    if config.schema_version != expected_schema_version:
        raise ValueError(f"schema_version must equal {expected_schema_version}")

    resolved: dict[str, Path] = {}
    for field_name in ("source_contract_path", "source_plan_path", "source_run_config_path"):
        resolved[field_name] = resolve_repo_file(
            getattr(config, field_name), repo_root=root, label=field_name
        )
        expected_hash = getattr(config, field_name.replace("_path", "_sha256"))
        actual_hash = sha256_file(resolved[field_name])
        if actual_hash != expected_hash:
            raise ValueError(f"{field_name.replace('_path', '_sha256')} mismatch")
    return config.model_copy(update=resolved), sha256_bytes(canonical)


def write_sensitivity_artifact(path: str | Path, body: dict[str, object]) -> dict[str, object]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json_bytes(body)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, target)
    return {**body, "artifact_hash": sha256_bytes(encoded)}


def run_attempt(
    *,
    runner: Callable[..., object] | None,
    default_runner: Callable[..., object],
    default_kwargs: dict[str, object],
) -> object:
    if runner is None:
        return default_runner(**default_kwargs)
    return runner(default_runner=default_runner, default_kwargs=default_kwargs)


def failure_text(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
    return message


def source_binding(config: MultiSeedConfig, *, config_hash: str, run_config: Any) -> dict[str, object]:
    return {
        "config_hash": config_hash,
        "source_contract_sha256": config.source_contract_sha256,
        "source_plan_sha256": config.source_plan_sha256,
        "source_run_config_sha256": config.source_run_config_sha256,
        "source_model_hash": run_config.model_hash,
        "source_dataset_hash": run_config.dataset_hash,
        "source_parent_hashes": list(run_config.parent_hashes),
    }
