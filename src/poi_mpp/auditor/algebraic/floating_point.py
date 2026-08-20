"""Empirical floating-point Freivalds checks with explicit tolerance reporting."""

from __future__ import annotations

import math
import random
from typing import Any

from poi_mpp.auditor.reports import AssuranceClass, AuditDisposition, AuditResult
from poi_mpp.evidence.models import EvidenceOrigin


def verify_freivalds_float(
    matrix_a: Any,
    matrix_b: Any,
    matrix_c: Any,
    *,
    rounds: int,
    seed: int,
    atol: float,
    rtol: float,
    evidence_origin: EvidenceOrigin = EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
) -> AuditResult:
    """Empirically verify floating-point matrix multiplication under tolerances."""

    _validate_rounds(rounds)
    _validate_seed(seed)
    _validate_tolerances(atol, rtol)
    left = _normalize_float_matrix(matrix_a)
    middle = _normalize_float_matrix(matrix_b)
    right = _normalize_float_matrix(matrix_c)
    dimensions = _validate_matmul_dimensions(left, middle, right)
    challenge_vectors = _generate_challenge_vectors(dimensions[2], rounds, seed)
    expected_product = _matmul_float(left, middle)
    max_abs_error, max_rel_error = _error_metrics(expected_product, right)

    for challenge in challenge_vectors:
        lhs = _matvec_float(right, challenge)
        rhs = _matvec_float(left, _matvec_float(middle, challenge))
        if not _vectors_close(lhs, rhs, atol, rtol):
            return AuditResult(
                evidence_origin=evidence_origin,
                assurance_class=AssuranceClass.EMPIRICAL_FLOAT_APPROXIMATION,
                accepted=False,
                disposition=AuditDisposition.REJECTED,
                challenge_vectors=challenge_vectors,
                rounds=rounds,
                seed=seed,
                atol=atol,
                rtol=rtol,
                dimensions=dimensions,
                residual_risk=(
                    "empirical floating-point audit rejected the proposed product",
                    "floating-point checks do not provide exact field soundness",
                ),
                max_abs_error=max_abs_error,
                max_rel_error=max_rel_error,
            )
    return AuditResult(
        evidence_origin=evidence_origin,
        assurance_class=AssuranceClass.EMPIRICAL_FLOAT_APPROXIMATION,
        accepted=True,
        disposition=AuditDisposition.ACCEPTED,
        challenge_vectors=challenge_vectors,
        rounds=rounds,
        seed=seed,
        atol=atol,
        rtol=rtol,
        dimensions=dimensions,
        residual_risk=(
            "empirical floating-point tolerance check only; no exact soundness guarantee",
        ),
        max_abs_error=max_abs_error,
        max_rel_error=max_rel_error,
    )


def _validate_rounds(rounds: int) -> None:
    if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds <= 0:
        raise ValueError("rounds must be a positive integer")


def _validate_seed(seed: int) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")


def _validate_tolerances(atol: float, rtol: float) -> None:
    if not math.isfinite(atol) or not math.isfinite(rtol) or atol < 0 or rtol < 0:
        raise ValueError("atol and rtol must be finite and non-negative")


def _normalize_float_matrix(value: Any) -> tuple[tuple[float, ...], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("floating-point matrices must be rectangular")
    rows: list[tuple[float, ...]] = []
    width: int | None = None
    for row in value:
        if not isinstance(row, (list, tuple)):
            raise ValueError("floating-point matrices must be rectangular")
        normalized_row: list[float] = []
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, (int, float)):
                raise ValueError("floating-point matrices must contain numeric entries")
            numeric = float(cell)
            if not math.isfinite(numeric):
                raise ValueError("floating-point matrices must contain only finite values")
            normalized_row.append(numeric)
        if width is None:
            width = len(normalized_row)
            if width == 0:
                raise ValueError("floating-point matrices must not contain empty rows")
        elif len(normalized_row) != width:
            raise ValueError("floating-point matrices must be rectangular")
        rows.append(tuple(normalized_row))
    if not rows:
        raise ValueError("floating-point matrices must not be empty")
    return tuple(rows)


