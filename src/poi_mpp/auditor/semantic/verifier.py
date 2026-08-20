"""Deterministic grounded verification with fail-closed abstention."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from poi_mpp.auditor.semantic.models import (
    ClaimVerificationOutcome,
    EvidenceAnnotationKind,
    EvidenceRecord,
    GroundedClaim,
    GroundedVerificationResult,
    NumericComparator,
    NumericExpectation,
    SemanticCalibrationArtifact,
    SemanticOutcome,
    VerificationDecision,
    VerificationMode,
    parse_bounded_decimal,
)
from poi_mpp.evidence.canonical import digest


def _compare_numeric(
    actual: Decimal,
    expectation: NumericExpectation,
) -> bool:
    expected = parse_bounded_decimal(expectation.value, label="numeric expectation value")
    if expectation.comparator is NumericComparator.EQUALS:
        return actual == expected
    if expectation.comparator is NumericComparator.AT_LEAST:
        return actual >= expected
    return actual <= expected


def _evaluate_claim(
    claim: GroundedClaim,
    citation_index: dict[str, list[EvidenceRecord]],
    calibration: SemanticCalibrationArtifact,
) -> ClaimVerificationOutcome:
    del calibration
    missing = [citation_id for citation_id in claim.cited_citation_ids if citation_id not in citation_index]
    duplicate = [
        citation_id
        for citation_id in claim.cited_citation_ids
        if len(citation_index.get(citation_id, ())) != 1
    ]
    if missing or duplicate:
        reasons = tuple(
            [f"missing citation: {citation_id}" for citation_id in missing]
            + [f"duplicate citation: {citation_id}" for citation_id in duplicate]
        )
        return ClaimVerificationOutcome(
            claim_id=claim.claim_id,
            outcome=SemanticOutcome.CITATION_ERROR,
            decision=VerificationDecision.REJECT,
            citation_ids=claim.cited_citation_ids,
            reasons=reasons,
        )

    records = tuple(citation_index[citation_id][0] for citation_id in claim.cited_citation_ids)
    reasons: list[str] = []
    evidence_ids: list[str] = []
    semantic_assertions_present = False

    for record in records:
        evidence_ids.append(record.evidence_id)
        claim_annotations = tuple(
            item for item in record.annotations if item.claim_id == claim.claim_id
        )
        claim_numeric_facts = tuple(
            fact for fact in record.numeric_facts if fact.claim_id == claim.claim_id
        )
        if claim_annotations or claim_numeric_facts:
            semantic_assertions_present = True
            reasons.append(
                f"annotation-driven semantic authority is deferred until a registry-backed capability exists for citation {record.citation_id}"
            )
            if record.label_authority == "TRUSTED_GROUNDED_ANNOTATOR":
                reasons.append(
                    f"caller-visible trusted authority is not sufficient for citation {record.citation_id}"
                )
            if (
                record.trusted_artifact_id is not None
                or record.trusted_provenance_hash is not None
                or record.trusted_annotation_hash is not None
            ):
                reasons.append(
                    f"serialized trust bindings are not accepted for citation {record.citation_id}"
                )
        else:
            reasons.append(f"citation {record.citation_id} provides no explicit support")

    if semantic_assertions_present:
        return ClaimVerificationOutcome(
            claim_id=claim.claim_id,
            outcome=SemanticOutcome.AMBIGUOUS,
            decision=VerificationDecision.ABSTAIN,
            citation_ids=claim.cited_citation_ids,
            evidence_ids=tuple(evidence_ids),
            reasons=tuple(reasons),
        )

    return ClaimVerificationOutcome(
        claim_id=claim.claim_id,
        outcome=SemanticOutcome.UNSUPPORTED,
        decision=VerificationDecision.REJECT,
        citation_ids=claim.cited_citation_ids,
        evidence_ids=tuple(evidence_ids),
        reasons=tuple(reasons) if reasons else ("no cited evidence explicitly supports the claim",),
    )


def verify_grounded(
    *,
    response: str,
    claims: tuple[GroundedClaim, ...] | list[GroundedClaim],
    evidence: tuple[EvidenceRecord, ...] | list[EvidenceRecord],
    calibration: SemanticCalibrationArtifact,
    mode: VerificationMode = VerificationMode.CONFIRMATORY,
) -> GroundedVerificationResult:
    """Verify trusted grounded labels against cited evidence without lexical inference."""

    del mode  # The frozen calibration artifact is the only tuning input at verification time.

    frozen_claims = tuple(claims)
    if not frozen_claims:
        raise ValueError("verify_grounded requires at least one claim")

    citation_index: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in evidence:
        citation_index[record.citation_id].append(record)

    outcomes = tuple(
        _evaluate_claim(claim, citation_index, calibration) for claim in frozen_claims
    )
    if any(outcome.decision is VerificationDecision.ABSTAIN for outcome in outcomes):
        decision = VerificationDecision.ABSTAIN
    elif all(outcome.decision is VerificationDecision.ACCEPT for outcome in outcomes):
        decision = VerificationDecision.ACCEPT
    else:
        decision = VerificationDecision.REJECT

    residual_risks = tuple(
        dict.fromkeys(
            reason
            for outcome in outcomes
            for reason in outcome.reasons
        )
    )
    return GroundedVerificationResult(
        response_hash=digest("SEMANTIC_RESPONSE", response),
        calibration_hash=calibration.content_hash,
        decision=decision,
        outcomes=outcomes,
        residual_risks=residual_risks,
    )
