from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "configs/confirmatory/e8.publication.yaml"


def _run(tmp_path: Path, *, name: str = "e8_multiepoch.json"):
    from poi_mpp.experiments.e8_multiepoch import load_and_run_e8_multiepoch

    return load_and_run_e8_multiepoch(PLAN_PATH, output_path=tmp_path / name)


def test_multiepoch_runner_is_deterministic_and_epoch_bound(tmp_path: Path):
    first = _run(tmp_path, name="first.json")
    second = _run(tmp_path, name="second.json")

    assert first == second
    assert (tmp_path / "first.json").read_bytes() == (tmp_path / "second.json").read_bytes()
    assert first.origin.value == "REPRODUCIBLE_SIMULATION"
    assert first.claim_disposition == "INCONCLUSIVE"
    assert tuple(epoch.epoch for epoch in first.epochs) == (8, 9, 10, 11)
    assert all(len(epoch.rows) == 10 for epoch in first.epochs)
    assert all(row.target_epoch == epoch.epoch for epoch in first.epochs for row in epoch.rows)
    assert all(
        batch.task.epoch == epoch.epoch - 1
        for epoch in first.epochs
        for row in epoch.rows
        for batch in row.task_batches
    )
    assert len({epoch.epoch_lineage_hash for epoch in first.epochs}) == 4


def test_multiepoch_artifact_binds_plan_contract_config_model_dataset_and_source(tmp_path: Path):
    artifact = _run(tmp_path)

    assert artifact.plan_hash == artifact.base_plan.plan_hash
    assert artifact.contract_hash == artifact.base_plan.contract_hash
    assert len(artifact.base_plan.base_source_closure_hash) == 64
    assert artifact.run_config_hash == artifact.base_plan.run_config_hash
    assert artifact.model_hash == artifact.base_plan.model_hash
    assert artifact.dataset_hash == artifact.base_plan.dataset_hash
    assert len(artifact.source_closure_hash) == 64
    assert len(artifact.artifact_lineage_hash) == 64
    assert artifact.epoch_count == 4


def test_loader_rejects_tampered_epoch_row_and_noncanonical_json(tmp_path: Path):
    from poi_mpp.experiments.e8_multiepoch import load_e8_multiepoch_artifact

    artifact_path = tmp_path / "e8_multiepoch.json"
    _run(tmp_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["epochs"][0]["rows"][0]["seed"] += 1
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="deterministic replay|lineage|contract"):
        load_e8_multiepoch_artifact(artifact_path)

    _run(tmp_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="canonical JSON"):
        load_e8_multiepoch_artifact(artifact_path)


def test_loader_accepts_exact_canonical_deterministic_replay(tmp_path: Path):
    from poi_mpp.experiments.e8_multiepoch import load_e8_multiepoch_artifact

    artifact_path = tmp_path / "e8_multiepoch.json"
    expected = _run(tmp_path)

    assert load_e8_multiepoch_artifact(artifact_path) == expected


def test_multiepoch_runner_rejects_symlinked_plan_and_output(tmp_path: Path):
    from poi_mpp.experiments.e8_multiepoch import load_and_run_e8_multiepoch

    plan_link = tmp_path / "plan.yaml"
    plan_link.symlink_to(PLAN_PATH)
    with pytest.raises(ValueError, match="symlink"):
        load_and_run_e8_multiepoch(plan_link)

    output_target = tmp_path / "target.json"
    output_target.write_text("{}\n", encoding="utf-8")
    output_link = tmp_path / "output.json"
    output_link.symlink_to(output_target)
    with pytest.raises(ValueError, match="symlink"):
        load_and_run_e8_multiepoch(PLAN_PATH, output_path=output_link)


def test_multiepoch_contract_fails_closed_on_origin_or_epoch_policy_tamper(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_confirmatory_contract

    contract_payload = (REPO_ROOT / "configs/confirmatory/e8.yaml").read_text(encoding="utf-8")
    synthetic = tmp_path / "synthetic.yaml"
    synthetic.write_text(
        contract_payload.replace(
            "required_run_origin: REPRODUCIBLE_SIMULATION",
            "required_run_origin: SYNTHETIC_NON_EVIDENCE",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="REPRODUCIBLE_SIMULATION"):
        load_e8_confirmatory_contract(synthetic)

    too_short = tmp_path / "too-short.yaml"
    too_short.write_text(contract_payload.replace("epoch_count: 4", "epoch_count: 1"), encoding="utf-8")
    with pytest.raises(ValueError, match="epoch_count"):
        load_e8_confirmatory_contract(too_short)


def test_multiepoch_loader_rejects_hardlinked_artifact(tmp_path: Path):
    from poi_mpp.experiments.e8_multiepoch import load_e8_multiepoch_artifact

    original = tmp_path / "e8_multiepoch.json"
    _run(tmp_path)
    hardlink = tmp_path / "hardlink.json"
    os.link(original, hardlink)
    with pytest.raises(ValueError, match="hardlink"):
        load_e8_multiepoch_artifact(hardlink)
