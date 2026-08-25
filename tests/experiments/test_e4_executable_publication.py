from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from poi_mpp.evidence import EvidenceOrigin
from poi_mpp.experiments.e4_execution import (
    E4_EXECUTION_METHOD_BOUNDARY,
    E4ExecutionError,
    execute_e4_reconstruction_simulation,
    load_e4_execution_config,
    replay_e4_reconstruction_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "configs" / "confirmatory" / "e4.v2.yaml"
CLI_PATH = REPO_ROOT / "experiments" / "e4_executable_da.py"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("e4_executable_da_cli", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_frozen_v2_config_declares_executable_reproducible_simulation_scope() -> None:
    config = load_e4_execution_config(CONFIG_PATH)

    assert config.experiment_id == "E4"
    assert config.origin is EvidenceOrigin.REPRODUCIBLE_SIMULATION
    assert config.method_boundary == E4_EXECUTION_METHOD_BOUNDARY
    assert config.claim_id == "C4"
    assert config.claim_disposition == "INCONCLUSIVE"
    assert config.seed == 424242
    assert {scenario.kind.value for scenario in config.scenarios} == {
        "HONEST_NEGATIVE_CONTROL",
        "RANDOM_WITHHOLDING",
        "TARGETED_WITHHOLDING",
        "CORRUPT_SHARD",
        "DUPLICATE_SHARD",
        "REORDERED_SHARD",
        "SELECTIVE_SERVICE",
    }


def test_config_rejects_real_or_synthetic_origin_and_duplicate_scenarios(tmp_path: Path) -> None:
    raw = CONFIG_PATH.read_text(encoding="utf-8")
    for forbidden_origin in ("REAL_MODEL_EXECUTION", "SYNTHETIC_NON_EVIDENCE"):
        path = tmp_path / f"{forbidden_origin}.yaml"
        path.write_text(
            raw.replace("origin: REPRODUCIBLE_SIMULATION", f"origin: {forbidden_origin}"),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="REPRODUCIBLE_SIMULATION"):
            load_e4_execution_config(path)

    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(
        raw.replace("scenario_id: random-withholding", "scenario_id: honest-negative-control"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique scenario_id"):
        load_e4_execution_config(duplicate)

    insufficient = tmp_path / "insufficient-withholding.yaml"
    insufficient.write_text(
        raw.replace(
            "scenario_id: random-withholding\n    kind: RANDOM_WITHHOLDING\n    seed_offset: 11\n    expected_status: WITHHELD\n    mutation_count: 4",
            "scenario_id: random-withholding\n    kind: RANDOM_WITHHOLDING\n    seed_offset: 11\n    expected_status: WITHHELD\n    mutation_count: 3",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cross reconstruction threshold"):
        load_e4_execution_config(insufficient)


def test_execute_performs_all_local_reconstruction_scenarios_and_preserves_negative_control(
    tmp_path: Path,
) -> None:
    result = execute_e4_reconstruction_simulation(
        config_path=CONFIG_PATH,
        output_root=tmp_path / "e4-run",
    )

    rows = {row.scenario_id: row for row in result.rows}
    assert rows["honest-negative-control"].actual_status == "VERIFIED"
    assert rows["random-withholding"].actual_status == "WITHHELD"
    assert rows["targeted-withholding"].actual_status == "WITHHELD"
    assert rows["corrupt-shard"].actual_status == "CORRUPT"
    assert rows["duplicate-shard"].actual_status == "CORRUPT"
    assert rows["reordered-shard"].actual_status == "CORRUPT"
    assert rows["selective-service"].actual_status == "SELECTIVE_SERVICE"
    assert rows["random-withholding"].sampling_mode == "STATIC_WITHOUT_REPLACEMENT"
    assert rows["targeted-withholding"].sampling_mode == "TARGETED_WITHHOLDING"
    assert rows["corrupt-shard"].sampling_mode == "CORRELATED_LOSS"
    assert rows["selective-service"].sampling_mode == "SELECTIVE_SERVING"
    assert all(row.assumption_label for row in rows.values())
    assert all(row.expected_outcome_detected for row in rows.values())
    assert rows["random-withholding"].missing_indices
    assert rows["targeted-withholding"].missing_indices
    assert rows["corrupt-shard"].corrupt_indices
    assert rows["duplicate-shard"].corrupt_indices
    assert rows["reordered-shard"].corrupt_indices
    assert rows["selective-service"].omitted_indices
    assert result.summary.claim_disposition == "INCONCLUSIVE"
    assert result.summary.origin == EvidenceOrigin.REPRODUCIBLE_SIMULATION.value
    assert result.summary.method_boundary == E4_EXECUTION_METHOD_BOUNDARY


def test_execution_writes_hash_bound_raw_provenance_and_manifest(tmp_path: Path) -> None:
    output_root = tmp_path / "e4-run"
    result = execute_e4_reconstruction_simulation(
        config_path=CONFIG_PATH,
        output_root=output_root,
    )

    provenance = _load_json(result.provenance_path)
    manifest = _load_json(result.manifest_path)
    assert provenance["origin"] == "REPRODUCIBLE_SIMULATION"
    assert provenance["method_boundary"] == E4_EXECUTION_METHOD_BOUNDARY
    assert len(provenance["config_hash"]) == 64
    assert len(provenance["model_hash"]) == 64
    assert len(provenance["data_hash"]) == 64
    assert provenance["seed"] == 424242
    assert provenance["claim_disposition"] == "INCONCLUSIVE"
    assert manifest["schema_version"] == "POI_MPP_E4_EXECUTION_MANIFEST_V2"
    assert manifest["files"] == sorted(manifest["files"], key=lambda item: item["path"])
    assert all(not item["path"].startswith("/") for item in manifest["files"])
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])
    assert all(str(tmp_path) not in json.dumps(item) for item in manifest["files"])
    assert any(item["path"].endswith("/shards/0000.bin") for item in manifest["files"])


def test_execution_is_byte_deterministic_across_distinct_output_roots(tmp_path: Path) -> None:
    first = execute_e4_reconstruction_simulation(
        config_path=CONFIG_PATH,
        output_root=tmp_path / "first",
    )
    second = execute_e4_reconstruction_simulation(
        config_path=CONFIG_PATH,
        output_root=tmp_path / "second",
    )

    assert first.artifact_hash == second.artifact_hash
    first_files = {
        path.relative_to(first.output_root): path.read_bytes()
        for path in first.output_root.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second.output_root): path.read_bytes()
        for path in second.output_root.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files
    assert replay_e4_reconstruction_artifacts(first.output_root).artifact_hash == first.artifact_hash


def test_replay_rejects_tampered_rows_and_shards(tmp_path: Path) -> None:
    first_root = tmp_path / "rows-tamper"
    first = execute_e4_reconstruction_simulation(config_path=CONFIG_PATH, output_root=first_root)
    first.rows_path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(E4ExecutionError, match="manifest hash mismatch"):
        replay_e4_reconstruction_artifacts(first_root)

    second_root = tmp_path / "shard-tamper"
    execute_e4_reconstruction_simulation(config_path=CONFIG_PATH, output_root=second_root)
    shard = second_root / "raw" / "honest-negative-control" / "store" / "shards" / "0000.bin"
    shard.write_bytes(b"tampered")
    with pytest.raises(E4ExecutionError, match="manifest hash mismatch"):
        replay_e4_reconstruction_artifacts(second_root)


def test_output_root_rejects_symlinks_repo_root_and_nonempty_directories(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(E4ExecutionError, match="symlink"):
        execute_e4_reconstruction_simulation(config_path=CONFIG_PATH, output_root=linked)

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    canonicalized = execute_e4_reconstruction_simulation(
        config_path=CONFIG_PATH,
        output_root=linked_parent / "child",
    )
    assert canonicalized.output_root == (real_parent / "child").resolve()
    assert canonicalized.manifest_path.is_file()

    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "keep.txt").write_text("user-data", encoding="utf-8")
    with pytest.raises(E4ExecutionError, match="empty"):
        execute_e4_reconstruction_simulation(config_path=CONFIG_PATH, output_root=nonempty)
    assert (nonempty / "keep.txt").read_text(encoding="utf-8") == "user-data"

    with pytest.raises(E4ExecutionError, match="repository root"):
        execute_e4_reconstruction_simulation(config_path=CONFIG_PATH, output_root=REPO_ROOT)


def test_cli_validate_is_read_only_and_execute_requires_an_empty_output_root(tmp_path: Path) -> None:
    module = _load_cli_module()
    output_root = tmp_path / "run"

    assert module.main(["validate", "--config", str(CONFIG_PATH)]) == 0
    assert not output_root.exists()
    assert module.main(
        ["execute", "--config", str(CONFIG_PATH), "--output-root", str(output_root)]
    ) == 0
    assert (output_root / "manifest.json").is_file()
    assert module.main(
        ["execute", "--config", str(CONFIG_PATH), "--output-root", str(output_root)]
    ) == 2
