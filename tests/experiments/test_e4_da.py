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
from poi_mpp.experiments.e4_da import AvailabilityScenario, build_e4_row
from poi_mpp.protocol import ActivateReceipt, InvalidTransition, TransitionContext, transition
from poi_mpp.protocol.availability import (
    ErasureParameters,
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
            mode=SamplingMode.SELECTIVE_SERVING,
            assumption_label=SamplingAssumption.STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC,
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
            mode=SamplingMode.STATIC_WITHOUT_REPLACEMENT,
            assumption_label=SamplingAssumption.STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC,
            total_shards=16,
            reconstruction_threshold=8,
            unavailable_shards=4,
            samples=8,
            replacement=False,
        ),
    )
    observed_row = build_e4_row(
        run_id="run-e4",
        experiment_id="E4",
        origin=EvidenceOrigin.REPRODUCIBLE_SIMULATION,
        scenario=AvailabilityScenario(
            scenario_id="corr-1",
            mode=SamplingMode.CORRELATED_LOSS,
            assumption_label=SamplingAssumption.CORRELATED_LOSS_DECLARED,
            total_shards=16,
            reconstruction_threshold=8,
            unavailable_shards=4,
            samples=8,
            replacement=False,
            observed_misses=7,
            observed_trials=20,
        ),
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
    assert figure_points[1].lower_bound <= figure_points[1].miss_probability <= figure_points[1].upper_bound


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
