import pytest
from pydantic import ValidationError

from poi_mpp.auditor.semantic.models import SemanticOutcome, VerificationDecision, VerificationMode
from poi_mpp.auditor.semantic.policy_v2 import (
    SEMANTIC_POLICY_V2_DOMAIN,
    SemanticPolicyV2,
)
from poi_mpp.evidence.models import EvidenceOrigin


def _hash(seed: str) -> str:
    return seed * 64


def _policy(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "POI_MPP_SEMANTIC_POLICY_V2",
        "claim_spec_hash": _hash("1"),
        "dataset_manifest_hash": _hash("2"),
        "authority_registry_snapshot_hash": _hash("3"),
        "model_manifest_hash": _hash("4"),
        "runtime_environment_hash": _hash("5"),
        "task_payload_hash": _hash("6"),
        "prompt_template_hash": _hash("7"),
        "calibration_hash": _hash("8"),
        "mode": "CONFIRMATORY",
        "calibration_split": "DEVELOPMENT",
        "support_threshold": 0.75,
        "reject_threshold": 0.25,
        "minimum_calibrated_confidence": 0.60,
        "freeze_locked": True,
        "require_output_trace_agreement": True,
        "allowed_evidence_origins": ("REAL_MODEL_EXECUTION",),
        "allowed_metric_ids": ("Brier", "Coverage", "FAR", "FRR"),
        "required_artifact_ids": ("F7", "T4", "T8"),
        "accept_outcomes": ("SUPPORTED",),
        "reject_outcomes": (
            "CONTRADICTORY",
            "UNSUPPORTED",
            "NUMERICAL_ERROR",
            "CITATION_ERROR",
        ),
        "abstain_outcomes": ("PARTIAL", "AMBIGUOUS"),
    }
    payload.update(overrides)
    return payload


def test_policy_v2_is_immutable_and_forbids_unknown_fields() -> None:
    policy = SemanticPolicyV2.model_validate(_policy())

    with pytest.raises(ValidationError):
        policy.support_threshold = 0.80

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SemanticPolicyV2.model_validate({**_policy(), "shadow_policy": True})


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("claim_spec_hash", "abc123"),
        ("dataset_manifest_hash", "0x" + "ab" * 32),
        ("prompt_template_hash", "z" * 64),
    ],
)
def test_policy_v2_rejects_invalid_hash_shapes(field_name: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field_name):
        SemanticPolicyV2.model_validate(_policy(**{field_name: value}))


