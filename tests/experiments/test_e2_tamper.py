from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from poi_mpp.evidence import ArtifactValidationError, EvidenceOrigin, evaluate_publication_gate


def _forged_seed_payload(row, *, new_seed: int) -> dict[str, object]:
    from poi_mpp.attacks.execution import AttackManifest, AttackReplayProof
    from poi_mpp.experiments.e2_tamper import E2ReceiptRow, _observation_key, _row_hash_material

    payload = {
        field_name: getattr(row, field_name)
        for field_name in type(row).model_fields
    }
    manifest = row.attack_manifest.model_dump(mode="python")
    replay_proof = dict(manifest["replay_proof"])
    manifest["replay_proof"] = AttackReplayProof.model_construct(**replay_proof)
    manifest["seed"] = new_seed
    payload["attack_manifest"] = AttackManifest.model_construct(**manifest)
    payload["attack_seed"] = new_seed
    payload["observation_key"] = _observation_key(
        row.attack_family,
        new_seed,
        row.original_target_hash,
        row.peer_receipt_id,
    )
    payload["row_hash"] = _row_hash_material(
        E2ReceiptRow.model_construct(
            **{
                **payload,
                "row_hash": "0x" + ("0" * 64),
            }
        )
    )
    return payload


def test_attack_changes_target_but_not_original_commitment() -> None:
    from poi_mpp.attacks.execution import corrupt_trace_node
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    attacked, manifest = corrupt_trace_node(honest_bundle, index=0, seed=9)

    assert attacked.trace_root != honest_bundle.trace_root
    assert attacked.commitment == honest_bundle.commitment
    assert manifest.original_commitment == honest_bundle.commitment.commitment_hash


def test_missing_attack_manifest_is_rejected() -> None:
    from poi_mpp.attacks.execution import corrupt_trace_node
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle, evaluate_receipt

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    attacked, manifest = corrupt_trace_node(honest_bundle, index=0, seed=3)
    row = evaluate_receipt(attacked, attack_manifest=manifest, audit_rate=0.05, freivalds_rounds=8)

    with pytest.raises(ValidationError):
        row.model_copy(update={"attack_manifest": None})


def test_mismatched_attack_manifest_is_rejected() -> None:
    from poi_mpp.attacks.execution import corrupt_trace_node
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle, evaluate_receipt

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    attacked, manifest = corrupt_trace_node(honest_bundle, index=2, seed=5)
    row = evaluate_receipt(attacked, attack_manifest=manifest, audit_rate=0.1, freivalds_rounds=8)

    with pytest.raises(ValidationError):
        row.model_copy(
            update={
                "attack_manifest": row.attack_manifest.model_copy(
                    update={"attacked_target_hash": "0x" + ("f" * 64)}
                )
            }
        )


def test_same_attack_seed_replays_deterministically() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    first_bundle, first_manifest = apply_attack(
        honest_bundle,
        AttackFamily.MODEL_ROOT_SUBSTITUTION,
        seed=11,
    )
    second_bundle, second_manifest = apply_attack(
        honest_bundle,
        AttackFamily.MODEL_ROOT_SUBSTITUTION,
        seed=11,
    )

    assert first_bundle.model_root == second_bundle.model_root
    assert first_manifest.attacked_target_hash == second_manifest.attacked_target_hash
    assert first_manifest.original_target_hash == second_manifest.original_target_hash


def test_tensor_attack_wrong_surface_label_is_rejected() -> None:
    from poi_mpp.attacks.execution import (
        AttackFamily,
        AttackManifest,
        AttackNumericMode,
    )

    with pytest.raises(ValueError):
        AttackManifest(
            family=AttackFamily.TENSOR_PRODUCT_CORRUPTION,
            numeric_mode=AttackNumericMode.EXACT_FIELD,
            analysis_surface="EMPIRICAL_FLOAT_APPROXIMATION",
            location="tensor.product",
            seed=31,
            origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
            original_commitment="0x" + ("1" * 64),
            original_target_hash="0x" + ("2" * 64),
            attacked_target_hash="0x" + ("3" * 64),
        )


def test_supported_attack_cannot_be_relabelled_unsupported() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle, evaluate_receipt

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    attacked, manifest = apply_attack(honest_bundle, AttackFamily.MODEL_ROOT_SUBSTITUTION, seed=29)
    row = evaluate_receipt(attacked, attack_manifest=manifest, audit_rate=0.05, freivalds_rounds=8)

    with pytest.raises(ValidationError):
        row.model_copy(
            update={
                "analysis_surface": "UNSUPPORTED_SURFACE",
                "accepted": False,
                "abstained": True,
                "detected": False,
            }
        )


