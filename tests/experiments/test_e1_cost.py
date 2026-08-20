from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import subprocess
import sys

import pyarrow.parquet as pq
import pytest

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig, approved_schema_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.evidence.provenance import EnvironmentManifest, freeze_run
from poi_mpp.evidence.registry import ArtifactRegistry
from poi_mpp.evidence.validation import ProvenanceBundle, artifact_content_material
from poi_mpp.protocol.types import ModelManifest, TaskClass, TaskSpec
from poi_mpp.reporting.e1 import E1Variant, summarize_e1_rows


def _clock(values: list[int]) -> Iterator[int]:
    for value in values:
        yield value


def _run_config(*, run_id: str = "run-e1", origin: str = "REPRODUCIBLE_SIMULATION", samples: int = 2) -> RunConfig:
    return RunConfig.model_validate(
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": run_id,
            "experiment_id": "E1",
            "origin": origin,
            "authorization_scope": "LOCAL_TEST_ONLY",
            "model_hash": "a" * 64,
            "dataset_hash": "b" * 64,
            "parent_hashes": [],
            "data_availability": {
                "total_shards": 16,
                "samples": samples,
                "replacement": False,
            },
        }
    )


def _bundle(*, run_id: str = "run-e1", samples: int = 2) -> ProvenanceBundle:
    config = _run_config(run_id=run_id, origin="REAL_MODEL_EXECUTION", samples=samples)
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


def _sample(*, protocol_model: ModelManifest, origin: EvidenceOrigin, seed: int = 1):
    from poi_mpp.experiments.e1_cost import E1ExecutionSample

    return E1ExecutionSample(
        origin=origin,
        response_hash="0x" + f"{seed:064x}"[-64:],
        trace_root="0x" + "66" * 32,
        evidence_root="0x" + "77" * 32,
        artifact_root="0x" + "88" * 32,
        total_ms=10.0 + seed,
        inference_ms=9.0 + seed,
        audit_ms=1.0,
        retained_trace_bytes=64,
        expected_dispute_cost=0.0,
        protocol_model_manifest=protocol_model,
    )


def test_cli_loads_quoted_hash_config_then_stops_at_real_run_boundary():
    repo = Path("/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts")
    completed = subprocess.run(
        [
            str(repo / ".venv/bin/python"),
            str(repo / "experiments/e1_single_pass_cost.py"),
            "--config",
            str(repo / "configs/pilot/e1.yaml"),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    combined = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode != 0
    assert "authorized local model adapter" in combined
    assert "schema_hash" not in combined


def test_two_run_baseline_invokes_inference_twice_and_uses_external_clock(
    task: TaskSpec,
    protocol_model: ModelManifest,
):
    from poi_mpp.experiments.e1_cost import MeasurementClock, run_two_run_baseline

    class CountingRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, task: TaskSpec):
            self.calls += 1
            return _sample(protocol_model=protocol_model, origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE, seed=self.calls)

    ticks = _clock([0, 7_000_000])
    result = run_two_run_baseline(
        CountingRunner(),
        task,
        run_id="run-e1",
        experiment_id="E1",
        pair_id="pair-0000",
        clock_ns=lambda: next(ticks),
    )

    assert result.raw_rows[0].variant is E1Variant.TWO_RUN_BASELINE
    assert result.raw_rows[0].measurement_clock is MeasurementClock.FIXTURE_SYNTHETIC
    assert result.raw_rows[0].measured_ms == 7.0
    assert len(result.measured_rows) == 1


def test_run_config_samples_drive_exact_pair_ids_and_warmups_stay_raw_only(
    task: TaskSpec,
    protocol_model: ModelManifest,
    tmp_path: Path,
):
    from poi_mpp.experiments.e1_cost import MeasurementClock, run_e1_cost_experiment

    class FixtureRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, task: TaskSpec):
            self.calls += 1
            return _sample(
                protocol_model=protocol_model,
                origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                seed=self.calls,
            )

    ticks = _clock([step * 1_000_000 for step in range(18)])
    result = run_e1_cost_experiment(
        runner=FixtureRunner(),
        run_config=_run_config(samples=2),
        task=task,
        output_dir=tmp_path,
        warmup_pairs=1,
        clock_ns=lambda: next(ticks),
    )

    measured_pair_ids = {row.pair_id for row in result.measured_rows}
    assert measured_pair_ids == {"pair-0000", "pair-0001"}
    assert len(result.measured_rows) == 6
    assert all(row.measurement_clock is MeasurementClock.FIXTURE_SYNTHETIC for row in result.measured_rows)
    table = pq.read_table(result.raw_rows_path)
    assert table.num_rows == 9
    assert result.summary.denominator == 2


