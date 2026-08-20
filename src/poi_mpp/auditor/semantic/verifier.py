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
    support_count = 0
    contradiction_count = 0
    reasons: list[str] = []
    evidence_ids: list[str] = []
    untrusted_semantic_labels = False

    for record in records:
        evidence_ids.append(record.evidence_id)
        if (
            record.label_authority != "TRUSTED_GROUNDED_ANNOTATOR"
            and (record.annotations or record.numeric_facts)
        ):
            untrusted_semantic_labels = True
            reasons.append(
                f"trusted semantic label authority not verified for citation {record.citation_id}"
            )
            continue
        kinds = {item.kind for item in record.annotations if item.claim_id == claim.claim_id}
        if EvidenceAnnotationKind.SUPPORTS in kinds and EvidenceAnnotationKind.CONTRADICTS in kinds:
            reasons.append(f"ambiguous annotation in citation {record.citation_id}")
        elif EvidenceAnnotationKind.CONTRADICTS in kinds:
            contradiction_count += 1
            reasons.append(f"citation {record.citation_id} contradicts the claim")
        elif EvidenceAnnotationKind.SUPPORTS in kinds:
            support_count += 1
        else:
            reasons.append(f"citation {record.citation_id} provides no explicit support")

    if untrusted_semantic_labels:
        return ClaimVerificationOutcome(
            claim_id=claim.claim_id,
            outcome=SemanticOutcome.AMBIGUOUS,
            decision=VerificationDecision.ABSTAIN,
            citation_ids=claim.cited_citation_ids,
            evidence_ids=tuple(evidence_ids),
            reasons=tuple(reasons),
        )
    if support_count and contradiction_count:
        reasons.append("mixed support and contradiction across cited evidence")
    if any(reason.startswith("ambiguous annotation") for reason in reasons) or (
        support_count and contradiction_count
    ):
        return ClaimVerificationOutcome(
            claim_id=claim.claim_id,
            outcome=SemanticOutcome.AMBIGUOUS,
            decision=VerificationDecision.ABSTAIN,
            citation_ids=claim.cited_citation_ids,
            evidence_ids=tuple(evidence_ids),
            reasons=tuple(reasons),
        )
    if contradiction_count and not support_count:
        return ClaimVerificationOutcome(
            claim_id=claim.claim_id,
            outcome=SemanticOutcome.CONTRADICTORY,
            decision=VerificationDecision.REJECT,
            citation_ids=claim.cited_citation_ids,
            evidence_ids=tuple(evidence_ids),
            reasons=tuple(reasons),
        )

    if claim.numeric_expectation is not None:
        numeric_facts = [
            fact
            for record in records
            for fact in record.numeric_facts
            if fact.claim_id == claim.claim_id and fact.metric == claim.numeric_expectation.metric
        ]
        if not numeric_facts:
            return ClaimVerificationOutcome(
                claim_id=claim.claim_id,
                outcome=SemanticOutcome.NUMERICAL_ERROR,
                decision=VerificationDecision.REJECT,
                citation_ids=claim.cited_citation_ids,
                evidence_ids=tuple(evidence_ids),
                reasons=("missing numeric fact for cited claim",),
            )
        parsed_values: list[Decimal] = []
        for fact in numeric_facts:
            if fact.unit != claim.numeric_expectation.unit:
                return ClaimVerificationOutcome(
                    claim_id=claim.claim_id,
                    outcome=SemanticOutcome.NUMERICAL_ERROR,
                    decision=VerificationDecision.REJECT,
                    citation_ids=claim.cited_citation_ids,
                    evidence_ids=tuple(evidence_ids),
                    reasons=(f"numeric unit mismatch for metric {fact.metric}",),
                )
            parsed_values.append(parse_bounded_decimal(fact.value, label="numeric fact value"))
        if not all(_compare_numeric(value, claim.numeric_expectation) for value in parsed_values):
            return ClaimVerificationOutcome(
                claim_id=claim.claim_id,
                outcome=SemanticOutcome.NUMERICAL_ERROR,
                decision=VerificationDecision.REJECT,
                citation_ids=claim.cited_citation_ids,
                evidence_ids=tuple(evidence_ids),
                reasons=("numeric evidence does not satisfy the bounded comparator",),
            )

    if support_count == 0:
        return ClaimVerificationOutcome(
            claim_id=claim.claim_id,
            outcome=SemanticOutcome.UNSUPPORTED,
            decision=VerificationDecision.REJECT,
            citation_ids=claim.cited_citation_ids,
            evidence_ids=tuple(evidence_ids),
            reasons=tuple(reasons) if reasons else ("no cited evidence explicitly supports the claim",),
        )

    support_fraction = support_count / len(records)
    if support_fraction >= calibration.minimum_support_fraction:
        return ClaimVerificationOutcome(
            claim_id=claim.claim_id,
            outcome=SemanticOutcome.SUPPORTED,
            decision=VerificationDecision.ACCEPT,
            citation_ids=claim.cited_citation_ids,
            evidence_ids=tuple(evidence_ids),
        )
    return ClaimVerificationOutcome(
        claim_id=claim.claim_id,
        outcome=SemanticOutcome.PARTIAL,
        decision=VerificationDecision.REJECT,
        citation_ids=claim.cited_citation_ids,
        evidence_ids=tuple(evidence_ids),
        reasons=(
            f"support fraction {support_fraction:.6f} is below calibrated threshold "
            f"{calibration.minimum_support_fraction:.6f}"
        ,),
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
