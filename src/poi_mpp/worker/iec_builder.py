"""Deterministic IEC construction without private reasoning capture."""

from __future__ import annotations

import re

from poi_mpp.worker.iec_schema import ClaimNode, EvidenceItem, IntelligenceEvidenceCapsule
from poi_mpp.worker.model_manifest import bytes32_word


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_claims(response: str) -> tuple[str, ...]:
    claims = tuple(sentence.strip() for sentence in _SENTENCE_SPLIT.split(response.strip()) if sentence.strip())
    return claims or (response.strip(),)


def _claim_evidence_ids(claim_text: str, evidence_items: tuple[EvidenceItem, ...]) -> tuple[str, ...]:
    lowered = claim_text.lower()
    matched = [
        item.evidence_id
        for item in evidence_items
        if any(keyword.lower() in lowered for keyword in item.keywords)
    ]
    return tuple(sorted(set(matched)))


def build_iec(
    *,
    response: str,
    evidence_items: tuple[EvidenceItem, ...],
    task_requirements: tuple[str, ...] = (),
    response_hash: str | None = None,
    claim_texts: tuple[str, ...] | None = None,
) -> IntelligenceEvidenceCapsule:
    claims_source = claim_texts if claim_texts is not None else _split_claims(response)
    claims = tuple(
        ClaimNode(
            claim_id=f"CLAIM-{index:04d}",
            text=text,
            evidence_ids=_claim_evidence_ids(text, evidence_items),
        )
        for index, text in enumerate(claims_source)
    )
    resolved_response_hash = response_hash or bytes32_word("WORKER_RESPONSE_TEXT", {"response": response})
    evidence_root = bytes32_word(
        "WORKER_IEC_ROOT",
        {
            "response_hash": resolved_response_hash,
            "claims": [claim.model_dump(mode="json") for claim in claims],
            "evidence_items": [item.model_dump(mode="json") for item in evidence_items],
            "task_requirements": list(task_requirements),
        },
    )
    return IntelligenceEvidenceCapsule(
        response_hash=resolved_response_hash,
        claims=claims,
        evidence_items=evidence_items,
        task_requirements=task_requirements,
        evidence_root=evidence_root,
    )
