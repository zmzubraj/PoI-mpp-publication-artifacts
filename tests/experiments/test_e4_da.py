from __future__ import annotations

from fractions import Fraction
from math import comb
from pathlib import Path
import subprocess

import pytest

from poi_mpp.auditor.availability import (
    ModelAssumptionError,
    ReconstructionStatus,
    miss_probability,
    miss_probability_for_mode,
    verify_reconstruction,
)
from poi_mpp.evidence.config import approved_schema_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e4_da import AvailabilityScenario, ClaimTarget, build_e4_row
from poi_mpp.protocol import ActivateReceipt, InvalidTransition, TransitionContext, transition
from poi_mpp.protocol.availability import (
    ErasureParameters,
    LocalShardAccessError,
    LocalShardStore,
    SamplingAssumption,
    SamplingMode,
    issue_sample_certificate,
)
from poi_mpp.reporting.e4 import f8_points, summarize_e4_rows, t9_rows
from poi_mpp.protocol.types import AuditDecision, Receipt, ReceiptState


def _layout(tmp_path: Path):
    store = LocalShardStore(tmp_path / "store")
    layout = store.initialize(
        finalized_commitment_hash="f" * 64,
        erasure=ErasureParameters(total_shards=6, reconstruction_threshold=4),
        shard_payloads=tuple(f"shard-{index}".encode("utf-8") for index in range(6)),
    )
    return store, layout


def _da_failed_receipt() -> Receipt:
    return Receipt(
        receipt_id=41,
        task_id=7,
        worker_id="0x0000000000000000000000000000000000002007",
        commitment_hash="0x" + "11" * 32,
        audit_id="0x" + "22" * 32,
        state=ReceiptState.DA_FAILED,
        epoch_issued=3,
        challenge_deadline=17,
        nullifier="0x" + "33" * 32,
        audit_decision=AuditDecision.ACCEPT,
        audit_accepted=True,
        da_decision=False,
        data_availability_passed=False,
        activated_epoch=None,
        challenge_reason=None,
        slash_reason=None,
    )


def test_without_replacement_uses_hypergeometric_probability():
    assert miss_probability(total=16, withheld=4, samples=8, replacement=False) == Fraction(
        comb(12, 8),
        comb(16, 8),
    )


def test_impossible_configs_and_nonstatic_formula_requests_fail_closed():
    with pytest.raises(ValueError, match="samples cannot exceed total"):
        miss_probability(total=8, withheld=2, samples=9, replacement=False)
    with pytest.raises(ModelAssumptionError, match="only defined for static withholding"):
        miss_probability_for_mode(
            mode=SamplingMode.CORRELATED_LOSS,
            total=16,
            withheld=4,
            samples=8,
            replacement=False,
        )


def test_without_replacement_certificate_uses_unique_indices_and_binds_hashes(tmp_path: Path):
    store, layout = _layout(tmp_path)
    certificate = issue_sample_certificate(
        layout=layout,
        store=store,
        beacon=b"beacon-1",
        round_index=2,
        sample_count=4,
        replacement=False,
    )

    assert len(set(certificate.sample_indices)) == certificate.sample_count
    assert certificate.finalized_commitment_hash == layout.finalized_commitment_hash
    assert certificate.shard_hashes == tuple(
        layout.shards[index].payload_hash for index in certificate.sample_indices
    )


