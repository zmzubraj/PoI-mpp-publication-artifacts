"""Deterministic E1 aggregation for T6/F5 inputs."""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
import random
from statistics import fmean
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MIN_E1_SUPPORTED_PAIRS = 2


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class E1Variant(StrEnum):
    NATIVE_SINGLE = "NATIVE_SINGLE"
    TWO_RUN_BASELINE = "TWO_RUN_BASELINE"
    MPP_SINGLE_PASS = "MPP_SINGLE_PASS"


class E1Summary(_FrozenModel):
    schema_version: str = "POI_MPP_E1_SUMMARY_V1"
    claim_id: str
    denominator: int = Field(gt=0)
    paired_count: int = Field(gt=0)
    minimum_pairs_required: int = Field(ge=MIN_E1_SUPPORTED_PAIRS)
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

    @model_validator(mode="after")
    def validate_denominator(self) -> "E1Summary":
        if self.denominator != self.paired_count:
            raise ValueError("denominator must equal paired_count")
        return self


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


def _require_str(row: Mapping[str, object], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"E1 rows require non-blank {field_name}")
    return value


def _require_int(row: Mapping[str, object], field_name: str) -> int:
    value = row.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"E1 rows require integer {field_name}")
    return value


def summarize_e1_rows(
    rows: list[dict[str, object]] | list[Mapping[str, object]],
    *,
    claim_id: str = "C1",
    minimum_pairs_required: int = MIN_E1_SUPPORTED_PAIRS,
) -> E1Summary:
    if minimum_pairs_required < MIN_E1_SUPPORTED_PAIRS:
        raise ValueError("minimum_pairs_required cannot weaken the frozen E1 floor")
    if not rows:
        raise ValueError("E1 summary requires measured rows")

    pair_rows: dict[str, dict[str, Mapping[str, object]]] = defaultdict(dict)
    expected_run_id: str | None = None
    expected_experiment_id: str | None = None
    expected_task_id: int | None = None
    expected_origin: str | None = None

    for raw in rows:
        row = dict(raw)
        if row.get("is_warmup") is True:
            raise ValueError("warmup rows cannot enter E1 summary")
        pair_id = _require_str(row, "pair_id")
        variant = _require_str(row, "variant")
        run_id = _require_str(row, "run_id")
        experiment_id = _require_str(row, "experiment_id")
        origin = _require_str(row, "origin")
        task_id = _require_int(row, "task_id")
        if variant not in {item.value for item in E1Variant}:
            raise ValueError(f"unknown E1 variant: {variant}")
        if expected_run_id is None:
            expected_run_id = run_id
            expected_experiment_id = experiment_id
            expected_task_id = task_id
            expected_origin = origin
        elif (
            run_id != expected_run_id
            or experiment_id != expected_experiment_id
            or task_id != expected_task_id
            or origin != expected_origin
        ):
            raise ValueError("E1 measured rows must share one run_id, experiment_id, task_id, and origin")
        if variant in pair_rows[pair_id]:
            raise ValueError(f"duplicate variant for pair_id {pair_id}: {variant}")
        pair_rows[pair_id][variant] = row

    ordered_pair_ids = sorted(pair_rows)
    missing = [
        pair_id
        for pair_id in ordered_pair_ids
        if set(pair_rows[pair_id]) != {item.value for item in E1Variant}
    ]
    if missing:
        raise ValueError(f"E1 pair is missing required variants: {', '.join(missing)}")

    two_run: list[float] = []
    mpp: list[float] = []
    for pair_id in ordered_pair_ids:
        group = pair_rows[pair_id]
        two_run.append(float(group[E1Variant.TWO_RUN_BASELINE.value]["measured_ms"]))
        mpp.append(float(group[E1Variant.MPP_SINGLE_PASS.value]["measured_ms"]))

    deltas = [baseline - candidate for baseline, candidate in zip(two_run, mpp, strict=True)]
    delta_ci = _bootstrap_interval(deltas)
    disposition = (
        "SUPPORTED"
        if len(ordered_pair_ids) >= minimum_pairs_required and delta_ci[0] > 0
        else "INCONCLUSIVE"
    )
    return E1Summary(
        claim_id=claim_id,
        denominator=len(ordered_pair_ids),
        paired_count=len(ordered_pair_ids),
        minimum_pairs_required=minimum_pairs_required,
        mean_two_run_ms=fmean(two_run),
        mean_mpp_ms=fmean(mpp),
        mean_delta_ms=fmean(deltas),
        delta_ci=delta_ci,
        claim_disposition=disposition,
    )