def test_policy_v2_rejects_synthetic_and_non_real_confirmatory_origins() -> None:
    with pytest.raises(ValidationError, match="SYNTHETIC_NON_EVIDENCE"):
        SemanticPolicyV2.model_validate(
            _policy(
                mode="DEVELOPMENT",
                allowed_evidence_origins=(
                    "REAL_MODEL_EXECUTION",
                    "SYNTHETIC_NON_EVIDENCE",
                ),
            )
        )

    with pytest.raises(ValidationError, match="REAL_MODEL_EXECUTION"):
        SemanticPolicyV2.model_validate(
            _policy(allowed_evidence_origins=("REAL_MODEL_EXECUTION", "REPRODUCIBLE_SIMULATION"))
        )


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("support_threshold", 1.01, "support_threshold"),
        ("reject_threshold", -0.01, "reject_threshold"),
        ("minimum_calibrated_confidence", 2.0, "minimum_calibrated_confidence"),
    ],
)
def test_policy_v2_rejects_invalid_threshold_ranges(
    field_name: str,
    value: float,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        SemanticPolicyV2.model_validate(_policy(**{field_name: value}))

    with pytest.raises(ValidationError, match="reject_threshold must not exceed support_threshold"):
        SemanticPolicyV2.model_validate(_policy(support_threshold=0.40, reject_threshold=0.50))


def test_policy_v2_rejects_confirmatory_calibration_and_incomplete_outcome_partition() -> None:
    with pytest.raises(ValidationError, match="development-only calibration"):
        SemanticPolicyV2.model_validate(_policy(calibration_split="CONFIRMATORY"))

    with pytest.raises(ValidationError, match="must partition SemanticOutcome"):
        SemanticPolicyV2.model_validate(_policy(abstain_outcomes=("AMBIGUOUS",)))


def test_policy_v2_hash_is_stable_under_reordering_but_changes_on_material_mutation() -> None:
    baseline = SemanticPolicyV2.model_validate(_policy())
    reordered = SemanticPolicyV2.model_validate(
        _policy(
            allowed_metric_ids=("FRR", "FAR", "Coverage", "Brier"),
            required_artifact_ids=("T8", "F7", "T4"),
        )
    )
    mutated = SemanticPolicyV2.model_validate(_policy(support_threshold=0.80))

    assert baseline.policy_hash() == reordered.policy_hash()
    assert baseline.canonical_payload() == reordered.canonical_payload()
    assert baseline.policy_hash() != mutated.policy_hash()
    assert baseline.policy_hash() != baseline.bound_hashes()["claim_spec_hash"]
    assert baseline.policy_hash() == baseline.policy_hash(domain=SEMANTIC_POLICY_V2_DOMAIN)


def test_policy_v2_rejects_missing_or_mutated_frozen_inputs() -> None:
    policy = SemanticPolicyV2.model_validate(_policy())

    bindings = policy.bound_hashes()
    policy.assert_frozen_inputs(bindings)

    with pytest.raises(ValueError, match="missing frozen input hashes: prompt_template_hash"):
        policy.assert_frozen_inputs(
            {key: value for key, value in bindings.items() if key != "prompt_template_hash"}
        )

    mutated = dict(bindings)
    mutated["prompt_template_hash"] = _hash("9")
    with pytest.raises(ValueError, match="prompt_template_hash"):
        policy.assert_frozen_inputs(mutated)


def test_policy_v2_enforces_output_trace_agreement_and_origin_policy() -> None:
    policy = SemanticPolicyV2.model_validate(_policy())

    with pytest.raises(ValueError, match="output decision and trace decision must agree"):
        policy.adjudicate(
            outcome=SemanticOutcome.SUPPORTED,
            support_fraction=0.90,
            calibrated_confidence=0.90,
            output_decision=VerificationDecision.ACCEPT,
            trace_decision=VerificationDecision.REJECT,
            evidence_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        )

    with pytest.raises(ValueError, match="unsupported evidence origin"):
        policy.adjudicate(
            outcome=SemanticOutcome.SUPPORTED,
            support_fraction=0.90,
            calibrated_confidence=0.90,
            output_decision=VerificationDecision.ACCEPT,
            trace_decision=VerificationDecision.ACCEPT,
            evidence_origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        )


def test_policy_v2_adjudicates_accept_reject_and_abstain_deterministically() -> None:
    policy = SemanticPolicyV2.model_validate(_policy())

    accepted = policy.adjudicate(
        outcome=SemanticOutcome.SUPPORTED,
        support_fraction=0.90,
        calibrated_confidence=0.90,
        output_decision=VerificationDecision.ACCEPT,
        trace_decision=VerificationDecision.ACCEPT,
        evidence_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
    )
    rejected = policy.adjudicate(
        outcome=SemanticOutcome.CONTRADICTORY,
        support_fraction=0.90,
        calibrated_confidence=0.90,
        output_decision=VerificationDecision.REJECT,
        trace_decision=VerificationDecision.REJECT,
        evidence_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
    )
    abstained = policy.adjudicate(
        outcome=SemanticOutcome.SUPPORTED,
        support_fraction=0.50,
        calibrated_confidence=0.59,
        output_decision=VerificationDecision.ABSTAIN,
        trace_decision=VerificationDecision.ABSTAIN,
        evidence_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
    )
    threshold_reject = policy.adjudicate(
        outcome=SemanticOutcome.SUPPORTED,
        support_fraction=0.25,
        calibrated_confidence=0.99,
        output_decision=VerificationDecision.REJECT,
        trace_decision=VerificationDecision.REJECT,
        evidence_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
    )

    assert accepted is VerificationDecision.ACCEPT
    assert rejected is VerificationDecision.REJECT
    assert abstained is VerificationDecision.ABSTAIN
    assert threshold_reject is VerificationDecision.REJECT


def test_development_policy_can_use_non_synthetic_non_confirmatory_origins() -> None:
    policy = SemanticPolicyV2.model_validate(
        _policy(
            mode=VerificationMode.DEVELOPMENT.value,
            allowed_evidence_origins=(
                EvidenceOrigin.REAL_MODEL_EXECUTION.value,
                EvidenceOrigin.REPRODUCIBLE_SIMULATION.value,
            ),
        )
    )

    assert policy.mode is VerificationMode.DEVELOPMENT
    assert policy.allowed_evidence_origins == (
        EvidenceOrigin.REAL_MODEL_EXECUTION,
        EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    )
