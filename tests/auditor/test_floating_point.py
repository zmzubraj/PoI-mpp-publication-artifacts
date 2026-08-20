import pytest

from poi_mpp.auditor.reports import AssuranceClass, AuditDisposition, AuditResult
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.auditor import verify_freivalds_float


def test_float_audit_cannot_claim_exact_soundness():
    matrix_a = ((1.0, 2.0), (3.0, 4.0))
    matrix_b = ((5.0, 6.0), (7.0, 8.0))
    approximate_product = ((19.0, 22.0), (43.0, 50.000001))

    result = verify_freivalds_float(
        matrix_a,
        matrix_b,
        approximate_product,
        rounds=4,
        seed=5,
        atol=1e-4,
        rtol=1e-4,
        evidence_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
    )

    assert result.accepted is True
    assert result.assurance_class != "EXACT_FIELD_SOUNDNESS"
    assert result.assurance_class == "EMPIRICAL_FLOAT_APPROXIMATION"
    assert result.soundness_error_bound is None
    assert result.max_abs_error is not None
    assert result.max_rel_error is not None
    assert result.evidence_origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE


def test_float_audit_rejects_nan_inf_and_negative_tolerances():
    matrix_b = ((5.0, 6.0), (7.0, 8.0))
    exact_product = ((19.0, 22.0), (43.0, 50.0))

    with pytest.raises(ValueError, match="atol and rtol must be finite and non-negative"):
        verify_freivalds_float(
            ((1.0, 2.0), (3.0, 4.0)),
            matrix_b,
            exact_product,
            rounds=2,
            seed=1,
            atol=-1e-6,
            rtol=1e-6,
        )

    with pytest.raises(ValueError, match="floating-point matrices must contain only finite values"):
        verify_freivalds_float(
            ((1.0, float("nan")), (3.0, 4.0)),
            matrix_b,
            exact_product,
            rounds=2,
            seed=1,
            atol=1e-6,
            rtol=1e-6,
        )

    with pytest.raises(ValueError, match="floating-point matrices must contain only finite values"):
        verify_freivalds_float(
            ((1.0, 2.0), (3.0, 4.0)),
            matrix_b,
            ((19.0, 22.0), (43.0, float("inf"))),
            rounds=2,
            seed=1,
            atol=1e-6,
            rtol=1e-6,
        )


def test_float_audit_rejects_shape_mismatch():
    with pytest.raises(ValueError, match="matrix dimensions do not align"):
        verify_freivalds_float(
            ((1.0, 2.0, 3.0),),
            ((4.0, 5.0), (6.0, 7.0)),
            ((16.0, 19.0),),
            rounds=2,
            seed=1,
            atol=1e-6,
            rtol=1e-6,
        )


def test_float_audit_rejects_overflowing_intermediates():
    huge = 1e308

    with pytest.raises(ValueError, match="non-finite intermediate"):
        verify_freivalds_float(
            ((huge, huge),),
            ((huge,), (huge,)),
            ((huge,),),
            rounds=2,
            seed=1,
            atol=1e-6,
            rtol=1e-6,
        )


def test_float_audit_zero_reference_metrics_remain_finite_and_tolerance_controls_acceptance():
    zero_product = ((0.0,),)
    small_observed = ((1e-9,),)

    accepted = verify_freivalds_float(
        ((0.0, 0.0),),
        ((0.0,), (0.0,)),
        zero_product,
        rounds=2,
        seed=1,
        atol=0.0,
        rtol=0.0,
    )
    rejected = verify_freivalds_float(
        ((0.0, 0.0),),
        ((0.0,), (0.0,)),
        small_observed,
        rounds=2,
        seed=1,
        atol=0.0,
        rtol=0.0,
    )
    tolerated = verify_freivalds_float(
        ((0.0, 0.0),),
        ((0.0,), (0.0,)),
        small_observed,
        rounds=2,
        seed=1,
        atol=1e-8,
        rtol=1.0,
    )

    assert accepted.accepted is True
    assert rejected.accepted is False
    assert tolerated.accepted is True
    for result in (accepted, rejected, tolerated):
        assert result.assurance_class is AssuranceClass.EMPIRICAL_FLOAT_APPROXIMATION
        assert result.max_abs_error is not None
        assert result.max_rel_error is not None
        assert result.max_rel_error < float("inf")


def test_audit_result_model_copy_forbids_provenance_and_assurance_promotion_and_revalidates_updates():
    result = AuditResult(
        evidence_origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        assurance_class=AssuranceClass.EXACT_MATCH,
        accepted=True,
        disposition=AuditDisposition.ACCEPTED,
        dimensions=(1, 1),
        residual_risk=("exact equality only",),
    )

    with pytest.raises(ValueError, match="model_copy updates cannot change evidence_origin"):
        result.model_copy(update={"evidence_origin": EvidenceOrigin.REAL_MODEL_EXECUTION})

    with pytest.raises(ValueError, match="model_copy updates cannot change assurance_class"):
        result.model_copy(update={"assurance_class": AssuranceClass.EXACT_FIELD_SOUNDNESS})

    with pytest.raises(ValueError, match="exact-match audits do not expose randomized soundness bounds"):
        result.model_copy(update={"soundness_error_bound": 0.5})

    with pytest.raises(ValueError, match="rounds must equal the number of challenge vectors"):
        result.model_copy(update={"rounds": 2})
