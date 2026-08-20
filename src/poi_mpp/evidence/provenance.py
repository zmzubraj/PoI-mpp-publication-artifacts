"""Deterministic collection and binding of run provenance.

Environment records intentionally contain only public, reproducibility-relevant
metadata.  They never include environment-variable values, executable paths,
working directories, usernames, or credentials.
"""

from __future__ import annotations

import platform
from pathlib import Path
import re
import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig, config_hash
from poi_mpp.evidence.models import RunManifest


UNVERSIONED_BLOCKED = "UNVERSIONED_BLOCKED"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_REVISION = re.compile(r"[0-9a-f]{40}\Z")


class EnvironmentManifest(BaseModel):
    """Immutable, privacy-preserving environment facts relevant to a run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["POI_MPP_ENVIRONMENT_MANIFEST_V1"] = "POI_MPP_ENVIRONMENT_MANIFEST_V1"
    python_implementation: str
    python_version: str
    os_name: str
    os_release: str
    machine: str
    cpu_model: str | None
    gpu_model: str | None
    package_lock_hash: str | None
    compiler_version: str | None
    foundry_version: str | None
    code_revision: str

    @field_validator(
        "python_implementation",
        "python_version",
        "os_name",
        "os_release",
        "machine",
    )
    @classmethod
    def require_public_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("package_lock_hash")
    @classmethod
    def validate_optional_lock_hash(cls, value: str | None) -> str | None:
        if value is not None and (not isinstance(value, str) or not _SHA256.fullmatch(value)):
            raise ValueError("package_lock_hash must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("cpu_model", "gpu_model", "compiler_version", "foundry_version")
    @classmethod
    def validate_optional_public_fact(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{info.field_name} must be nonblank when present")
        return value

    @field_validator("code_revision")
    @classmethod
    def validate_revision_or_explicit_block(cls, value: str) -> str:
        if value == UNVERSIONED_BLOCKED or _GIT_REVISION.fullmatch(value):
            return value
        raise ValueError("code_revision must be a git SHA-1 or UNVERSIONED_BLOCKED")


def environment_hash(environment: EnvironmentManifest) -> str:
    """Return the canonical hash of an immutable environment manifest."""

    return digest("ENVIRONMENT_MANIFEST", environment)


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _git_revision(repo_root: Path) -> str:
    """Read a clean HEAD without changing the repository; block otherwise."""

    try:
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if status.stdout:
            return UNVERSIONED_BLOCKED
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return UNVERSIONED_BLOCKED
    candidate = completed.stdout.strip()
    return candidate if _GIT_REVISION.fullmatch(candidate) else UNVERSIONED_BLOCKED


def _lock_hash(lock_path: Path) -> str | None:
    if not lock_path.is_file():
        return None
    try:
        contents = lock_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"unable to read package lock: {lock_path.name}") from error
    return digest("PACKAGE_LOCK", {"content": contents})


def collect_environment(
    *, repo_root: str | Path | None = None, lock_path: str | Path | None = None
) -> EnvironmentManifest:
    """Collect deterministic, non-secret host metadata for a frozen run.

    CPU/GPU and external tool versions are explicitly recorded as absent because
    automated discovery commonly embeds paths, drivers, or user-local state.
    A later authorized collector may provide a separately reviewed extension.
    """

    root = Path(repo_root) if repo_root is not None else _default_repo_root()
    lock = Path(lock_path) if lock_path is not None else root / "requirements.lock"
    return EnvironmentManifest(
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        os_name=platform.system(),
        os_release=platform.release(),
        machine=platform.machine(),
        cpu_model=None,
        gpu_model=None,
        package_lock_hash=_lock_hash(lock),
        compiler_version=None,
        foundry_version=None,
        code_revision=_git_revision(root),
    )


def freeze_run(config: RunConfig, environment: EnvironmentManifest) -> RunManifest:
    """Produce the immutable run root from strict config and environment inputs.

    ``UNVERSIONED_BLOCKED`` is deliberately retained as a visible code
    disposition.  This function records provenance only; it never upgrades a
    blocked or synthetic run to publication eligibility.
    """

    return RunManifest(
        run_id=config.run_id,
        experiment_id=config.experiment_id,
        config_hash=config_hash(config),
        environment_hash=environment_hash(environment),
        code_revision=environment.code_revision,
        origin=config.origin,
        authorization_scope=config.authorization_scope,
        model_hash=config.model_hash,
        dataset_hash=config.dataset_hash,
        parent_hashes=config.parent_hashes,
    )
