from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Callable

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from poi_mpp.evidence import (
    ArtifactRegistry,
    ProvenanceBundle,
    collect_environment,
    freeze_run,
    load_run_config,
    publication_path_ref,
)
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.evidence.canonical import digest
from poi_mpp.experiments.e1_cost import E1ExecutionSample, PUBLICATION_EVIDENCE_AUTHORIZED, run_e1_cost_experiment
from poi_mpp.protocol.types import TaskSpec
from poi_mpp.worker import (
    DeterministicDecodePolicy,
    ExecutionBundle,
    PinnedModelManifest,
    TransformersCausalLMAdapter,
    execute_once,
)
from poi_mpp.worker.real_transformers import AuthorizedLocalTransformersSession


def _load_public_document(path: str | Path) -> dict[str, object]:
    candidate = Path(path)
    try:
        loaded = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise SystemExit(f"unable to load public document: {candidate}") from error
    if not isinstance(loaded, dict):
        raise SystemExit(f"public document must be a mapping: {candidate}")
    return loaded


def load_task_spec(path: str | Path) -> TaskSpec:
    return TaskSpec.model_validate(_load_public_document(path))


def load_model_manifest(path: str | Path) -> PinnedModelManifest:
    return PinnedModelManifest.model_validate(_load_public_document(path))


def default_policy(*, seed: int, max_new_tokens: int) -> DeterministicDecodePolicy:
    return DeterministicDecodePolicy(
        seed=seed,
        max_new_tokens=max_new_tokens,
    )


def _retained_trace_bytes(bundle: ExecutionBundle) -> int:
    return len(bundle.trace_sidecar.model_dump_json().encode("utf-8"))


@dataclass(frozen=True)
class RealE1Runner:
    adapter: TransformersCausalLMAdapter
    manifest: PinnedModelManifest
    policy: DeterministicDecodePolicy

    def run(self, task: TaskSpec) -> E1ExecutionSample:
        bundle = execute_once(
            task,
            self.manifest,
            self.policy,
            adapter=self.adapter,
        )
        return E1ExecutionSample(
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
            response_hash=bundle.response_hash,
            trace_root=bundle.trace_root,
            evidence_root=bundle.evidence_root,
            artifact_root=bundle.artifact_root,
            total_ms=bundle.timings.total_ms,
            inference_ms=bundle.timings.inference_ms,
            audit_ms=0.0,
            retained_trace_bytes=_retained_trace_bytes(bundle),
            expected_dispute_cost=0.0,
            protocol_model_manifest=bundle.protocol_model_manifest,
        )


def build_real_e1_runner(
    *,
    model_path: str | Path,
    tokenizer_path: str | Path | None,
    manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
) -> RealE1Runner:
    session = AuthorizedLocalTransformersSession()
    adapter = TransformersCausalLMAdapter(
        model_path=str(Path(model_path)),
        tokenizer_path=str(Path(tokenizer_path)) if tokenizer_path is not None else None,
        loader=session,
    )
    return RealE1Runner(adapter=adapter, manifest=manifest, policy=policy)


def _require_real_cli_authority(run_config, *, publication_authorized: bool) -> None:
    if run_config.experiment_id != "E1":
        raise SystemExit("E1 real CLI requires experiment_id E1")
    if run_config.origin is not EvidenceOrigin.REAL_MODEL_EXECUTION:
        raise SystemExit("E1 real CLI is reserved for REAL_MODEL_EXECUTION runs")
    if run_config.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        raise SystemExit(
            f"E1 real CLI requires {PUBLICATION_EVIDENCE_AUTHORIZED} authorization_scope"
        )
    if not publication_authorized:
        raise SystemExit("E1 real CLI requires explicit --publication-authorized confirmation")


def _require_model_hash_binding(
    *,
    run_config,
    manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
) -> None:
    expected_model_hash = manifest.manifest_hash(policy).removeprefix("0x")
    if run_config.model_hash != expected_model_hash:
        raise SystemExit("run_config.model_hash must equal the pinned model manifest hash for the selected deterministic policy")


def e1_dataset_hash(task: TaskSpec, policy: DeterministicDecodePolicy) -> str:
    return digest(
        "E1_REAL_PILOT_TASKSET",
        {
            "task": task.model_dump(mode="json"),
            "decode_policy": policy.model_dump(mode="json"),
        },
    )


def _require_dataset_hash_binding(*, run_config, task: TaskSpec, policy: DeterministicDecodePolicy) -> None:
    if run_config.dataset_hash != e1_dataset_hash(task, policy):
        raise SystemExit("run_config.dataset_hash must equal the canonical TaskSpec and decode-policy hash")


