from __future__ import annotations

import pytest

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.worker.iec_builder import build_iec
from poi_mpp.worker.iec_schema import EvidenceItem


@pytest.fixture()
def evidence_items() -> tuple[EvidenceItem, ...]:
    return (
        EvidenceItem(
            evidence_id="E-001",
            artifact_label="snippet-1",
            content="The sample answer is supported by citation one.",
            keywords=("sample", "citation"),
            origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        ),
    )


def test_iec_does_not_contain_private_reasoning(evidence_items: tuple[EvidenceItem, ...]) -> None:
    iec = build_iec(
        response="Sample answer. Citation one supports it.",
        evidence_items=evidence_items,
        task_requirements=("state one support",),
    )
    assert "chain_of_thought" not in iec.model_dump()


def test_evidence_item_rejects_nonfinite_confidence() -> None:
    with pytest.raises(ValueError, match="finite"):
        EvidenceItem(
            evidence_id="E-002",
            artifact_label="snippet-2",
            content="NaN confidence is not allowed.",
            keywords=("nan",),
            origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
            confidence=float("nan"),
        )


def test_iec_rejects_explicit_empty_claim_texts(
    evidence_items: tuple[EvidenceItem, ...],
) -> None:
    with pytest.raises(ValueError, match="claim_texts"):
        build_iec(
            response="Sample answer. Citation one supports it.",
            evidence_items=evidence_items,
            claim_texts=(),
        )