def test_model_validate_rejects_forged_attack_seed_with_recomputed_row_hash() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import E2ReceiptRow, build_fixture_bundle, evaluate_receipt

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    attacked, manifest = apply_attack(honest_bundle, AttackFamily.MODEL_ROOT_SUBSTITUTION, seed=33)
    row = evaluate_receipt(attacked, attack_manifest=manifest, audit_rate=0.05, freivalds_rounds=8)
    payload = _forged_seed_payload(row, new_seed=int(row.attack_seed) + 1)

    with pytest.raises(ValidationError):
        E2ReceiptRow.model_validate(payload)


def test_model_validate_json_rejects_forged_attack_seed_with_recomputed_row_hash() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import E2ReceiptRow, build_fixture_bundle, evaluate_receipt

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    attacked, manifest = apply_attack(honest_bundle, AttackFamily.MODEL_ROOT_SUBSTITUTION, seed=35)
    row = evaluate_receipt(attacked, attack_manifest=manifest, audit_rate=0.05, freivalds_rounds=8)
    forged = E2ReceiptRow.model_construct(**_forged_seed_payload(row, new_seed=int(row.attack_seed) + 1))

    with pytest.raises(ValidationError):
        E2ReceiptRow.model_validate_json(json.dumps(forged.model_dump(mode="json")))


def test_replay_attack_is_detected_when_nullifier_was_already_seen() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle, evaluate_receipt

    honest_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0001",
        seed=1,
    )
    peer_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0002",
        seed=2,
    )
    attacked, manifest = apply_attack(
        honest_bundle,
        AttackFamily.REPLAY_NULLIFIER,
        seed=13,
        peer_bundle=peer_bundle,
    )

    row = evaluate_receipt(
        attacked,
        attack_manifest=manifest,
        audit_rate=0.05,
        freivalds_rounds=8,
        prior_nullifiers=frozenset({peer_bundle.nullifier}),
    )

    assert row.detected is True
    assert row.abstained is False


def test_replay_attack_requires_prior_nullifier_membership() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle, evaluate_receipt

    honest_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0001",
        seed=1,
    )
    peer_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0002",
        seed=2,
    )
    attacked, manifest = apply_attack(
        honest_bundle,
        AttackFamily.REPLAY_NULLIFIER,
        seed=41,
        peer_bundle=peer_bundle,
    )

    row = evaluate_receipt(
        attacked,
        attack_manifest=manifest,
        audit_rate=0.05,
        freivalds_rounds=8,
        prior_nullifiers=frozenset(),
    )

    assert row.detected is False
    assert row.accepted is True
    assert any("not replay" in reason for reason in row.residual_risk)


def test_validate_attack_receipt_confirms_replay_atomically_from_unvalidated_row() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import (
        ReplayValidationDisposition,
        build_fixture_bundle,
        evaluate_receipt,
        validate_attack_receipt,
    )

    honest_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0001",
        seed=1,
    )
    peer_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0002",
        seed=2,
    )
    attacked, manifest = apply_attack(
        honest_bundle,
        AttackFamily.REPLAY_NULLIFIER,
        seed=43,
        peer_bundle=peer_bundle,
    )
    unvalidated = evaluate_receipt(
        attacked,
        attack_manifest=manifest,
        audit_rate=0.05,
        freivalds_rounds=8,
    )

    validated = validate_attack_receipt(
        unvalidated,
        prior_nullifiers=frozenset({peer_bundle.nullifier}),
    )

    assert unvalidated.replay_validation == ReplayValidationDisposition.UNVALIDATED
    assert unvalidated.detected is False
    assert validated.replay_validation == ReplayValidationDisposition.CONFIRMED_REPLAY
    assert validated.detected is True
    assert validated.accepted is False
    assert validated.row_hash != unvalidated.row_hash
    assert any("already appeared" in reason for reason in validated.residual_risk)


def test_validate_attack_receipt_marks_nonmember_replay_atomically() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import (
        ReplayValidationDisposition,
        build_fixture_bundle,
        evaluate_receipt,
        validate_attack_receipt,
    )

    honest_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0001",
        seed=1,
    )
    peer_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0002",
        seed=2,
    )
    attacked, manifest = apply_attack(
        honest_bundle,
        AttackFamily.REPLAY_NULLIFIER,
        seed=47,
        peer_bundle=peer_bundle,
    )
    unvalidated = evaluate_receipt(
        attacked,
        attack_manifest=manifest,
        audit_rate=0.05,
        freivalds_rounds=8,
    )

    validated = validate_attack_receipt(
        unvalidated,
        prior_nullifiers=frozenset(),
    )

    assert validated.replay_validation == ReplayValidationDisposition.VERIFIED_NOT_REPLAY
    assert validated.detected is False
    assert validated.accepted is True
    assert validated.row_hash != unvalidated.row_hash
    assert any("not replay" in reason for reason in validated.residual_risk)


