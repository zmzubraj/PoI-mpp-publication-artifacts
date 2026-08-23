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

from poi_mpp.attacks.execution import AttackAnalysisSurface, AttackFamily, apply_attack
from poi_mpp.evidence import (
    ArtifactRegistry,
    ProvenanceBundle,
    artifact_content_material,
    collect_environment,
    freeze_run,
    load_run_config,
    publication_path_ref,
)
from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.evidence.publication_gate import GateDecision, evaluate_publication_gate
from poi_mpp.experiments.e2_tamper import (
    PUBLICATION_EVIDENCE_AUTHORIZED,
    build_publication_record,
    evaluate_receipt,
)
from poi_mpp.protocol.types import TaskSpec
from poi_mpp.reporting.e2 import E2Summary, summarize_e2_rows
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
from poi_mpp.worker.e2_tensor_capture import (
    TensorCaptureSpec,
    TensorProductCapture,
    build_real_e2_bundle,
)
from poi_mpp.worker.model_manifest import PinnedModelManifest


E2_MEASUREMENT_DESIGN = "NARROW_SCOPE_PILOT"
E2_CLAIM_DISPOSITION_REASON = (
    "NARROW_SCOPE_PILOT is methodologically capped at INCONCLUSIVE; "
    "one model, one task, one layer, one token, one 4x4 activation slice, "
    "and four attack observations cannot support paper claim C2"
)
E2_FROZEN_SCOPE = {
    "model_count": 1,
    "task_count": 1,
    "layer_count": 1,
    "token_count": 1,
    "activation_slice": "4x4",
    "attack_observation_count": 4,
}


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


def load_capture_spec(path: str | Path) -> TensorCaptureSpec:
    return TensorCaptureSpec.model_validate(_load_public_document(path))


def default_policy(*, seed: int, max_new_tokens: int) -> DeterministicDecodePolicy:
    return DeterministicDecodePolicy(seed=seed, max_new_tokens=max_new_tokens)


def default_capture_spec_path() -> Path:
    return ROOT / "configs" / "publication_real_e2" / "capture.yaml"


def default_capture_spec() -> TensorCaptureSpec:
    return load_capture_spec(default_capture_spec_path())


def _require_frozen_narrow_scope(capture_spec: TensorCaptureSpec) -> None:
    if capture_spec.input_width != 4 or capture_spec.output_width != 4:
        raise SystemExit(
            "NARROW_SCOPE_PILOT requires the separately frozen 4x4 activation slice"
        )


def _require_frozen_capture_artifact(capture: TensorProductCapture) -> None:
    if (
        capture.input_width != 4
        or capture.output_width != 4
        or len(capture.float_matrix_a) != 1
    ):
        raise SystemExit(
            "NARROW_SCOPE_PILOT capture artifact must contain one frozen 4x4 activation slice"
        )


def dataset_hash_for_inputs(
    *,
    task_document: dict[str, object],
    policy: DeterministicDecodePolicy,
    capture_spec: TensorCaptureSpec,
) -> str:
    return digest(
        "E2_REAL_DATASET_BINDING",
        {
            "task": task_document,
            "policy": policy.model_dump(mode="json"),
            "capture_spec": capture_spec.model_dump(mode="json"),
            "measurement_design": E2_MEASUREMENT_DESIGN,
            "frozen_scope": E2_FROZEN_SCOPE,
            "attack_plan": [
                {"family": "WEIGHT_CORRUPTION", "seed": 11, "audit_rate": 0.05, "freivalds_rounds": 8},
                {"family": "TRACE_NODE_MUTATION", "seed": 13, "audit_rate": 0.1, "freivalds_rounds": 8},
                {"family": "TENSOR_PRODUCT_CORRUPTION", "surface": "EXACT_FIELD_SOUNDNESS", "seed": 17, "audit_rate": 0.05, "freivalds_rounds": 8},
                {"family": "TENSOR_PRODUCT_CORRUPTION", "surface": "EMPIRICAL_FLOAT_APPROXIMATION", "seed": 19, "audit_rate": 0.1, "freivalds_rounds": 8},
            ],
        },
    )


def _require_real_cli_authority(run_config, *, publication_authorized: bool) -> None:
    if run_config.experiment_id != "E2":
        raise SystemExit("E2 real CLI requires experiment_id E2")
    if run_config.origin is not EvidenceOrigin.REAL_MODEL_EXECUTION:
        raise SystemExit("E2 real CLI is reserved for REAL_MODEL_EXECUTION runs")
    if run_config.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        raise SystemExit(
            f"E2 real CLI requires {PUBLICATION_EVIDENCE_AUTHORIZED} authorization_scope"
        )
    if not publication_authorized:
        raise SystemExit("E2 real CLI requires explicit --publication-authorized confirmation")


