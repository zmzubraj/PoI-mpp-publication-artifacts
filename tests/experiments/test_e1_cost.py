from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.protocol.types import ModelManifest, TaskClass, TaskSpec


@pytest.fixture()
def task() -> TaskSpec:
    return TaskSpec(
        task_id=11,
        task_root="0xaa" + "11" * 31,
        worker_id="0x0000000000000000000000000000000000002011",
        task_class=TaskClass.CONSENSUS,
        active=True,
        registered=True,
        credit_budget=90,
        epoch=7,
        deadline=500,
        commitment_height=120,
        commitment_finality_depth=5,
        challenge_window_blocks=9,
        audit_domain_size=16,
    )


@pytest.fixture()
def protocol_model() -> ModelManifest:
    return ModelManifest(
        model_root="0xbb" + "22" * 31,
        runtime_root="0xcc" + "33" * 31,
        model_manifest_hash="0xdd" + "44" * 31,
        assurance_class=1,
    )


def test_two_run_baseline_invokes_inference_twice(task: TaskSpec, protocol_model: ModelManifest):
    from poi_mpp.experiments.e1_cost import E1ExecutionSample, run_two_run_baseline

    class CountingRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, task: TaskSpec) -> E1ExecutionSample:
            self.calls += 1
            return E1ExecutionSample(
                origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
                response_hash="0x" + "55" * 32,
                trace_root="0x" + "66" * 32,
                evidence_root="0x" + "77" * 32,
                artifact_root="0x" + "88" * 32,
                total_ms=10.0,
                inference_ms=9.0,
                audit_ms=0.0,
                retained_trace_bytes=64,
                expected_dispute_cost=0.0,
                protocol_model_manifest=protocol_model,
            )

    runner = CountingRunner()
    result = run_two_run_baseline(runner, task, pair_id="pair-1")

    assert runner.calls == 2
    assert len(result.measured_rows) == 1
    assert result.measured_rows[0].variant == "TWO_RUN_BASELINE"


def test_warmups_are_excluded_from_measured_rows(task: TaskSpec, protocol_model: ModelManifest, tmp_path: Path):
    from poi_mpp.experiments.e1_cost import E1ExecutionSample, run_e1_cost_experiment

    class FixtureRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, task: TaskSpec) -> E1ExecutionSample:
            self.calls += 1
            return E1ExecutionSample(
                origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                response_hash="0x" + f"{self.calls:064x}"[-64:],
                trace_root="0x" + "66" * 32,
                evidence_root="0x" + "77" * 32,
                artifact_root="0x" + "88" * 32,
                total_ms=10.0 + self.calls,
                inference_ms=9.0 + self.calls,
                audit_ms=1.0,
                retained_trace_bytes=64,
                expected_dispute_cost=0.0,
                protocol_model_manifest=protocol_model,
            )

    result = run_e1_cost_experiment(
        runner=FixtureRunner(),
        task=task,
        output_dir=tmp_path,
        run_id="synthetic-e1",
        experiment_id="E1",
        warmup_pairs=1,
    )

    assert result.raw_rows_path.is_file()
    assert all(not row.is_warmup for row in result.measured_rows)
    table = pq.read_table(result.raw_rows_path)
    assert table.num_rows > len(result.measured_rows)


def test_synthetic_fixture_rows_are_blocked_from_publication(
    task: TaskSpec,
    protocol_model: ModelManifest,
    tmp_path: Path,
):
    from poi_mpp.experiments.e1_cost import E1ExecutionSample, run_e1_cost_experiment

    class SyntheticRunner:
        def run(self, task: TaskSpec) -> E1ExecutionSample:
            return E1ExecutionSample(
                origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                response_hash="0x" + "55" * 32,
                trace_root="0x" + "66" * 32,
                evidence_root="0x" + "77" * 32,
                artifact_root="0x" + "88" * 32,
                total_ms=10.0,
                inference_ms=9.0,
                audit_ms=1.0,
                retained_trace_bytes=64,
                expected_dispute_cost=0.0,
                protocol_model_manifest=protocol_model,
            )

    result = run_e1_cost_experiment(
        runner=SyntheticRunner(),
        task=task,
        output_dir=tmp_path,
        run_id="synthetic-e1",
        experiment_id="E1",
    )

    assert result.publication_decision.completeness == "INCOMPLETE"
    assert "synthetic" in " ".join(result.publication_decision.reasons).lower()
