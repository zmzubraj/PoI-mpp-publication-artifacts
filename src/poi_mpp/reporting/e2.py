"""Deterministic aggregation for E2 tamper-detection artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class E2Summary(_FrozenModel):
    schema_version: str = "POI_MPP_E2_SUMMARY_V1"
    claim_id: str
    denominator: int = Field(ge=0)
    exact_denominator: int = Field(ge=0)
    exact_detected: int = Field(ge=0)
    exact_detection_rate: float = Field(ge=0.0, le=1.0)
    empirical_denominator: int = Field(ge=0)
    empirical_detected: int = Field(ge=0)
    empirical_detection_rate: float = Field(ge=0.0, le=1.0)
    unsupported_attack_count: int = Field(ge=0)
    honest_control_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_positive_rate: float = Field(ge=0.0, le=1.0)
    residual_surface_ledger: tuple[str, ...] = ()
    claim_disposition: str

    @field_validator("claim_id", "claim_disposition")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary text fields must not be blank")
        return value

    @model_validator(mode="after")
    def validate_counts(self) -> "E2Summary":
        if self.denominator != self.exact_denominator + self.empirical_denominator:
            raise ValueError("denominator must equal exact + empirical supported counts")
        if self.exact_detected > self.exact_denominator:
            raise ValueError("exact_detected cannot exceed exact_denominator")
        if self.empirical_detected > self.empirical_denominator:
            raise ValueError("empirical_detected cannot exceed empirical_denominator")
        if self.false_positive_count > self.honest_control_count:
            raise ValueError("false_positive_count cannot exceed honest_control_count")
        return self


def _require_str(row: Mapping[str, object], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"E2 rows require non-blank {field_name}")
    return value


def _require_bool(row: Mapping[str, object], field_name: str) -> bool:
    value = row.get(field_name)
    if not isinstance(value, bool):
        raise ValueError(f"E2 rows require boolean {field_name}")
    return value


def summarize_e2_rows(
    rows: list[dict[str, object]] | list[Mapping[str, object]],
    *,
    claim_id: str = "C2",
) -> E2Summary:
    if not rows:
        raise ValueError("E2 summary requires receipt rows")

    run_ids = {_require_str(dict(row), "run_id") for row in rows}
    experiment_ids = {_require_str(dict(row), "experiment_id") for row in rows}
    if len(run_ids) != 1 or len(experiment_ids) != 1:
        raise ValueError("E2 rows must share a single run_id and experiment_id")

    exact_denominator = 0
    exact_detected = 0
    empirical_denominator = 0
    empirical_detected = 0
    unsupported_attack_count = 0
    honest_control_count = 0
    false_positive_count = 0
    residuals: list[str] = []

    for raw in rows:
        row = dict(raw)
        family = row.get("attack_family")
        analysis_surface = _require_str(row, "analysis_surface")
        detected = _require_bool(row, "detected")
        abstained = _require_bool(row, "abstained")
        false_positive = _require_bool(row, "false_positive")
        if false_positive:
            false_positive_count += 1
        residuals.extend(str(item) for item in row.get("residual_risk", ()) if str(item).strip())

        if family is None:
            honest_control_count += 1
            continue
        if analysis_surface == "UNSUPPORTED_SURFACE":
            if not abstained:
                raise ValueError("unsupported E2 attacks must abstain")
            unsupported_attack_count += 1
            continue
        if analysis_surface == "EXACT_MATCH":
            exact_denominator += 1
            exact_detected += int(detected)
            continue
        if analysis_surface in {"EXACT_FIELD_SOUNDNESS", "EMPIRICAL_FLOAT_APPROXIMATION"}:
            if analysis_surface == "EXACT_FIELD_SOUNDNESS":
                exact_denominator += 1
                exact_detected += int(detected)
            else:
                empirical_denominator += 1
                empirical_detected += int(detected)
            continue
        raise ValueError(f"unknown E2 analysis_surface: {analysis_surface}")

    denominator = exact_denominator + empirical_denominator
    exact_rate = exact_detected / exact_denominator if exact_denominator else 0.0
    empirical_rate = empirical_detected / empirical_denominator if empirical_denominator else 0.0
    false_positive_rate = (
        false_positive_count / honest_control_count if honest_control_count else 0.0
    )
    if denominator == 0:
        disposition = "INCONCLUSIVE"
    elif exact_detected + empirical_detected != denominator:
        disposition = "NOT_SUPPORTED"
    elif false_positive_count:
        disposition = "INCONCLUSIVE"
    else:
        disposition = "SUPPORTED"
    return E2Summary(
        claim_id=claim_id,
        denominator=denominator,
        exact_denominator=exact_denominator,
        exact_detected=exact_detected,
        exact_detection_rate=exact_rate,
        empirical_denominator=empirical_denominator,
        empirical_detected=empirical_detected,
        empirical_detection_rate=empirical_rate,
        unsupported_attack_count=unsupported_attack_count,
        honest_control_count=honest_control_count,
        false_positive_count=false_positive_count,
        false_positive_rate=false_positive_rate,
        residual_surface_ledger=tuple(dict.fromkeys(residuals)),
        claim_disposition=disposition,
    )