def test_reloaded_replay_row_requires_explicit_prior_context_to_self_authorize() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import (
        E2ReceiptRow,
        build_fixture_bundle,
        evaluate_receipt,
        validate_attack_receipt,
    )

    honest_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0001",
        seed=1,
    )
    peer_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0002",
        seed=2,
    )
    attacked, manifest = apply_attack(
        honest_bundle,
        AttackFamily.REPLAY_NULLIFIER,
        seed=51,
        peer_bundle=peer_bundle,
    )
    validated = evaluate_receipt(
        attacked,
        attack_manifest=manifest,
        audit_rate=0.05,
        freivalds_rounds=8,
        prior_nullifiers=frozenset({peer_bundle.nullifier}),
    )
    reloaded = E2ReceiptRow.model_validate_json(validated.model_dump_json())

    with pytest.raises(ArtifactValidationError):
        validate_attack_receipt(reloaded)

    revalidated = validate_attack_receipt(
        reloaded,
        prior_nullifiers=frozenset({peer_bundle.nullifier}),
    )

    assert revalidated.detected is True
    assert revalidated.accepted is False
    assert revalidated.row_hash == validated.row_hash


def test_summary_rejects_reloaded_replay_row_without_context_validation() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import E2ReceiptRow, build_fixture_bundle, evaluate_receipt
    from poi_mpp.reporting.e2 import summarize_e2_rows

    honest_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0001",
        seed=1,
    )
    peer_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0002",
        seed=2,
    )
    attacked, manifest = apply_attack(
        honest_bundle,
        AttackFamily.REPLAY_NULLIFIER,
        seed=45,
        peer_bundle=peer_bundle,
    )
    validated = evaluate_receipt(
        attacked,
        attack_manifest=manifest,
        audit_rate=0.05,
        freivalds_rounds=8,
        prior_nullifiers=frozenset({peer_bundle.nullifier}),
    )
    reloaded = E2ReceiptRow.model_validate_json(validated.model_dump_json())

    with pytest.raises(ArtifactValidationError):
        summarize_e2_rows([reloaded])


def test_publication_record_rejects_reloaded_replay_row_without_context_validation() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import (
        E2ReceiptRow,
        build_fixture_bundle,
        build_publication_record,
        evaluate_receipt,
    )
    from poi_mpp.reporting.e2 import E2Summary

    honest_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0001",
        seed=1,
    )
    peer_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-0002",
        seed=2,
    )
    attacked, manifest = apply_attack(
        honest_bundle,
        AttackFamily.REPLAY_NULLIFIER,
        seed=49,
        peer_bundle=peer_bundle,
    )
    validated = evaluate_receipt(
        attacked,
        attack_manifest=manifest,
        audit_rate=0.05,
        freivalds_rounds=8,
        prior_nullifiers=frozenset({peer_bundle.nullifier}),
    )
    reloaded = E2ReceiptRow.model_validate_json(validated.model_dump_json())
    summary = E2Summary(
        claim_id="C2",
        denominator=1,
        minimum_supported_denominator=2,
        minimum_unique_attack_seeds=2,
        unique_attack_seed_count=0,
        exact_denominator=1,
        exact_detected=1,
        exact_detection_rate=1.0,
        exact_confidence_interval=(0.0, 1.0),
        empirical_denominator=0,
        empirical_detected=0,
        empirical_detection_rate=0.0,
        empirical_confidence_interval=(0.0, 1.0),
        unsupported_attack_count=0,
        honest_control_count=0,
        false_positive_count=0,
        false_positive_rate=0.0,
        confidence_interval=(0.0, 1.0),
        residual_surface_ledger=(),
        claim_disposition="INCONCLUSIVE",
    )

    with pytest.raises(ArtifactValidationError):
        build_publication_record(summary=summary, rows=[reloaded], run_config=honest_bundle.run_config)


def test_unsupported_kernel_abstains_and_stays_out_of_detection_denominator() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle, evaluate_receipt
    from poi_mpp.reporting.e2 import summarize_e2_rows

    honest_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-control",
        seed=1,
    )
    attacked_bundle = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-unsupported",
        seed=2,
    ).model_copy(update={"run_id": honest_bundle.run_id})
    attacked, manifest = apply_attack(
        attacked_bundle,
        AttackFamily.UNSUPPORTED_KERNEL,
        seed=17,
    )

    control_row = evaluate_receipt(honest_bundle, audit_rate=0.05, freivalds_rounds=8)
    attacked_row = evaluate_receipt(
        attacked,
        attack_manifest=manifest,
        audit_rate=0.05,
        freivalds_rounds=8,
    )
    summary = summarize_e2_rows([control_row, attacked_row])

    assert attacked_row.abstained is True
    assert attacked_row.detected is False
    assert summary.denominator == 0
    assert summary.unsupported_attack_count == 1


