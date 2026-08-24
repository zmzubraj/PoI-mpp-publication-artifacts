import math

import pytest
from pydantic import ValidationError

from poi_mpp.evidence.claim_spec import (
    ClaimDecisionRule,
    ClaimDisposition,
    ClaimMetricObservation,
    ClaimMetricSpec,
    ClaimRuleCondition,
    ClaimScope,
    ClaimSpecV2,
    EvidenceMaturity,
)
from poi_mpp.evidence.models import EvidenceOrigin


def _scope(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "model_ids": ("TinyLlama-1.1B",),
        "task_ids": ("E3_CONFIRMATORY",),
        "environment_ids": ("LOCAL_PYTHON",),
        "experiment_ids": ("E3_V2",),
    }
    payload.update(overrides)
    return payload


def _metric(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "metric_id": "FAR",
        "denominator_id": "invalid_items",
        "minimum_denominator": 2,
        "confidence_interval_required": True,
    }
    payload.update(overrides)
    return payload


def _condition(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "metric_id": "FAR",
        "source": "POINT_ESTIMATE",
        "operator": "<=",
        "threshold": 0.25,
        "minimum_denominator": 2,
    }
    payload.update(overrides)
    return payload


def _rule(disposition: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "disposition": disposition,
        "conditions": (_condition(),),
        "reason": f"{disposition.lower()} rule",
    }
    payload.update(overrides)
    return payload


def _claim_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "POI_MPP_CLAIM_SPEC_V2",
        "claim_id": "C3",
        "revision": 2,
        "admissible_wording": (
            "Within the frozen E3-v2 confirmatory scope, the semantic audit claim "
            "is supported only when FAR stays at or below alpha_sem = 0.25."
        ),
        "scope": _scope(),
        "evidence_maturity_ceiling": "V3_INTERNAL",
        "allowed_evidence_origins": (
            "REAL_MODEL_EXECUTION",
            "FOUNDRY_MEASUREMENT",
        ),
        "primary_metrics": (
            _metric(),
            _metric(
                metric_id="FRR",
                denominator_id="valid_items",
                threshold_hint=0.25,
            ),
        ),
        "confidence_interval_method": "WILSON_SCORE_95",
        "supported_rule": _rule("SUPPORTED"),
        "inconclusive_rule": _rule(
            "INCONCLUSIVE",
            conditions=(
                _condition(operator=">", threshold=0.25, source="LOWER_CONFIDENCE_BOUND"),
            ),
        ),
        "not_supported_rule": _rule(
            "NOT_SUPPORTED",
            conditions=(
                _condition(operator=">", threshold=0.25),
            ),
        ),
        "required_artifacts": ("T4", "T8", "F7"),
        "prohibited_generalizations": (
            "This establishes general semantic reliability across arbitrary datasets.",
            "This supports production-grade semantic consensus security.",
        ),
    }
    payload.update(overrides)
    return payload


def test_claim_spec_is_immutable_and_forbids_unknown_fields() -> None:
    spec = ClaimSpecV2.model_validate(_claim_payload())

    with pytest.raises(ValidationError):
        spec.claim_id = "C4"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ClaimSpecV2.model_validate({**_claim_payload(), "unknown_field": True})


@pytest.mark.parametrize("claim_id", ["", "claim-3", "C03", "C3-v2"])
def test_claim_spec_rejects_malformed_claim_ids(claim_id: str) -> None:
    with pytest.raises(ValidationError, match="claim_id"):
        ClaimSpecV2.model_validate(_claim_payload(claim_id=claim_id))


@pytest.mark.parametrize("revision", [0, -1, True, 2.5])
def test_claim_spec_rejects_malformed_revisions(revision: object) -> None:
    with pytest.raises(ValidationError, match="revision"):
        ClaimSpecV2.model_validate(_claim_payload(revision=revision))


def test_claim_spec_rejects_duplicate_metric_ids_and_required_artifacts() -> None:
    with pytest.raises(ValidationError, match="primary_metrics"):
        ClaimSpecV2.model_validate(
            _claim_payload(primary_metrics=(_metric(metric_id="FAR"), _metric(metric_id="FAR")))
        )

    with pytest.raises(ValidationError, match="required_artifacts"):
        ClaimSpecV2.model_validate(_claim_payload(required_artifacts=("T4", "T4")))


def test_claim_spec_rejects_invalid_thresholds_and_denominators() -> None:
    with pytest.raises(ValidationError, match="threshold"):
        ClaimRuleCondition.model_validate(_condition(threshold=math.nan))

    with pytest.raises(ValidationError, match="minimum_denominator"):
        ClaimMetricSpec.model_validate(_metric(minimum_denominator=0))

    with pytest.raises(ValidationError, match="minimum_denominator"):
        ClaimRuleCondition.model_validate(_condition(minimum_denominator=0))


def test_claim_spec_requires_all_three_decision_rules() -> None:
    payload = _claim_payload()
    payload.pop("inconclusive_rule")

    with pytest.raises(ValidationError, match="inconclusive_rule"):
        ClaimSpecV2.model_validate(payload)


def test_claim_spec_rejects_synthetic_publication_origins_and_prohibited_admissible_wording() -> None:
    with pytest.raises(ValidationError, match="allowed_evidence_origins"):
        ClaimSpecV2.model_validate(
            _claim_payload(
                allowed_evidence_origins=(
                    "REAL_MODEL_EXECUTION",
                    "SYNTHETIC_NON_EVIDENCE",
                )
            )
        )

    with pytest.raises(ValidationError, match="prohibited_generalizations"):
        ClaimSpecV2.model_validate(
            _claim_payload(
                prohibited_generalizations=(
                    _claim_payload()["admissible_wording"],
                    "This supports production-grade semantic consensus security.",
                )
            )
        )


