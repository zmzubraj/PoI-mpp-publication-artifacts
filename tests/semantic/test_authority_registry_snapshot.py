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

    authority_id = str(overrides.pop("authority_id", "AUTHORITY_E3_V1"))
    key_id = str(overrides.pop("key_id", "ssh-ed25519:authority-key-1"))
    registry_revision = int(overrides.pop("registry_revision", 7))
    registry_snapshot_hash = str(overrides.pop("registry_snapshot_hash", "e" * 64))
    experiment_id = str(overrides.pop("experiment_id", "E3"))
    claim_id = str(overrides.pop("claim_id", "C3"))
    claim_spec_hash = str(overrides.pop("claim_spec_hash", "a" * 64))
    dataset_manifest_hash = str(overrides.pop("dataset_manifest_hash", "b" * 64))
    semantic_policy_hash = str(overrides.pop("semantic_policy_hash", "c" * 64))
    runtime_environment_hash = str(overrides.pop("runtime_environment_hash", "d" * 64))

    scope = SemanticAuthorityScopeV1(
        experiment_id=experiment_id,
        claim_id=claim_id,
        claim_spec_hash=claim_spec_hash,
        dataset_manifest_hash=dataset_manifest_hash,
        semantic_policy_hash=semantic_policy_hash,
        runtime_environment_hash=runtime_environment_hash,
        evidence_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        use_mode=SemanticAuthorityUseMode.CONFIRMATORY_PUBLICATION,
        allowed_metric_ids=("FAR", "FRR", "ABSTAIN", "coverage", "calibration"),
        allowed_artifact_ids=("T4", "T8", "F7", "RAW_E3_EXECUTION"),
    )
    payload = {
        "authority_id": authority_id,
        "key_id": key_id,
        "accountable_identity_reference": "orcid:0000-0001-2345-6789",
        "registry_revision": registry_revision,
        "registry_snapshot_hash": registry_snapshot_hash,
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


def _bind_snapshot(registry_revision: int, *records):
    from poi_mpp.auditor.semantic.authority_registry import SemanticAuthorityRegistrySnapshotV1

    snapshot_hash = SemanticAuthorityRegistrySnapshotV1.preview_snapshot_hash(
        registry_revision=registry_revision,
        authority_records=records,
    )
    bound_records = tuple(
        _record(
            **{
                **record.model_dump(mode="python"),
                "registry_revision": registry_revision,
                "registry_snapshot_hash": snapshot_hash,
            }
        )
        for record in records
    )
    snapshot = SemanticAuthorityRegistrySnapshotV1.model_validate(
        {
            "registry_revision": registry_revision,
            "authority_records": bound_records,
        }
    )
    return snapshot, bound_records


def _verification(record, snapshot, **overrides: object):
    from poi_mpp.auditor.semantic.authority_registry import (
        SemanticAuthorityCryptoVerificationV1,
    )

    payload = {
        "authority_id": record.authority_id,
        "key_id": record.key_id,
        "record_digest": record.record_digest,
        "registry_revision": snapshot.registry_revision,
        "registry_snapshot_hash": snapshot.snapshot_hash,
        "cryptographic_validity_verified": True,
        "verification_receipt": {
            "verifier_id": "canonical-external-authority-verifier-v1",
            "verification_method": "OPENSSH_DETACHED_SIGNATURE",
            "verified_on": "2026-08-24",
            "authority_record_digest": record.record_digest,
            "key_id": record.key_id,
            "authority_record_sha256": "1" * 64,
            "detached_signature_sha256": record.detached_signature_sha256,
            "allowed_signers_sha256": "2" * 64,
            "verifier_output_sha256": "3" * 64,
        },
    }
    payload.update(overrides)
    return SemanticAuthorityCryptoVerificationV1.model_validate(payload)


def test_registry_snapshot_is_canonical_and_exposes_active_lookups():
    from poi_mpp.auditor.semantic.authority_registry import (
        SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1_DOMAIN,
        SemanticAuthorityRegistrySnapshotV1,
    )
    from poi_mpp.evidence.canonical import digest

    raw_a = _record()
    raw_b = _record(
        authority_id="AUTHORITY_E4_V1",
        key_id="ssh-ed25519:authority-key-2",
        experiment_id="E4",
        claim_id="C4",
        claim_spec_hash="1" * 64,
        dataset_manifest_hash="2" * 64,
        semantic_policy_hash="3" * 64,
        runtime_environment_hash="4" * 64,
    )
    expected_hash = SemanticAuthorityRegistrySnapshotV1.preview_snapshot_hash(
        registry_revision=7,
        authority_records=(raw_b, raw_a),
    )
    snapshot, bound_records = _bind_snapshot(7, raw_b, raw_a)
    verification = _verification(bound_records[1], snapshot)

    assert snapshot.snapshot_hash == expected_hash
    assert tuple(entry.authority_id for entry in snapshot.entries) == (
        "AUTHORITY_E3_V1",
        "AUTHORITY_E4_V1",
    )
    assert snapshot.get_authority("AUTHORITY_E3_V1") == bound_records[1]
    assert snapshot.get_by_key_id("ssh-ed25519:authority-key-2") == bound_records[0]
    assert snapshot.active_lookup_reasons(
        authority_id="AUTHORITY_E3_V1",
        cryptographic_verification=verification,
        on_date=date(2026, 8, 24),
    ) == ()
    assert snapshot.get_active_authority(
        authority_id="AUTHORITY_E3_V1",
        cryptographic_verification=verification,
        on_date=date(2026, 8, 24),
    ) == bound_records[1]
    assert snapshot.snapshot_hash == digest(
        SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1_DOMAIN,
        snapshot.canonical_payload(),
    )


def test_registry_snapshot_rejects_duplicate_authority_ids_and_key_ids():
    from poi_mpp.auditor.semantic.authority_registry import SemanticAuthorityRegistrySnapshotV1

    duplicate_authority = _record(key_id="ssh-ed25519:authority-key-2")
    duplicate_key = _record(
        authority_id="AUTHORITY_E4_V1",
        key_id="ssh-ed25519:authority-key-1",
        experiment_id="E4",
        claim_id="C4",
        claim_spec_hash="1" * 64,
        dataset_manifest_hash="2" * 64,
        semantic_policy_hash="3" * 64,
        runtime_environment_hash="4" * 64,
    )

    duplicate_authority_hash = SemanticAuthorityRegistrySnapshotV1.preview_snapshot_hash(
        registry_revision=7,
        authority_records=(_record(), duplicate_authority),
    )
    with pytest.raises(ValueError, match="authority_id"):
        SemanticAuthorityRegistrySnapshotV1.model_validate(
            {
                "registry_revision": 7,
                "authority_records": (
                    _record(registry_snapshot_hash=duplicate_authority_hash),
                    _record(
                        key_id="ssh-ed25519:authority-key-2",
                        registry_snapshot_hash=duplicate_authority_hash,
                    ),
                ),
            }
        )

    duplicate_key_hash = SemanticAuthorityRegistrySnapshotV1.preview_snapshot_hash(
        registry_revision=7,
        authority_records=(_record(), duplicate_key),
    )
    with pytest.raises(ValueError, match="key_id"):
        SemanticAuthorityRegistrySnapshotV1.model_validate(
            {
                "registry_revision": 7,
                "authority_records": (
                    _record(registry_snapshot_hash=duplicate_key_hash),
                    _record(
                        authority_id="AUTHORITY_E4_V1",
                        key_id="ssh-ed25519:authority-key-1",
                        experiment_id="E4",
                        claim_id="C4",
                        claim_spec_hash="1" * 64,
                        dataset_manifest_hash="2" * 64,
                        semantic_policy_hash="3" * 64,
                        runtime_environment_hash="4" * 64,
                        registry_snapshot_hash=duplicate_key_hash,
                    ),
                ),
            }
        )


@pytest.mark.parametrize(
    ("payload_overrides", "error_match"),
    [
        ({"registry_revision": 6}, "registry_revision"),
        ({"registry_snapshot_hash": "9" * 64}, "registry_snapshot_hash"),
    ],
)
def test_registry_snapshot_rejects_stale_revision_or_hash_bindings(
    payload_overrides: dict[str, object],
    error_match: str,
):
    from poi_mpp.auditor.semantic.authority_registry import SemanticAuthorityRegistrySnapshotV1

    raw = _record()
    expected_hash = SemanticAuthorityRegistrySnapshotV1.preview_snapshot_hash(
        registry_revision=7,
        authority_records=(raw,),
    )

    with pytest.raises(ValueError, match=error_match):
        SemanticAuthorityRegistrySnapshotV1.model_validate(
            {
                "registry_revision": 7,
                "authority_records": (
                    _record(
                        **{
                            **{"registry_snapshot_hash": expected_hash},
                            **payload_overrides,
                        }
                    ),
                ),
            }
        )


def test_active_lookup_requires_fresh_external_crypto_receipt():
    snapshot, (record,) = _bind_snapshot(7, _record())

    valid = _verification(record, snapshot)
    stale_revision = _verification(record, snapshot, registry_revision=6)
    stale_hash = _verification(record, snapshot, registry_snapshot_hash="9" * 64)
    unverified = _verification(record, snapshot, cryptographic_validity_verified=False)

    assert snapshot.get_active_authority(
        authority_id=record.authority_id,
        cryptographic_verification=valid,
        on_date=date(2026, 8, 24),
    ) == record
    assert "revision" in " ".join(
        snapshot.active_lookup_reasons(
            authority_id=record.authority_id,
            cryptographic_verification=stale_revision,
            on_date=date(2026, 8, 24),
        )
    ).lower()
    assert "snapshot hash" in " ".join(
        snapshot.active_lookup_reasons(
            authority_id=record.authority_id,
            cryptographic_verification=stale_hash,
            on_date=date(2026, 8, 24),
        )
    ).lower()
    assert "unverified" in " ".join(
        snapshot.active_lookup_reasons(
            authority_id=record.authority_id,
            cryptographic_verification=unverified,
            on_date=date(2026, 8, 24),
        )
    ).lower()


def test_crypto_verification_receipt_is_canonical_and_record_bound():
    snapshot, (record,) = _bind_snapshot(7, _record())
    verification = _verification(record, snapshot)

    assert len(verification.verification_receipt.receipt_digest) == 64
    assert verification.verification_receipt.authority_record_digest == record.record_digest
    assert verification.verification_receipt.key_id == record.key_id

    wrong_record_receipt = verification.verification_receipt.model_copy(
        update={"authority_record_digest": "9" * 64}
    )
    forged = verification.model_copy(
        update={"verification_receipt": wrong_record_receipt}
    )
    reasons = snapshot.cryptographic_binding_reasons(
        record=record,
        cryptographic_verification=forged,
    )

    assert "receipt authority_record_digest mismatch" in reasons


def test_scope_match_helpers_cover_claim_dataset_policy_and_environment():
    snapshot, (record,) = _bind_snapshot(7, _record())

    assert snapshot.claim_scope_match(
        record,
        claim_id="C3",
        claim_spec_hash="a" * 64,
    )
    assert snapshot.dataset_scope_match(record, dataset_manifest_hash="b" * 64)
    assert snapshot.policy_scope_match(record, semantic_policy_hash="c" * 64)
    assert snapshot.environment_scope_match(record, runtime_environment_hash="d" * 64)

    assert "claim_id" in " ".join(
        snapshot.claim_scope_reasons(
            record,
            claim_id="C4",
            claim_spec_hash="a" * 64,
        )
    )
    assert "claim_spec_hash" in " ".join(
        snapshot.claim_scope_reasons(
            record,
            claim_id="C3",
            claim_spec_hash="1" * 64,
        )
    )
    assert "dataset_manifest_hash" in " ".join(
        snapshot.dataset_scope_reasons(record, dataset_manifest_hash="1" * 64)
    )
    assert "semantic_policy_hash" in " ".join(
        snapshot.policy_scope_reasons(record, semantic_policy_hash="1" * 64)
    )
    assert "runtime_environment_hash" in " ".join(
        snapshot.environment_scope_reasons(record, runtime_environment_hash="1" * 64)
    )


def test_registry_hash_excludes_task_policy_to_avoid_circular_binding():
    from poi_mpp.auditor.semantic.authority_registry import (
        SemanticAuthorityRegistrySnapshotV1,
    )

    first = _record(semantic_policy_hash="1" * 64)
    second = _record(semantic_policy_hash="2" * 64)

    first_hash = SemanticAuthorityRegistrySnapshotV1.preview_snapshot_hash(
        registry_revision=7,
        authority_records=(first,),
    )
    second_hash = SemanticAuthorityRegistrySnapshotV1.preview_snapshot_hash(
        registry_revision=7,
        authority_records=(second,),
    )

    assert first_hash == second_hash
    assert first.record_digest != second.record_digest
