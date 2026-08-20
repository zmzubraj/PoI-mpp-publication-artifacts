from __future__ import annotations

import pytest

from poi_mpp.auditor.semantic import (
    EvidenceAnnotation,
    EvidenceAnnotationKind,
    EvidenceRecord,
    GroundedClaim,
    NumericExpectation,
    NumericFact,
    SemanticCalibrationArtifact,
    SemanticLabelAuthority,
    VerificationMode,
    verify_grounded,
)
from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import EvidenceOrigin


def _evidence(
    citation_id: str,
    *,
    evidence_id: str | None = None,
    source_family: str = "paper-a",
    annotations: tuple[EvidenceAnnotation, ...] = (),
    numeric_facts: tuple[NumericFact, ...] = (),
) -> EvidenceRecord:
    text = f"evidence::{citation_id}"
    return EvidenceRecord(
        evidence_id=evidence_id or f"evidence-{citation_id}",
        citation_id=citation_id,
        source_family=source_family,
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        label_authority=SemanticLabelAuthority.TRUSTED_GROUNDED_ANNOTATOR,
        content=text,
        content_hash=digest(
            "SEMANTIC_EVIDENCE_CONTENT",
            {"citation_id": citation_id, "content": text, "source_family": source_family},
        ),
        annotations=annotations,
        numeric_facts=numeric_facts,
    )


def _claim(
    claim_id: str,
    *citations: str,
    numeric_expectation: NumericExpectation | None = None,
) -> GroundedClaim:
    return GroundedClaim(
        claim_id=claim_id,
        text=f"claim::{claim_id}",
        cited_citation_ids=citations,
        numeric_expectation=numeric_expectation,
    )


def _calibration(*, threshold: float = 1.0) -> SemanticCalibrationArtifact:
    return SemanticCalibrationArtifact.create(
        dataset_label="development-fixture",
        minimum_support_fraction=threshold,
        example_count=3,
    )


def test_supported_claim_accepts_with_exact_citation_resolution():
    claim = _claim("claim-1", "cite-1")
    evidence = (
        _evidence(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="supported by the cited source",
                ),
            ),
        ),
    )

    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=evidence,
        calibration=_calibration(),
        mode=VerificationMode.CONFIRMATORY,
    )

    assert result.decision == "ACCEPT"
    assert result.outcomes[0].outcome == "SUPPORTED"
    assert result.outcomes[0].citation_ids == ("cite-1",)


def test_ambiguous_evidence_abstains():
    claim = _claim("claim-1", "cite-1")
    evidence = (
        _evidence(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="one table appears to support the claim",
                ),
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.CONTRADICTS,
                    reason="another table contradicts the claim",
                ),
            ),
        ),
    )

    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=evidence,
        calibration=_calibration(),
    )

    assert result.decision == "ABSTAIN"
    assert result.outcomes[0].outcome == "AMBIGUOUS"


def test_missing_citation_rejects_with_citation_error():
    claim = _claim("claim-1", "cite-1")

    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=(),
        calibration=_calibration(),
    )

    assert result.decision == "REJECT"
    assert result.outcomes[0].outcome == "CITATION_ERROR"
    assert "missing citation" in " ".join(result.outcomes[0].reasons).lower()


def test_duplicate_citation_ids_fail_closed():
    claim = _claim("claim-1", "cite-1")
    evidence = (
        _evidence(
            "cite-1",
            evidence_id="evidence-a",
            annotations=(
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="first fragment",
                ),
            ),
        ),
        _evidence(
            "cite-1",
            evidence_id="evidence-b",
            annotations=(
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="second fragment",
                ),
            ),
        ),
    )

    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=evidence,
        calibration=_calibration(),
    )

    assert result.decision == "REJECT"
    assert result.outcomes[0].outcome == "CITATION_ERROR"
    assert "duplicate citation" in " ".join(result.outcomes[0].reasons).lower()


def test_partial_support_rejects_when_calibration_requires_full_coverage():
    claim = _claim("claim-1", "cite-1", "cite-2")
    evidence = (
        _evidence(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="first citation supports the claim",
                ),
            ),
        ),
        _evidence("cite-2"),
    )

    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=evidence,
        calibration=_calibration(threshold=1.0),
    )

    assert result.decision == "REJECT"
    assert result.outcomes[0].outcome == "PARTIAL"


def test_explicit_contradiction_rejects():
    claim = _claim("claim-1", "cite-1")
    evidence = (
        _evidence(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.CONTRADICTS,
                    reason="the cited result reports the opposite finding",
                ),
            ),
        ),
    )

    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=evidence,
        calibration=_calibration(),
    )

    assert result.decision == "REJECT"
    assert result.outcomes[0].outcome == "CONTRADICTORY"


def test_numeric_mismatch_rejects_with_numerical_error():
    claim = _claim(
        "claim-1",
        "cite-1",
        numeric_expectation=NumericExpectation(
            metric="accuracy",
            comparator="AT_LEAST",
            value="0.95",
            unit="ratio",
        ),
    )
    evidence = (
        _evidence(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="the citation reports a numeric result",
                ),
            ),
            numeric_facts=(
                NumericFact(
                    claim_id="claim-1",
                    metric="accuracy",
                    value="0.91",
                    unit="ratio",
                ),
            ),
        ),
    )

    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=evidence,
        calibration=_calibration(),
    )

    assert result.decision == "REJECT"
    assert result.outcomes[0].outcome == "NUMERICAL_ERROR"


def test_unannotated_citation_is_unsupported():
    claim = _claim("claim-1", "cite-1")
    evidence = (_evidence("cite-1"),)

    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=evidence,
        calibration=_calibration(),
    )

    assert result.decision == "REJECT"
    assert result.outcomes[0].outcome == "UNSUPPORTED"


def test_untrusted_caller_annotations_are_rejected_before_semantic_acceptance():
    claim = _claim("claim-1", "cite-1")
    text = "Totally unrelated text that does not support the claim."

    with pytest.raises(ValueError, match="trusted label authority"):
        verify_grounded(
            response="claim::claim-1",
            claims=(claim,),
            evidence=(
                EvidenceRecord(
                    evidence_id="evidence-cite-1",
                    citation_id="cite-1",
                    source_family="paper-a",
                    origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
                    label_authority=SemanticLabelAuthority.UNTRUSTED_CALLER,
                    content=text,
                    content_hash=digest(
                        "SEMANTIC_EVIDENCE_CONTENT",
                        {"citation_id": "cite-1", "content": text, "source_family": "paper-a"},
                    ),
                    annotations=(
                        EvidenceAnnotation(
                            claim_id="claim-1",
                            kind=EvidenceAnnotationKind.SUPPORTS,
                            reason="caller supplied support",
                        ),
                    ),
                ),
            ),
            calibration=_calibration(),
        )