def _require_model_hash_binding(
    *,
    run_config,
    manifest: PinnedModelManifest,
    policy: DeterministicDecodePolicy,
) -> None:
    expected_model_hash = manifest.manifest_hash(policy).removeprefix("0x")
    if run_config.model_hash != expected_model_hash:
        raise SystemExit("run_config.model_hash must equal the pinned model manifest hash for the selected deterministic policy")


def _require_dataset_hash_binding(
    *,
    run_config,
    task_document: dict[str, object],
    policy: DeterministicDecodePolicy,
    capture_spec: TensorCaptureSpec,
) -> None:
    expected_dataset_hash = dataset_hash_for_inputs(
        task_document=task_document,
        policy=policy,
        capture_spec=capture_spec,
    )
    if run_config.dataset_hash != expected_dataset_hash:
        raise SystemExit("run_config.dataset_hash must equal the hash of the exact E2 task, deterministic policy, capture spec, and attack plan")


def _boundary_message(config_path: Path) -> str:
    return (
        "authorized local model adapter, bounded tensor capture, and frozen provenance bundle are required for the real E2 pilot; "
        f"loaded config from {config_path.resolve()}"
    )


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _apply_narrow_scope_publication_boundary(
    record: dict[str, object],
) -> dict[str, object]:
    """Bind the frozen pilot design and cap C2 without changing raw observations."""

    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise TypeError("E2 publication record payload must be a mapping")
    bounded_record = {
        **record,
        "payload": {
            **payload,
            "measurement_design": E2_MEASUREMENT_DESIGN,
            "frozen_scope": E2_FROZEN_SCOPE,
            "claim_disposition_reason": E2_CLAIM_DISPOSITION_REASON,
        },
        "claim_disposition": "INCONCLUSIVE",
        "content_hash": "",
    }
    bounded_record["content_hash"] = digest(
        "ARTIFACT_CONTENT",
        artifact_content_material(bounded_record),
    )
    return bounded_record


def _bounded_summary_payload(summary: E2Summary) -> dict[str, object]:
    return {
        **summary.model_dump(mode="json"),
        "measurement_design": E2_MEASUREMENT_DESIGN,
        "frozen_scope": E2_FROZEN_SCOPE,
        "claim_disposition": "INCONCLUSIVE",
        "claim_disposition_reason": E2_CLAIM_DISPOSITION_REASON,
    }


def _observation_bundle(bundle, *, receipt_suffix: str):
    return bundle.model_copy(
        update={
            "receipt_id": f"{bundle.receipt_id}-{receipt_suffix}",
            "bundle_id": f"{bundle.run_id}:{bundle.receipt_id}-{receipt_suffix}",
        }
    )


@dataclass(frozen=True)
class RealE2ExperimentResult:
    raw_rows_path: Path
    capture_artifact_path: Path
    publication_record_path: Path
    summary_path: Path
    publication_decision: GateDecision
    frozen_artifact_path: Path | None