def _boundary_message(config_path: Path) -> str:
    return (
        "authorized local model adapter and frozen provenance bundle are required for the real E1 pilot; "
        f"loaded config from {config_path.resolve()}"
    )


def run_real_e1(
    *,
    config_path: str | Path,
    task_path: str | Path,
    model_manifest_path: str | Path,
    model_path: str | Path,
    output_root: str | Path,
    publication_authorized: bool,
    tokenizer_path: str | Path | None = None,
    warmup_pairs: int = 0,
    seed: int = 7,
    max_new_tokens: int = 24,
    repo_root: str | Path = ROOT,
    lock_path: str | Path | None = None,
    registry_root: str | Path | None = None,
    runner_factory: Callable[..., object] = build_real_e1_runner,
    environment_collector: Callable[..., object] = collect_environment,
    registry_factory: Callable[[str | Path], ArtifactRegistry] = ArtifactRegistry,
    experiment_runner: Callable[..., object] = run_e1_cost_experiment,
) -> object:
    run_config = load_run_config(config_path)
    _require_real_cli_authority(run_config, publication_authorized=publication_authorized)
    task = load_task_spec(task_path)
    manifest = load_model_manifest(model_manifest_path)
    policy = default_policy(seed=seed, max_new_tokens=max_new_tokens)
    _require_model_hash_binding(run_config=run_config, manifest=manifest, policy=policy)
    _require_dataset_hash_binding(run_config=run_config, task=task, policy=policy)
    if warmup_pairs < 1:
        raise SystemExit("authorized real E1 requires at least one warmup pair so model load is excluded from C1")

    environment = environment_collector(
        repo_root=Path(repo_root),
        lock_path=Path(lock_path) if lock_path is not None else Path(repo_root) / "requirements.lock",
    )
    provenance_bundle = ProvenanceBundle(
        config=run_config,
        environment=environment,
        manifest=freeze_run(run_config, environment),
    )
    target_output_root = Path(output_root)
    target_output_root.mkdir(parents=True, exist_ok=True)
    registry = registry_factory(registry_root or target_output_root / "registry")
    try:
        runner = runner_factory(
            model_path=model_path,
            tokenizer_path=tokenizer_path,
            manifest=manifest,
            policy=policy,
        )
        return experiment_runner(
            runner=runner,
            run_config=run_config,
            task=task,
            output_dir=target_output_root,
            warmup_pairs=warmup_pairs,
            provenance_bundle=provenance_bundle,
            registry=registry,
        )
    finally:
        close = getattr(registry, "close", None)
        if callable(close):
            close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--task")
    parser.add_argument("--model-manifest")
    parser.add_argument("--model-path")
    parser.add_argument("--tokenizer-path")
    parser.add_argument("--output-root")
    parser.add_argument("--registry-root")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--lock-path")
    parser.add_argument("--warmup-pairs", type=int, default=0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--max-new-tokens", type=int, default=24)
    parser.add_argument("--publication-authorized", action="store_true")
    args = parser.parse_args(argv)

    config = load_run_config(args.config)
    has_execution_inputs = all(
        (
            args.task,
            args.model_manifest,
            args.model_path,
            args.output_root,
        )
    )
    if not has_execution_inputs:
        if config.origin is not EvidenceOrigin.REAL_MODEL_EXECUTION:
            raise SystemExit("E1 pilot CLI is reserved for authorized REAL_MODEL_EXECUTION runs")
        raise SystemExit(_boundary_message(Path(args.config)))

    result = run_real_e1(
        config_path=args.config,
        task_path=args.task,
        model_manifest_path=args.model_manifest,
        model_path=args.model_path,
        tokenizer_path=args.tokenizer_path,
        output_root=args.output_root,
        registry_root=args.registry_root,
        publication_authorized=args.publication_authorized,
        warmup_pairs=args.warmup_pairs,
        seed=args.seed,
        max_new_tokens=args.max_new_tokens,
        repo_root=args.repo_root,
        lock_path=args.lock_path,
    )
    summary = {
        "raw_rows_path": publication_path_ref(result.raw_rows_path, repo_root=args.repo_root),
        "publication_completeness": result.publication_decision.completeness,
        "publication_claim_disposition": result.publication_decision.claim_support,
        "frozen_artifact_path": publication_path_ref(
            result.frozen_artifact_path,
            repo_root=args.repo_root,
        ),
    }
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
