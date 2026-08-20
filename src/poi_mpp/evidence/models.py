"""Immutable, fail-closed records for the evidence kernel."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class EvidenceOrigin(StrEnum):
    """The provenance category of an evidence-producing execution."""

    REAL_MODEL_EXECUTION = "REAL_MODEL_EXECUTION"
    FOUNDRY_MEASUREMENT = "FOUNDRY_MEASUREMENT"
    REPRODUCIBLE_SIMULATION = "REPRODUCIBLE_SIMULATION"
    SYNTHETIC_NON_EVIDENCE = "SYNTHETIC_NON_EVIDENCE"


class ArtifactStage(StrEnum):
    """The only valid lifecycle stages for a canonical artifact."""

    GENERATED = "GENERATED"
    SCHEMA_VALID = "SCHEMA_VALID"
    SEMANTICALLY_VALID = "SEMANTICALLY_VALID"
    FROZEN = "FROZEN"
    PUBLICATION_ELIGIBLE = "PUBLICATION_ELIGIBLE"


_STAGE_ORDER = tuple(ArtifactStage)
_STAGE_INDEX = {stage: index for index, stage in enumerate(_STAGE_ORDER)}


class _FrozenEvidenceModel(BaseModel):
    """Shared model policy: immutable instances and no silent extra fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactRecord(_FrozenEvidenceModel):
    """A hash-addressable artifact and its lifecycle/provenance disposition.

    This model records completeness-oriented lifecycle state only. Whether an
    artifact scientifically supports a claim is deliberately owned by the later
    publication-gate layer.
    """

    schema_version: Literal["POI_MPP_EVIDENCE_V1"] = "POI_MPP_EVIDENCE_V1"
    artifact_id: str
    run_id: str
    experiment_id: str
    origin: EvidenceOrigin
    stage: ArtifactStage
    content_hash: str | None = None
    parent_hashes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def reject_synthetic_freeze(self) -> "ArtifactRecord":
        if (
            self.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE
            and _STAGE_INDEX[self.stage] >= _STAGE_INDEX[ArtifactStage.FROZEN]
        ):
            raise ValueError("synthetic evidence cannot be frozen or publication eligible")
        return self

    @classmethod
    def minimal(
        cls,
        *,
        origin: EvidenceOrigin = EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        stage: ArtifactStage = ArtifactStage.GENERATED,
    ) -> "ArtifactRecord":
        """Build a deterministic minimal record for unit-level plumbing tests."""

        return cls(
            artifact_id="MINIMAL_ARTIFACT",
            run_id="MINIMAL_RUN",
            experiment_id="MINIMAL_EXPERIMENT",
            origin=origin,
            stage=stage,
        )

    def can_advance_to(self, stage: ArtifactStage) -> bool:
        """Return whether ``stage`` is the next (and only next) lifecycle step."""

        target = ArtifactStage(stage)
        return _STAGE_INDEX[target] == _STAGE_INDEX[self.stage] + 1

    def advance_to(self, stage: ArtifactStage) -> "ArtifactRecord":
        """Create a validated record at the next lifecycle stage.

        Direct construction remains available for deserializing already-frozen
        records, while this method prevents in-process lifecycle skips or
        regressions.
        """

        target = ArtifactStage(stage)
        if not self.can_advance_to(target):
            raise ValueError(
                f"invalid lifecycle transition: {self.stage.value} -> {target.value}"
            )
        return type(self).model_validate(
            {**self.model_dump(mode="json"), "stage": target.value}
        )


class RunManifest(_FrozenEvidenceModel):
    """Canonical run-level provenance roots used by later freeze operations."""

    schema_version: Literal["POI_MPP_RUN_MANIFEST_V1"] = "POI_MPP_RUN_MANIFEST_V1"
    run_id: str
    experiment_id: str
    config_hash: str
    environment_hash: str
    code_revision: str
    origin: EvidenceOrigin
    authorization_scope: str
    model_hash: str | None = None
    dataset_hash: str | None = None
    input_root: str | None = None
    response_root: str | None = None
    trace_root: str | None = None
    evidence_root: str | None = None
    artifact_root: str | None = None
    parent_hashes: tuple[str, ...] = ()
