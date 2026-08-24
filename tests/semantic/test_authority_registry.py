from __future__ import annotations

from datetime import date

import pytest

from poi_mpp.evidence.models import EvidenceOrigin


def _record(**overrides: object):
    from poi_mpp.auditor.semantic.authority import (
        IdentityBindingStatus,
        KeyCustodyStatus,
        SemanticAuthorityRecordV1,
        SemanticAuthorityScopeV1,
        SemanticAuthorityUseMode,
        TrustIndependenceStatus,
    )

    scope = SemanticAuthorityScopeV1(
        experiment_id="E3",
        claim_id="C3",
        claim_spec_hash="a" * 64,
        dataset_manifest_hash="b" * 64,
        semantic_policy_hash="c" * 64,
        runtime_environment_hash="d" * 64,
        evidence_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        use_mode=SemanticAuthorityUseMode.CONFIRMATORY_PUBLICATION,
        allowed_metric_ids=("FAR", "FRR", "ABSTAIN", "coverage", "calibration"),
        allowed_artifact_ids=("T4", "T8", "F7", "RAW_E3_EXECUTION"),
    )
    payload = {
        "authority_id": "AUTHORITY_E3_V1",
        "key_id": "ssh-ed25519:authority-key-1",
        "accountable_identity_reference": "orcid:0000-0001-2345-6789",
        "registry_revision": 7,
        "registry_snapshot_hash": "e" * 64,
        "signature_namespace": "file",
        "signature_reference": "POI_E3_EXTERNAL/signatures/e3-authority.sig",
        "detached_signature_sha256": "f" * 64,
        "decision": "APPROVED",
        "valid_from": "2026-08-20",
        "valid_until": "2026-08-31",
        "revocation_state": "ACTIVE",
        "scope": scope,
        "identity_binding_status": IdentityBindingStatus.VERIFIED_ACCOUNTABLE_IDENTITY,
        "independence_status": TrustIndependenceStatus.VERIFIED_OUT_OF_BAND,
        "key_custody_status": KeyCustodyStatus.VERIFIED_OUT_OF_BAND,
        "independence_basis": "different institution, no authorship overlap",
        "unresolved_out_of_band_checks": (),
    }
    payload.update(overrides)
    return SemanticAuthorityRecordV1.model_validate(payload)


def test_authority_record_is_canonical_and_locally_eligible_only_after_crypto_check():
    from poi_mpp.auditor.semantic.authority import SEMANTIC_AUTHORITY_RECORD_V1_DOMAIN
    from poi_mpp.evidence.canonical import digest

    record = _record()

    assert record.scope_gate_reasons(on_date=date(2026, 8, 24)) == ()
    assert record.out_of_band_review_reasons() == ()
    assert record.publication_eligibility_gate_reasons(
        cryptographic_validity_verified=True,
        requested_metric_ids=("FAR", "FRR"),
        requested_artifact_ids=("T8", "F7"),
        on_date=date(2026, 8, 24),
    ) == ()
    assert record.is_publication_eligible(
        cryptographic_validity_verified=True,
        requested_metric_ids=("FAR", "FRR"),
        requested_artifact_ids=("T8", "F7"),
        on_date=date(2026, 8, 24),
    )
    assert not record.is_publication_eligible(
        cryptographic_validity_verified=False,
        requested_metric_ids=("FAR",),
        requested_artifact_ids=("T8",),
        on_date=date(2026, 8, 24),
    )
    assert record.record_digest == digest(
        SEMANTIC_AUTHORITY_RECORD_V1_DOMAIN,
        record.canonical_payload(),
    )


def test_out_of_band_identity_independence_and_key_custody_remain_separate():
    from poi_mpp.auditor.semantic.authority import (
        IdentityBindingStatus,
        KeyCustodyStatus,
        TrustIndependenceStatus,
    )

    record = _record(
        identity_binding_status=IdentityBindingStatus.UNVERIFIED_OUT_OF_BAND,
        independence_status=TrustIndependenceStatus.UNVERIFIED_OUT_OF_BAND,
        key_custody_status=KeyCustodyStatus.UNVERIFIED_OUT_OF_BAND,
        unresolved_out_of_band_checks=(
            "identity binding pending",
            "independence pending",
            "key custody pending",
        ),
    )

    assert record.scope_gate_reasons(on_date=date(2026, 8, 24)) == ()
    reasons = record.out_of_band_review_reasons()
    assert "identity" in " ".join(reasons).lower()
    assert "independence" in " ".join(reasons).lower()
    assert "custody" in " ".join(reasons).lower()
    assert not record.is_publication_eligible(
        cryptographic_validity_verified=True,
        requested_metric_ids=("FAR",),
        requested_artifact_ids=("T8",),
        on_date=date(2026, 8, 24),
    )


