"""Typed data-availability objects and local shard-store mechanics."""

from __future__ import annotations

from enum import StrEnum
import hashlib
import os
from pathlib import Path
import stat
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence.canonical import digest


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SamplingMode(StrEnum):
    STATIC_WITH_REPLACEMENT = "STATIC_WITH_REPLACEMENT"
    STATIC_WITHOUT_REPLACEMENT = "STATIC_WITHOUT_REPLACEMENT"
    TARGETED_WITHHOLDING = "TARGETED_WITHHOLDING"
    SELECTIVE_SERVING = "SELECTIVE_SERVING"
    CORRELATED_LOSS = "CORRELATED_LOSS"


class SamplingAssumption(StrEnum):
    STATIC_WITH_REPLACEMENT_EXACT = "STATIC_WITH_REPLACEMENT_EXACT"
    STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC = "STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC"
    TARGETED_WITHHOLDING_DECLARED = "TARGETED_WITHHOLDING_DECLARED"
    SELECTIVE_SERVING_DECLARED = "SELECTIVE_SERVING_DECLARED"
    CORRELATED_LOSS_DECLARED = "CORRELATED_LOSS_DECLARED"


class LocalShardAccessError(ValueError):
    """Raised when a shard path escapes or mutates outside the trusted local store."""


class ErasureParameters(_FrozenModel):
    total_shards: int = Field(gt=0)
    reconstruction_threshold: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_threshold(self) -> "ErasureParameters":
        if self.reconstruction_threshold > self.total_shards:
            raise ValueError("reconstruction_threshold cannot exceed total_shards")
        return self


