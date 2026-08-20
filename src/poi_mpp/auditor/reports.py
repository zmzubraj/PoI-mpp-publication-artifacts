"""Typed result envelopes for exact and approximate execution audits."""

from __future__ import annotations

from enum import StrEnum
import math

from pydantic import BaseModel, ConfigDict, model_validator

from poi_mpp.evidence.models import EvidenceOrigin


class AuditDisposition(StrEnum):
    """Normalized audit outcomes across exact and approximate paths."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INVALID_INPUT = "INVALID_INPUT"


class AssuranceClass(StrEnum):
    """Assurance levels exposed by the publication-facing audit surface."""

    EXACT_MATCH = "EXACT_MATCH"
    EXACT_FIELD_SOUNDNESS = "EXACT_FIELD_SOUNDNESS"
    DECLARED_MODULUS_ASSUMPTION = "DECLARED_MODULUS_ASSUMPTION"
    EMPIRICAL_FLOAT_APPROXIMATION = "EMPIRICAL_FLOAT_APPROXIMATION"


class AuditResult(BaseModel):
    """Immutable audit report with explicit assurance and residual risk."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_origin: EvidenceOrigin
    assurance_class: AssuranceClass
    accepted: bool
    disposition: AuditDisposition
    challenge_vectors: tuple[tuple[int, ...], ...] = ()
    rounds: int = 0
    seed: int | None = None
    modulus: int | None = None
    atol: float | None = None
    rtol: float | None = None
    dimensions: tuple[int, ...] = ()
    residual_risk: tuple[str, ...] = ()
    soundness_error_bound: float | None = None
    max_abs_error: float | None = None
    max_rel_error: float | None = None

    @model_validator(mode="after")
    def validate_consistency(self) -> "AuditResult":
        if self.accepted != (self.disposition is AuditDisposition.ACCEPTED):
            raise ValueError("accepted must match disposition")
        if self.rounds < 0:
            raise ValueError("rounds must be non-negative")
        if self.rounds != len(self.challenge_vectors):
            raise ValueError("rounds must equal the number of challenge vectors")
        if self.assurance_class is AssuranceClass.EXACT_MATCH:
            if self.challenge_vectors:
                raise ValueError("exact-match audits do not record challenge vectors")
            if self.soundness_error_bound is not None:
                raise ValueError("exact-match audits do not expose randomized soundness bounds")
            if self.atol is not None or self.rtol is not None:
                raise ValueError("exact-match audits do not accept floating tolerances")
        if self.assurance_class in {
            AssuranceClass.EXACT_FIELD_SOUNDNESS,
            AssuranceClass.DECLARED_MODULUS_ASSUMPTION,
        }:
            if self.modulus is None:
                raise ValueError("field audits require a modulus")
            if self.atol is not None or self.rtol is not None:
                raise ValueError("field audits do not accept floating tolerances")
        if self.assurance_class is AssuranceClass.EXACT_FIELD_SOUNDNESS:
            if self.soundness_error_bound is None:
                raise ValueError("exact field audits must record a soundness bound")
            if not math.isfinite(self.soundness_error_bound):
                raise ValueError("soundness_error_bound must be finite")
        if self.assurance_class is AssuranceClass.EMPIRICAL_FLOAT_APPROXIMATION:
            if self.soundness_error_bound is not None:
                raise ValueError("floating-point audits cannot claim exact soundness bounds")
            if self.atol is None or self.rtol is None:
                raise ValueError("floating-point audits must record atol and rtol")
        for field_name in ("atol", "rtol", "soundness_error_bound", "max_abs_error", "max_rel_error"):
            value = getattr(self, field_name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{field_name} must be finite when provided")
        return self