def _validate_matmul_dimensions(
    matrix_a: tuple[tuple[float, ...], ...],
    matrix_b: tuple[tuple[float, ...], ...],
    matrix_c: tuple[tuple[float, ...], ...],
) -> tuple[int, int, int]:
    rows_a = len(matrix_a)
    cols_a = len(matrix_a[0])
    rows_b = len(matrix_b)
    cols_b = len(matrix_b[0])
    rows_c = len(matrix_c)
    cols_c = len(matrix_c[0])
    if cols_a != rows_b or rows_c != rows_a or cols_c != cols_b:
        raise ValueError("matrix dimensions do not align")
    return rows_a, cols_a, cols_b


def _generate_challenge_vectors(length: int, rounds: int, seed: int) -> tuple[tuple[int, ...], ...]:
    rng = random.Random(seed)
    vectors: list[tuple[int, ...]] = []
    for _ in range(rounds):
        challenge = tuple(rng.randint(0, 1) for _ in range(length))
        while not any(challenge):
            challenge = tuple(rng.randint(0, 1) for _ in range(length))
        vectors.append(challenge)
    return tuple(vectors)


def _matmul_float(
    matrix_a: tuple[tuple[float, ...], ...],
    matrix_b: tuple[tuple[float, ...], ...],
) -> tuple[tuple[float, ...], ...]:
    transpose_b = tuple(zip(*matrix_b, strict=True))
    rows: list[tuple[float, ...]] = []
    for row in matrix_a:
        current_row: list[float] = []
        for column in transpose_b:
            products = []
            for left, right in zip(row, column, strict=True):
                product = left * right
                if not math.isfinite(product):
                    raise ValueError("non-finite intermediate during floating-point multiplication")
                products.append(product)
            total = math.fsum(products)
            if not math.isfinite(total):
                raise ValueError("non-finite intermediate during floating-point accumulation")
            current_row.append(total)
        rows.append(tuple(current_row))
    return tuple(rows)


def _matvec_float(
    matrix: tuple[tuple[float, ...], ...],
    vector: tuple[int, ...] | tuple[float, ...],
) -> tuple[float, ...]:
    result: list[float] = []
    for row in matrix:
        products = []
        for value, challenge in zip(row, vector, strict=True):
            product = value * float(challenge)
            if not math.isfinite(product):
                raise ValueError("non-finite intermediate during floating-point multiplication")
            products.append(product)
        total = math.fsum(products)
        if not math.isfinite(total):
            raise ValueError("non-finite intermediate during floating-point accumulation")
        result.append(total)
    return tuple(result)


def _vectors_close(
    left: tuple[float, ...],
    right: tuple[float, ...],
    atol: float,
    rtol: float,
) -> bool:
    for observed, expected in zip(left, right, strict=True):
        if abs(observed - expected) > atol + (rtol * abs(expected)):
            return False
    return True


def _error_metrics(
    expected: tuple[tuple[float, ...], ...],
    observed: tuple[tuple[float, ...], ...],
) -> tuple[float, float]:
    max_abs_error = 0.0
    max_rel_error = 0.0
    for expected_row, observed_row in zip(expected, observed, strict=True):
        for expected_value, observed_value in zip(expected_row, observed_row, strict=True):
            abs_error = abs(expected_value - observed_value)
            max_abs_error = max(max_abs_error, abs_error)
            denominator = abs(expected_value)
            rel_error = 0.0 if denominator == 0.0 and abs_error == 0.0 else (
                float("inf") if denominator == 0.0 else abs_error / denominator
            )
            max_rel_error = max(max_rel_error, rel_error)
    if not math.isfinite(max_rel_error):
        raise ValueError("non-finite intermediate during floating-point error analysis")
    return max_abs_error, max_rel_error