def test_exact_and_empirical_surfaces_are_reported_separately() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily, AttackAnalysisSurface
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle, evaluate_receipt
    from poi_mpp.reporting.e2 import summarize_e2_rows

    exact_source = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-exact",
        seed=3,
    )
    float_source = build_fixture_bundle(
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        receipt_id="receipt-float",
        seed=4,
    ).model_copy(update={"run_id": exact_source.run_id})
    exact_bundle, exact_manifest = apply_attack(
        exact_source,
        AttackFamily.MODEL_ROOT_SUBSTITUTION,
        seed=19,
    )
    float_bundle, float_manifest = apply_attack(
        float_source,
        AttackFamily.TENSOR_PRODUCT_CORRUPTION,
        seed=23,
        analysis_surface=AttackAnalysisSurface.EMPIRICAL_FLOAT,
    )

    summary = summarize_e2_rows(
        [
            evaluate_receipt(exact_bundle, attack_manifest=exact_manifest, audit_rate=0.05, freivalds_rounds=8),
            evaluate_receipt(float_bundle, attack_manifest=float_manifest, audit_rate=0.05, freivalds_rounds=8),
        ]
    )

    assert summary.denominator == 2
    assert summary.exact_denominator == 1
    assert summary.empirical_denominator == 1
    assert summary.exact_detection_rate == 1.0
    assert summary.empirical_detection_rate == 1.0
    assert summary.minimum_supported_denominator == 2
    assert summary.unique_attack_seed_count == 2
    assert summary.confidence_interval[0] <= summary.confidence_interval[1]


def test_summary_rejects_duplicate_receipt_ids() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle, evaluate_receipt
    from poi_mpp.reporting.e2 import summarize_e2_rows

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    attacked, manifest = apply_attack(honest_bundle, AttackFamily.MODEL_ROOT_SUBSTITUTION, seed=43)
    row = evaluate_receipt(attacked, attack_manifest=manifest, audit_rate=0.05, freivalds_rounds=8)

    with pytest.raises(ValueError):
        summarize_e2_rows([row, row])


def test_summary_rejects_duplicate_attack_observation_key() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle, evaluate_receipt
    from poi_mpp.reporting.e2 import summarize_e2_rows

    first_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE, receipt_id="receipt-a", seed=1)
    second_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE, receipt_id="receipt-b", seed=1)
    first_attacked, first_manifest = apply_attack(first_bundle, AttackFamily.MODEL_ROOT_SUBSTITUTION, seed=47)
    second_attacked = second_bundle.model_copy(update={"model_root": first_attacked.model_root})
    row_one = evaluate_receipt(first_attacked, attack_manifest=first_manifest, audit_rate=0.05, freivalds_rounds=8)
    row_two = evaluate_receipt(second_attacked, attack_manifest=first_manifest, audit_rate=0.05, freivalds_rounds=8)

    with pytest.raises(ValueError):
        summarize_e2_rows([row_one, row_two])


def test_synthetic_rows_cannot_publish() -> None:
    from poi_mpp.experiments.e2_tamper import (
        build_fixture_bundle,
        build_publication_record,
        evaluate_receipt,
    )
    from poi_mpp.reporting.e2 import summarize_e2_rows

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    row = evaluate_receipt(honest_bundle, audit_rate=0.05, freivalds_rounds=8)
    summary = summarize_e2_rows([row])
    record = build_publication_record(summary=summary, rows=[row], run_config=honest_bundle.run_config)

    decision = evaluate_publication_gate("C2", [record])

    assert record["stage"] == "SEMANTICALLY_VALID"
    assert decision.completeness == "INCOMPLETE"
    assert any("synthetic non-evidence origin" in reason for reason in decision.reasons)


@pytest.mark.parametrize(
    ("origin",),
    [
        (EvidenceOrigin.REAL_MODEL_EXECUTION,),
        (EvidenceOrigin.REPRODUCIBLE_SIMULATION,),
    ],
)
def test_fixture_bundle_rejects_non_synthetic_origins(origin: EvidenceOrigin) -> None:
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle

    with pytest.raises(ValueError):
        build_fixture_bundle(origin=origin)


def test_cli_loads_config_then_stops_at_real_run_boundary() -> None:
    repo = Path("/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts")
    completed = subprocess.run(
        [
            str(repo / ".venv/bin/python"),
            str(repo / "experiments/e2_tamper_detection.py"),
            "--config",
            str(repo / "configs/pilot/e2.yaml"),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    combined = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode != 0
    assert "authorized local model adapter" in combined
    assert "schema_hash" not in combined
