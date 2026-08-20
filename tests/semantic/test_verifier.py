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
from poi_mpp.auditor.semantic.models import (
    _issue_trusted_evidence,
    normalize_source_family,
    semantic_annotation_payload_hash,
    semantic_evidence_content_hash,
)
from poi_mpp.evidence.models import ArtifactRecord, ArtifactStage, EvidenceOrigin, RunManifest


def _provenance(origin: EvidenceOrigin) -> RunManifest:
    return RunManifest(
        run_id="run-1",
        experiment_id="experiment-1",
        config_hash="a" * 64,
        environment_hash="b" * 64,
        code_revision="c" * 40,
        origin=origin,
        authorization_scope="semantic-fixture",
    )


def _trusted_artifact(
    *,
    evidence_id: str,
    citation_id: str,
    source_family: str,
    content: str,
    origin: EvidenceOrigin = EvidenceOrigin.REAL_MODEL_EXECUTION,
    annotations: tuple[EvidenceAnnotation, ...] = (),
    numeric_facts: tuple[NumericFact, ...] = (),
) -> ArtifactRecord:
    annotation_hash = semantic_annotation_payload_hash(
        evidence_id=evidence_id,
        citation_id=citation_id,
        source_family=source_family,
        annotations=annotations,
        numeric_facts=numeric_facts,
    )
    record = ArtifactRecord(
        artifact_id=f"artifact-{evidence_id}",
        run_id="run-1",
        experiment_id="experiment-1",
        origin=origin,
        stage=ArtifactStage.GENERATED,
        content_hash=semantic_evidence_content_hash(
            citation_id=citation_id,
            content=content,
            source_family=source_family,
        ),
        parent_hashes=(annotation_hash,),
    )
    return (
        record.advance_to(ArtifactStage.SCHEMA_VALID)
        .advance_to(ArtifactStage.SEMANTICALLY_VALID)
        .advance_to(ArtifactStage.FROZEN)
    )


def _evidence(
    citation_id: str,
    *,
    evidence_id: str | None = None,
    source_family: str = "paper-a",
    annotations: tuple[EvidenceAnnotation, ...] = (),
    numeric_facts: tuple[NumericFact, ...] = (),
) -> EvidenceRecord:
    text = f"evidence::{citation_id}"
    trusted_evidence_id = evidence_id or f"evidence-{citation_id}"
    return _issue_trusted_evidence(
        artifact=_trusted_artifact(
            evidence_id=trusted_evidence_id,
            citation_id=citation_id,
            source_family=source_family,
            content=text,
            annotations=annotations,
            numeric_facts=numeric_facts,
        ),
        provenance=_provenance(EvidenceOrigin.REAL_MODEL_EXECUTION),
        evidence_id=trusted_evidence_id,
        citation_id=citation_id,
        source_family=source_family,
        content=text,
        annotations=annotations,
        numeric_facts=numeric_facts,
    )


def _self_asserted_record(
    *,
    constructor: str,
    citation_id: str = "cite-1",
    source_family: str = "paper-a",
    annotations: tuple[EvidenceAnnotation, ...],
    numeric_facts: tuple[NumericFact, ...] = (),
) -> EvidenceRecord:
    text = f"evidence::{citation_id}"
    payload = {
        "evidence_id": f"evidence-{citation_id}",
        "citation_id": citation_id,
        "source_family": source_family,
        "origin": EvidenceOrigin.REAL_MODEL_EXECUTION,
        "label_authority": SemanticLabelAuthority.TRUSTED_GROUNDED_ANNOTATOR,
        "trusted_artifact_id": "artifact-forged",
        "trusted_provenance_hash": "a" * 64,
        "trusted_annotation_hash": "b" * 64,
        "content": text,
        "content_hash": semantic_evidence_content_hash(
            citation_id=citation_id,
            content=text,
            source_family=source_family,
        ),
        "annotations": annotations,
        "numeric_facts": numeric_facts,
    }
    if constructor == "constructor":
        return EvidenceRecord(**payload)
    if constructor == "model_validate":
        return EvidenceRecord.model_validate(payload)
    if constructor == "model_copy":
        base = EvidenceRecord(
            evidence_id=f"evidence-{citation_id}",
            citation_id=citation_id,
            source_family=source_family,
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
            content=text,
            content_hash=semantic_evidence_content_hash(
                citation_id=citation_id,
                content=text,
                source_family=source_family,
            ),
            annotations=annotations,
            numeric_facts=numeric_facts,
        )
        return base.model_copy(update=payload)
    raise AssertionError(f"unknown constructor mode: {constructor}")


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
    assert evidence[0].label_authority is SemanticLabelAuthority.TRUSTED_GROUNDED_ANNOTATOR
    assert evidence[0].trusted_artifact_id == "artifact-evidence-cite-1"


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


@pytest.mark.parametrize("constructor", ["constructor", "model_validate", "model_copy"])
def test_self_asserted_trusted_authority_is_blocked_without_verified_issue_path(constructor: str):
    claim = _claim("claim-1", "cite-1")
    record = _self_asserted_record(
        constructor=constructor,
        annotations=(
            EvidenceAnnotation(
                claim_id="claim-1",
                kind=EvidenceAnnotationKind.SUPPORTS,
                reason="caller supplied support",
            ),
        ),
    )

    assert record.label_authority is SemanticLabelAuthority.UNTRUSTED_CALLER
    assert record.trusted_artifact_id is None
    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=(record,),
        calibration=_calibration(),
    )

    assert result.decision == "ABSTAIN"
    assert result.outcomes[0].outcome == "AMBIGUOUS"
    assert "trusted semantic label authority not verified" in " ".join(
        result.outcomes[0].reasons
    ).lower()


def test_public_reload_of_trusted_record_downgrades_to_untrusted():
    claim = _claim("claim-1", "cite-1")
    trusted = _evidence(
        "cite-1",
        annotations=(
            EvidenceAnnotation(
                claim_id="claim-1",
                kind=EvidenceAnnotationKind.SUPPORTS,
                reason="verified support",
            ),
        ),
    )
    reloaded = EvidenceRecord.model_validate(trusted.model_dump(mode="json"))

    assert reloaded.label_authority is SemanticLabelAuthority.UNTRUSTED_CALLER
    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=(reloaded,),
        calibration=_calibration(),
    )

    assert result.decision == "ABSTAIN"
    assert result.outcomes[0].outcome == "AMBIGUOUS"


def test_trusted_issue_path_rejects_synthetic_publication_evidence():
    support = (
        EvidenceAnnotation(
            claim_id="claim-1",
            kind=EvidenceAnnotationKind.SUPPORTS,
            reason="synthetic support",
        ),
    )
    with pytest.raises(
        ValueError,
        match="synthetic evidence cannot be frozen or publication eligible|non-synthetic publication evidence origin",
    ):
        _issue_trusted_evidence(
            artifact=_trusted_artifact(
                evidence_id="evidence-cite-1",
                citation_id="cite-1",
                source_family="paper-a",
                content="evidence::cite-1",
                origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                annotations=support,
            ),
            provenance=_provenance(EvidenceOrigin.SYNTHETIC_NON_EVIDENCE),
            evidence_id="evidence-cite-1",
            citation_id="cite-1",
            source_family="paper-a",
            content="evidence::cite-1",
            annotations=support,
        )


def test_source_family_is_nfkc_casefold_normalized_before_hash_binding():
    composed = " Café-Paper "
    decomposed = "cafe\u0301-paper"
    normalized = normalize_source_family(composed)

    assert normalized == normalize_source_family(decomposed)
    assert normalized == "café-paper"
