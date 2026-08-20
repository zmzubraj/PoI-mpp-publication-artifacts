from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from poi_mpp.evidence import ArtifactValidationError, EvidenceOrigin, evaluate_publication_gate
from poi_mpp.evidence.provenance import EnvironmentManifest, freeze_run
from poi_mpp.evidence.validation import ProvenanceBundle


def _publication_bundle(config) -> ProvenanceBundle:
    environment = EnvironmentManifest(
        python_implementation="CPython",
        python_version="3.11.15",
        os_name="Linux",
        os_release="test",
        machine="x86_64",
        cpu_model=None,
        gpu_model=None,
        package_lock_hash="c" * 64,
        compiler_version=None,
        foundry_version=None,
        code_revision="d" * 40,
    )
    return ProvenanceBundle(config=config, environment=environment, manifest=freeze_run(config, environment))


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
    from poi_mpp.experiments.e2_tamper import (
        build_fixture_bundle,
        evaluate_receipt,
        validate_attack_receipt,
    )

    honest_bundle = build_fixture_bundle(origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE)
    attacked, manifest = apply_attack(honest_bundle, AttackFamily.MODEL_ROOT_SUBSTITUTION, seed=29)
    row = evaluate_receipt(attacked, attack_manifest=manifest, audit_rate=0.05, freivalds_rounds=8)

    tampered = row.model_copy(
        update={
            "analysis_surface": "UNSUPPORTED_SURFACE",
            "accepted": False,
            "abstained": True,
            "detected": False,
        }
    )
    with pytest.raises(ArtifactValidationError):
        validate_attack_receipt(tampered)


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


def test_one_supported_row_cannot_freeze() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import (
        PUBLICATION_EVIDENCE_AUTHORIZED,
        build_fixture_bundle,
        build_publication_record,
        evaluate_receipt,
    )
    from poi_mpp.reporting.e2 import summarize_e2_rows

    bundle = build_fixture_bundle(origin=EvidenceOrigin.REAL_MODEL_EXECUTION)
    published_config = bundle.run_config.model_copy(update={"authorization_scope": PUBLICATION_EVIDENCE_AUTHORIZED})
    published_bundle = bundle.model_copy(update={"run_config": published_config})
    attacked, manifest = apply_attack(published_bundle, AttackFamily.MODEL_ROOT_SUBSTITUTION, seed=53)
    row = evaluate_receipt(attacked, attack_manifest=manifest, audit_rate=0.05, freivalds_rounds=8)
    summary = summarize_e2_rows([row])
    provenance_bundle = _publication_bundle(published_config)
    record = build_publication_record(
        summary=summary,
        rows=[row],
        run_config=published_config,
        provenance_bundle=provenance_bundle,
    )

    assert summary.claim_disposition == "INCONCLUSIVE"
    assert record["stage"] == "SEMANTICALLY_VALID"


def test_reproducible_simulation_can_freeze_with_matching_scope_and_provenance() -> None:
    from poi_mpp.attacks.execution import apply_attack, AttackFamily
    from poi_mpp.experiments.e2_tamper import (
        PUBLICATION_EVIDENCE_AUTHORIZED,
        build_fixture_bundle,
        build_publication_record,
        evaluate_receipt,
    )
    from poi_mpp.reporting.e2 import summarize_e2_rows

    bundle_one = build_fixture_bundle(origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION, receipt_id="receipt-1", seed=11)
    bundle_two = build_fixture_bundle(origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION, receipt_id="receipt-2", seed=12)
    published_config = bundle_one.run_config.model_copy(update={"authorization_scope": PUBLICATION_EVIDENCE_AUTHORIZED})
    published_one = bundle_one.model_copy(update={"run_config": published_config})
    published_two = bundle_two.model_copy(update={"run_config": published_config, "run_id": published_config.run_id})
    attacked_one, manifest_one = apply_attack(published_one, AttackFamily.MODEL_ROOT_SUBSTITUTION, seed=59)
    attacked_two, manifest_two = apply_attack(published_two, AttackFamily.WEIGHT_CORRUPTION, seed=61)
    rows = [
        evaluate_receipt(attacked_one, attack_manifest=manifest_one, audit_rate=0.05, freivalds_rounds=8),
        evaluate_receipt(attacked_two, attack_manifest=manifest_two, audit_rate=0.05, freivalds_rounds=8),
    ]
    summary = summarize_e2_rows(rows)
    provenance_bundle = _publication_bundle(published_config)
    record = build_publication_record(
        summary=summary,
        rows=rows,
        run_config=published_config,
        provenance_bundle=provenance_bundle,
    )

    assert record["stage"] == "FROZEN"
    assert record["ci_required"] is True
    assert "confidence_interval" in record


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
