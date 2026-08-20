"""Aggregate independent completeness and claim-support publication decisions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from poi_mpp.evidence.validation import ValidationReport, validate_artifact


ClaimDisposition = Literal["SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"]


@dataclass(frozen=True)
class GateDecision:
    """A claim gate result; completeness never derives from claim support."""

    claim_id: str
    completeness: Literal["COMPLETE", "INCOMPLETE"]
    claim_support: ClaimDisposition
    reasons: tuple[str, ...]

    @property
    def disposition(self) -> ClaimDisposition:
        """Compatibility-friendly name for the scientific claim disposition."""

        return self.claim_support


def _claim_disposition(record: dict[str, Any], claim_id: str) -> tuple[ClaimDisposition | None, str | None]:
    matrix = record.get("claim_dispositions")
    if matrix is not None:
        if not isinstance(matrix, dict):
            return None, "claim_dispositions must be a mapping"
        candidate = matrix.get(claim_id)
    elif record.get("claim_id") == claim_id:
        candidate = record.get("claim_disposition", record.get("claim_support"))
    else:
        return None, f"missing claim disposition for {claim_id}"
    if candidate not in {"SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"}:
        return None, f"invalid claim disposition for {claim_id}"
    return candidate, None


def evaluate_publication_gate(claim_id: str, artifacts: Sequence[object]) -> GateDecision:
    """Evaluate a claim without turning complete negative evidence into failure."""

    if not isinstance(claim_id, str) or not claim_id.strip():
        return GateDecision(
            claim_id=str(claim_id),
            completeness="INCOMPLETE",
            claim_support="INCONCLUSIVE",
            reasons=("claim_id must not be blank",),
        )
    if not artifacts:
        return GateDecision(
            claim_id=claim_id,
            completeness="INCOMPLETE",
            claim_support="INCONCLUSIVE",
            reasons=("no artifacts supplied for claim",),
        )

    normalized: list[dict[str, Any]] = []
    for index, artifact in enumerate(artifacts):
        try:
            # Parent closure is intentionally not inferred: absent registered
            # context makes a declared parent incomplete.
            report: ValidationReport = validate_artifact(artifact, raise_on_error=False)
            normalized.append(report.record)
        except Exception as error:
            normalized.append({"_unreadable_index": index})
            # Preserve input ordering while retaining the exact exception only
            # as a reason; it can never be treated as a valid empty artifact.
            normalized[-1]["_unreadable_reason"] = str(error)

    known_hashes = {
        record.get("content_hash")
        for record in normalized
        if isinstance(record.get("content_hash"), str)
    }
    reasons: list[str] = []
    complete_reports: list[ValidationReport] = []
    for index, record in enumerate(normalized):
        if "_unreadable_reason" in record:
            reasons.append(f"artifact[{index}]: unreadable artifact: {record['_unreadable_reason']}")
            continue
        own_hash = record.get("content_hash")
        report = validate_artifact(
            record,
            known_parent_hashes=known_hashes - ({own_hash} if isinstance(own_hash, str) else set()),
            raise_on_error=False,
        )
        complete_reports.append(report)
        reasons.extend(f"artifact[{index}]: {reason}" for reason in report.reasons)
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        return GateDecision(
            claim_id=claim_id,
            completeness="INCOMPLETE",
            claim_support="INCONCLUSIVE",
            reasons=tuple(reasons),
        )

    dispositions: list[ClaimDisposition] = []
    claim_reasons: list[str] = []
    for record in (report.record for report in complete_reports):
        disposition, error = _claim_disposition(record, claim_id)
        if error is not None:
            claim_reasons.append(error)
        elif disposition is not None:
            dispositions.append(disposition)
    if claim_reasons:
        return GateDecision(
            claim_id=claim_id,
            completeness="INCOMPLETE",
            claim_support="INCONCLUSIVE",
            reasons=tuple(dict.fromkeys(claim_reasons)),
        )
    unique = tuple(dict.fromkeys(dispositions))
    if len(unique) == 1:
        return GateDecision(
            claim_id=claim_id,
            completeness="COMPLETE",
            claim_support=unique[0],
            reasons=(),
        )
    return GateDecision(
        claim_id=claim_id,
        completeness="COMPLETE",
        claim_support="INCONCLUSIVE",
        reasons=("mixed complete claim dispositions are inconclusive",),
    )
