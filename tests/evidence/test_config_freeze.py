from pathlib import Path

import pytest
from pydantic import ValidationError

from poi_mpp.evidence.config import RunConfig, load_run_config, schema_hash


_HASH = "a" * 64


def _valid_config() -> dict[str, object]:
    return {
        "schema_version": "POI_MPP_RUN_CONFIG_V1",
        "run_id": "run-001",
        "experiment_id": "E1",
        "origin": "REPRODUCIBLE_SIMULATION",
        "authorization_scope": "LOCAL_TEST_ONLY",
        "model_hash": _HASH,
        "dataset_hash": "b" * 64,
        "parent_hashes": ["c" * 64],
        "data_availability": {
            "total_shards": 16,
            "samples": 8,
            "replacement": False,
        },
    }


def test_invalid_da_sample_count_is_rejected(tmp_path: Path):
    path = tmp_path / "run.yaml"
    path.write_text(
        "data_availability:\n  total_shards: 16\n  samples: 32\n  replacement: false\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="samples cannot exceed total_shards"):
        load_run_config(path)


def test_loader_rejects_unknown_keys_and_preserves_no_implicit_corrections(tmp_path: Path):
    path = tmp_path / "run.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: POI_MPP_RUN_CONFIG_V1",
                "run_id: run-001",
                "experiment_id: E1",
                "origin: REPRODUCIBLE_SIMULATION",
                "authorization_scope: LOCAL_TEST_ONLY",
                f"model_hash: {_HASH}",
                f"dataset_hash: {'b' * 64}",
                "parent_hashes:",
                f"  - {'c' * 64}",
                "data_availability:",
                "  total_shards: 16",
                "  samples: 8",
                "  replacement: false",
                "unexpected: rejected",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown configuration fields"):
        load_run_config(path)


def test_run_config_is_frozen_and_rejects_non_sha256_values():
    with pytest.raises(ValidationError):
        RunConfig.model_validate({**_valid_config(), "schema_hash": "not-a-digest"})

    config = RunConfig.model_validate({**_valid_config(), "schema_hash": schema_hash()})
    with pytest.raises(ValidationError):
        config.run_id = "changed"


def test_direct_construction_rejects_a_foreign_schema_hash():
    with pytest.raises(ValueError, match="approved run configuration schema"):
        RunConfig.model_validate({**_valid_config(), "schema_hash": _HASH})


def test_valid_loaded_config_binds_the_exact_schema_hash(tmp_path: Path):
    path = tmp_path / "run.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: POI_MPP_RUN_CONFIG_V1",
                "run_id: run-001",
                "experiment_id: E1",
                "origin: REPRODUCIBLE_SIMULATION",
                "authorization_scope: LOCAL_TEST_ONLY",
                f"model_hash: {_HASH}",
                f"dataset_hash: {'b' * 64}",
                "parent_hashes:",
                f"  - {'c' * 64}",
                "data_availability:",
                "  total_shards: 16",
                "  samples: 8",
                "  replacement: false",
            ]
        ),
        encoding="utf-8",
    )

    config = load_run_config(path)

    assert config.schema_hash != ""
    assert config.data_availability.samples == 8


def test_loader_cannot_select_a_foreign_schema_path(tmp_path: Path):
    config_path = tmp_path / "run.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: POI_MPP_RUN_CONFIG_V1",
                "run_id: run-001",
                "experiment_id: E1",
                "origin: REPRODUCIBLE_SIMULATION",
                "authorization_scope: LOCAL_TEST_ONLY",
                f"model_hash: {_HASH}",
                f"dataset_hash: {'b' * 64}",
                "data_availability:",
                "  total_shards: 16",
                "  samples: 8",
                "  replacement: false",
            ]
        ),
        encoding="utf-8",
    )
    foreign_schema = tmp_path / "foreign-schema.json"
    foreign_schema.write_text('{"type":"object"}', encoding="utf-8")

    with pytest.raises(TypeError):
        load_run_config(config_path, schema_path=foreign_schema)

    assert load_run_config(config_path).schema_hash == schema_hash()
