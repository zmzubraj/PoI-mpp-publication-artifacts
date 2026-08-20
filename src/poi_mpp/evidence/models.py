"""Immutable, fail-closed records for the evidence kernel."""

from __future__ import annotations

from enum import StrEnum
import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator


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
_TERMINAL_STAGES = frozenset({ArtifactStage.FROZEN, ArtifactStage.PUBLICATION_ELIGIBLE})
_LOWERCASE_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


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

    @field_validator("artifact_id", "run_id", "experiment_id")
    @classmethod
    def reject_blank_identifiers(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str | None) -> str | None:
        if value is not None and not _LOWERCASE_SHA256.fullmatch(value):
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("parent_hashes")
    @classmethod
    def validate_parent_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not _LOWERCASE_SHA256.fullmatch(value):
                raise ValueError("parent_hashes must contain lowercase SHA-256 hex digests")
        return values

    @model_validator(mode="after")
    def validate_lifecycle(self, info: ValidationInfo) -> "ArtifactRecord":
        if (
            self.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE
            and self.stage in _TERMINAL_STAGES
        ):
            raise ValueError("synthetic evidence cannot be frozen or publication eligible")
        if self.stage in _TERMINAL_STAGES:
            if self.content_hash is None:
                raise ValueError("terminal artifacts require a lowercase SHA-256 content_hash")
            trusted_restore = isinstance(info.context, dict) and info.context.get(
                "_poi_mpp_trusted_restore"
            ) is True
            if not trusted_restore:
                raise ValueError("terminal stages must be obtained through advance_to")
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
            {**self.model_dump(mode="json"), "stage": target.value},
            context={"_poi_mpp_trusted_restore": True},
        )

    @classmethod
    def trusted_load(cls, data: Mapping[str, Any]) -> "ArtifactRecord":
        """Restore a persisted record after validation of all current invariants.

        This is intentionally distinct from normal construction. It is the sole
        supported route for loading a previously persisted terminal artifact;
        it still enforces nonblank identities, hash syntax, provenance origin,
        and the synthetic-evidence prohibition.
        """

        return cls.model_validate(data, context={"_poi_mpp_trusted_restore": True})


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
