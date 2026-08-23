from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from functools import partial
from pathlib import Path

import pytest

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
from poi_mpp.worker.inference import AdapterRunResult, TransformersCausalLMAdapter
from poi_mpp.worker.inference import execute_once
from poi_mpp.worker.model_manifest import PinnedModelManifest
from poi_mpp.worker.real_transformers import (
    AuthorizedLocalTransformersSession,
    _extract_prompt_token_ids,
    _generation_kwargs,
    _response_binding,
    authorized_local_transformers_loader,
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FakeBatchEncoding(Mapping[str, object]):
    """Minimal non-dict mapping matching the Transformers BatchEncoding boundary."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __getitem__(self, key: str) -> object:
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)


def test_extract_prompt_token_ids_accepts_batch_encoding_mapping() -> None:
    assert _extract_prompt_token_ids(FakeBatchEncoding({"input_ids": [17, 23, 42]})) == (
        17,
        23,
        42,
    )
    assert _extract_prompt_token_ids(FakeBatchEncoding({"input_ids": [[17, 23, 42]]})) == (
        17,
        23,
        42,
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "sequence input_ids"),
        ({"input_ids": []}, "empty input_ids"),
        ({"input_ids": [[1], [2]]}, "exactly one input sequence"),
        ({"input_ids": [1, True]}, "non-negative integers"),
        ({"input_ids": [1, -2]}, "non-negative integers"),
        ({"input_ids": "1,2"}, "sequence input_ids"),
    ],
)
def test_extract_prompt_token_ids_rejects_malformed_batch_encoding(
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        _extract_prompt_token_ids(FakeBatchEncoding(payload))


def test_greedy_generation_omits_sampling_only_parameters(policy) -> None:
    kwargs = _generation_kwargs(policy)

    assert kwargs == {
        "max_new_tokens": 24,
        "do_sample": False,
        "repetition_penalty": 1.0,
    }
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs


class FakeRuntime:
    runtime_name = "transformers"
    runtime_version = "5.14.1"

    def __init__(
        self,
        *,
        model_revision: str,
        tokenizer_revision: str,
        response: str = "Deterministic local answer.",
        generated_token_ids: tuple[int, ...] = (101, 102, 103),
    ) -> None:
        self.model_revision = model_revision
        self.tokenizer_revision = tokenizer_revision
        self.response = response
        self.generated_token_ids = generated_token_ids
        self.model_loads = 0
        self.tokenizer_loads = 0
        self.last_use_safetensors: bool | None = None

    def load_model(self, *, model_path: str, revision: str, local_files_only: bool, use_safetensors: bool, precision: str) -> dict[str, object]:
        self.model_loads += 1
        self.last_use_safetensors = use_safetensors
        return {
            "kind": "model",
            "model_path": model_path,
            "revision": revision,
            "local_files_only": local_files_only,
            "use_safetensors": use_safetensors,
            "precision": precision,
        }

    def load_tokenizer(self, *, tokenizer_path: str, revision: str, local_files_only: bool) -> dict[str, object]:
        self.tokenizer_loads += 1
        return {
            "kind": "tokenizer",
            "tokenizer_path": tokenizer_path,
            "revision": revision,
            "local_files_only": local_files_only,
        }

    def resolve_model_revision(self, loaded_model: object) -> str | None:
        del loaded_model
        return self.model_revision

    def resolve_tokenizer_revision(self, loaded_tokenizer: object) -> str | None:
        del loaded_tokenizer
        return self.tokenizer_revision

    def encode_task(self, loaded_tokenizer: object, task: object) -> tuple[int, ...]:
        del loaded_tokenizer
        return (int(task.task_id), int(task.epoch), int(task.credit_budget))

    def generate(self, loaded_model: object, prompt_token_ids: tuple[int, ...], policy: DeterministicDecodePolicy) -> tuple[int, ...]:
        del loaded_model, prompt_token_ids, policy
        return self.generated_token_ids

    def decode(self, loaded_tokenizer: object, token_ids: tuple[int, ...]) -> str:
        del loaded_tokenizer, token_ids
        return self.response


def _manifest_for_paths(
    model_path: Path,
    tokenizer_path: Path,
    *,
    revision: str = "9" * 40,
    tokenizer_revision: str = "9" * 40,
    include_model_sidecar: bool = False,
    include_tokenizer_sidecar: bool = False,
) -> PinnedModelManifest:
    model_hashes = {
        "model.safetensors": _sha256_text(model_path.joinpath("model.safetensors").read_text(encoding="utf-8"))
    }
    tokenizer_hashes = {
        "tokenizer.json": _sha256_text(tokenizer_path.joinpath("tokenizer.json").read_text(encoding="utf-8"))
    }
    if include_model_sidecar:
        model_hashes["POI_MODEL_REVISION.json"] = _sha256_text(
            model_path.joinpath("POI_MODEL_REVISION.json").read_text(encoding="utf-8")
        )
    if include_tokenizer_sidecar:
        tokenizer_hashes["POI_MODEL_REVISION.json"] = _sha256_text(
            tokenizer_path.joinpath("POI_MODEL_REVISION.json").read_text(encoding="utf-8")
        )
    return PinnedModelManifest(
        model_id="local-qwen-1.5b",
        repository="Qwen/Qwen2.5-1.5B-Instruct",
        revision=revision,
        tokenizer_id="Qwen/Qwen2.5-1.5B-Instruct",
        tokenizer_revision=tokenizer_revision,
        license_id="apache-2.0",
        parameter_scale="1.5B",
        precision="bfloat16",
        quantization="none",
        runtime_name="transformers",
        runtime_version="5.14.1",
        model_file_hashes=model_hashes,
        tokenizer_file_hashes=tokenizer_hashes,
    )


def _write_revision_sidecar(path: Path, *, repository: str, revision: str, tokenizer_revision: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "POI_MPP_MODEL_REVISION_SIDECAR_V1",
                "repository": repository,
                "revision": revision,
                "tokenizer_revision": tokenizer_revision,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def policy() -> DeterministicDecodePolicy:
    return DeterministicDecodePolicy(seed=7, max_new_tokens=24)


@pytest.fixture(autouse=True)
def offline_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")


def test_loader_fails_closed_when_runtime_is_missing(task, policy: DeterministicDecodePolicy, tmp_path: Path) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("actual-model-weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("actual-tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path)

    def missing_runtime() -> object:
        raise ImportError("transformers is not installed")

    with pytest.raises(RuntimeError, match="runtime is unavailable"):
        authorized_local_transformers_loader(
            model_path=str(model_path),
            tokenizer_path=str(tokenizer_path),
            local_files_only=True,
            manifest=manifest,
            policy=policy,
            task=task,
            runtime_factory=missing_runtime,
        )


def test_loader_rejects_model_file_hash_mismatch(task, policy: DeterministicDecodePolicy, tmp_path: Path) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("actual-model-weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("actual-tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path).model_copy(
        update={"model_file_hashes": {"model.safetensors": "0" * 64}}
    )

    with pytest.raises(ValueError, match="model_file_hashes"):
        authorized_local_transformers_loader(
            model_path=str(model_path),
            tokenizer_path=str(tokenizer_path),
            local_files_only=True,
            manifest=manifest,
            policy=policy,
            task=task,
            runtime_factory=lambda: FakeRuntime(
                model_revision=manifest.revision,
                tokenizer_revision=manifest.tokenizer_revision,
            ),
        )


def test_loader_rejects_revision_mismatch(task, policy: DeterministicDecodePolicy, tmp_path: Path) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("actual-model-weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("actual-tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path)

    with pytest.raises(ValueError, match="revision"):
        authorized_local_transformers_loader(
            model_path=str(model_path),
            tokenizer_path=str(tokenizer_path),
            local_files_only=True,
            manifest=manifest,
            policy=policy,
            task=task,
            runtime_factory=lambda: FakeRuntime(
                model_revision="1" * 40,
                tokenizer_revision=manifest.tokenizer_revision,
            ),
        )


def test_loader_requires_sidecar_when_runtime_revision_is_unavailable(
    task,
    policy: DeterministicDecodePolicy,
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("actual-model-weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("actual-tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path)

    with pytest.raises(ValueError, match="POI_MODEL_REVISION.json is required"):
        authorized_local_transformers_loader(
            model_path=str(model_path),
            tokenizer_path=str(tokenizer_path),
            local_files_only=True,
            manifest=manifest,
            policy=policy,
            task=task,
            runtime_factory=lambda: FakeRuntime(
                model_revision=None,
                tokenizer_revision=manifest.tokenizer_revision,
            ),
        )


def test_loader_rejects_mismatched_revision_sidecar(
    task,
    policy: DeterministicDecodePolicy,
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("actual-model-weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("actual-tokenizer", encoding="utf-8")
    _write_revision_sidecar(
        model_path / "POI_MODEL_REVISION.json",
        repository="Qwen/Qwen2.5-1.5B-Instruct",
        revision="1" * 40,
        tokenizer_revision="9" * 40,
    )
    manifest = _manifest_for_paths(
        model_path,
        tokenizer_path,
        include_model_sidecar=True,
    )

    with pytest.raises(ValueError, match="revision sidecar does not match pinned manifest"):
        authorized_local_transformers_loader(
            model_path=str(model_path),
            tokenizer_path=str(tokenizer_path),
            local_files_only=True,
            manifest=manifest,
            policy=policy,
            task=task,
            runtime_factory=lambda: FakeRuntime(
                model_revision=None,
                tokenizer_revision=manifest.tokenizer_revision,
            ),
        )


def test_loader_accepts_verified_revision_sidecars_when_runtime_revisions_are_unavailable(
    task,
    policy: DeterministicDecodePolicy,
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("actual-model-weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("actual-tokenizer", encoding="utf-8")
    _write_revision_sidecar(
        model_path / "POI_MODEL_REVISION.json",
        repository="Qwen/Qwen2.5-1.5B-Instruct",
        revision="9" * 40,
        tokenizer_revision="9" * 40,
    )
    _write_revision_sidecar(
        tokenizer_path / "POI_MODEL_REVISION.json",
        repository="Qwen/Qwen2.5-1.5B-Instruct",
        revision="9" * 40,
        tokenizer_revision="9" * 40,
    )
    manifest = _manifest_for_paths(
        model_path,
        tokenizer_path,
        include_model_sidecar=True,
        include_tokenizer_sidecar=True,
    )

    result = authorized_local_transformers_loader(
        model_path=str(model_path),
        tokenizer_path=str(tokenizer_path),
        local_files_only=True,
        manifest=manifest,
        policy=policy,
        task=task,
        runtime_factory=lambda: FakeRuntime(
            model_revision=None,
            tokenizer_revision=None,
            response="Sidecar-backed deterministic answer.",
        ),
    )

    assert result.loaded_manifest == manifest
    assert result.response == "Sidecar-backed deterministic answer."


def test_loader_returns_adapter_run_result_for_authorized_local_execution(
    task,
    policy: DeterministicDecodePolicy,
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("actual-model-weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("actual-tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path)
    fake_runtime = FakeRuntime(
        model_revision=manifest.revision,
        tokenizer_revision=manifest.tokenizer_revision,
        response="Local deterministic answer.",
        generated_token_ids=(401, 402),
    )
    clock_points = iter((10.0, 10.25, 10.25, 11.0))

    adapter = TransformersCausalLMAdapter(
        model_path=str(model_path),
        tokenizer_path=str(tokenizer_path),
        loader=partial(
            authorized_local_transformers_loader,
            runtime_factory=lambda: fake_runtime,
            clock=lambda: next(clock_points),
        ),
    )

    result = adapter.run(task=task, manifest=manifest, policy=policy)

    assert isinstance(result, AdapterRunResult)
    assert result.loaded_manifest == manifest
    assert result.response == "Local deterministic answer."
    assert result.warmup_ms == pytest.approx(250.0)
    assert result.inference_ms == pytest.approx(750.0)
    assert len(result.trace_events) == 2
    assert all(event.metadata["surface"] == EvidenceOrigin.REAL_MODEL_EXECUTION.value for event in result.trace_events)
    assert all(item.origin is EvidenceOrigin.REAL_MODEL_EXECUTION for item in result.evidence_items)
    assert result.evidence_items[0].artifact_label == "execution-transcript-binding"
    assert result.evidence_items[0].content == _response_binding(result.response)
    assert fake_runtime.last_use_safetensors is True


def test_session_reuses_one_loaded_model_and_tokenizer(task, policy, tmp_path: Path) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("actual-model-weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("actual-tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path)
    runtime = FakeRuntime(model_revision=manifest.revision, tokenizer_revision=manifest.tokenizer_revision)
    ticks = iter((1.0, 1.2, 1.3, 1.5, 1.6, 1.9))
    session = AuthorizedLocalTransformersSession(runtime_factory=lambda: runtime, clock=lambda: next(ticks))

    first = session(model_path=str(model_path), tokenizer_path=str(tokenizer_path), local_files_only=True, manifest=manifest, policy=policy, task=task)
    second = session(model_path=str(model_path), tokenizer_path=str(tokenizer_path), local_files_only=True, manifest=manifest, policy=policy, task=task)

    assert session.load_count == 1
    assert runtime.model_loads == 1
    assert runtime.tokenizer_loads == 1
    assert first.warmup_ms == pytest.approx(200.0)
    assert second.warmup_ms == 0.0
    assert first.inference_ms == pytest.approx(200.0)
    assert second.inference_ms == pytest.approx(300.0)


def test_loader_requires_offline_flags(task, policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path)
    with pytest.raises(RuntimeError, match="HF_HUB_OFFLINE"):
        authorized_local_transformers_loader(model_path=str(model_path), tokenizer_path=str(tokenizer_path), local_files_only=True, manifest=manifest, policy=policy, task=task, runtime_factory=lambda: FakeRuntime(model_revision=manifest.revision, tokenizer_revision=manifest.tokenizer_revision))


def test_loader_rejects_alternate_weight_format(task, policy, tmp_path: Path) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("weights", encoding="utf-8")
    (model_path / "pytorch_model.bin").write_text("alternate", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path)
    with pytest.raises(ValueError, match="safetensors-only"):
        authorized_local_transformers_loader(model_path=str(model_path), tokenizer_path=str(tokenizer_path), local_files_only=True, manifest=manifest, policy=policy, task=task, runtime_factory=lambda: FakeRuntime(model_revision=manifest.revision, tokenizer_revision=manifest.tokenizer_revision))


def test_loader_rejects_tokenizer_revision_mismatch(task, policy, tmp_path: Path) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path)
    with pytest.raises(ValueError, match="tokenizer_revision"):
        authorized_local_transformers_loader(
            model_path=str(model_path),
            tokenizer_path=str(tokenizer_path),
            local_files_only=True,
            manifest=manifest,
            policy=policy,
            task=task,
            runtime_factory=lambda: FakeRuntime(
                model_revision=manifest.revision,
                tokenizer_revision="1" * 40,
            ),
        )


def test_loader_rejects_runtime_version_outside_manifest(task, policy, tmp_path: Path) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path).model_copy(
        update={"runtime_version": "0.0.1"}
    )
    ledger = tmp_path / "ledger.sha256"
    ledger.write_text(
        "0" * 64 + "  transformers-0.0.1-py3-none-any.whl\n"
        "1" * 64 + "  safetensors-0.8.0-py3-none-any.whl\n"
        "2" * 64 + "  tokenizers-0.22.2-py3-none-any.whl\n"
        "3" * 64 + "  torch-2.13.0-py3-none-any.whl\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="runtime_version"):
        authorized_local_transformers_loader(
            model_path=str(model_path),
            tokenizer_path=str(tokenizer_path),
            local_files_only=True,
            manifest=manifest,
            policy=policy,
            task=task,
            runtime_ledger_path=ledger,
            runtime_factory=lambda: FakeRuntime(
                model_revision=manifest.revision,
                tokenizer_revision=manifest.tokenizer_revision,
            ),
        )


def test_loader_rejects_unreviewed_runtime_ledger(task, policy, tmp_path: Path) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path)
    ledger = tmp_path / "ledger.sha256"
    ledger.write_text("0" * 64 + "  transformers-5.14.1-py3-none-any.whl\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not cover"):
        authorized_local_transformers_loader(
            model_path=str(model_path),
            tokenizer_path=str(tokenizer_path),
            local_files_only=True,
            manifest=manifest,
            policy=policy,
            task=task,
            runtime_ledger_path=ledger,
            runtime_factory=lambda: FakeRuntime(
                model_revision=manifest.revision,
                tokenizer_revision=manifest.tokenizer_revision,
            ),
        )


def test_multilingual_transcript_keeps_exact_response_and_deterministic_roots(
    task,
    policy,
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "model"
    tokenizer_path = tmp_path / "tokenizer"
    model_path.mkdir()
    tokenizer_path.mkdir()
    (model_path / "model.safetensors").write_text("weights", encoding="utf-8")
    (tokenizer_path / "tokenizer.json").write_text("tokenizer", encoding="utf-8")
    manifest = _manifest_for_paths(model_path, tokenizer_path)
    response = "可验证的智能证明。" * 20
    runtime = FakeRuntime(
        model_revision=manifest.revision,
        tokenizer_revision=manifest.tokenizer_revision,
        response=response,
        generated_token_ids=(70001, 70002, 70003),
    )
    ticks = iter((1.0, 1.1, 1.2, 1.3, 2.0, 2.4))
    session = AuthorizedLocalTransformersSession(
        runtime_factory=lambda: runtime,
        clock=lambda: next(ticks),
    )
    adapter = TransformersCausalLMAdapter(
        model_path=str(model_path),
        tokenizer_path=str(tokenizer_path),
        loader=session,
    )

    first = execute_once(task, manifest, policy, adapter=adapter)
    second = execute_once(task, manifest, policy, adapter=adapter)

    assert first.response == response
    assert first.response_hash == _response_binding(response)
    assert first.iec.evidence_items[0].content == first.response_hash
    assert first.iec.evidence_items[0].origin is EvidenceOrigin.REAL_MODEL_EXECUTION
    transcript_metadata = first.trace_sidecar.events[0].metadata
    transcript_hex = "".join(
        transcript_metadata[f"transcript_utf8_hex_{index:04d}"]
        for index in range(transcript_metadata["transcript_chunk_count"])
    )
    assert transcript_metadata["transcript_chunk_count"] > 1
    assert bytes.fromhex(transcript_hex).decode("utf-8") == response
    assert transcript_metadata["response_hash"] == first.response_hash
    assert first.response_hash == second.response_hash
    assert first.trace_root == second.trace_root
    assert first.evidence_root == second.evidence_root
    assert first.artifact_root == second.artifact_root