class ShardRecord(_FrozenModel):
    index: int = Field(ge=0)
    payload_hash: str
    relative_path: str

    @field_validator("payload_hash")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("payload_hash must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("relative_path")
    @classmethod
    def require_relative_path(cls, value: str) -> str:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts or not value.strip():
            raise ValueError("relative_path must stay under the local shard root")
        return value


class ShardLayout(_FrozenModel):
    schema_version: str = "POI_MPP_DA_LAYOUT_V1"
    finalized_commitment_hash: str
    erasure: ErasureParameters
    shards: tuple[ShardRecord, ...]

    @field_validator("finalized_commitment_hash")
    @classmethod
    def require_nonblank_commitment(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("finalized_commitment_hash must not be blank")
        return value

    @model_validator(mode="after")
    def validate_shard_contract(self) -> "ShardLayout":
        if len(self.shards) != self.erasure.total_shards:
            raise ValueError("shard count must equal erasure.total_shards")
        indices = tuple(record.index for record in self.shards)
        expected = tuple(range(self.erasure.total_shards))
        if indices != expected:
            raise ValueError("shards must be contiguous zero-based indices")
        if len({record.relative_path for record in self.shards}) != len(self.shards):
            raise ValueError("shard relative paths must be unique")
        return self


class SampleCertificate(_FrozenModel):
    schema_version: str = "POI_MPP_DA_SAMPLE_CERTIFICATE_V1"
    finalized_commitment_hash: str
    beacon_hash: str
    round_index: int = Field(ge=0)
    sample_count: int = Field(gt=0)
    replacement: bool
    assumption_label: SamplingAssumption
    sample_indices: tuple[int, ...]
    shard_hashes: tuple[str, ...]
    certificate_hash: str

    @field_validator("finalized_commitment_hash")
    @classmethod
    def require_nonblank_commitment(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("finalized_commitment_hash must not be blank")
        return value

    @field_validator("beacon_hash", "certificate_hash", "shard_hashes")
    @classmethod
    def require_sha256_values(cls, value):
        if isinstance(value, tuple):
            for item in value:
                if len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item):
                    raise ValueError("shard_hashes must contain lowercase SHA-256 hex digests")
            return value
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("certificate hashes must be lowercase SHA-256 hex digests")
        return value

    @model_validator(mode="after")
    def validate_certificate(self) -> "SampleCertificate":
        if len(self.sample_indices) != self.sample_count:
            raise ValueError("sample_indices length must match sample_count")
        if len(self.shard_hashes) != self.sample_count:
            raise ValueError("shard_hashes length must match sample_count")
        if not self.replacement and len(set(self.sample_indices)) != self.sample_count:
            raise ValueError("without-replacement certificates require unique sample_indices")
        expected_hash = digest(
            "DA_SAMPLE_CERTIFICATE",
            {
                "finalized_commitment_hash": self.finalized_commitment_hash,
                "beacon_hash": self.beacon_hash,
                "round_index": self.round_index,
                "sample_count": self.sample_count,
                "replacement": self.replacement,
                "assumption_label": self.assumption_label.value,
                "sample_indices": self.sample_indices,
                "shard_hashes": self.shard_hashes,
            },
        )
        if self.certificate_hash != expected_hash:
            raise ValueError("certificate_hash does not match canonical certificate material")
        return self


def _payload_hash(index: int, payload: bytes) -> str:
    return digest(
        "DA_SHARD",
        {
            "index": index,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_size": len(payload),
        },
    )


class LocalShardStore:
    """Owns a local directory tree of DA shards.

    The store never reaches across the network and only serves files under the
    configured root.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ValueError("local shard store root must be a directory")

    def shard_path(self, index: int) -> Path:
        if index < 0:
            raise ValueError("shard index must be non-negative")
        return self.root / "shards" / f"{index:04d}.bin"

    def _open_root_fd(self) -> int:
        return os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)

    def _path_parts(self, relative_path: str) -> tuple[str, ...]:
        parts = Path(relative_path).parts
        if not parts:
            raise LocalShardAccessError("shard relative path must not be empty")
        if any(part in {"", ".", ".."} for part in parts):
            raise LocalShardAccessError("shard relative path must stay under the trusted store root")
        return parts

    def _secure_open_shard_fd(self, relative_path: str) -> int:
        parts = self._path_parts(relative_path)
        root_fd = self._open_root_fd()
        current_fd = root_fd
        opened_parents: list[int] = []
        try:
            for parent in parts[:-1]:
                try:
                    next_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current_fd)
                except FileNotFoundError as error:
                    raise FileNotFoundError(f"trusted shard parent {parent!r} is missing") from error
                except OSError as error:
                    raise LocalShardAccessError(
                        f"trusted shard parent {parent!r} could not be opened safely"
                    ) from error
                parent_stat = os.fstat(next_fd)
                if not stat.S_ISDIR(parent_stat.st_mode):
                    os.close(next_fd)
                    raise LocalShardAccessError(f"trusted shard parent {parent!r} is not a directory")
                opened_parents.append(next_fd)
                current_fd = next_fd
            filename = parts[-1]
            try:
                pre_stat = os.stat(filename, dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError as error:
                raise FileNotFoundError(f"trusted shard file {filename!r} is missing") from error
            if not stat.S_ISREG(pre_stat.st_mode):
                raise LocalShardAccessError(f"trusted shard file {filename!r} is not a regular file")
            try:
                file_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current_fd)
            except OSError as error:
                raise LocalShardAccessError(f"trusted shard file {filename!r} could not be opened safely") from error
            fd_stat = os.fstat(file_fd)
            post_stat = os.stat(filename, dir_fd=current_fd, follow_symlinks=False)
            identities = {
                (pre_stat.st_dev, pre_stat.st_ino),
                (fd_stat.st_dev, fd_stat.st_ino),
                (post_stat.st_dev, post_stat.st_ino),
            }
            if len(identities) != 1:
                os.close(file_fd)
                raise LocalShardAccessError("trusted shard file changed identity during access")
            if not stat.S_ISREG(fd_stat.st_mode):
                os.close(file_fd)
                raise LocalShardAccessError(f"trusted shard file {filename!r} is not a regular file")
            return file_fd
        finally:
            for parent_fd in reversed(opened_parents):
                os.close(parent_fd)
            os.close(root_fd)

    def initialize(
        self,
        *,
        finalized_commitment_hash: str,
        erasure: ErasureParameters,
        shard_payloads: Sequence[bytes],
    ) -> ShardLayout:
        if len(shard_payloads) != erasure.total_shards:
            raise ValueError("shard_payloads length must equal erasure.total_shards")
        shard_root = self.root / "shards"
        shard_root.mkdir(parents=True, exist_ok=True)
        records: list[ShardRecord] = []
        for index, payload in enumerate(shard_payloads):
            if not isinstance(payload, bytes):
                raise ValueError("shard_payloads must contain bytes")
            path = self.shard_path(index)
            path.write_bytes(payload)
            records.append(
                ShardRecord(
                    index=index,
                    payload_hash=_payload_hash(index, payload),
                    relative_path=str(path.relative_to(self.root)),
                )
            )
        return ShardLayout(
            finalized_commitment_hash=finalized_commitment_hash,
            erasure=erasure,
            shards=tuple(records),
        )

    def read_shard(self, layout: ShardLayout, index: int) -> bytes:
        record = layout.shards[index]
        file_fd = self._secure_open_shard_fd(record.relative_path)
        try:
            chunks: list[bytes] = []
            while True:
                chunk = os.read(file_fd, 8192)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(file_fd)

    def available_indices(self, layout: ShardLayout) -> tuple[int, ...]:
        available: list[int] = []
        for record in layout.shards:
            try:
                file_fd = self._secure_open_shard_fd(record.relative_path)
            except (FileNotFoundError, LocalShardAccessError):
                continue
            else:
                os.close(file_fd)
                available.append(record.index)
        return tuple(available)

    def shard_hash(self, layout: ShardLayout, index: int) -> str | None:
        record = layout.shards[index]
        try:
            payload = self.read_shard(layout, index)
        except (FileNotFoundError, LocalShardAccessError):
            return None
        return _payload_hash(index, payload)

    def verified_layout_hash(self, layout: ShardLayout, index: int) -> str:
        observed_hash = self.shard_hash(layout, index)
        if observed_hash is None:
            raise FileNotFoundError(f"sampled shard {index} is not present in the local shard store")
        expected_hash = layout.shards[index].payload_hash
        if observed_hash != expected_hash:
            raise ValueError(f"sampled shard {index} no longer matches the finalized shard layout")
        return expected_hash


def derive_sample_indices(
    *,
    total_shards: int,
    sample_count: int,
    replacement: bool,
    finalized_commitment_hash: str,
    beacon_hash: str,
    round_index: int,
) -> tuple[int, ...]:
    if total_shards <= 0:
        raise ValueError("total_shards must be positive")
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")
    if not replacement and sample_count > total_shards:
        raise ValueError("sample_count cannot exceed total_shards when replacement is false")
    seed = {
        "finalized_commitment_hash": finalized_commitment_hash,
        "beacon_hash": beacon_hash,
        "round_index": round_index,
    }
    if replacement:
        return tuple(
            int(
                digest("DA_SAMPLE_DRAW", {**seed, "draw_index": draw_index}),
                16,
            )
            % total_shards
            for draw_index in range(sample_count)
        )
    ranked = [
        (
            int(digest("DA_SAMPLE_SCORE", {**seed, "candidate_index": index}), 16),
            index,
        )
        for index in range(total_shards)
    ]
    ranked.sort()
    return tuple(index for _, index in ranked[:sample_count])


def issue_sample_certificate(
    *,
    layout: ShardLayout,
    store: LocalShardStore,
    beacon: bytes,
    round_index: int,
    sample_count: int,
    replacement: bool,
) -> SampleCertificate:
    beacon_hash = hashlib.sha256(beacon).hexdigest()
    sample_indices = derive_sample_indices(
        total_shards=layout.erasure.total_shards,
        sample_count=sample_count,
        replacement=replacement,
        finalized_commitment_hash=layout.finalized_commitment_hash,
        beacon_hash=beacon_hash,
        round_index=round_index,
    )
    shard_hashes: list[str] = []
    for index in sample_indices:
        shard_hashes.append(store.verified_layout_hash(layout, index))
    assumption = (
        SamplingAssumption.STATIC_WITH_REPLACEMENT_EXACT
        if replacement
        else SamplingAssumption.STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC
    )
    material = {
        "finalized_commitment_hash": layout.finalized_commitment_hash,
        "beacon_hash": beacon_hash,
        "round_index": round_index,
        "sample_count": sample_count,
        "replacement": replacement,
        "assumption_label": assumption.value,
        "sample_indices": sample_indices,
        "shard_hashes": tuple(shard_hashes),
    }
    return SampleCertificate(
        finalized_commitment_hash=layout.finalized_commitment_hash,
        beacon_hash=beacon_hash,
        round_index=round_index,
        sample_count=sample_count,
        replacement=replacement,
        assumption_label=assumption,
        sample_indices=sample_indices,
        shard_hashes=tuple(shard_hashes),
        certificate_hash=digest("DA_SAMPLE_CERTIFICATE", material),
    )
