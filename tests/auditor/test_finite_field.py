import pytest

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.auditor import verify_freivalds_field


def test_field_audit_rejects_wrong_product():
    matrix_a = ((1, 2), (3, 4))
    matrix_b = ((5, 6), (7, 8))
    wrong_product = ((19, 22), (43, 51))

    result = verify_freivalds_field(
        matrix_a,
        matrix_b,
        wrong_product,
        rounds=8,
        seed=7,
        modulus=2_147_483_647,
        evidence_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
    )

    assert result.accepted is False
    assert result.disposition == "REJECTED"
    assert result.assurance_class == "EXACT_FIELD_SOUNDNESS"
    assert result.soundness_error_bound == 2**-8
    assert len(result.challenge_vectors) == 8
    assert all(any(bit == 1 for bit in challenge) for challenge in result.challenge_vectors)


def test_field_audit_is_deterministic_and_records_dimensions():
    matrix_a = ((1, 2), (3, 4))
    matrix_b = ((5, 6), (7, 8))
    exact_product = ((19, 22), (43, 50))

    left = verify_freivalds_field(
        matrix_a,
        matrix_b,
        exact_product,
        rounds=4,
        seed=11,
        modulus=2_147_483_647,
        evidence_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    )
    right = verify_freivalds_field(
        matrix_a,
        matrix_b,
        exact_product,
        rounds=4,
        seed=11,
        modulus=2_147_483_647,
        evidence_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    )

    assert left.accepted is True
    assert left.challenge_vectors == right.challenge_vectors
    assert left.dimensions == (2, 2, 2)
    assert left.soundness_error_bound == 2**-4


def test_field_audit_rejects_invalid_rounds_and_non_prime_modulus_without_declaration():
    matrix_a = ((1, 2), (3, 4))
    matrix_b = ((5, 6), (7, 8))
    exact_product = ((19, 22), (43, 50))

    with pytest.raises(ValueError, match="rounds must be a positive integer"):
        verify_freivalds_field(
            matrix_a,
            matrix_b,
            exact_product,
            rounds=0,
            seed=3,
            modulus=2_147_483_647,
        )

    with pytest.raises(ValueError, match="prime modulus required"):
        verify_freivalds_field(
            matrix_a,
            matrix_b,
            exact_product,
            rounds=2,
            seed=3,
            modulus=15,
        )


def test_field_audit_allows_declared_non_prime_modulus_with_bounded_residual_risk():
    matrix_a = ((1, 2), (3, 4))
    matrix_b = ((5, 6), (7, 8))
    exact_product = ((4, 7), (13, 5))

    result = verify_freivalds_field(
        matrix_a,
        matrix_b,
        exact_product,
        rounds=2,
        seed=3,
        modulus=15,
        declared_modulus_only=True,
    )

    assert result.accepted is True
    assert result.assurance_class == "DECLARED_MODULUS_ASSUMPTION"
    assert "declared modulus" in " ".join(result.residual_risk).lower()


@pytest.mark.parametrize(
    "matrix_a",
    [
        ((-1, 2), (3, 4)),
        ((1, 2.5), (3, 4)),
        ((1, 2), (3, 2_147_483_647)),
    ],
)
def test_field_audit_rejects_negative_noninteger_and_oversized_values(matrix_a):
    matrix_b = ((5, 6), (7, 8))
    exact_product = ((19, 22), (43, 50))

    with pytest.raises(ValueError, match="field entries must be integers in \\[0, modulus\\)"):
        verify_freivalds_field(
            matrix_a,
            matrix_b,
            exact_product,
            rounds=2,
            seed=3,
            modulus=2_147_483_647,
        )
