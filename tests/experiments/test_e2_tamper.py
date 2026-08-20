from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from poi_mpp.evidence import ArtifactValidationError, EvidenceOrigin, evaluate_publication_gate


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
    from poi_mpp.experiments.e2_tamper import (
        build_fixture_bundle,
        evaluate_receipt,
        validate_attack_receipt,
    )

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    attacked, manifest = corrupt_trace_node(honest_bundle, index=0, seed=3)
    row = evaluate_receipt(attacked, attack_manifest=manifest, audit_rate=0.05, freivalds_rounds=8)

    with pytest.raises(ArtifactValidationError):
        validate_attack_receipt(row.model_copy(update={"attack_manifest": None}))


def test_mismatched_attack_manifest_is_rejected() -> None:
    from poi_mpp.attacks.execution import corrupt_trace_node
    from poi_mpp.experiments.e2_tamper import (
        build_fixture_bundle,
        evaluate_receipt,
        validate_attack_receipt,
    )

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    attacked, manifest = corrupt_trace_node(honest_bundle, index=2, seed=5)
    row = evaluate_receipt(attacked, attack_manifest=manifest, audit_rate=0.1, freivalds_rounds=8)
    mismatched = row.model_copy(
        update={
            "attack_manifest": row.attack_manifest.model_copy(
                update={"attacked_target_hash": "0x" + ("f" * 64)}
            )
        }
    )

    with pytest.raises(ArtifactValidationError):
        validate_attack_receipt(mismatched)


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


def test_unsupported_kernel_abstains_and_stays_out_of_detection_denominator() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import build_fixture_bundle, evaluate_receipt
    from poi_mpp.reporting.e2 import summarize_e2_rows

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    attacked, manifest = apply_attack(
        honest_bundle,
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

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    exact_bundle, exact_manifest = apply_attack(
        honest_bundle,
        AttackFamily.MODEL_ROOT_SUBSTITUTION,
        seed=19,
    )
    float_bundle, float_manifest = apply_attack(
        honest_bundle,
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
