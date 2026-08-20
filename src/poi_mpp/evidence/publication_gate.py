"""Publication gate with independent completeness and claim-support outcomes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from poi_mpp.evidence.validation import (
    ArtifactValidationError,
    ProvenanceBundle,
    validate_artifact,
    validate_artifact_graph,
)


ClaimDisposition = Literal["SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"]


@dataclass(frozen=True)
class GateDecision:
    claim_id: str
    completeness: Literal["COMPLETE", "INCOMPLETE"]
    claim_support: ClaimDisposition
    reasons: tuple[str, ...]

    @property
    def disposition(self) -> ClaimDisposition:
        return self.claim_support


def _claim_disposition(record: dict[str, Any], claim_id: str) -> tuple[ClaimDisposition | None, str | None]:
    if "claim_dispositions" in record:
        matrix = record["claim_dispositions"]
        candidate = matrix.get(claim_id) if isinstance(matrix, dict) else None
    elif record.get("claim_id") == claim_id:
        candidate = record.get("claim_disposition")
    else:
        return None, f"missing claim disposition for {claim_id}"
    if candidate not in {"SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"}:
        return None, f"invalid claim disposition for {claim_id}"
    return candidate, None


def evaluate_publication_gate(claim_id: str, artifacts: Sequence[object], *, provenance_bundles: Sequence[ProvenanceBundle | None] | None = None) -> GateDecision:
    """Fail closed on evidence integrity, without penalizing negative findings."""

    if not isinstance(claim_id, str) or not claim_id.strip():
        return GateDecision(str(claim_id), "INCOMPLETE", "INCONCLUSIVE", ("claim_id must not be blank",))
    if not artifacts:
        return GateDecision(claim_id, "INCOMPLETE", "INCONCLUSIVE", ("no artifacts supplied for claim",))
    bundles = list(provenance_bundles) if provenance_bundles is not None else [None] * len(artifacts)
    if len(bundles) != len(artifacts):
        return GateDecision(claim_id, "INCOMPLETE", "INCONCLUSIVE", ("provenance bundle count does not match artifacts",))
    known_hashes = {
        item.get("content_hash")
        for item in artifacts
        if isinstance(item, dict) and isinstance(item.get("content_hash"), str)
    }
    reports = []
    reasons: list[str] = []
    for index, (artifact, bundle) in enumerate(zip(artifacts, bundles, strict=True)):
        try:
            own_hash = artifact.get("content_hash") if isinstance(artifact, dict) else None
            report = validate_artifact(artifact, provenance_bundle=bundle, known_parent_hashes=known_hashes - ({own_hash} if isinstance(own_hash, str) else set()), raise_on_error=False)
            reports.append(report)
            reasons.extend(f"artifact[{index}]: {reason}" for reason in report.reasons)
        except ArtifactValidationError as error:
            reasons.extend(f"artifact[{index}]: {reason}" for reason in error.reasons)
    records = [report.record for report in reports]
    reasons.extend(validate_artifact_graph(records))
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        return GateDecision(claim_id, "INCOMPLETE", "INCONCLUSIVE", tuple(reasons))
    dispositions: list[ClaimDisposition] = []
    claim_reasons: list[str] = []
    for report in reports:
        disposition, reason = _claim_disposition(report.record, claim_id)
        if reason:
            claim_reasons.append(reason)
        elif disposition:
            dispositions.append(disposition)
    if claim_reasons:
        return GateDecision(claim_id, "INCOMPLETE", "INCONCLUSIVE", tuple(dict.fromkeys(claim_reasons)))
    unique = tuple(dict.fromkeys(dispositions))
    if len(unique) == 1:
        return GateDecision(claim_id, "COMPLETE", unique[0], ())
    return GateDecision(claim_id, "COMPLETE", "INCONCLUSIVE", ("mixed complete claim dispositions are inconclusive",))
