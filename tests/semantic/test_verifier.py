from __future__ import annotations

import importlib

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
    normalize_source_family,
    semantic_evidence_content_hash,
)
from poi_mpp.evidence.models import EvidenceOrigin


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


def _record(
    citation_id: str,
    *,
    source_family: str = "paper-a",
    origin: EvidenceOrigin = EvidenceOrigin.REAL_MODEL_EXECUTION,
    annotations: tuple[EvidenceAnnotation, ...] = (),
    numeric_facts: tuple[NumericFact, ...] = (),
    trusted_fields: bool = False,
) -> EvidenceRecord:
    text = f"evidence::{citation_id}"
    payload = {
        "evidence_id": f"evidence-{citation_id}",
        "citation_id": citation_id,
        "source_family": source_family,
        "origin": origin,
        "content": text,
        "content_hash": semantic_evidence_content_hash(
            citation_id=citation_id,
            content=text,
            source_family=source_family,
        ),
        "annotations": annotations,
        "numeric_facts": numeric_facts,
    }
    if trusted_fields:
        payload.update(
            {
                "label_authority": SemanticLabelAuthority.TRUSTED_GROUNDED_ANNOTATOR,
                "trusted_artifact_id": "artifact-stale",
                "trusted_provenance_hash": "a" * 64,
                "trusted_annotation_hash": "b" * 64,
            }
        )
    return EvidenceRecord.model_validate(payload)


