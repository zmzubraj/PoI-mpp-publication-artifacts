"""Fail-closed exact equality audits for matrices, bytes, and hashes."""

from __future__ import annotations

import re
from typing import Any

from poi_mpp.auditor.reports import AssuranceClass, AuditDisposition, AuditResult
from poi_mpp.evidence.models import EvidenceOrigin

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def verify_exact(
    expected: Any,
    observed: Any,
    *,
    evidence_origin: EvidenceOrigin = EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
) -> AuditResult:
    """Compare canonical exact values without coercion or tolerance."""

    try:
        expected_kind, expected_value, dimensions = _normalize_exact_value(expected)
        observed_kind, observed_value, observed_dimensions = _normalize_exact_value(observed)
    except ValueError as exc:
        return AuditResult(
            evidence_origin=evidence_origin,
            assurance_class=AssuranceClass.EXACT_MATCH,
            accepted=False,
            disposition=AuditDisposition.INVALID_INPUT,
            dimensions=(),
            residual_risk=(str(exc),),
        )

    if expected_kind != observed_kind:
        return AuditResult(
            evidence_origin=evidence_origin,
            assurance_class=AssuranceClass.EXACT_MATCH,
            accepted=False,
            disposition=AuditDisposition.INVALID_INPUT,
            dimensions=dimensions,
            residual_risk=("exact comparison requires matching canonical input kinds",),
        )
    if dimensions != observed_dimensions:
        return AuditResult(
            evidence_origin=evidence_origin,
            assurance_class=AssuranceClass.EXACT_MATCH,
            accepted=False,
            disposition=AuditDisposition.INVALID_INPUT,
            dimensions=dimensions,
            residual_risk=("exact comparison requires matching canonical dimensions",),
        )
    if expected_value != observed_value:
        return AuditResult(
            evidence_origin=evidence_origin,
            assurance_class=AssuranceClass.EXACT_MATCH,
            accepted=False,
            disposition=AuditDisposition.REJECTED,
            dimensions=dimensions,
            residual_risk=("exact mismatch observed; reject and inspect corruption or serialization drift",),
        )
    return AuditResult(
        evidence_origin=evidence_origin,
        assurance_class=AssuranceClass.EXACT_MATCH,
        accepted=True,
        disposition=AuditDisposition.ACCEPTED,
        dimensions=dimensions,
        residual_risk=("exact equality only; no tolerance or probabilistic bound applies",),
    )


def _normalize_exact_value(value: Any) -> tuple[str, Any, tuple[int, ...]]:
    if isinstance(value, bytes):
        return "bytes", value, (len(value),)
    if isinstance(value, str):
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("hash inputs must be lowercase SHA-256 hex digests")
        return "hash", value, (64,)
    if isinstance(value, (list, tuple)):
        matrix = _normalize_exact_matrix(value)
        return "matrix", matrix, (len(matrix), len(matrix[0]) if matrix else 0)
    if isinstance(value, int) and not isinstance(value, bool):
        return "int", value, (1,)
    raise ValueError("exact audit inputs must be bytes, lowercase SHA-256 digests, integers, or integer matrices")


def _normalize_exact_matrix(value: list[Any] | tuple[Any, ...]) -> tuple[tuple[int, ...], ...]:
    rows: list[tuple[int, ...]] = []
    width: int | None = None
    for row in value:
        if not isinstance(row, (list, tuple)):
            raise ValueError("exact matrix inputs must be rectangular integer matrices")
        normalized_row: list[int] = []
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, int):
                raise ValueError("exact matrix inputs must be rectangular integer matrices")
            normalized_row.append(cell)
        if width is None:
            width = len(normalized_row)
            if width == 0:
                raise ValueError("exact matrix inputs must not have empty rows")
        elif len(normalized_row) != width:
            raise ValueError("exact matrix inputs must be rectangular integer matrices")
        rows.append(tuple(normalized_row))
    if not rows:
        raise ValueError("exact matrix inputs must not be empty")
    return tuple(rows)