def test_claim_spec_hash_is_order_stable_but_changes_on_material_mutation() -> None:
    first = ClaimSpecV2.model_validate(_claim_payload())
    reordered = ClaimSpecV2.model_validate(
        _claim_payload(
            allowed_evidence_origins=(
                "FOUNDRY_MEASUREMENT",
                "REAL_MODEL_EXECUTION",
            ),
            primary_metrics=(
                _metric(
                    metric_id="FRR",
                    denominator_id="valid_items",
                    threshold_hint=0.25,
                ),
                _metric(),
            ),
            required_artifacts=("F7", "T8", "T4"),
            prohibited_generalizations=tuple(reversed(_claim_payload()["prohibited_generalizations"])),
        )
    )
    mutated = ClaimSpecV2.model_validate(
        _claim_payload(
            not_supported_rule=_rule(
                "NOT_SUPPORTED",
                conditions=(_condition(operator=">", threshold=0.30),),
            )
        )
    )

    assert first.claim_spec_hash() == reordered.claim_spec_hash()
    assert first.canonical_material() == reordered.canonical_material()
    assert first.claim_spec_hash() != mutated.claim_spec_hash()


def test_claim_spec_enforces_exact_wording_and_rejects_prohibited_generalizations() -> None:
    spec = ClaimSpecV2.model_validate(_claim_payload())

    spec.assert_publication_statement(spec.admissible_wording)

    with pytest.raises(ValueError, match="prohibited generalization"):
        spec.assert_publication_statement(spec.prohibited_generalizations[0])

    with pytest.raises(ValueError, match="exact admissible wording"):
        spec.assert_publication_statement("A paraphrase that broadens the claim.")


def test_claim_spec_adjudicates_supported_not_supported_and_inconclusive_deterministically() -> None:
    spec = ClaimSpecV2.model_validate(_claim_payload())

    supported = spec.adjudicate(
        metrics={
            "FAR": ClaimMetricObservation(
                metric_id="FAR",
                point_estimate=0.20,
                denominator=2,
                confidence_interval=(0.10, 0.24),
            )
        },
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        statement=spec.admissible_wording,
    )
    not_supported = spec.adjudicate(
        metrics={
            "FAR": ClaimMetricObservation(
                metric_id="FAR",
                point_estimate=0.40,
                denominator=2,
                confidence_interval=(0.32, 0.48),
            )
        },
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        statement=spec.admissible_wording,
    )
    inconclusive = spec.adjudicate(
        metrics={
            "FAR": ClaimMetricObservation(
                metric_id="FAR",
                point_estimate=0.24,
                denominator=1,
                confidence_interval=(0.10, 0.40),
            )
        },
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        statement=spec.admissible_wording,
    )

    assert supported is ClaimDisposition.SUPPORTED
    assert not_supported is ClaimDisposition.NOT_SUPPORTED
    assert inconclusive is ClaimDisposition.INCONCLUSIVE


def test_claim_spec_rejects_unsupported_evidence_origin_at_adjudication_time() -> None:
    spec = ClaimSpecV2.model_validate(_claim_payload())

    with pytest.raises(ValueError, match="unsupported evidence origin"):
        spec.adjudicate(
            metrics={
                "FAR": ClaimMetricObservation(
                    metric_id="FAR",
                    point_estimate=0.20,
                    denominator=2,
                    confidence_interval=(0.10, 0.24),
                )
            },
            origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
            statement=spec.admissible_wording,
        )


def test_claim_scope_normalizes_order_and_rejects_duplicates() -> None:
    scope = ClaimScope.model_validate(
        _scope(
            model_ids=("B", "A"),
            task_ids=("task-b", "task-a"),
            environment_ids=("env-b", "env-a"),
            experiment_ids=("exp-b", "exp-a"),
        )
    )

    assert scope.model_ids == ("A", "B")
    assert scope.task_ids == ("task-a", "task-b")
    assert scope.environment_ids == ("env-a", "env-b")
    assert scope.experiment_ids == ("exp-a", "exp-b")

    with pytest.raises(ValidationError, match="must not contain duplicates"):
        ClaimScope.model_validate(_scope(model_ids=("TinyLlama-1.1B", "TinyLlama-1.1B")))


def test_decision_rule_references_known_metrics_only() -> None:
    with pytest.raises(ValidationError, match="unknown metric_id"):
        ClaimSpecV2.model_validate(
            _claim_payload(
                supported_rule=_rule(
                    "SUPPORTED",
                    conditions=(_condition(metric_id="UNKNOWN"),),
                )
            )
        )


def test_decision_rule_disposition_and_condition_source_are_frozen() -> None:
    rule = ClaimDecisionRule.model_validate(_rule("SUPPORTED"))
    condition = ClaimRuleCondition.model_validate(_condition())

    assert rule.disposition is ClaimDisposition.SUPPORTED
    assert condition.source == "POINT_ESTIMATE"


def test_evidence_maturity_enum_exposes_frozen_v0_to_v5_ladder() -> None:
    assert EvidenceMaturity.V0_ASSERTED.value == "V0_ASSERTED"
    assert EvidenceMaturity.V5_FIELD.value == "V5_FIELD"