def test_limited_scope_enforces_metric_and_artifact_scope_exactly():
    base = _record()
    record = _record(
        decision="LIMITED_SCOPE",
        scope={
            **base.scope.model_dump(mode="python"),
            "allowed_metric_ids": ("FAR",),
            "allowed_artifact_ids": ("T8",),
        },
    )

    assert record.is_publication_eligible(
        cryptographic_validity_verified=True,
        requested_metric_ids=("FAR",),
        requested_artifact_ids=("T8",),
        on_date=date(2026, 8, 24),
    )
    reasons = record.publication_eligibility_gate_reasons(
        cryptographic_validity_verified=True,
        requested_metric_ids=("FAR", "FRR"),
        requested_artifact_ids=("T8", "F7"),
        on_date=date(2026, 8, 24),
    )
    assert "metric" in " ".join(reasons).lower()
    assert "artifact" in " ".join(reasons).lower()

    wider_signed_scope = _record(decision="LIMITED_SCOPE")
    subset_reasons = wider_signed_scope.publication_eligibility_gate_reasons(
        cryptographic_validity_verified=True,
        requested_metric_ids=("FAR",),
        requested_artifact_ids=("T8",),
        on_date=date(2026, 8, 24),
    )
    assert "exact signed metric scope" in " ".join(subset_reasons)
    assert "exact signed artifact scope" in " ".join(subset_reasons)


@pytest.mark.parametrize(
    ("use_mode", "origin"),
    [
        ("CONFIRMATORY_PUBLICATION", EvidenceOrigin.REPRODUCIBLE_SIMULATION),
        ("CONFIRMATORY_PUBLICATION", EvidenceOrigin.FOUNDRY_MEASUREMENT),
        ("DEVELOPMENT_ONLY", EvidenceOrigin.SYNTHETIC_NON_EVIDENCE),
    ],
)
def test_authority_record_rejects_synthetic_or_confirmatory_origin_violations(
    use_mode: str,
    origin: EvidenceOrigin,
):
    with pytest.raises(ValueError, match="evidence_origin"):
        _record(
            scope={
                "experiment_id": "E3",
                "claim_id": "C3",
                "claim_spec_hash": "a" * 64,
                "dataset_manifest_hash": "b" * 64,
                "semantic_policy_hash": "c" * 64,
                "runtime_environment_hash": "d" * 64,
                "evidence_origin": origin.value,
                "use_mode": use_mode,
                "allowed_metric_ids": ("FAR",),
                "allowed_artifact_ids": ("T8",),
            }
        )


def test_authority_record_fails_closed_for_expiry_and_revocation():
    expired = _record(valid_until="2026-08-23")
    revoked = _record(revocation_state="REVOKED")

    assert "expired" in " ".join(expired.scope_gate_reasons(on_date=date(2026, 8, 24))).lower()
    assert "revoked" in " ".join(revoked.scope_gate_reasons(on_date=date(2026, 8, 24))).lower()


def test_authority_record_rejects_duplicate_scope_entries():
    with pytest.raises(ValueError, match="duplicates"):
        _record(
            scope={
                "experiment_id": "E3",
                "claim_id": "C3",
                "claim_spec_hash": "a" * 64,
                "dataset_manifest_hash": "b" * 64,
                "semantic_policy_hash": "c" * 64,
                "runtime_environment_hash": "d" * 64,
                "evidence_origin": EvidenceOrigin.REAL_MODEL_EXECUTION.value,
                "use_mode": "CONFIRMATORY_PUBLICATION",
                "allowed_metric_ids": ("FAR", "FAR"),
                "allowed_artifact_ids": ("T8",),
            }
        )


def test_authority_record_requires_empty_unresolved_checks_once_all_statuses_are_verified():
    with pytest.raises(ValueError, match="unresolved_out_of_band_checks"):
        _record(unresolved_out_of_band_checks=("identity pending",))