def test_annotation_driven_support_abstains_without_registry_backed_capability():
    claim = _claim("claim-1", "cite-1")
    evidence = (
        _record(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="caller-supplied support",
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

    assert result.decision == "ABSTAIN"
    assert result.outcomes[0].outcome == "AMBIGUOUS"
    assert "registry-backed capability" in " ".join(result.outcomes[0].reasons)


def test_annotation_driven_contradiction_abstains_without_registry_backed_capability():
    claim = _claim("claim-1", "cite-1")
    evidence = (
        _record(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.CONTRADICTS,
                    reason="caller-supplied contradiction",
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


def test_annotation_driven_numeric_assertion_abstains_without_registry_backed_capability():
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
        _record(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="numeric claim support",
                ),
            ),
            numeric_facts=(
                NumericFact(
                    claim_id="claim-1",
                    metric="accuracy",
                    value="0.99",
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
        _record(
            "cite-1",
            annotations=(
                EvidenceAnnotation(
                    claim_id="claim-1",
                    kind=EvidenceAnnotationKind.SUPPORTS,
                    reason="first fragment",
                ),
            ),
        ),
        _record(
            "cite-1",
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


def test_unannotated_citation_is_unsupported():
    claim = _claim("claim-1", "cite-1")
    evidence = (_record("cite-1"),)

    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=evidence,
        calibration=_calibration(),
    )

    assert result.decision == "REJECT"
    assert result.outcomes[0].outcome == "UNSUPPORTED"


@pytest.mark.parametrize("constructor", ["constructor", "model_validate", "model_copy"])
def test_self_asserted_trusted_authority_is_downgraded_and_abstains(constructor: str):
    annotation = EvidenceAnnotation(
        claim_id="claim-1",
        kind=EvidenceAnnotationKind.SUPPORTS,
        reason="forged support",
    )
    base = _record("cite-1", annotations=(annotation,))
    payload = {
        "evidence_id": "evidence-cite-1",
        "citation_id": "cite-1",
        "source_family": "paper-a",
        "origin": EvidenceOrigin.REAL_MODEL_EXECUTION,
        "label_authority": SemanticLabelAuthority.TRUSTED_GROUNDED_ANNOTATOR,
        "trusted_artifact_id": "artifact-stale",
        "trusted_provenance_hash": "a" * 64,
        "trusted_annotation_hash": "b" * 64,
        "content": "evidence::cite-1",
        "content_hash": semantic_evidence_content_hash(
            citation_id="cite-1",
            content="evidence::cite-1",
            source_family="paper-a",
        ),
        "annotations": (annotation,),
        "numeric_facts": (),
    }
    if constructor == "constructor":
        record = EvidenceRecord(**payload)
    elif constructor == "model_validate":
        record = EvidenceRecord.model_validate(payload)
    else:
        record = base.model_copy(update=payload)

    assert record.label_authority is SemanticLabelAuthority.UNTRUSTED_CALLER
    assert record.trusted_artifact_id is None

    result = verify_grounded(
        response="claim::claim-1",
        claims=(_claim("claim-1", "cite-1"),),
        evidence=(record,),
        calibration=_calibration(),
    )

    assert result.decision == "ABSTAIN"
    assert result.outcomes[0].outcome == "AMBIGUOUS"


def test_model_construct_is_disabled_for_evidence_record():
    with pytest.raises(TypeError, match="model_construct is disabled"):
        EvidenceRecord.model_construct(
            evidence_id="evidence-cite-1",
            citation_id="cite-1",
            source_family="paper-a",
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
            content="evidence::cite-1",
            content_hash=semantic_evidence_content_hash(
                citation_id="cite-1",
                content="evidence::cite-1",
                source_family="paper-a",
            ),
        )


def test_private_issue_helper_is_absent_from_models_module():
    models = importlib.import_module("poi_mpp.auditor.semantic.models")
    assert not hasattr(models, "_issue_trusted_evidence")


def test_serialized_trust_bindings_cannot_be_reloaded_as_capability():
    original = _record(
        "cite-1",
        annotations=(
            EvidenceAnnotation(
                claim_id="claim-1",
                kind=EvidenceAnnotationKind.SUPPORTS,
                reason="serialized support",
            ),
        ),
        trusted_fields=True,
    )
    reloaded = EvidenceRecord.model_validate(original.model_dump(mode="json"))

    assert reloaded.label_authority is SemanticLabelAuthority.UNTRUSTED_CALLER
    assert reloaded.trusted_provenance_hash is None

    result = verify_grounded(
        response="claim::claim-1",
        claims=(_claim("claim-1", "cite-1"),),
        evidence=(reloaded,),
        calibration=_calibration(),
    )

    assert result.decision == "ABSTAIN"
    assert result.outcomes[0].outcome == "AMBIGUOUS"


def test_stale_registry_reference_fields_are_ignored_and_abstain():
    record = _record(
        "cite-1",
        annotations=(
            EvidenceAnnotation(
                claim_id="claim-1",
                kind=EvidenceAnnotationKind.SUPPORTS,
                reason="stale registry binding",
            ),
        ),
        trusted_fields=True,
    )

    assert record.label_authority is SemanticLabelAuthority.UNTRUSTED_CALLER
    assert record.trusted_artifact_id is None

    result = verify_grounded(
        response="claim::claim-1",
        claims=(_claim("claim-1", "cite-1"),),
        evidence=(record,),
        calibration=_calibration(),
    )

    assert result.decision == "ABSTAIN"


def test_synthetic_annotation_record_cannot_become_trusted_and_abstains():
    record = _record(
        "cite-1",
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        annotations=(
            EvidenceAnnotation(
                claim_id="claim-1",
                kind=EvidenceAnnotationKind.SUPPORTS,
                reason="synthetic support",
            ),
        ),
        trusted_fields=True,
    )

    assert record.label_authority is SemanticLabelAuthority.UNTRUSTED_CALLER

    result = verify_grounded(
        response="claim::claim-1",
        claims=(_claim("claim-1", "cite-1"),),
        evidence=(record,),
        calibration=_calibration(),
    )

    assert result.decision == "ABSTAIN"


def test_source_family_is_nfkc_casefold_normalized_before_hash_binding():
    composed = " Café-Paper "
    decomposed = "cafe\u0301-paper"
    normalized = normalize_source_family(composed)

    assert normalized == normalize_source_family(decomposed)
    assert normalized == "café-paper"