def test_certificate_refuses_missing_or_tampered_live_sampled_shards(tmp_path: Path):
    store, layout = _layout(tmp_path)
    sample_indices = tuple(
        sorted(
            set(
                store.shard_path(index)
                for index in range(layout.erasure.total_shards)
            )
        )
    )
    certificate = issue_sample_certificate(
        layout=layout,
        store=store,
        beacon=b"beacon-issue",
        round_index=0,
        sample_count=4,
        replacement=False,
    )
    tampered_index = certificate.sample_indices[0]
    store.shard_path(tampered_index).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="no longer matches the finalized shard layout"):
        issue_sample_certificate(
            layout=layout,
            store=store,
            beacon=b"beacon-issue",
            round_index=0,
            sample_count=4,
            replacement=False,
        )

    store2, layout2 = _layout(tmp_path / "missing")
    certificate2 = issue_sample_certificate(
        layout=layout2,
        store=store2,
        beacon=b"beacon-missing",
        round_index=0,
        sample_count=4,
        replacement=False,
    )
    store2.shard_path(certificate2.sample_indices[0]).unlink()
    with pytest.raises(FileNotFoundError, match="not present"):
        issue_sample_certificate(
            layout=layout2,
            store=store2,
            beacon=b"beacon-missing",
            round_index=0,
            sample_count=4,
            replacement=False,
        )


def test_local_shard_store_rejects_symlink_parent_paths(tmp_path: Path):
    store, layout = _layout(tmp_path)
    shard_dir = store.root / "shards"
    real_dir = store.root / "real-shards"
    shard_dir.rename(real_dir)
    shard_dir.symlink_to(real_dir)

    with pytest.raises(LocalShardAccessError, match="could not be opened safely|not a directory"):
        store.read_shard(layout, 0)


def test_reconstruction_refuses_withheld_corrupt_and_selective_service(tmp_path: Path):
    store, layout = _layout(tmp_path)
    certificate = issue_sample_certificate(
        layout=layout,
        store=store,
        beacon=b"beacon-2",
        round_index=1,
        sample_count=4,
        replacement=False,
    )

    (store.root / layout.shards[certificate.sample_indices[0]].relative_path).unlink()
    (store.root / layout.shards[4].relative_path).unlink()
    (store.root / layout.shards[5].relative_path).unlink()
    withheld = verify_reconstruction(
        layout=layout,
        store=store,
        certificate=certificate,
        mode=SamplingMode.STATIC_WITHOUT_REPLACEMENT,
    )
    assert withheld.status == ReconstructionStatus.WITHHELD
    assert withheld.verified_total_shards < withheld.reconstruction_threshold

    corrupt_store, corrupt_layout = _layout(tmp_path / "corrupt")
    corrupt_certificate = issue_sample_certificate(
        layout=corrupt_layout,
        store=corrupt_store,
        beacon=b"beacon-3",
        round_index=1,
        sample_count=4,
        replacement=False,
    )
    corrupt_path = corrupt_store.root / corrupt_layout.shards[corrupt_certificate.sample_indices[0]].relative_path
    corrupt_path.write_bytes(b"tampered")
    corrupt = verify_reconstruction(
        layout=corrupt_layout,
        store=corrupt_store,
        certificate=corrupt_certificate,
        mode=SamplingMode.STATIC_WITHOUT_REPLACEMENT,
    )
    assert corrupt.status == ReconstructionStatus.CORRUPT

    selective_store, selective_layout = _layout(tmp_path / "selective")
    selective_certificate = issue_sample_certificate(
        layout=selective_layout,
        store=selective_store,
        beacon=b"beacon-4",
        round_index=1,
        sample_count=4,
        replacement=False,
    )
    selective = verify_reconstruction(
        layout=selective_layout,
        store=selective_store,
        certificate=selective_certificate,
        mode=SamplingMode.SELECTIVE_SERVING,
        served_indices=selective_certificate.sample_indices[:-1],
    )
    assert selective.status == ReconstructionStatus.SELECTIVE_SERVICE


def test_selective_serving_mislabeled_static_is_rejected():
    with pytest.raises(ValueError, match="selective serving must be labeled"):
        AvailabilityScenario(
            scenario_id="selective-wrong",
            observation_key="obs-selective-wrong",
            certificate_observation_key="cert-selective-wrong",
            seed_observation_key="seed-selective-wrong",
            mode=SamplingMode.SELECTIVE_SERVING,
            assumption_label=SamplingAssumption.STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC,
            claim_target=ClaimTarget.ATTACK_DETECTION,
            expected_outcome=ReconstructionStatus.SELECTIVE_SERVICE,
            total_shards=16,
            reconstruction_threshold=8,
            unavailable_shards=4,
            samples=8,
            replacement=False,
            observed_misses=3,
            observed_trials=10,
        )


