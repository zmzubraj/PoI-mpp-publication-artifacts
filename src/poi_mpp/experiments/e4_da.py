"""E4 data-availability scenario rows and authority boundaries."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.auditor.availability.sampling import (
    ModelAssumptionError,
    ReconstructionResult,
    ReconstructionStatus,
    miss_probability_for_mode,
    wilson_interval,
)
from poi_mpp.evidence import EvidenceOrigin, RunConfig
from poi_mpp.protocol.availability import SamplingAssumption, SamplingMode


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IntervalKind(StrEnum):
    EXACT = "EXACT"
    WILSON = "WILSON"


class AuthorityBoundaryError(ValueError):
    """Raised when the E4 CLI would overstate unpublished authority."""


class AvailabilityScenario(_FrozenModel):
    scenario_id: str
    mode: SamplingMode
    assumption_label: SamplingAssumption
    total_shards: int = Field(gt=0)
    reconstruction_threshold: int = Field(gt=0)
    unavailable_shards: int = Field(ge=0)
    samples: int = Field(gt=0)
    replacement: bool
    observed_misses: int | None = Field(default=None, ge=0)
    observed_trials: int | None = Field(default=None, ge=0)

    @field_validator("scenario_id")
    @classmethod
    def require_nonblank_scenario_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scenario_id must not be blank")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> "AvailabilityScenario":
        if self.reconstruction_threshold > self.total_shards:
            raise ValueError("reconstruction_threshold cannot exceed total_shards")
        if self.unavailable_shards > self.total_shards:
            raise ValueError("unavailable_shards cannot exceed total_shards")
        if not self.replacement and self.samples > self.total_shards:
            raise ValueError("samples cannot exceed total_shards when replacement is false")
        if self.mode is SamplingMode.STATIC_WITH_REPLACEMENT:
            if self.assumption_label is not SamplingAssumption.STATIC_WITH_REPLACEMENT_EXACT:
                raise ValueError("static with-replacement scenarios require STATIC_WITH_REPLACEMENT_EXACT")
            if not self.replacement:
                raise ValueError("static with-replacement scenarios require replacement=true")
        elif self.mode is SamplingMode.STATIC_WITHOUT_REPLACEMENT:
            if self.assumption_label is not SamplingAssumption.STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC:
                raise ValueError(
                    "static without-replacement scenarios require STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC"
                )
            if self.replacement:
                raise ValueError("static without-replacement scenarios require replacement=false")
        elif self.mode is SamplingMode.TARGETED_WITHHOLDING:
            if self.assumption_label is not SamplingAssumption.TARGETED_WITHHOLDING_DECLARED:
                raise ValueError("targeted withholding must be labeled TARGETED_WITHHOLDING_DECLARED")
        elif self.mode is SamplingMode.SELECTIVE_SERVING:
            if self.assumption_label is not SamplingAssumption.SELECTIVE_SERVING_DECLARED:
                raise ValueError("selective serving must be labeled SELECTIVE_SERVING_DECLARED")
        elif self.mode is SamplingMode.CORRELATED_LOSS:
            if self.assumption_label is not SamplingAssumption.CORRELATED_LOSS_DECLARED:
                raise ValueError("correlated loss must be labeled CORRELATED_LOSS_DECLARED")
        if self.mode in {
            SamplingMode.STATIC_WITH_REPLACEMENT,
            SamplingMode.STATIC_WITHOUT_REPLACEMENT,
        }:
            if self.observed_misses is not None or self.observed_trials is not None:
                raise ValueError("static scenarios use exact probability and cannot mix observed counts")
            return self
        if self.observed_misses is None or self.observed_trials is None:
            raise ValueError("non-static scenarios require observed_misses and observed_trials")
        if self.observed_misses > self.observed_trials:
            raise ValueError("observed_misses cannot exceed observed_trials")
        return self


class E4ScenarioRow(_FrozenModel):
    schema_version: str = "POI_MPP_E4_SCENARIO_ROW_V1"
    run_id: str
    experiment_id: str
    scenario_id: str
    origin: EvidenceOrigin
    mode: SamplingMode
    assumption_label: SamplingAssumption
    interval_kind: IntervalKind
    denominator: int = Field(gt=0)
    miss_probability: float = Field(ge=0.0, le=1.0)
    exact_miss_probability: str | None = None
    confidence_interval: tuple[float, float]
    reconstruction_status: str
    notes: tuple[str, ...] = ()

    @field_validator("run_id", "experiment_id", "scenario_id")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("E4 identifiers must not be blank")
        return value

    @model_validator(mode="after")
    def validate_interval(self) -> "E4ScenarioRow":
        if len(self.confidence_interval) != 2 or self.confidence_interval[0] > self.confidence_interval[1]:
            raise ValueError("confidence_interval must contain ordered bounds")
        if self.interval_kind is IntervalKind.EXACT and self.exact_miss_probability is None:
            raise ValueError("EXACT rows must carry exact_miss_probability")
        return self


def build_e4_row(
    *,
    run_id: str,
    experiment_id: str,
    origin: EvidenceOrigin,
    scenario: AvailabilityScenario,
    reconstruction: ReconstructionResult | None = None,
) -> E4ScenarioRow:
    if scenario.mode in {
        SamplingMode.STATIC_WITH_REPLACEMENT,
        SamplingMode.STATIC_WITHOUT_REPLACEMENT,
    }:
        exact = miss_probability_for_mode(
            mode=scenario.mode,
            total=scenario.total_shards,
            withheld=scenario.unavailable_shards,
            samples=scenario.samples,
            replacement=scenario.replacement,
        )
        value = float(exact)
        return E4ScenarioRow(
            run_id=run_id,
            experiment_id=experiment_id,
            scenario_id=scenario.scenario_id,
            origin=origin,
            mode=scenario.mode,
            assumption_label=scenario.assumption_label,
            interval_kind=IntervalKind.EXACT,
            denominator=1,
            miss_probability=value,
            exact_miss_probability=f"{exact.numerator}/{exact.denominator}",
            confidence_interval=(value, value),
            reconstruction_status=(
                ReconstructionStatus.VERIFIED if reconstruction is None else reconstruction.status
            ),
            notes=(),
        )

    assert scenario.observed_misses is not None
    assert scenario.observed_trials is not None
    interval = wilson_interval(misses=scenario.observed_misses, trials=scenario.observed_trials)
    notes = ("exact closed-form intentionally not used",)
    if scenario.mode is SamplingMode.CORRELATED_LOSS:
        try:
            miss_probability_for_mode(
                mode=scenario.mode,
                total=scenario.total_shards,
                withheld=scenario.unavailable_shards,
                samples=scenario.samples,
                replacement=scenario.replacement,
            )
        except ModelAssumptionError:
            pass
    return E4ScenarioRow(
        run_id=run_id,
        experiment_id=experiment_id,
        scenario_id=scenario.scenario_id,
        origin=origin,
        mode=scenario.mode,
        assumption_label=scenario.assumption_label,
        interval_kind=IntervalKind.WILSON,
        denominator=scenario.observed_trials,
        miss_probability=scenario.observed_misses / scenario.observed_trials,
        exact_miss_probability=None,
        confidence_interval=interval,
        reconstruction_status=(
            ReconstructionStatus.VERIFIED if reconstruction is None else reconstruction.status
        ),
        notes=notes,
    )


def assert_cli_authority_boundary(run_config: RunConfig) -> None:
    if run_config.experiment_id != "E4":
        raise AuthorityBoundaryError("E4 wrapper requires experiment_id E4")
    if run_config.origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
        raise AuthorityBoundaryError("no authorized real pilot/result exists for E4; only reproducible simulation is allowed")
    if run_config.authorization_scope != "LOCAL_TEST_ONLY":
        raise AuthorityBoundaryError("E4 wrapper only permits LOCAL_TEST_ONLY reproducible simulation")
    raise AuthorityBoundaryError(
        "E4 wrapper intentionally stops before ad-hoc artifact generation; use the library with an explicit local shard fixture"
    )
