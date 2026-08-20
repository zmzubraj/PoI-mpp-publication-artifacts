"""Pinned worker-model manifest and protocol binding helpers."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.protocol.types import ModelManifest as ProtocolModelManifest


if TYPE_CHECKING:
    from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy


_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_REVISION_HEX = re.compile(r"[0-9a-f]{40}\Z")
_PRIVATE_PATH = re.compile(r"(?:^|\s)(?:/|~(?:/|$)|[A-Za-z]:[\\/])")
_CREDENTIAL_MARKER = re.compile(
    r"(?:credential|secret|token|password|passwd|api[ _-]?key|private[ _-]?key|begin .*private key)",
    re.IGNORECASE,
)
_SAFE_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:/@ -]{0,127}\Z")
_FILE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_ALLOWED_PARAMETER_SCALES = frozenset({"1B", "1.5B", "2B", "3B", "7B", "8B"})


class _FrozenWorkerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_safe_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    normalized = " ".join(value.split())
    if not _SAFE_TEXT.fullmatch(normalized):
        raise ValueError(f"{field_name} contains unsupported characters")
    if _PRIVATE_PATH.search(normalized) or _CREDENTIAL_MARKER.search(normalized):
        raise ValueError(f"{field_name} must not contain private paths or secrets")
    return normalized


def _require_public_text_map(
    values: dict[str, str],
    *,
    field_name: str,
) -> dict[str, str]:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    normalized: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not _FILE_LABEL.fullmatch(key):
            raise ValueError(f"{field_name} keys must be stable file labels")
        if PurePosixPath(key).name != key or "\\" in key:
            raise ValueError(f"{field_name} keys must not contain paths")
        if not isinstance(value, str) or not _SHA256_HEX.fullmatch(value):
            raise ValueError(f"{field_name} values must be lowercase SHA-256 hex digests")
        normalized[key] = value
    return dict(sorted(normalized.items()))


def bytes32_word(domain: str, value: object) -> str:
    """Return a protocol-ready bytes32 word from a canonical SHA-256 digest."""

    return f"0x{digest(domain, value)}"


def validate_public_json(value: object, *, field_name: str) -> object:
    """Reject non-finite, private, or secret-bearing JSON-compatible content."""

    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"{field_name} must contain only finite numbers")
        return value
    if isinstance(value, str):
        return _require_safe_text(value, field_name)
    if isinstance(value, tuple):
        return tuple(validate_public_json(item, field_name=field_name) for item in value)
    if isinstance(value, list):
        return [validate_public_json(item, field_name=field_name) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"{field_name} keys must be non-blank strings")
            lowered = key.lower()
            if lowered in {"chain_of_thought", "cot", "private_reasoning", "reasoning_trace"}:
                raise ValueError(f"{field_name} must not contain private reasoning fields")
            normalized[key] = validate_public_json(item, field_name=field_name)
        return normalized
    raise ValueError(f"{field_name} contains unsupported value type {type(value).__name__}")


class PinnedModelManifest(_FrozenWorkerModel):
    """Exact-pinned model identity for a local worker execution."""

    schema_version: str = "POI_MPP_WORKER_MODEL_MANIFEST_V1"
    model_id: str
    repository: str
    revision: str
    tokenizer_id: str
    tokenizer_revision: str
    license_id: str
    parameter_scale: str
    precision: str
    quantization: str
    runtime_name: str
    runtime_version: str
    model_file_hashes: dict[str, str]
    tokenizer_file_hashes: dict[str, str]
    assurance_class: int = 1

    @field_validator(
        "model_id",
        "repository",
        "tokenizer_id",
        "license_id",
        "parameter_scale",
        "precision",
        "quantization",
        "runtime_name",
        "runtime_version",
    )
    @classmethod
    def require_safe_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_safe_text(value, info.field_name)

    @field_validator("revision", "tokenizer_revision")
    @classmethod
    def require_exact_revision(cls, value: str, info: ValidationInfo) -> str:
        normalized = value.strip()
        if not _REVISION_HEX.fullmatch(normalized):
            raise ValueError(f"{info.field_name} must be an exact 40-character lowercase revision")
        return normalized

    @field_validator("parameter_scale")
    @classmethod
    def require_supported_scale(cls, value: str) -> str:
        if value not in _ALLOWED_PARAMETER_SCALES:
            raise ValueError(f"parameter_scale must be one of {sorted(_ALLOWED_PARAMETER_SCALES)}")
        return value

    @field_validator("model_file_hashes", "tokenizer_file_hashes")
    @classmethod
    def require_hash_maps(cls, value: dict[str, str], info: ValidationInfo) -> dict[str, str]:
        return _require_public_text_map(value, field_name=info.field_name)

    @field_validator("assurance_class")
    @classmethod
    def require_assurance_class(cls, value: int) -> int:
        if value < 0 or value > 255:
            raise ValueError("assurance_class must fit uint8")
        return value

    def _model_payload(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "repository": self.repository,
            "revision": self.revision,
            "license_id": self.license_id,
            "parameter_scale": self.parameter_scale,
            "model_file_hashes": self.model_file_hashes,
        }

    def _runtime_payload(self, policy: DeterministicDecodePolicy) -> dict[str, object]:
        return {
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_revision": self.tokenizer_revision,
            "tokenizer_file_hashes": self.tokenizer_file_hashes,
            "precision": self.precision,
            "quantization": self.quantization,
            "runtime_name": self.runtime_name,
            "runtime_version": self.runtime_version,
            "policy": policy.model_dump(mode="json"),
        }

    def model_root(self) -> str:
        return bytes32_word("WORKER_MODEL_ROOT", self._model_payload())

    def runtime_root(self, policy: DeterministicDecodePolicy) -> str:
        return bytes32_word("WORKER_RUNTIME_ROOT", self._runtime_payload(policy))

    def manifest_hash(self, policy: DeterministicDecodePolicy) -> str:
        return bytes32_word(
            "WORKER_MODEL_MANIFEST",
            {
                **self.model_dump(mode="json"),
                "policy": policy.model_dump(mode="json"),
            },
        )

    def to_protocol_manifest(self, policy: DeterministicDecodePolicy) -> ProtocolModelManifest:
        return ProtocolModelManifest(
            model_root=self.model_root(),
            runtime_root=self.runtime_root(policy),
            model_manifest_hash=self.manifest_hash(policy),
            assurance_class=self.assurance_class,
        )

    def assert_matches_loaded(self, loaded: "PinnedModelManifest") -> None:
        comparisons = (
            "repository",
            "revision",
            "tokenizer_id",
            "tokenizer_revision",
            "license_id",
            "parameter_scale",
            "precision",
            "quantization",
            "runtime_name",
            "runtime_version",
            "model_file_hashes",
            "tokenizer_file_hashes",
        )
        for field_name in comparisons:
            if getattr(self, field_name) != getattr(loaded, field_name):
                raise ValueError(f"loaded model {field_name} does not match pinned manifest")
