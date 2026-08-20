"""Deterministic E1 aggregation for T6/F5 inputs."""

from __future__ import annotations

from enum import StrEnum
import random
from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class E1Variant(StrEnum):
    NATIVE_SINGLE = "NATIVE_SINGLE"
    TWO_RUN_BASELINE = "TWO_RUN_BASELINE"
    MPP_SINGLE_PASS = "MPP_SINGLE_PASS"


class E1Summary(_FrozenModel):
    schema_version: str = "POI_MPP_E1_SUMMARY_V1"
    claim_id: str
    paired_count: int = Field(gt=0)
    mean_two_run_ms: float = Field(ge=0.0)
    mean_mpp_ms: float = Field(ge=0.0)
    mean_delta_ms: float
    delta_ci: tuple[float, float]
    claim_disposition: str

    @field_validator("claim_id", "claim_disposition")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary text fields must not be blank")
        return value

    @field_validator("delta_ci")
    @classmethod
    def validate_ci(cls, value: tuple[float, float]) -> tuple[float, float]:
        if len(value) != 2 or value[0] > value[1]:
            raise ValueError("delta_ci must contain two ordered bounds")
        return value


def _bootstrap_interval(values: list[float], *, seed: int = 1, iterations: int = 256) -> tuple[float, float]:
    generator = random.Random(seed)
    means: list[float] = []
    for _ in range(iterations):
        sample = [generator.choice(values) for _ in range(len(values))]
        means.append(fmean(sample))
    means.sort()
    lower_index = max(0, int(0.025 * (iterations - 1)))
    upper_index = min(iterations - 1, int(0.975 * (iterations - 1)))
    return means[lower_index], means[upper_index]


def summarize_e1_rows(rows: list[dict[str, object]], *, claim_id: str = "C1") -> E1Summary:
    two_run = [float(row["measured_ms"]) for row in rows if row["variant"] == E1Variant.TWO_RUN_BASELINE.value]
    mpp = [float(row["measured_ms"]) for row in rows if row["variant"] == E1Variant.MPP_SINGLE_PASS.value]
    if not two_run or not mpp or len(two_run) != len(mpp):
        raise ValueError("E1 summary requires paired two-run and MPP measured rows")
    deltas = [baseline - candidate for baseline, candidate in zip(two_run, mpp, strict=True)]
    delta_ci = _bootstrap_interval(deltas)
    disposition = "SUPPORTED" if delta_ci[0] > 0 else "INCONCLUSIVE"
    return E1Summary(
        claim_id=claim_id,
        paired_count=len(deltas),
        mean_two_run_ms=fmean(two_run),
        mean_mpp_ms=fmean(mpp),
        mean_delta_ms=fmean(deltas),
        delta_ci=delta_ci,
        claim_disposition=disposition,
    )