def test_da_failed_receipt_cannot_activate():
    with pytest.raises(InvalidTransition):
        transition(
            _da_failed_receipt(),
            ActivateReceipt(),
            TransitionContext(current_height=17, current_epoch=4, used_nullifiers=frozenset()),
        )


def test_e4_reporting_preserves_denominators_intervals_assumptions_and_origin():
    exact_row = build_e4_row(
        run_id="run-e4",
        experiment_id="E4",
        origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        scenario=AvailabilityScenario(
            scenario_id="static-wo",
            observation_key="obs-static-wo",
            certificate_observation_key="cert-static-wo",
            seed_observation_key="seed-static-wo",
            mode=SamplingMode.STATIC_WITHOUT_REPLACEMENT,
            assumption_label=SamplingAssumption.STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC,
            claim_target=ClaimTarget.ATTACK_DETECTION,
            expected_outcome=ReconstructionStatus.WITHHELD,
            total_shards=16,
            reconstruction_threshold=8,
            unavailable_shards=4,
            samples=8,
            replacement=False,
            observed_misses=None,
            observed_trials=None,
        ),
        reconstruction=type("Recon", (), {"status": ReconstructionStatus.WITHHELD})(),
    )
    observed_row = build_e4_row(
        run_id="run-e4",
        experiment_id="E4",
        origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        scenario=AvailabilityScenario(
            scenario_id="corr-1",
            observation_key="obs-corr-1",
            certificate_observation_key="cert-corr-1",
            seed_observation_key="seed-corr-1",
            mode=SamplingMode.CORRELATED_LOSS,
            assumption_label=SamplingAssumption.CORRELATED_LOSS_DECLARED,
            claim_target=ClaimTarget.ATTACK_DETECTION,
            expected_outcome=ReconstructionStatus.CORRUPT,
            total_shards=16,
            reconstruction_threshold=8,
            unavailable_shards=4,
            samples=8,
            replacement=False,
            observed_misses=7,
            observed_trials=20,
        ),
        reconstruction=type("Recon", (), {"status": ReconstructionStatus.CORRUPT})(),
    )

    summary = summarize_e4_rows([exact_row, observed_row])
    table_rows = t9_rows([exact_row, observed_row])
    figure_points = f8_points([exact_row, observed_row])

    assert summary.denominator == 2
    assert summary.claim_disposition == "SUPPORTED"
    assert "STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC" in summary.assumption_ledger
    assert "CORRELATED_LOSS_DECLARED" in summary.assumption_ledger
    assert table_rows[0].origin == EvidenceOrigin.REPRODUCIBLE_SIMULATION.value
    assert table_rows[1].denominator == 20
    assert table_rows[0].expected_outcome_detected is True
    assert table_rows[0].observed_availability_success is False
    assert table_rows[1].observed_attack_detected is True
    assert figure_points[1].lower_bound <= figure_points[1].miss_probability <= figure_points[1].upper_bound


def test_withheld_outcome_cannot_support_availability_success_claim():
    with pytest.raises(ValueError, match="availability-success rows must actually observe successful availability"):
        build_e4_row(
            run_id="run-e4",
            experiment_id="E4",
            origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
            scenario=AvailabilityScenario(
                scenario_id="avail-reviewer-repro",
                observation_key="obs-avail-reviewer-repro",
                certificate_observation_key="cert-avail-reviewer-repro",
                seed_observation_key="seed-avail-reviewer-repro",
                mode=SamplingMode.CORRELATED_LOSS,
                assumption_label=SamplingAssumption.CORRELATED_LOSS_DECLARED,
                claim_target=ClaimTarget.AVAILABILITY_SUCCESS,
                expected_outcome=ReconstructionStatus.VERIFIED,
                total_shards=16,
                reconstruction_threshold=8,
                unavailable_shards=4,
                samples=8,
                replacement=False,
                observed_misses=7,
                observed_trials=20,
            ),
            reconstruction=type("Recon", (), {"status": ReconstructionStatus.WITHHELD})(),
        )