def run_real_e2(
    *,
    config_path: str | Path,
    task_path: str | Path,
    model_manifest_path: str | Path,
    model_path: str | Path,
    output_root: str | Path,
    publication_authorized: bool,
    tokenizer_path: str | Path | None = None,
    capture_spec_path: str | Path | None = None,
    seed: int = 7,
    max_new_tokens: int = 24,
    receipt_id: str = "receipt-real-e2-0001",
    repo_root: str | Path = ROOT,
    lock_path: str | Path | None = None,
    registry_root: str | Path | None = None,
    bundle_factory: Callable[..., tuple[object, TensorProductCapture]] = build_real_e2_bundle,
    environment_collector: Callable[..., object] = collect_environment,
    registry_factory: Callable[[str | Path], ArtifactRegistry] = ArtifactRegistry,
) -> RealE2ExperimentResult:
    run_config = load_run_config(config_path)
    _require_real_cli_authority(run_config, publication_authorized=publication_authorized)
    task_document = _load_public_document(task_path)
    task = TaskSpec.model_validate(task_document)
    manifest = load_model_manifest(model_manifest_path)
    capture_spec = load_capture_spec(capture_spec_path) if capture_spec_path is not None else default_capture_spec()
    _require_frozen_narrow_scope(capture_spec)
    policy = default_policy(seed=seed, max_new_tokens=max_new_tokens)
    _require_model_hash_binding(run_config=run_config, manifest=manifest, policy=policy)
    _require_dataset_hash_binding(
        run_config=run_config,
        task_document=task_document,
        policy=policy,
        capture_spec=capture_spec,
    )

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
        bundle, capture = bundle_factory(
            run_config=run_config,
            task=task,
            manifest=manifest,
            policy=policy,
            model_path=model_path,
            tokenizer_path=tokenizer_path,
            capture_spec=capture_spec,
            receipt_id=receipt_id,
        )
        _require_frozen_capture_artifact(capture)
        control_row = evaluate_receipt(bundle, audit_rate=0.05, freivalds_rounds=8)
        weight_bundle, weight_manifest = apply_attack(bundle, AttackFamily.WEIGHT_CORRUPTION, seed=11)
        trace_bundle, trace_manifest = apply_attack(bundle, AttackFamily.TRACE_NODE_MUTATION, seed=13)
        tensor_field_bundle, tensor_field_manifest = apply_attack(
            bundle,
            AttackFamily.TENSOR_PRODUCT_CORRUPTION,
            seed=17,
            analysis_surface=AttackAnalysisSurface.EXACT_FIELD,
        )
        tensor_float_bundle, tensor_float_manifest = apply_attack(
            bundle,
            AttackFamily.TENSOR_PRODUCT_CORRUPTION,
            seed=19,
            analysis_surface=AttackAnalysisSurface.EMPIRICAL_FLOAT,
        )
        rows = [
            control_row,
            evaluate_receipt(
                _observation_bundle(weight_bundle, receipt_suffix="weight-attack"),
                attack_manifest=weight_manifest,
                audit_rate=0.05,
                freivalds_rounds=8,
            ),
            evaluate_receipt(
                _observation_bundle(trace_bundle, receipt_suffix="trace-attack"),
                attack_manifest=trace_manifest,
                audit_rate=0.1,
                freivalds_rounds=8,
            ),
            evaluate_receipt(
                _observation_bundle(tensor_field_bundle, receipt_suffix="tensor-field-attack"),
                attack_manifest=tensor_field_manifest,
                audit_rate=0.05,
                freivalds_rounds=8,
            ),
            evaluate_receipt(
                _observation_bundle(tensor_float_bundle, receipt_suffix="tensor-float-attack"),
                attack_manifest=tensor_float_manifest,
                audit_rate=0.1,
                freivalds_rounds=8,
            ),
        ]
        summary = summarize_e2_rows(rows, claim_id="C2")
        record = _apply_narrow_scope_publication_boundary(
            build_publication_record(
                summary=summary,
                rows=rows,
                run_config=run_config,
                provenance_bundle=provenance_bundle,
            )
        )
        publication_decision = evaluate_publication_gate(
            summary.claim_id,
            [record],
            provenance_bundles=[provenance_bundle],
        )
        raw_rows_path = _write_json(
            target_output_root / "e2_receipt_rows.json",
            [row.model_dump(mode="json") for row in rows],
        )
        capture_artifact_path = _write_json(
            target_output_root / "e2_tensor_capture.json",
            capture.model_dump(mode="json"),
        )
        publication_record_path = _write_json(
            target_output_root / "e2_publication_record.json",
            record,
        )
        summary_path = _write_json(
            target_output_root / "e2_summary.json",
            _bounded_summary_payload(summary),
        )
        frozen_artifact_path: Path | None = None
        if publication_decision.completeness == "COMPLETE":
            frozen_artifact_path = registry.write_atomic(record, provenance_bundle=provenance_bundle)
        return RealE2ExperimentResult(
            raw_rows_path=raw_rows_path,
            capture_artifact_path=capture_artifact_path,
            publication_record_path=publication_record_path,
            summary_path=summary_path,
            publication_decision=publication_decision,
            frozen_artifact_path=frozen_artifact_path,
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
    parser.add_argument("--capture-spec")
    parser.add_argument("--output-root")
    parser.add_argument("--registry-root")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--lock-path")
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
            raise SystemExit("E2 pilot CLI is reserved for authorized REAL_MODEL_EXECUTION runs")
        raise SystemExit(_boundary_message(Path(args.config)))

    result = run_real_e2(
        config_path=args.config,
        task_path=args.task,
        model_manifest_path=args.model_manifest,
        model_path=args.model_path,
        tokenizer_path=args.tokenizer_path,
        capture_spec_path=args.capture_spec,
        output_root=args.output_root,
        registry_root=args.registry_root,
        publication_authorized=args.publication_authorized,
        seed=args.seed,
        max_new_tokens=args.max_new_tokens,
        repo_root=args.repo_root,
        lock_path=args.lock_path,
    )
    print(
        json.dumps(
            {
                "raw_rows_path": publication_path_ref(result.raw_rows_path, repo_root=args.repo_root),
                "capture_artifact_path": publication_path_ref(
                    result.capture_artifact_path,
                    repo_root=args.repo_root,
                ),
                "publication_record_path": publication_path_ref(
                    result.publication_record_path,
                    repo_root=args.repo_root,
                ),
                "summary_path": publication_path_ref(
                    result.summary_path,
                    repo_root=args.repo_root,
                ),
                "publication_completeness": result.publication_decision.completeness,
                "publication_claim_disposition": result.publication_decision.claim_support,
                "measurement_design": E2_MEASUREMENT_DESIGN,
                "claim_disposition_reason": E2_CLAIM_DISPOSITION_REASON,
                "frozen_artifact_path": publication_path_ref(
                    result.frozen_artifact_path,
                    repo_root=args.repo_root,
                ),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