def test_summary_groups_by_pair_id_and_fails_closed_for_one_pair():
    rows = [
        {
            "run_id": "run-e1",
            "experiment_id": "E1",
            "task_id": 11,
            "pair_id": "pair-0000",
            "variant": "NATIVE_SINGLE",
            "is_warmup": False,
            "origin": "REAL_MODEL_EXECUTION",
            "measured_ms": 5.0,
        },
        {
            "run_id": "run-e1",
            "experiment_id": "E1",
            "task_id": 11,
            "pair_id": "pair-0000",
            "variant": "TWO_RUN_BASELINE",
            "is_warmup": False,
            "origin": "REAL_MODEL_EXECUTION",
            "measured_ms": 10.0,
        },
        {
            "run_id": "run-e1",
            "experiment_id": "E1",
            "task_id": 11,
            "pair_id": "pair-0000",
            "variant": "MPP_SINGLE_PASS",
            "is_warmup": False,
            "origin": "REAL_MODEL_EXECUTION",
            "measured_ms": 6.0,
        },
    ]

    summary = summarize_e1_rows(rows)

    assert summary.denominator == 1
    assert summary.claim_disposition == "INCONCLUSIVE"


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [
                {
                    "run_id": "run-e1",
                    "experiment_id": "E1",
                    "task_id": 11,
                    "pair_id": "pair-0000",
                    "variant": "NATIVE_SINGLE",
                    "is_warmup": False,
                    "origin": "REAL_MODEL_EXECUTION",
                    "measured_ms": 5.0,
                },
                {
                    "run_id": "run-e1",
                    "experiment_id": "E1",
                    "task_id": 11,
                    "pair_id": "pair-0000",
                    "variant": "NATIVE_SINGLE",
                    "is_warmup": False,
                    "origin": "REAL_MODEL_EXECUTION",
                    "measured_ms": 5.1,
                },
            ],
            "duplicate variant",
        ),
        (
            [
                {
                    "run_id": "run-e1",
                    "experiment_id": "E1",
                    "task_id": 11,
                    "pair_id": "pair-0000",
                    "variant": "NATIVE_SINGLE",
                    "is_warmup": False,
                    "origin": "REAL_MODEL_EXECUTION",
                    "measured_ms": 5.0,
                },
                {
                    "run_id": "run-e2",
                    "experiment_id": "E1",
                    "task_id": 11,
                    "pair_id": "pair-0000",
                    "variant": "TWO_RUN_BASELINE",
                    "is_warmup": False,
                    "origin": "REAL_MODEL_EXECUTION",
                    "measured_ms": 9.0,
                },
            ],
            "must share one run_id",
        ),
        (
            [
                {
                    "run_id": "run-e1",
                    "experiment_id": "E1",
                    "task_id": 11,
                    "pair_id": "pair-0000",
                    "variant": "NATIVE_SINGLE",
                    "is_warmup": False,
                    "origin": "REAL_MODEL_EXECUTION",
                    "measured_ms": 5.0,
                },
                {
                    "run_id": "run-e1",
                    "experiment_id": "E1",
                    "task_id": 11,
                    "pair_id": "pair-0000",
                    "variant": "TWO_RUN_BASELINE",
                    "is_warmup": False,
                    "origin": "REAL_MODEL_EXECUTION",
                    "measured_ms": 9.0,
                },
                {
                    "run_id": "run-e1",
                    "experiment_id": "E1",
                    "task_id": 11,
                    "pair_id": "pair-0000",
                    "variant": "MPP_SINGLE_PASS",
                    "is_warmup": False,
                    "origin": "SYNTHETIC_NON_EVIDENCE",
                    "measured_ms": 6.0,
                },
            ],
            "must share one run_id",
        ),
    ],
)
def test_summary_rejects_duplicate_missing_and_mismatched_rows(rows: list[dict[str, object]], message: str):
    with pytest.raises(ValueError, match=message):
        summarize_e1_rows(rows)


def test_publication_record_uses_exact_artifact_material_and_complete_round_trip(
    task: TaskSpec,
    protocol_model: ModelManifest,
    tmp_path: Path,
):
    from poi_mpp.experiments.e1_cost import run_e1_cost_experiment

    class RealRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, task: TaskSpec):
            self.calls += 1
            total = 0
            for value in range(50_000):
                total += value
            return _sample(
                protocol_model=protocol_model,
                origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
                seed=self.calls + total % 3,
            )

    bundle = _bundle(run_id="run-real", samples=2)
    registry = ArtifactRegistry(tmp_path / "registry")
    result = run_e1_cost_experiment(
        runner=RealRunner(),
        run_config=bundle.config,
        task=task,
        output_dir=tmp_path / "raw",
        provenance_bundle=bundle,
        registry=registry,
    )

    assert result.publication_record["content_hash"] == digest(
        "ARTIFACT_CONTENT",
        artifact_content_material(result.publication_record),
    )
    assert result.publication_decision.completeness == "COMPLETE"
    assert result.frozen_artifact_path is not None
    assert result.frozen_artifact_path.exists()


def test_synthetic_fixture_rows_are_blocked_from_publication(
    task: TaskSpec,
    protocol_model: ModelManifest,
    tmp_path: Path,
):
    from poi_mpp.experiments.e1_cost import run_e1_cost_experiment

    class SyntheticRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, task: TaskSpec):
            self.calls += 1
            return _sample(
                protocol_model=protocol_model,
                origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                seed=self.calls,
            )

    ticks = _clock([step * 1_000_000 for step in range(12)])
    result = run_e1_cost_experiment(
        runner=SyntheticRunner(),
        run_config=_run_config(samples=2),
        task=task,
        output_dir=tmp_path,
        clock_ns=lambda: next(ticks),
    )

    assert result.publication_decision.completeness == "INCOMPLETE"
    assert result.frozen_artifact_path is None
    assert "synthetic" in " ".join(result.publication_decision.reasons).lower()
