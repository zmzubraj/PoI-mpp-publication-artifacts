from __future__ import annotations

import pytest

from poi_mpp.evidence.models import ArtifactStage, EvidenceOrigin
from poi_mpp.protocol.types import ModelManifest as ProtocolModelManifest
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
from poi_mpp.worker.inference import FixtureInferenceAdapter, TransformersCausalLMAdapter, execute_once
from poi_mpp.worker.model_manifest import PinnedModelManifest


@pytest.fixture()
def policy() -> DeterministicDecodePolicy:
    return DeterministicDecodePolicy(seed=7, max_new_tokens=24)


@pytest.fixture()
def manifest() -> PinnedModelManifest:
    revision = "1" * 40
    tokenizer_revision = "2" * 40
    return PinnedModelManifest(
        model_id="fixture-qwen-1.5b",
        repository="Qwen/Qwen2.5-1.5B-Instruct",
        revision=revision,
        tokenizer_id="Qwen/Qwen2.5-1.5B-Instruct",
        tokenizer_revision=tokenizer_revision,
        license_id="apache-2.0",
        parameter_scale="1.5B",
        precision="int4",
        quantization="q4_k_m",
        runtime_name="transformers",
        runtime_version="4.44.0",
        model_file_hashes={"model.safetensors": "a" * 64},
        tokenizer_file_hashes={"tokenizer.json": "b" * 64},
    )


def test_execute_once_is_deterministic_for_same_inputs(
    task,
    manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
) -> None:
    adapter = FixtureInferenceAdapter.synthetic(
        response="Deterministic answer. Evidence sentence.",
        trace_token_ids=(11, 12),
        evidence_texts=("Evidence sentence.",),
    )

    first = execute_once(task, manifest, policy, adapter=adapter)
    second = execute_once(task, manifest, policy, adapter=adapter)

    assert first == second
    assert first.response_hash.startswith("0x")
    assert first.trace_root.startswith("0x")
    assert first.evidence_root.startswith("0x")
    assert first.artifact_root.startswith("0x")
    assert all(ref.record.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE for ref in first.retained_artifacts)
    assert all(ref.record.stage is ArtifactStage.GENERATED for ref in first.retained_artifacts)


def test_execute_once_rejects_model_revision_mismatch(
    task,
    manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
) -> None:
    adapter = FixtureInferenceAdapter.synthetic(
        response="Mismatch",
        trace_token_ids=(1,),
        evidence_texts=("Mismatch evidence.",),
        loaded_revision="3" * 40,
    )

    with pytest.raises(ValueError, match="revision"):
        execute_once(task, manifest, policy, adapter=adapter)


def test_execute_once_rejects_model_id_mismatch(
    task,
    manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
) -> None:
    loaded_manifest = manifest.model_copy(update={"model_id": "other-model"})
    adapter = FixtureInferenceAdapter.synthetic(
        response="Mismatch",
        trace_token_ids=(1,),
        evidence_texts=("Mismatch evidence.",),
        loaded_manifest=loaded_manifest,
    )

    with pytest.raises(ValueError, match="model_id"):
        execute_once(task, manifest, policy, adapter=adapter)


def test_execute_once_rejects_assurance_class_mismatch(
    task,
    manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
) -> None:
    loaded_manifest = manifest.model_copy(update={"assurance_class": 7})
    adapter = FixtureInferenceAdapter.synthetic(
        response="Mismatch",
        trace_token_ids=(1,),
        evidence_texts=("Mismatch evidence.",),
        loaded_manifest=loaded_manifest,
    )

    with pytest.raises(ValueError, match="assurance_class"):
        execute_once(task, manifest, policy, adapter=adapter)


def test_execute_once_rejects_nondeterministic_decode_policy(
    task,
    manifest: PinnedModelManifest,
) -> None:
    adapter = FixtureInferenceAdapter.synthetic(
        response="Nondeterministic",
        trace_token_ids=(1,),
        evidence_texts=("Evidence.",),
    )

    with pytest.raises(ValueError, match="deterministic"):
        execute_once(
            task,
            manifest,
            DeterministicDecodePolicy(seed=7, max_new_tokens=24, do_sample=True),
            adapter=adapter,
        )


def test_transformers_adapter_refuses_implicit_network_download() -> None:
    with pytest.raises(ValueError, match="local_files_only"):
        TransformersCausalLMAdapter(model_path="fixtures/model", local_files_only=False)


def test_execution_bundle_uses_typed_protocol_manifest(
    task,
    manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
) -> None:
    adapter = FixtureInferenceAdapter.synthetic(
        response="Typed answer. Evidence sentence.",
        trace_token_ids=(11, 12),
        evidence_texts=("Evidence sentence.",),
    )

    bundle = execute_once(task, manifest, policy, adapter=adapter)

    assert isinstance(bundle.protocol_model_manifest, ProtocolModelManifest)
