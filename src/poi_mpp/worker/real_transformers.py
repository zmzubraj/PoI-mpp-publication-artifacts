"""Authorized local-files-only Transformers loader for real worker execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Callable, Protocol

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.protocol.types import TaskSpec
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
from poi_mpp.worker.iec_schema import EvidenceItem
from poi_mpp.worker.inference import AdapterRunResult
from poi_mpp.worker.model_manifest import PinnedModelManifest, bytes32_word
from poi_mpp.worker.trace_schema import TraceEvent

_REVISION_SIDECAR_NAME = "POI_MODEL_REVISION.json"
_REVISION_SIDECAR_SCHEMA_VERSION = "POI_MPP_MODEL_REVISION_SIDECAR_V1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_RUNTIME_LEDGER = _REPO_ROOT / "envs" / "model_runtime_wheels.sha256"
_REQUIRED_OFFLINE_FLAGS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
_FORBIDDEN_WEIGHT_SUFFIXES = (".bin", ".pt", ".pth", ".ckpt")


class _RuntimeAdapter(Protocol):
    runtime_name: str
    runtime_version: str

    def load_model(
        self,
        *,
        model_path: str,
        revision: str,
        local_files_only: bool,
        use_safetensors: bool,
        precision: str,
    ) -> object: ...

    def load_tokenizer(self, *, tokenizer_path: str, revision: str, local_files_only: bool) -> object: ...

    def resolve_model_revision(self, loaded_model: object) -> str | None: ...

    def resolve_tokenizer_revision(self, loaded_tokenizer: object) -> str | None: ...

    def encode_task(self, loaded_tokenizer: object, task: TaskSpec) -> tuple[int, ...]: ...

    def generate(
        self,
        loaded_model: object,
        prompt_token_ids: tuple[int, ...],
        policy: DeterministicDecodePolicy,
    ) -> tuple[int, ...]: ...

    def decode(self, loaded_tokenizer: object, token_ids: tuple[int, ...]) -> str: ...


def _sha256_path(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _response_binding(response: str) -> str:
    """Canonical ASCII-safe binding to the exact UTF-8 transcript."""

    return bytes32_word("WORKER_RESPONSE_TEXT", {"response": response})


def _generation_kwargs(policy: DeterministicDecodePolicy) -> dict[str, object]:
    """Pass only generation options that are meaningful for the selected mode."""

    kwargs: dict[str, object] = {
        "max_new_tokens": policy.max_new_tokens,
        "do_sample": policy.do_sample,
        "repetition_penalty": policy.repetition_penalty,
    }
    if policy.do_sample:
        kwargs.update(
            {
                "temperature": policy.temperature,
                "top_p": policy.top_p,
                "top_k": policy.top_k,
            }
        )
    return kwargs


def _transcript_metadata(response: str) -> dict[str, object]:
    """Losslessly retain exact UTF-8 transcript as bounded ASCII-safe sidecar chunks."""

    encoded = response.encode("utf-8").hex()
    chunks = tuple(encoded[index : index + 96] for index in range(0, len(encoded), 96))
    metadata: dict[str, object] = {
        "response_hash": _response_binding(response),
        "transcript_encoding": "utf8-hex",
        "transcript_chunk_count": len(chunks),
    }
    metadata.update(
        {f"transcript_utf8_hex_{index:04d}": chunk for index, chunk in enumerate(chunks)}
    )
    return metadata


def _extract_prompt_token_ids(encoded: object) -> tuple[int, ...]:
    """Extract one tokenizer sequence from dict or Transformers BatchEncoding output."""

    getter = getattr(encoded, "get", None)
    if not isinstance(encoded, Mapping) and not callable(getter):
        raise RuntimeError("transformers tokenizer output must be mapping-compatible")
    input_ids = getter("input_ids") if callable(getter) else encoded.get("input_ids")
    if not isinstance(input_ids, Sequence) or isinstance(input_ids, str | bytes):
        raise RuntimeError("transformers tokenizer did not return sequence input_ids")
    if not input_ids:
        raise RuntimeError("transformers tokenizer returned empty input_ids")
    first = input_ids[0]
    if isinstance(first, Sequence) and not isinstance(first, str | bytes):
        if len(input_ids) != 1:
            raise RuntimeError("transformers tokenizer must return exactly one input sequence")
        input_ids = first
    if not input_ids:
        raise RuntimeError("transformers tokenizer returned empty input_ids")
    if any(isinstance(token_id, bool) or not isinstance(token_id, int) or token_id < 0 for token_id in input_ids):
        raise RuntimeError("transformers tokenizer input_ids must be non-negative integers")
    return tuple(input_ids)


def _trace_events(
    *,
    task: TaskSpec,
    policy: DeterministicDecodePolicy,
    prompt_token_ids: tuple[int, ...],
    generated_token_ids: tuple[int, ...],
    response: str,
) -> tuple[TraceEvent, ...]:
    if not generated_token_ids:
        raise ValueError("real execution must emit at least one generated token")
    return tuple(
        TraceEvent(
            event_index=index,
            op_name="transformers_generate_step",
            input_hashes=(
                bytes32_word(
                    "WORKER_TRACE_INPUT",
                    {
                        "task": task.model_dump(mode="json"),
                        "seed": policy.seed,
                        "prompt_token_ids": list(prompt_token_ids),
                        "prior_generated_token_ids": list(generated_token_ids[:index]),
                    },
                ),
            ),
            output_hash=bytes32_word(
                "WORKER_TRACE_OUTPUT",
                {
                    "token_id": token_id,
                    "position": index,
                    "seed": policy.seed,
                },
            ),
            metadata={
                "token_id": token_id,
                "position": index,
                "surface": EvidenceOrigin.REAL_MODEL_EXECUTION.value,
                **(_transcript_metadata(response) if index == 0 else {}),
            },
        )
        for index, token_id in enumerate(generated_token_ids)
    )


def _revision_sidecar_payload(manifest: PinnedModelManifest) -> dict[str, str]:
    return {
        "schema_version": _REVISION_SIDECAR_SCHEMA_VERSION,
        "repository": manifest.repository,
        "revision": manifest.revision,
        "tokenizer_revision": manifest.tokenizer_revision,
    }


def _require_revision_sidecar(
    *,
    root: Path,
    manifest: PinnedModelManifest,
    verified_hashes: dict[str, str],
    kind: str,
) -> str:
    expected_hash = verified_hashes.get(_REVISION_SIDECAR_NAME)
    if expected_hash is None:
        raise ValueError(
            f"loaded model {kind}_revision is unavailable and {_REVISION_SIDECAR_NAME} is required"
        )
    sidecar_path = root / _REVISION_SIDECAR_NAME
    if not sidecar_path.is_file():
        raise RuntimeError(f"required {kind} revision sidecar is missing: {_REVISION_SIDECAR_NAME}")
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"loaded model {kind} revision sidecar is invalid") from error
    if payload != _revision_sidecar_payload(manifest):
        raise ValueError(f"loaded model {kind} revision sidecar does not match pinned manifest")
    return expected_hash


def _resolve_loaded_revision(
    *,
    resolved_revision: str | None,
    expected_revision: str,
    root: Path,
    manifest: PinnedModelManifest,
    verified_hashes: dict[str, str],
    kind: str,
) -> str:
    if resolved_revision is None:
        _require_revision_sidecar(
            root=root,
            manifest=manifest,
            verified_hashes=verified_hashes,
            kind=kind,
        )
        return expected_revision
    if resolved_revision != expected_revision:
        raise ValueError(f"loaded model {kind}_revision does not match pinned manifest")
    return resolved_revision


def _load_runtime() -> _RuntimeAdapter:
    try:
        import transformers
    except ImportError as error:
        raise RuntimeError("authorized local transformers runtime is unavailable") from error

    class _TransformersRuntime:
        runtime_name = "transformers"
        runtime_version = str(transformers.__version__)

        def load_model(
            self,
            *,
            model_path: str,
            revision: str,
            local_files_only: bool,
            use_safetensors: bool,
            precision: str,
        ) -> object:
            import torch

            dtypes = {
                "bfloat16": torch.bfloat16,
                "float16": torch.float16,
                "float32": torch.float32,
            }
            try:
                dtype = dtypes[precision]
            except KeyError as error:
                raise ValueError(f"unsupported pinned transformers precision: {precision}") from error
            return transformers.AutoModelForCausalLM.from_pretrained(
                model_path,
                revision=revision,
                local_files_only=local_files_only,
                trust_remote_code=False,
                use_safetensors=use_safetensors,
                dtype=dtype,
            )

        def load_tokenizer(self, *, tokenizer_path: str, revision: str, local_files_only: bool) -> object:
            return transformers.AutoTokenizer.from_pretrained(
                tokenizer_path,
                revision=revision,
                local_files_only=local_files_only,
                trust_remote_code=False,
            )

        def resolve_model_revision(self, loaded_model: object) -> str | None:
            config = getattr(loaded_model, "config", None)
            return getattr(config, "_commit_hash", None)

        def resolve_tokenizer_revision(self, loaded_tokenizer: object) -> str | None:
            init_kwargs = getattr(loaded_tokenizer, "init_kwargs", None)
            if isinstance(init_kwargs, dict):
                value = init_kwargs.get("_commit_hash") or init_kwargs.get("revision")
                return str(value) if value is not None else None
            return None

        def encode_task(self, loaded_tokenizer: object, task: TaskSpec) -> tuple[int, ...]:
            prompt = json.dumps(task.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            encoded = loaded_tokenizer(prompt, return_tensors=None, add_special_tokens=True)
            return _extract_prompt_token_ids(encoded)

        def generate(
            self,
            loaded_model: object,
            prompt_token_ids: tuple[int, ...],
            policy: DeterministicDecodePolicy,
        ) -> tuple[int, ...]:
            import torch

            torch.manual_seed(policy.seed)
            generated = loaded_model.generate(
                input_ids=torch.tensor([list(prompt_token_ids)], dtype=torch.long),
                **_generation_kwargs(policy),
            )
            sequence = generated[0].tolist()
            return tuple(int(token_id) for token_id in sequence[len(prompt_token_ids) :])

        def decode(self, loaded_tokenizer: object, token_ids: tuple[int, ...]) -> str:
            return str(loaded_tokenizer.decode(list(token_ids), skip_special_tokens=True)).strip()

    return _TransformersRuntime()


def _require_offline_environment(environ: dict[str, str] | os._Environ[str]) -> None:
    missing = [name for name in _REQUIRED_OFFLINE_FLAGS if environ.get(name) != "1"]
    if missing:
        raise RuntimeError(
            "authorized local transformers loader requires offline flags set to 1: "
            + ", ".join(missing)
        )


def _require_reviewed_runtime_ledger(
    manifest: PinnedModelManifest,
    *,
    ledger_path: Path,
) -> None:
    try:
        lines = tuple(
            line.strip().lower()
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except OSError as error:
        raise RuntimeError("reviewed model runtime wheel ledger is unavailable") from error
    try:
        required_versions = {
            "transformers": manifest.runtime_version,
            "safetensors": metadata.version("safetensors"),
            "tokenizers": metadata.version("tokenizers"),
            "torch": metadata.version("torch"),
        }
    except metadata.PackageNotFoundError as error:
        raise RuntimeError("installed model runtime boundary is incomplete") from error
    reviewed_filenames = tuple(line.split()[-1] for line in lines)
    missing = [
        f"{name}=={version}"
        for name, version in required_versions.items()
        if not any(filename.startswith(f"{name}-{version}-") for filename in reviewed_filenames)
    ]
    if missing:
        raise RuntimeError(
            "reviewed model runtime wheel ledger does not cover installed boundary: "
            + ", ".join(missing)
        )


def _require_safetensors_only(model_root: Path, manifest: PinnedModelManifest) -> None:
    if manifest.quantization != "none":
        raise ValueError("authorized transformers session requires explicitly unquantized safetensors")
    weight_names = tuple(manifest.model_file_hashes)
    if not any(name.endswith(".safetensors") for name in weight_names):
        raise ValueError("pinned model manifest must include safetensors weights")
    forbidden_manifest = [name for name in weight_names if name.lower().endswith(_FORBIDDEN_WEIGHT_SUFFIXES)]
    forbidden_local = [
        path.name
        for path in model_root.iterdir()
        if path.is_file() and path.name.lower().endswith(_FORBIDDEN_WEIGHT_SUFFIXES)
    ]
    if forbidden_manifest or forbidden_local:
        raise ValueError("alternate model weight formats are forbidden; safetensors-only loading is required")


class AuthorizedLocalTransformersSession:
    """One verified, process-local model/tokenizer session reused across E1 calls."""

    def __init__(
        self,
        *,
        runtime_factory: Callable[[], _RuntimeAdapter] = _load_runtime,
        clock: Callable[[], float] = perf_counter,
        file_hash: Callable[[Path], str] = _sha256_path,
        runtime_ledger_path: str | Path = _DEFAULT_RUNTIME_LEDGER,
        environ: dict[str, str] | os._Environ[str] = os.environ,
    ) -> None:
        self._runtime_factory = runtime_factory
        self._clock = clock
        self._file_hash = file_hash
        self._runtime_ledger_path = Path(runtime_ledger_path)
        self._environ = environ
        self._binding: tuple[object, ...] | None = None
        self._runtime: _RuntimeAdapter | None = None
        self._loaded_model: object | None = None
        self._loaded_tokenizer: object | None = None
        self._loaded_manifest: PinnedModelManifest | None = None
        self.load_count = 0

    def __call__(
        self,
        *,
        model_path: str,
        tokenizer_path: str,
        local_files_only: bool,
        manifest: PinnedModelManifest,
        policy: DeterministicDecodePolicy,
        task: TaskSpec,
    ) -> AdapterRunResult:
        if not local_files_only:
            raise ValueError("authorized local transformers loader requires local_files_only=True")
        _require_offline_environment(self._environ)
        _require_reviewed_runtime_ledger(manifest, ledger_path=self._runtime_ledger_path)

        model_root = Path(model_path)
        tokenizer_root = Path(tokenizer_path)
        _require_safetensors_only(model_root, manifest)
        binding = (
            str(model_root.resolve()),
            str(tokenizer_root.resolve()),
            manifest.model_dump_json(),
            policy.model_dump_json(),
        )
        load_ms = 0.0
        if self._binding is None:
            actual_model_hashes: dict[str, str] = {}
            for filename, expected_hash in manifest.model_file_hashes.items():
                candidate = model_root / filename
                if not candidate.is_file():
                    raise RuntimeError(f"required model file is missing: {filename}")
                actual_hash = self._file_hash(candidate)
                if actual_hash != expected_hash:
                    raise ValueError("loaded model model_file_hashes do not match pinned manifest")
                actual_model_hashes[filename] = actual_hash
            actual_tokenizer_hashes: dict[str, str] = {}
            for filename, expected_hash in manifest.tokenizer_file_hashes.items():
                candidate = tokenizer_root / filename
                if not candidate.is_file():
                    raise RuntimeError(f"required tokenizer file is missing: {filename}")
                actual_hash = self._file_hash(candidate)
                if actual_hash != expected_hash:
                    raise ValueError("loaded model tokenizer_file_hashes do not match pinned manifest")
                actual_tokenizer_hashes[filename] = actual_hash

            try:
                runtime = self._runtime_factory()
            except ImportError as error:
                raise RuntimeError("authorized local transformers runtime is unavailable") from error
            if runtime.runtime_name != manifest.runtime_name:
                raise ValueError("loaded model runtime_name does not match pinned manifest")
            if runtime.runtime_version != manifest.runtime_version:
                raise ValueError("loaded model runtime_version does not match pinned manifest")
            load_start = self._clock()
            loaded_model = runtime.load_model(
                model_path=str(model_root),
                revision=manifest.revision,
                local_files_only=True,
                use_safetensors=True,
                precision=manifest.precision,
            )
            loaded_tokenizer = runtime.load_tokenizer(
                tokenizer_path=str(tokenizer_root),
                revision=manifest.tokenizer_revision,
                local_files_only=True,
            )
            after_load = self._clock()
            resolved_model_revision = _resolve_loaded_revision(
                resolved_revision=runtime.resolve_model_revision(loaded_model),
                expected_revision=manifest.revision,
                root=model_root,
                manifest=manifest,
                verified_hashes=actual_model_hashes,
                kind="revision",
            )
            resolved_tokenizer_revision = _resolve_loaded_revision(
                resolved_revision=runtime.resolve_tokenizer_revision(loaded_tokenizer),
                expected_revision=manifest.tokenizer_revision,
                root=tokenizer_root,
                manifest=manifest,
                verified_hashes=actual_tokenizer_hashes,
                kind="tokenizer",
            )
            self._loaded_manifest = manifest.model_copy(
                update={
                    "model_file_hashes": actual_model_hashes,
                    "tokenizer_file_hashes": actual_tokenizer_hashes,
                    "revision": resolved_model_revision,
                    "tokenizer_revision": resolved_tokenizer_revision,
                    "runtime_name": runtime.runtime_name,
                    "runtime_version": runtime.runtime_version,
                }
            )
            self._binding = binding
            self._runtime = runtime
            self._loaded_model = loaded_model
            self._loaded_tokenizer = loaded_tokenizer
            self.load_count += 1
            load_ms = (after_load - load_start) * 1000.0
        elif binding != self._binding:
            raise ValueError("loaded session cannot cross model, tokenizer, manifest, or decode-policy boundary")

        assert self._runtime is not None
        assert self._loaded_model is not None
        assert self._loaded_tokenizer is not None
        assert self._loaded_manifest is not None
        inference_start = self._clock()
        prompt_token_ids = tuple(
            int(token_id) for token_id in self._runtime.encode_task(self._loaded_tokenizer, task)
        )
        generated_token_ids = tuple(
            int(token_id)
            for token_id in self._runtime.generate(self._loaded_model, prompt_token_ids, policy)
        )
        response = self._runtime.decode(self._loaded_tokenizer, generated_token_ids).strip()
        after_inference = self._clock()
        inference_ms = (after_inference - inference_start) * 1000.0
        return AdapterRunResult(
            loaded_manifest=self._loaded_manifest,
            response=response,
            claim_texts=(f"Exact UTF8 transcript bound by {_response_binding(response)}",),
            trace_events=_trace_events(
                task=task,
                policy=policy,
                prompt_token_ids=prompt_token_ids,
                generated_token_ids=generated_token_ids,
                response=response,
            ),
            evidence_items=(
                EvidenceItem(
                    evidence_id="REAL-MODEL-EXECUTION-TRANSCRIPT",
                    artifact_label="execution-transcript-binding",
                    content=_response_binding(response),
                    keywords=("response", "hash", "utf8-transcript"),
                    origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
                    confidence=None,
                ),
            ),
            warmup_ms=load_ms,
            inference_ms=inference_ms,
        )


def authorized_local_transformers_loader(
    *,
    model_path: str,
    tokenizer_path: str,
    local_files_only: bool,
    manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
    task: TaskSpec,
    runtime_factory: Callable[[], _RuntimeAdapter] = _load_runtime,
    clock: Callable[[], float] = perf_counter,
    file_hash: Callable[[Path], str] = _sha256_path,
    runtime_ledger_path: str | Path = _DEFAULT_RUNTIME_LEDGER,
    environ: dict[str, str] | os._Environ[str] = os.environ,
) -> AdapterRunResult:
    return AuthorizedLocalTransformersSession(
        runtime_factory=runtime_factory,
        clock=clock,
        file_hash=file_hash,
        runtime_ledger_path=runtime_ledger_path,
        environ=environ,
    )(
        model_path=model_path,
        tokenizer_path=tokenizer_path,
        local_files_only=local_files_only,
        manifest=manifest,
        policy=policy,
        task=task,
    )

__all__ = [
    "AuthorizedLocalTransformersSession",
    "authorized_local_transformers_loader",
]
