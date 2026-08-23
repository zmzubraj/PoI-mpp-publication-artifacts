"""Deterministic collection and binding of run provenance.

Environment records intentionally contain only public, reproducibility-relevant
metadata.  They never include environment-variable values, executable paths,
working directories, usernames, or credentials.
"""

from __future__ import annotations

import json
import platform
from pathlib import Path
import re
import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig, config_hash, require_approved_run_config
from poi_mpp.evidence.models import RunManifest


UNVERSIONED_BLOCKED = "UNVERSIONED_BLOCKED"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_PRIVATE_PATH = re.compile(r"(?:^|\s)(?:/|~(?:/|$)|[A-Za-z]:[\\/])")
_CREDENTIAL_MARKER = re.compile(
    r"(?:credential|secret|token|password|passwd|api[ _-]?key|private[ _-]?key|begin .*private key)",
    re.IGNORECASE,
)
_MAX_PUBLIC_FACT_LENGTH = 160
_CPU_BRAND_COMMAND = ("sysctl", "-n", "machdep.cpu.brand_string")
_GPU_DETAILS_COMMAND = ("system_profiler", "SPDisplaysDataType", "-json")
_GPU_FIELDS = ("sppci_model", "spdisplays_chipset_model")


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
        if value is not None and not _is_safe_public_fact(value):
            raise ValueError(f"{info.field_name} must be a safe public fact")
        return value

    @field_validator("code_revision")
    @classmethod
    def validate_revision_or_explicit_block(cls, value: str) -> str:
        if value == UNVERSIONED_BLOCKED or _GIT_REVISION.fullmatch(value):
            return value
        raise ValueError("code_revision must be a git SHA-1 or UNVERSIONED_BLOCKED")


class PublicationBuildEnvironment(BaseModel):
    """Revision-independent runtime facts for a tracked publication bundle.

    Exact experiment and collector revisions remain in their provenance records.
    The publication manifest binds reporting code separately through its generator
    source-closure hash, avoiding a self-reference when generated outputs are
    committed after a clean build.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["POI_MPP_PUBLICATION_BUILD_ENVIRONMENT_V1"] = (
        "POI_MPP_PUBLICATION_BUILD_ENVIRONMENT_V1"
    )
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


def environment_hash(environment: EnvironmentManifest) -> str:
    """Return the canonical hash of an immutable environment manifest."""

    return digest("ENVIRONMENT_MANIFEST", environment)


def publication_build_environment_hash(environment: EnvironmentManifest) -> str:
    """Hash runtime facts while leaving exact code binding to source closure."""

    projection = PublicationBuildEnvironment.model_validate(
        {
            **environment.model_dump(mode="python", exclude={"schema_version", "code_revision"}),
            "schema_version": "POI_MPP_PUBLICATION_BUILD_ENVIRONMENT_V1",
        }
    )
    return digest("PUBLICATION_BUILD_ENVIRONMENT", projection)


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _git_revision(repo_root: Path) -> str:
    """Read a clean HEAD without changing the repository; block otherwise."""

    try:
        status = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if _has_material_git_status(status.stdout):
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


def _has_material_git_status(porcelain: str) -> bool:
    """Ignore only newly generated publication outputs, never source changes.

    Publication CLIs collect provenance after earlier experiment slices may
    already have written untracked files below ``results/publication``.  Those
    generated outputs do not change the executing code revision.  Any tracked
    change, rename, deletion, or untracked file outside that dedicated output
    tree still fails closed.
    """

    for line in porcelain.splitlines():
        if not line:
            continue
        status = line[:2]
        path = line[3:] if len(line) > 3 else ""
        if status == "??" and path.startswith("results/publication/"):
            continue
        return True
    return False


def _lock_hash(lock_path: Path) -> str | None:
    if not lock_path.is_file():
        return None
    try:
        contents = lock_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"unable to read package lock: {lock_path.name}") from error
    return digest("PACKAGE_LOCK", {"content": contents})


def _is_safe_public_fact(value: object) -> bool:
    """Allow only short normalized hardware/tool labels safe for publication."""

    if not isinstance(value, str) or not value or len(value) > _MAX_PUBLIC_FACT_LENGTH:
        return False
    if value != " ".join(value.split()) or not all(character.isprintable() for character in value):
        return False
    return not _PRIVATE_PATH.search(value) and not _CREDENTIAL_MARKER.search(value)


def _normalize_collected_public_fact(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized if _is_safe_public_fact(normalized) else None


def _run_public_collector(argv: tuple[str, ...]) -> str | None:
    """Run a fixed local metadata command and return only its text output."""

    try:
        completed = subprocess.run(
            list(argv),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if isinstance(completed.stdout, str) else None


def _collect_cpu_model(os_name: str) -> str | None:
    """Collect a normalized macOS CPU brand only from its fixed system field."""

    if os_name != "Darwin":
        return None
    output = _run_public_collector(_CPU_BRAND_COMMAND)
    return _normalize_collected_public_fact(output)


def _collect_gpu_model(os_name: str) -> str | None:
    """Collect sorted, deduplicated macOS GPU model labels from allowlisted keys."""

    if os_name != "Darwin":
        return None
    output = _run_public_collector(_GPU_DETAILS_COMMAND)
    if output is None:
        return None
    try:
        document = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return None
    displays = document.get("SPDisplaysDataType") if isinstance(document, dict) else None
    if not isinstance(displays, list):
        return None
    models: set[str] = set()
    for display in displays:
        if not isinstance(display, dict):
            return None
        for field in _GPU_FIELDS:
            model = _normalize_collected_public_fact(display.get(field))
            if model is not None:
                models.add(model)
    return "; ".join(sorted(models)) if models else None


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
    os_name = platform.system()
    return EnvironmentManifest(
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        os_name=os_name,
        os_release=platform.release(),
        machine=platform.machine(),
        cpu_model=_collect_cpu_model(os_name),
        gpu_model=_collect_gpu_model(os_name),
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

    require_approved_run_config(config)
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