def test_withheld_reviewer_repro_stays_inconclusive_for_wrong_attack_label():
    wrong_detection = build_e4_row(
        run_id="run-e4",
        experiment_id="E4",
        origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        scenario=AvailabilityScenario(
            scenario_id="reviewer-corr",
            observation_key="obs-reviewer-corr",
            certificate_observation_key="cert-reviewer-corr",
            seed_observation_key="seed-reviewer-corr",
            mode=SamplingMode.CORRELATED_LOSS,
            assumption_label=SamplingAssumption.CORRELATED_LOSS_DECLARED,
            claim_target=ClaimTarget.ATTACK_DETECTION,
            expected_outcome=ReconstructionStatus.CORRUPT,
            total_shards=16,
            reconstruction_threshold=8,
            unavailable_shards=4,
            samples=8,
            replacement=False,
            observed_misses=7,
            observed_trials=20,
        ),
        reconstruction=type("Recon", (), {"status": ReconstructionStatus.WITHHELD})(),
    )
    matched_detection = build_e4_row(
        run_id="run-e4",
        experiment_id="E4",
        origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        scenario=AvailabilityScenario(
            scenario_id="reviewer-withheld",
            observation_key="obs-reviewer-withheld",
            certificate_observation_key="cert-reviewer-withheld",
            seed_observation_key="seed-reviewer-withheld",
            mode=SamplingMode.CORRELATED_LOSS,
            assumption_label=SamplingAssumption.CORRELATED_LOSS_DECLARED,
            claim_target=ClaimTarget.ATTACK_DETECTION,
            expected_outcome=ReconstructionStatus.WITHHELD,
            total_shards=16,
            reconstruction_threshold=8,
            unavailable_shards=4,
            samples=8,
            replacement=False,
            observed_misses=7,
            observed_trials=20,
        ),
        reconstruction=type("Recon", (), {"status": ReconstructionStatus.WITHHELD})(),
    )
    summary = summarize_e4_rows([wrong_detection, matched_detection])
    assert summary.expected_outcome_detected_count == 1
    assert summary.claim_disposition == "INCONCLUSIVE"


def test_duplicate_observation_keys_are_rejected():
    row = build_e4_row(
        run_id="run-e4",
        experiment_id="E4",
        origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        scenario=AvailabilityScenario(
            scenario_id="dup-1",
            observation_key="obs-dup",
            certificate_observation_key="cert-dup-1",
            seed_observation_key="seed-dup-1",
            mode=SamplingMode.CORRELATED_LOSS,
            assumption_label=SamplingAssumption.CORRELATED_LOSS_DECLARED,
            claim_target=ClaimTarget.ATTACK_DETECTION,
            expected_outcome=ReconstructionStatus.WITHHELD,
            total_shards=16,
            reconstruction_threshold=8,
            unavailable_shards=4,
            samples=8,
            replacement=False,
            observed_misses=7,
            observed_trials=20,
        ),
        reconstruction=type("Recon", (), {"status": ReconstructionStatus.WITHHELD})(),
    )
    duplicate = row.model_copy(update={"scenario_id": "dup-2"})
    with pytest.raises(ValueError, match="unique observation_key"):
        summarize_e4_rows([row, duplicate])


