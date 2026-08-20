import pytest

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.auditor import verify_exact


def test_exact_matrix_audit_accepts_matching_outputs_and_preserves_origin():
    expected = ((19, 22), (43, 50))
    observed = ((19, 22), (43, 50))

    result = verify_exact(
        expected,
        observed,
        evidence_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
    )

    assert result.accepted is True
    assert result.disposition == "ACCEPTED"
    assert result.assurance_class == "EXACT_MATCH"
    assert result.evidence_origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE
    assert result.dimensions == (2, 2)
    assert result.challenge_vectors == ()
    assert result.rounds == 0


def test_exact_matrix_audit_rejects_corruption():
    expected = ((19, 22), (43, 50))
    observed = ((19, 22), (43, 51))

    result = verify_exact(
        expected,
        observed,
        evidence_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    )

    assert result.accepted is False
    assert result.disposition == "REJECTED"
    assert "exact mismatch" in " ".join(result.residual_risk).lower()


def test_exact_hash_check_fails_closed_on_malformed_hash():
    result = verify_exact(
        "A" * 64,
        "a" * 64,
        evidence_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    )

    assert result.accepted is False
    assert result.disposition == "INVALID_INPUT"
    assert "lowercase sha-256" in " ".join(result.residual_risk).lower()


@pytest.mark.parametrize(
    ("expected", "observed"),
    [
        (((1, 2),), ((1, 2, 3),)),
        (((1.0, 2.0),), ((1.0, 2.0),)),
        (((True, False),), ((True, False),)),
    ],
)
def test_exact_audit_rejects_noncanonical_inputs(expected, observed):
    result = verify_exact(
        expected,
        observed,
        evidence_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    )

    assert result.accepted is False
    assert result.disposition == "INVALID_INPUT"
