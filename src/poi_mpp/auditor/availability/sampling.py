"""Exact availability sampling math and local reconstruction checks."""

from __future__ import annotations

from fractions import Fraction
from math import comb, sqrt
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from poi_mpp.protocol.availability import (
    LocalShardStore,
    SampleCertificate,
    SamplingMode,
    ShardLayout,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelAssumptionError(ValueError):
    """Raised when a caller requests an exact formula for a non-static model."""


class ReconstructionStatus(str):
    VERIFIED = "VERIFIED"
    WITHHELD = "WITHHELD"
    CORRUPT = "CORRUPT"
    SELECTIVE_SERVICE = "SELECTIVE_SERVICE"


class ReconstructionResult(_FrozenModel):
    status: str
    verified_sample_count: int = Field(ge=0)
    verified_total_shards: int = Field(ge=0)
    reconstruction_threshold: int = Field(ge=0)
    missing_indices: tuple[int, ...] = ()
    corrupt_indices: tuple[int, ...] = ()
    omitted_indices: tuple[int, ...] = ()
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_counts(self) -> "ReconstructionResult":
        if self.verified_sample_count > self.verified_total_shards:
            raise ValueError("verified_sample_count cannot exceed verified_total_shards")
        return self


def miss_probability(*, total: int, withheld: int, samples: int, replacement: bool) -> Fraction:
    if total <= 0:
        raise ValueError("total must be positive")
    if withheld < 0 or withheld > total:
        raise ValueError("withheld must be between 0 and total")
    if samples <= 0:
        raise ValueError("samples must be positive")
    if not replacement and samples > total:
        raise ValueError("samples cannot exceed total when replacement is false")
    available = total - withheld
    if replacement:
        return Fraction(available, total) ** samples
    if available < samples:
        return Fraction(0, 1)
    return Fraction(comb(available, samples), comb(total, samples))


def miss_probability_for_mode(
    *,
    mode: SamplingMode,
    total: int,
    withheld: int,
    samples: int,
    replacement: bool,
) -> Fraction:
    if mode not in {
        SamplingMode.STATIC_WITH_REPLACEMENT,
        SamplingMode.STATIC_WITHOUT_REPLACEMENT,
    }:
        raise ModelAssumptionError("exact closed-form miss probability is only defined for static withholding")
    if mode is SamplingMode.STATIC_WITH_REPLACEMENT and not replacement:
        raise ValueError("STATIC_WITH_REPLACEMENT requires replacement=true")
    if mode is SamplingMode.STATIC_WITHOUT_REPLACEMENT and replacement:
        raise ValueError("STATIC_WITHOUT_REPLACEMENT requires replacement=false")
    return miss_probability(total=total, withheld=withheld, samples=samples, replacement=replacement)


def wilson_interval(*, misses: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    if misses < 0 or misses > trials:
        raise ValueError("misses must be between 0 and trials")
    proportion = misses / trials
    z_squared = z * z
    denominator = 1.0 + (z_squared / trials)
    centre = proportion + (z_squared / (2.0 * trials))
    margin = z * sqrt(
        ((proportion * (1.0 - proportion)) / trials) + (z_squared / (4.0 * trials * trials))
    )
    lower = max(0.0, (centre - margin) / denominator)
    upper = min(1.0, (centre + margin) / denominator)
    return (lower, upper)


def verify_reconstruction(
    *,
    layout: ShardLayout,
    store: LocalShardStore,
    certificate: SampleCertificate,
    mode: SamplingMode,
    served_indices: Sequence[int] | None = None,
) -> ReconstructionResult:
    if certificate.finalized_commitment_hash != layout.finalized_commitment_hash:
        raise ValueError("certificate finalized commitment does not match the shard layout")
    expected_hashes = tuple(layout.shards[index].payload_hash for index in certificate.sample_indices)
    if certificate.shard_hashes != expected_hashes:
        raise ValueError("certificate shard hashes do not match the shard layout")

    served = tuple(certificate.sample_indices if served_indices is None else served_indices)
    served_set = set(served)
    if not served_set.issubset(set(certificate.sample_indices)):
        raise ValueError("served_indices must be a subset of the certified sample_indices")

    omitted_indices = tuple(index for index in certificate.sample_indices if index not in served_set)
    missing_indices: list[int] = []
    corrupt_indices: list[int] = []
    verified_sample_count = 0
    verified_total_shards = 0

    for record in layout.shards:
        observed_hash = store.shard_hash(layout, record.index)
        if observed_hash == record.payload_hash:
            verified_total_shards += 1

    for index, expected_hash in zip(certificate.sample_indices, certificate.shard_hashes, strict=True):
        if index in omitted_indices:
            continue
        observed_hash = store.shard_hash(layout, index)
        if observed_hash is None:
            missing_indices.append(index)
            continue
        if observed_hash != expected_hash:
            corrupt_indices.append(index)
            continue
        verified_sample_count += 1

    reasons: list[str] = []
    if omitted_indices:
        reasons.append("sampled shard service omitted one or more certified indices")
    if missing_indices:
        reasons.append("certified shard is missing from the local shard store")
    if corrupt_indices:
        reasons.append("certified shard hash no longer matches the certified payload")
    if verified_total_shards < layout.erasure.reconstruction_threshold:
        reasons.append("verified shard count is below the reconstruction threshold")

    if omitted_indices and mode is SamplingMode.SELECTIVE_SERVING:
        status = ReconstructionStatus.SELECTIVE_SERVICE
    elif corrupt_indices:
        status = ReconstructionStatus.CORRUPT
    elif missing_indices or verified_total_shards < layout.erasure.reconstruction_threshold:
        status = ReconstructionStatus.WITHHELD
    else:
        status = ReconstructionStatus.VERIFIED
    return ReconstructionResult(
        status=status,
        verified_sample_count=verified_sample_count,
        verified_total_shards=verified_total_shards,
        reconstruction_threshold=layout.erasure.reconstruction_threshold,
        missing_indices=tuple(missing_indices),
        corrupt_indices=tuple(corrupt_indices),
        omitted_indices=omitted_indices,
        reasons=tuple(reasons),
    )
