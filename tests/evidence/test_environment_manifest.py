import pytest
from pydantic import ValidationError

from poi_mpp.evidence.environment_manifest import (
    ExecutionEnvironmentManifestV1,
    ExecutionHardwareInventoryV1,
    ExecutionModelBindingV1,
    GenerationParametersV1,
)


def _word(seed: str) -> str:
    return seed * 64


def _model(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "model_id": "Qwen/Qwen2.5-1.5B-Instruct",
        "model_revision": "1" * 40,
        "model_weights_hash": _word("2"),
        "tokenizer_id": "Qwen/Qwen2.5-1.5B-Instruct",
        "tokenizer_revision": "1" * 40,
        "tokenizer_hash": _word("3"),
        "weight_access": "OPEN_WEIGHT",
        "parameter_count_billions": 1.5,
    }
    payload.update(overrides)
    return payload


def _runtime(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "python_version": "3.12.4",
        "framework_name": "transformers",
        "framework_version": "4.44.0",
        "dependency_lock_hash": _word("4"),
        "environment_sbom_digest": _word("5"),
    }
    payload.update(overrides)
    return payload


def _hardware(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "accelerator_label": "Apple M4 Pro",
        "accelerator_count": 1,
        "driver_version": "metal-1.0",
    }
    payload.update(overrides)
    return payload


def _deterministic(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "global_seed": 11,
        "inference_seed": 29,
        "local_files_only": True,
        "hash_check_enforced": True,
    }
    payload.update(overrides)
    return payload


def _generation(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "do_sample": False,
        "temperature": 0.0,
        "top_p": 1.0,
        "max_new_tokens": 256,
    }
    payload.update(overrides)
    return payload


def _manifest(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "POI_MPP_EXECUTION_ENVIRONMENT_MANIFEST_V1",
        "environment_id": "E3_CONFIRMATORY_ENVIRONMENT_V1",
        "model": _model(),
        "runtime": _runtime(),
        "hardware": _hardware(),
        "deterministic": _deterministic(),
        "generation": _generation(),
        "script_hashes": {
            "runner": _word("6"),
            "artifact_exporter": _word("7"),
        },
        "config_hashes": {
            "experiment_protocol": _word("8"),
            "generation_config": _word("9"),
        },
        "network_access": "LOCAL_ONLY",
        "external_services": (),
    }
    payload.update(overrides)
    return payload


def test_execution_environment_manifest_v1_is_frozen_and_forbids_unknown_fields() -> None:
    manifest = ExecutionEnvironmentManifestV1.model_validate(_manifest())

    with pytest.raises(ValidationError):
        manifest.environment_id = "mutated"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExecutionEnvironmentManifestV1.model_validate({**_manifest(), "unexpected": True})


def test_execution_environment_manifest_v1_hash_is_order_stable() -> None:
    first = ExecutionEnvironmentManifestV1.model_validate(_manifest())
    reordered = ExecutionEnvironmentManifestV1.model_validate(
        _manifest(
            script_hashes={"artifact_exporter": _word("7"), "runner": _word("6")},
            config_hashes={"generation_config": _word("9"), "experiment_protocol": _word("8")},
        )
    )
    mutated = ExecutionEnvironmentManifestV1.model_validate(
        _manifest(generation=_generation(max_new_tokens=512))
    )

    assert first.canonical_material() == reordered.canonical_material()
    assert first.environment_manifest_hash() == reordered.environment_manifest_hash()
    assert first.environment_manifest_hash() != mutated.environment_manifest_hash()


def test_execution_environment_manifest_v1_rejects_unpinned_or_out_of_scope_model_bindings() -> None:
    with pytest.raises(ValidationError, match="pinned 40- or 64-hex revision"):
        ExecutionEnvironmentManifestV1.model_validate(
            _manifest(model=_model(model_revision="main"))
        )

    with pytest.raises(ValidationError, match="1B-8B publication scope"):
        ExecutionEnvironmentManifestV1.model_validate(
            _manifest(model=_model(parameter_count_billions=8.5))
        )

    with pytest.raises(ValidationError, match="Input should be 'OPEN_WEIGHT'"):
        ExecutionEnvironmentManifestV1.model_validate(
            _manifest(model=_model(weight_access="CLOSED_WEIGHT"))
        )


def test_execution_environment_manifest_v1_rejects_missing_required_hash_bindings() -> None:
    with pytest.raises(ValidationError, match="script_hashes must not be empty"):
        ExecutionEnvironmentManifestV1.model_validate(_manifest(script_hashes={}))

    with pytest.raises(ValidationError, match="dependency_lock_hash"):
        ExecutionEnvironmentManifestV1.model_validate(
            _manifest(runtime=_runtime(dependency_lock_hash=""))
        )

    with pytest.raises(ValidationError, match="environment_sbom_digest"):
        ExecutionEnvironmentManifestV1.model_validate(
            _manifest(runtime=_runtime(environment_sbom_digest="not-a-hash"))
        )

    with pytest.raises(ValidationError, match="required script hash binding"):
        ExecutionEnvironmentManifestV1.model_validate(
            _manifest(script_hashes={"runner": _word("6")})
        )

    with pytest.raises(ValidationError, match="required config hash binding"):
        ExecutionEnvironmentManifestV1.model_validate(
            _manifest(config_hashes={"experiment_protocol": _word("8")})
        )


def test_execution_environment_manifest_v1_rejects_nonlocal_or_nondeterministic_execution() -> None:
    with pytest.raises(ValidationError, match="local_files_only must be true"):
        ExecutionEnvironmentManifestV1.model_validate(
            _manifest(deterministic=_deterministic(local_files_only=False))
        )

    with pytest.raises(ValidationError, match="do_sample must be false"):
        ExecutionEnvironmentManifestV1.model_validate(
            _manifest(generation=_generation(do_sample=True, temperature=0.7))
        )

    with pytest.raises(ValidationError, match="external_services must be empty"):
        ExecutionEnvironmentManifestV1.model_validate(
            _manifest(external_services=("huggingface_hub",))
        )


def test_execution_environment_manifest_v1_exports_component_models() -> None:
    model = ExecutionModelBindingV1.model_validate(_model(parameter_count_billions=8.0))
    hardware = ExecutionHardwareInventoryV1.model_validate(_hardware())
    generation = GenerationParametersV1.model_validate(_generation())

    assert model.weight_access == "OPEN_WEIGHT"
    assert model.parameter_count_billions == 8.0
    assert hardware.accelerator_count == 1
    assert generation.max_new_tokens == 256
