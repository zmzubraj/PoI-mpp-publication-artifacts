from __future__ import annotations

import inspect
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

_EXPECTED_GRANT_KEYWORDS = {
    "experiment_id",
    "experiment_generation",
    "claim_id",
    "claim_generation",
    "task_class",
    "evidence_origin",
    "metric_scope",
    "artifact_scope",
    "privacy_scope",
    "request_scope_digest",
    "authority_record_sha256",
    "decision",
    "authority_identity",
    "request_manifest_sha256",
    "request_manifest_self_digest",
    "result_attestation_status",
    "development_bundle_manifest_sha256",
    "development_dataset_manifest_hash",
    "development_model_manifest_hash",
    "development_decode_policy_hash",
    "development_environment_manifest_hash",
    "development_policy_inputs_digest",
    "confirmatory_freeze_material_lineage_hash",
    "confirmatory_dataset_manifest_hash",
    "confirmatory_development_manifest_hash",
    "calibration_freeze_content_hash",
    "support_rule_id",
    "wilson_z_value",
    "far_wilson_upper_bound_max",
    "frr_wilson_upper_bound_max",
    "coverage_min",
    "confirmatory_composition",
    "_verification_transcript",
}

_EXPECTED_SLOTS = {
    "_experiment_id",
    "_experiment_generation",
    "_claim_id",
    "_claim_generation",
    "_task_class",
    "_evidence_origin",
    "_metric_scope",
    "_artifact_scope",
    "_privacy_scope",
    "_request_scope_digest",
    "_authority_record_sha256",
    "_decision",
    "_authority_identity",
    "_request_manifest_sha256",
    "_request_manifest_self_digest",
    "_result_attestation_status",
    "_development_bundle_manifest_sha256",
    "_development_dataset_manifest_hash",
    "_development_model_manifest_hash",
    "_development_decode_policy_hash",
    "_development_environment_manifest_hash",
    "_development_policy_inputs_digest",
    "_confirmatory_freeze_material_lineage_hash",
    "_confirmatory_dataset_manifest_hash",
    "_confirmatory_development_manifest_hash",
    "_calibration_freeze_content_hash",
    "_support_rule_id",
    "_wilson_z_value",
    "_far_wilson_upper_bound_max",
    "_frr_wilson_upper_bound_max",
    "_coverage_min",
    "_confirmatory_composition",
    "_locked",
    "__weakref__",
}


def _grant_kwargs() -> dict[str, object]:
    digest = "a" * 64
    return {
        "experiment_id": "E3",
        "experiment_generation": "E3_V2",
        "claim_id": "C3",
        "claim_generation": "C3_V2",
        "task_class": "GROUNDED_SEMANTIC_ASSURANCE",
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "metric_scope": ("ABSTAIN", "FAR", "FRR", "calibration", "coverage"),
        "artifact_scope": ("F7", "RAW_E3_EXECUTION", "T4", "T8"),
        "privacy_scope": "AUTHORIZED_PUBLIC",
        "request_scope_digest": digest,
        "authority_record_sha256": digest,
        "decision": "APPROVED",
        "authority_identity": "evaluator-test-only",
        "request_manifest_sha256": digest,
        "request_manifest_self_digest": digest,
        "result_attestation_status": "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION",
        "development_bundle_manifest_sha256": digest,
        "development_dataset_manifest_hash": digest,
        "development_model_manifest_hash": digest,
        "development_decode_policy_hash": digest,
        "development_environment_manifest_hash": digest,
        "development_policy_inputs_digest": digest,
        "confirmatory_freeze_material_lineage_hash": digest,
        "confirmatory_dataset_manifest_hash": digest,
        "confirmatory_development_manifest_hash": digest,
        "calibration_freeze_content_hash": digest,
        "support_rule_id": "C3_V2_WILSON_SUPPORT_V1",
        "wilson_z_value": "1.959963984540054",
        "far_wilson_upper_bound_max": "0.25",
        "frr_wilson_upper_bound_max": "0.25",
        "coverage_min": "0.50",
        "confirmatory_composition": {"ACCEPT": 200, "REJECT": 200, "ABSTAIN": 100, "total": 500},
        "_verification_transcript": None,
    }


def test_direct_construction_is_refused() -> None:
    from poi_mpp.experiments.e3_v2_authority import VerifiedE3V2AuthorityGrant

    with pytest.raises(TypeError, match="only verify_authority may produce a verified grant"):
        VerifiedE3V2AuthorityGrant(**_grant_kwargs())


def test_constructor_requires_the_full_v2_keyword_surface() -> None:
    from poi_mpp.experiments.e3_v2_authority import VerifiedE3V2AuthorityGrant

    signature = inspect.signature(VerifiedE3V2AuthorityGrant.__init__)
    parameters = dict(signature.parameters)
    parameters.pop("self")
    assert set(parameters) == _EXPECTED_GRANT_KEYWORDS
    for name, parameter in parameters.items():
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameter.default is inspect.Parameter.empty, name


def test_grant_slots_cover_the_v2_contract() -> None:
    from poi_mpp.experiments.e3_v2_authority import VerifiedE3V2AuthorityGrant

    assert set(VerifiedE3V2AuthorityGrant.__slots__) == _EXPECTED_SLOTS


def test_canonical_verifier_is_the_v2_verifier_script() -> None:
    from poi_mpp.experiments import e3_v2_authority

    assert (
        e3_v2_authority._CANONICAL_AUTHORITY_VERIFIER
        == REPO_ROOT / "scripts" / "verify_e3_v2_authority.py"
    )


def test_grant_is_authentic_rejects_foreign_objects() -> None:
    from poi_mpp.experiments.e3_v2_authority import _grant_is_authentic

    assert _grant_is_authentic(object()) is False
    assert _grant_is_authentic(None) is False
    assert _grant_is_authentic({"decision": "APPROVED"}) is False
