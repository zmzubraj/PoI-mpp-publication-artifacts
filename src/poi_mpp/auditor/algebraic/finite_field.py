"""Exact Freivalds-style matrix audits over declared modular arithmetic."""

from __future__ import annotations

import math
import random
from typing import Any

from poi_mpp.auditor.reports import AssuranceClass, AuditDisposition, AuditResult
from poi_mpp.evidence.models import EvidenceOrigin

_MAX_MPP_FIELD_BITS = 31


def verify_freivalds_field(
    matrix_a: Any,
    matrix_b: Any,
    matrix_c: Any,
    *,
    rounds: int,
    seed: int,
    modulus: int,
    evidence_origin: EvidenceOrigin = EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
    declared_modulus_only: bool = False,
) -> AuditResult:
    """Verify ``matrix_c`` equals ``matrix_a @ matrix_b`` in exact modular arithmetic."""

    _validate_rounds(rounds)
    _validate_seed(seed)
    _validate_modulus(modulus, declared_modulus_only)
    left = _normalize_field_matrix(matrix_a, modulus)
    middle = _normalize_field_matrix(matrix_b, modulus)
    right = _normalize_field_matrix(matrix_c, modulus)
    dimensions = _validate_matmul_dimensions(left, middle, right)
    challenge_vectors = _generate_challenge_vectors(dimensions[2], rounds, seed)

    assurance = (
        AssuranceClass.DECLARED_MODULUS_ASSUMPTION
        if declared_modulus_only
        else AssuranceClass.EXACT_FIELD_SOUNDNESS
    )
    residual = (
        "declared modulus path relies on caller-declared exact modular semantics",
        "binary nonzero Freivalds challenges provide at most 2^-k error under declared exact arithmetic",
    )
    for challenge in challenge_vectors:
        lhs = _matvec_mod(right, challenge, modulus)
        rhs = _matvec_mod(left, _matvec_mod(middle, challenge, modulus), modulus)
        if lhs != rhs:
            return AuditResult(
                evidence_origin=evidence_origin,
                assurance_class=assurance,
                accepted=False,
                disposition=AuditDisposition.REJECTED,
                challenge_vectors=challenge_vectors,
                rounds=rounds,
                seed=seed,
                modulus=modulus,
                dimensions=dimensions,
                residual_risk=residual + ("field audit rejected the proposed product",),
                soundness_error_bound=None if declared_modulus_only else 2**-rounds,
            )
    return AuditResult(
        evidence_origin=evidence_origin,
        assurance_class=assurance,
        accepted=True,
        disposition=AuditDisposition.ACCEPTED,
        challenge_vectors=challenge_vectors,
        rounds=rounds,
        seed=seed,
        modulus=modulus,
        dimensions=dimensions,
        residual_risk=residual,
        soundness_error_bound=None if declared_modulus_only else 2**-rounds,
    )


def _validate_rounds(rounds: int) -> None:
    if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds <= 0:
        raise ValueError("rounds must be a positive integer")


def _validate_seed(seed: int) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")


def _validate_modulus(modulus: int, declared_modulus_only: bool) -> None:
    if isinstance(modulus, bool) or not isinstance(modulus, int) or modulus <= 1:
        raise ValueError("modulus must be an integer greater than 1")
    if modulus.bit_length() > _MAX_MPP_FIELD_BITS:
        raise ValueError(
            f"modulus exceeds the {_MAX_MPP_FIELD_BITS}-bit MPP field limit"
        )
    if not declared_modulus_only and not _is_prime(modulus):
        raise ValueError("prime modulus required unless declared_modulus_only=True")


def _is_prime(value: int) -> bool:
    if value <= 1:
        return False
    if value <= 3:
        return True
    if value % 2 == 0:
        return False
    limit = math.isqrt(value)
    factor = 3
    while factor <= limit:
        if value % factor == 0:
            return False
        factor += 2
    return True


def _normalize_field_matrix(value: Any, modulus: int) -> tuple[tuple[int, ...], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("field matrices must be rectangular")
    rows: list[tuple[int, ...]] = []
    width: int | None = None
    for row in value:
        if not isinstance(row, (list, tuple)):
            raise ValueError("field matrices must be rectangular")
        normalized_row: list[int] = []
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, int) or cell < 0 or cell >= modulus:
                raise ValueError("field entries must be integers in [0, modulus)")
            normalized_row.append(cell)
        if width is None:
            width = len(normalized_row)
            if width == 0:
                raise ValueError("field matrices must not contain empty rows")
        elif len(normalized_row) != width:
            raise ValueError("field matrices must be rectangular")
        rows.append(tuple(normalized_row))
    if not rows:
        raise ValueError("field matrices must not be empty")
    return tuple(rows)


def _validate_matmul_dimensions(
    matrix_a: tuple[tuple[int, ...], ...],
    matrix_b: tuple[tuple[int, ...], ...],
    matrix_c: tuple[tuple[int, ...], ...],
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


def _matvec_mod(
    matrix: tuple[tuple[int, ...], ...],
    vector: tuple[int, ...],
    modulus: int,
) -> tuple[int, ...]:
    result: list[int] = []
    for row in matrix:
        total = 0
        for value, challenge in zip(row, vector, strict=True):
            total = (total + (value * challenge)) % modulus
        result.append(total)
    return tuple(result)