def test_duplicate_certificate_or_seed_keys_are_rejected():
    row = build_e4_row(
        run_id="run-e4",
        experiment_id="E4",
        origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        scenario=AvailabilityScenario(
            scenario_id="dup-cert-1",
            observation_key="obs-dup-cert-1",
            certificate_observation_key="cert-dup",
            seed_observation_key="seed-dup-1",
            mode=SamplingMode.CORRELATED_LOSS,
            assumption_label=SamplingAssumption.CORRELATED_LOSS_DECLARED,
            claim_target=ClaimTarget.ATTACK_DETECTION,
            expected_outcome=ReconstructionStatus.WITHHELD,
            total_shards=16,
            reconstruction_threshold=8,
            unavailable_shards=4,
            samples=8,
            replacement=False,
            observed_misses=7,
            observed_trials=20,
        ),
        reconstruction=type("Recon", (), {"status": ReconstructionStatus.WITHHELD})(),
    )
    duplicate_certificate = row.model_copy(
        update={
            "scenario_id": "dup-cert-2",
            "observation_key": "obs-dup-cert-2",
            "seed_observation_key": "seed-dup-2",
        }
    )
    with pytest.raises(ValueError, match="unique certificate_observation_key"):
        summarize_e4_rows([row, duplicate_certificate])

    duplicate_seed = row.model_copy(
        update={
            "scenario_id": "dup-seed-2",
            "observation_key": "obs-dup-seed-2",
            "certificate_observation_key": "cert-dup-2",
        }
    )
    with pytest.raises(ValueError, match="unique seed_observation_key"):
        summarize_e4_rows([row, duplicate_seed])


def test_synthetic_rows_always_remain_inconclusive():
    row_one = build_e4_row(
        run_id="run-e4",
        experiment_id="E4",
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        scenario=AvailabilityScenario(
            scenario_id="synthetic-1",
            observation_key="obs-synthetic-1",
            certificate_observation_key="cert-synthetic-1",
            seed_observation_key="seed-synthetic-1",
            mode=SamplingMode.CORRELATED_LOSS,
            assumption_label=SamplingAssumption.CORRELATED_LOSS_DECLARED,
            claim_target=ClaimTarget.ATTACK_DETECTION,
            expected_outcome=ReconstructionStatus.WITHHELD,
            total_shards=16,
            reconstruction_threshold=8,
            unavailable_shards=4,
            samples=8,
            replacement=False,
            observed_misses=7,
            observed_trials=20,
        ),
        reconstruction=type("Recon", (), {"status": ReconstructionStatus.WITHHELD})(),
    )
    row_two = build_e4_row(
        run_id="run-e4",
        experiment_id="E4",
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        scenario=AvailabilityScenario(
            scenario_id="synthetic-2",
            observation_key="obs-synthetic-2",
            certificate_observation_key="cert-synthetic-2",
            seed_observation_key="seed-synthetic-2",
            mode=SamplingMode.CORRELATED_LOSS,
            assumption_label=SamplingAssumption.CORRELATED_LOSS_DECLARED,
            claim_target=ClaimTarget.ATTACK_DETECTION,
            expected_outcome=ReconstructionStatus.WITHHELD,
            total_shards=16,
            reconstruction_threshold=8,
            unavailable_shards=4,
            samples=8,
            replacement=False,
            observed_misses=7,
            observed_trials=20,
        ),
        reconstruction=type("Recon", (), {"status": ReconstructionStatus.WITHHELD})(),
    )
    summary = summarize_e4_rows([row_one, row_two])
    assert summary.claim_disposition == "INCONCLUSIVE"


def test_cli_stops_at_e4_authority_boundary(tmp_path: Path):
    repo = Path("/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts")
    config_path = tmp_path / "e4.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: POI_MPP_RUN_CONFIG_V1",
                f"schema_hash: \"{approved_schema_hash()}\"",
                "run_id: run-e4-cli",
                "experiment_id: E4",
                "origin: REAL_MODEL_EXECUTION",
                "authorization_scope: PUBLICATION_EVIDENCE_AUTHORIZED",
                f"model_hash: \"{'1' * 64}\"",
                f"dataset_hash: \"{'2' * 64}\"",
                "parent_hashes: []",
                "data_availability:",
                "  total_shards: 16",
                "  samples: 8",
                "  replacement: false",
            ]
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            str(repo / ".venv/bin/python"),
            str(repo / "experiments/e4_da_withholding.py"),
            "--config",
            str(config_path),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    combined = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode != 0
    assert "no authorized real pilot/result exists for E4" in combined
