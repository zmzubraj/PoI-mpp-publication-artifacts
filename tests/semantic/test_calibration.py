from __future__ import annotations

import pytest

from poi_mpp.auditor.semantic import (
    DevelopmentCalibrationExample,
    EvidenceAnnotation,
    EvidenceAnnotationKind,
    EvidenceRecord,
    GroundedClaim,
    SemanticCalibrationArtifact,
    SemanticLabelAuthority,
    VerificationMode,
    fit_development_calibration,
    verify_grounded,
)
from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import EvidenceOrigin


def _evidence(citation_id: str) -> EvidenceRecord:
    text = f"evidence::{citation_id}"
    return EvidenceRecord(
        evidence_id=f"evidence-{citation_id}",
        citation_id=citation_id,
        source_family="paper-a",
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        label_authority=SemanticLabelAuthority.TRUSTED_GROUNDED_ANNOTATOR,
        content=text,
        content_hash=digest(
            "SEMANTIC_EVIDENCE_CONTENT",
            {"citation_id": citation_id, "content": text, "source_family": "paper-a"},
        ),
        annotations=(
            EvidenceAnnotation(
                claim_id="claim-1",
                kind=EvidenceAnnotationKind.SUPPORTS,
                reason="supported by the citation",
            ),
        ),
    )


def test_development_calibration_is_frozen_and_tie_breaks_fail_closed():
    artifact = fit_development_calibration(
        (
            DevelopmentCalibrationExample(
                example_id="supported-half",
                supported_citations=1,
                total_citations=2,
                should_accept=False,
            ),
            DevelopmentCalibrationExample(
                example_id="supported-all",
                supported_citations=2,
                total_citations=2,
                should_accept=True,
            ),
        )
    )

    assert artifact.minimum_support_fraction == 1.0
    with pytest.raises(Exception):
        artifact.minimum_support_fraction = 0.5


def test_confirmatory_verification_uses_frozen_calibration_without_tuning():
    calibration = SemanticCalibrationArtifact.create(
        dataset_label="development-fixture",
        minimum_support_fraction=1.0,
        example_count=2,
    )
    claim = GroundedClaim(
        claim_id="claim-1",
        text="claim::claim-1",
        cited_citation_ids=("cite-1",),
    )
    result = verify_grounded(
        response="claim::claim-1",
        claims=(claim,),
        evidence=(_evidence("cite-1"),),
        calibration=calibration,
        mode=VerificationMode.CONFIRMATORY,
    )

    assert result.calibration_hash == calibration.content_hash
    assert calibration.minimum_support_fraction == 1.0
