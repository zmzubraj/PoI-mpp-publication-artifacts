"""Shared external-bundle fixtures for E3-v2 script contract tests.

These builders write valid external development and confirmatory bundles that
satisfy the fail-closed Phase-3 and Phase-4 preflight contracts. They are test
infrastructure only: every bundle is synthetic plumbing material and can never
enter real publication evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Sequence

from poi_mpp.auditor.semantic.models import (
    SEMANTIC_CALIBRATION_ERROR_TAXONOMY_VERSION,
    SEMANTIC_CALIBRATION_SELECTION_RULE_V2,
    SemanticCalibrationFreezeV2,
    semantic_calibration_taxonomy_hash,
)
from poi_mpp.evidence.models import EvidenceOrigin


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def write_canonical_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_token(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def development_dataset_manifest_payload(
    *,
    dataset_origin: str = EvidenceOrigin.REAL_MODEL_EXECUTION.value,
    dataset_id: str = "e3-v2-development-test-only",
) -> dict[str, Any]:
    records: list[dict[str, object]] = []
    for index in range(120):
        if index < 50:
            expected = "ACCEPT"
            outcome = "SUPPORTED_GROUNDS"
        elif index < 100:
            expected = "REJECT"
            outcome = "REJECTED_GROUNDS"
        else:
            expected = "ABSTAIN"
            outcome = "ABSTAIN_GROUNDS"
        record_id = f"test-only-{index:03d}"
        item_bytes = f"item::{record_id}".encode("utf-8")
        label_bytes = canonical_json_bytes({"expected_decision": expected, "record_id": record_id})
        records.append(
            {
                "record_id": record_id,
                "item_path": f"items/{record_id}.txt",
                "label_path": f"labels/{record_id}.json",
                "item_hash": sha256_bytes(item_bytes),
                "label_hash": sha256_bytes(label_bytes),
                "content_hash": hash_token(f"content::{record_id}"),
                "split": "DEVELOPMENT",
                "license_id": "CC-BY-4.0",
                "privacy_status": "AUTHORIZED_PUBLIC",
                "expected_decision": expected,
                "expected_semantic_outcome": outcome,
                "error_family": "BASELINE",
                "subgroup": "core",
                "difficulty": "standard",
                "deduplication_group": f"group-{index:03d}",
                "annotation": {
                    "annotation_scope": "semantic-development",
                    "annotation_hash": hash_token(f"annotation::{record_id}"),
                    "agreement_fraction": 1.0,
                },
                "evidence_origin": dataset_origin,
            }
        )
    return {
        "schema_version": "POI_MPP_DATASET_MANIFEST_V2",
        "dataset_id": dataset_id,
        "split": "DEVELOPMENT",
        "records": records,
    }


def development_bundle_payloads(
    *,
    parameter_scale: str = "1.5B",
    environment_parameter_count: float = 1.5,
    dataset_origin: str = EvidenceOrigin.REAL_MODEL_EXECUTION.value,
    owner_id: str = "owner-test-only",
    accountable_reviewer_id: str = "reviewer-test-only",
    manifest_mutator: Callable[[list[dict[str, str]]], list[dict[str, str]]] | None = None,
) -> dict[str, object]:
    owner_declaration = {
        "schema_version": "POI_MPP_E3_V2_OWNER_DECLARATION_V1",
        "owner_id": owner_id,
        "accountable_reviewer_id": accountable_reviewer_id,
        "offline_execution_declared": True,
        "local_only_execution_declared": True,
        "license_review_reference": "reviewed-license-ledger-entry",
        "runtime_wheel_ledger_review_reference": "reviewed-runtime-ledger-entry",
        "deterministic_decode_review_reference": "reviewed-decode-policy-entry",
        "dataset_review_reference": "reviewed-dataset-entry",
        "annotation_review_reference": "reviewed-annotation-entry",
        "policy_review_reference": "reviewed-policy-entry",
    }
    model_manifest = {
        "schema_version": "POI_MPP_WORKER_MODEL_MANIFEST_V1",
        "model_id": "qwen25-1p5b-test-only",
        "repository": "Qwen/Qwen2.5-1.5B-Instruct",
        "revision": "989aa7980e4cf806f80c7fef2b1adb7bc71aa306",
        "tokenizer_id": "Qwen/Qwen2.5-1.5B-Instruct",
        "tokenizer_revision": "989aa7980e4cf806f80c7fef2b1adb7bc71aa306",
        "license_id": "Apache-2.0",
        "parameter_scale": parameter_scale,
        "precision": "bfloat16",
        "quantization": "none",
        "runtime_name": "transformers",
        "runtime_version": "5.14.1",
        "model_file_hashes": {
            "model.safetensors": hash_token("model.safetensors"),
            "POI_MODEL_REVISION.json": hash_token("sidecar"),
        },
        "tokenizer_file_hashes": {
            "tokenizer.json": hash_token("tokenizer.json"),
            "POI_MODEL_REVISION.json": hash_token("sidecar"),
        },
        "assurance_class": 1,
    }
    decode_policy = {
        "schema_version": "POI_MPP_DETERMINISTIC_DECODE_V1",
        "seed": 7,
        "max_new_tokens": 96,
        "do_sample": False,
        "temperature": 0.0,
        "top_p": 1.0,
        "top_k": 0,
        "repetition_penalty": 1.0,
        "stop_sequences": [],
    }
    environment_manifest = {
        "schema_version": "POI_MPP_EXECUTION_ENVIRONMENT_MANIFEST_V1",
        "environment_id": "e3-dev-test-only",
        "model": {
            "model_id": model_manifest["model_id"],
            "model_revision": model_manifest["revision"],
            "model_weights_hash": hash_token("weights-root"),
            "tokenizer_id": model_manifest["tokenizer_id"],
            "tokenizer_revision": model_manifest["tokenizer_revision"],
            "tokenizer_hash": hash_token("tokenizer-root"),
            "weight_access": "OPEN_WEIGHT",
            "parameter_count_billions": environment_parameter_count,
        },
        "runtime": {
            "python_version": "3.12.9",
            "framework_name": "transformers",
            "framework_version": "5.14.1",
            "dependency_lock_hash": hash_token("dependency-lock"),
            "environment_sbom_digest": hash_token("sbom"),
        },
        "hardware": {
            "accelerator_label": "NVIDIA-TEST-ONLY",
            "accelerator_count": 1,
            "driver_version": "550.0",
        },
        "deterministic": {
            "global_seed": 7,
            "inference_seed": 7,
            "local_files_only": True,
            "hash_check_enforced": True,
        },
        "generation": {
            "do_sample": False,
            "temperature": 0.0,
            "top_p": 1.0,
            "max_new_tokens": 96,
        },
        "script_hashes": {
            "artifact_exporter": hash_token("artifact-exporter"),
            "runner": hash_token("runner"),
        },
        "config_hashes": {
            "experiment_protocol": hash_token("experiment-protocol"),
            "generation_config": hash_token("generation-config"),
        },
        "network_access": "LOCAL_ONLY",
        "external_services": [],
    }

    dataset_manifest = development_dataset_manifest_payload(dataset_origin=dataset_origin)
    records = dataset_manifest["records"]

    payloads: dict[str, object] = {
        "owner_declaration.json": owner_declaration,
        "model/pinned_model_manifest.json": model_manifest,
        "dataset/dataset_manifest_v2.json": dataset_manifest,
        "dataset/annotation_agreement.json": {
            "agreement_fraction": 1.0,
            "denominator": 120,
            "numerator": 120,
            "schema_version": "POI_MPP_TEST_ONLY_ANNOTATION_AGREEMENT_V1",
        },
        "dataset/adjudication_ledger.json": {
            "rows": [],
            "schema_version": "POI_MPP_TEST_ONLY_ADJUDICATION_LEDGER_V1",
        },
        "dataset/license_privacy_ledger.json": {
            "rows": [],
            "schema_version": "POI_MPP_TEST_ONLY_LICENSE_PRIVACY_LEDGER_V1",
        },
        "policy/claim_spec.json": {
            "claim_id": "C3",
            "schema_version": "POI_MPP_TEST_ONLY_CLAIM_SPEC_V1",
        },
        "policy/output_schema.json": {
            "fields": ["decision", "confidence"],
            "schema_version": "POI_MPP_TEST_ONLY_OUTPUT_SCHEMA_V1",
        },
        "policy/contradiction_policy.json": {
            "mode": "strict",
            "schema_version": "POI_MPP_TEST_ONLY_CONTRADICTION_POLICY_V1",
        },
        "policy/error_recovery_policy.json": {
            "mode": "fail_closed",
            "schema_version": "POI_MPP_TEST_ONLY_ERROR_RECOVERY_POLICY_V1",
        },
        "policy/error_taxonomy_review.json": {
            "review_reference": "reviewed-taxonomy-entry",
            "schema_version": "POI_MPP_TEST_ONLY_TAXONOMY_REVIEW_V1",
        },
        "execution/environment_manifest.json": environment_manifest,
        "execution/deterministic_decode_policy.json": decode_policy,
    }
    prompt_text = "You are a grounded semantic verifier.\n"
    annotation_blob = canonical_json_bytes(
        {"records": 120, "schema_version": "POI_MPP_TEST_ONLY_ANNOTATIONS_V1"}
    )
    file_hash_lines = [
        f"{model_manifest['model_file_hashes']['POI_MODEL_REVISION.json']}  POI_MODEL_REVISION.json",
        f"{model_manifest['model_file_hashes']['model.safetensors']}  model.safetensors",
        f"{model_manifest['tokenizer_file_hashes']['tokenizer.json']}  tokenizer.json",
    ]
    bundle_bytes: dict[str, bytes] = {
        "policy/prompt_template.txt": prompt_text.encode("utf-8"),
        "model/file_hashes.sha256": ("\n".join(file_hash_lines) + "\n").encode("utf-8"),
        "dataset/annotations/semantic-development.json": annotation_blob,
    }
    for record in records:
        record_id = str(record["record_id"])
        bundle_bytes[f"dataset/items/{record_id}.txt"] = f"item::{record_id}".encode("utf-8")
        bundle_bytes[f"dataset/labels/{record_id}.json"] = canonical_json_bytes(
            {"expected_decision": record["expected_decision"], "record_id": record_id}
        )

    manifest_entries = []
    for relative_path, payload in payloads.items():
        manifest_entries.append({"path": relative_path, "sha256": sha256_bytes(canonical_json_bytes(payload))})
    for relative_path, raw in bundle_bytes.items():
        manifest_entries.append({"path": relative_path, "sha256": sha256_bytes(raw)})
    manifest_entries.sort(key=lambda item: item["path"])
    if manifest_mutator is not None:
        manifest_entries = manifest_mutator(manifest_entries)
    payloads["manifest.json"] = {
        "schema_version": "POI_MPP_E3_V2_DEVELOPMENT_BUNDLE_MANIFEST_V1",
        "files": manifest_entries,
    }
    return {"payloads": payloads, "bytes": bundle_bytes}


def write_development_bundle(
    bundle_root: Path,
    *,
    parameter_scale: str = "1.5B",
    environment_parameter_count: float = 1.5,
    dataset_origin: str = EvidenceOrigin.REAL_MODEL_EXECUTION.value,
    owner_id: str = "owner-test-only",
    accountable_reviewer_id: str = "reviewer-test-only",
    manifest_mutator: Callable[[list[dict[str, str]]], list[dict[str, str]]] | None = None,
    canonical_manifest: bool = True,
) -> Path:
    rendered = development_bundle_payloads(
        parameter_scale=parameter_scale,
        environment_parameter_count=environment_parameter_count,
        dataset_origin=dataset_origin,
        owner_id=owner_id,
        accountable_reviewer_id=accountable_reviewer_id,
        manifest_mutator=manifest_mutator,
    )
    payloads = rendered["payloads"]
    bundle_bytes = rendered["bytes"]
    for relative_path, payload in payloads.items():
        path = bundle_root / relative_path
        if relative_path == "manifest.json" and not canonical_manifest:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            write_canonical_json(path, payload)
    for relative_path, raw in bundle_bytes.items():
        path = bundle_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return bundle_root


def write_external_development_manifest(path: Path, **kwargs: object) -> Path:
    write_canonical_json(path, development_dataset_manifest_payload(**kwargs))
    return path


def confirmatory_bundle_payloads(
    *,
    dataset_origin: str = EvidenceOrigin.REAL_MODEL_EXECUTION.value,
    dataset_id: str = "e3-v2-confirmatory-test-only",
    disagreement_record_ids: Sequence[str] = (),
    annotator_a: str = "annotator-alpha-test-only",
    annotator_b: str = "annotator-beta-test-only",
    adjudicator_id: str = "adjudicator-gamma-test-only",
) -> dict[str, object]:
    """Build a fully reconciled 500-record confirmatory bundle payload set."""

    disagreements = set(disagreement_record_ids)
    records: list[dict[str, object]] = []
    annotation_rows: list[dict[str, object]] = []
    adjudication_rows: list[dict[str, object]] = []
    license_rows: list[dict[str, object]] = []
    bundle_bytes: dict[str, bytes] = {}
    agreements = 0

    for index in range(500):
        if index < 200:
            decision = "ACCEPT"
            outcome = "SUPPORTED_GROUNDS"
        elif index < 400:
            decision = "REJECT"
            outcome = "REJECTED_GROUNDS"
        else:
            decision = "ABSTAIN"
            outcome = "ABSTAIN_GROUNDS"
        record_id = f"e3v2-conf-{index:03d}"
        item_bytes = f"E3V2_CONFIRMATORY_ITEM::{record_id}".encode("utf-8")
        label_bytes = canonical_json_bytes({"expected_decision": decision, "record_id": record_id})
        bundle_bytes[f"items/{record_id}.txt"] = item_bytes
        bundle_bytes[f"labels/{record_id}.json"] = label_bytes

        first_decision = decision
        second_decision = "ABSTAIN" if record_id in disagreements and decision != "ABSTAIN" else (
            "ACCEPT" if record_id in disagreements else first_decision
        )
        annotations = []
        for suffix, annotator_id, annotation_decision in (
            ("a", annotator_a, first_decision),
            ("b", annotator_b, second_decision),
        ):
            annotation_path = f"annotations/{record_id}-{suffix}.json"
            annotation_blob = canonical_json_bytes(
                {
                    "annotator_id": annotator_id,
                    "decision": annotation_decision,
                    "record_id": record_id,
                }
            )
            bundle_bytes[annotation_path] = annotation_blob
            annotations.append(
                {
                    "annotator_id": annotator_id,
                    "decision": annotation_decision,
                    "annotation_path": annotation_path,
                    "annotation_hash": sha256_bytes(annotation_blob),
                }
            )
        row: dict[str, object] = {
            "record_id": record_id,
            "annotations": annotations,
            "provenance_reference": "E3V2_CONFIRMATORY_ANNOTATION_V1",
        }
        annotation_rows.append(row)

        if record_id in disagreements:
            agreements_fraction = 0.0
            adjudication_blob = canonical_json_bytes(
                {
                    "adjudicator_id": adjudicator_id,
                    "decision": first_decision,
                    "record_id": record_id,
                }
            )
            adjudication_path = f"adjudications/{record_id}.json"
            bundle_bytes[adjudication_path] = adjudication_blob
            adjudication_rows.append(
                {
                    "record_id": record_id,
                    "adjudicator_id": adjudicator_id,
                    "decision": first_decision,
                    "adjudication_path": adjudication_path,
                    "adjudication_hash": sha256_bytes(adjudication_blob),
                }
            )
        else:
            agreements_fraction = 1.0
            agreements += 1

        records.append(
            {
                "record_id": record_id,
                "item_path": f"items/{record_id}.txt",
                "label_path": f"labels/{record_id}.json",
                "item_hash": sha256_bytes(item_bytes),
                "label_hash": sha256_bytes(label_bytes),
                "content_hash": hash_token(f"conf-content::{record_id}"),
                "split": "CONFIRMATORY",
                "license_id": "CC-BY-4.0",
                "privacy_status": "AUTHORIZED_PUBLIC",
                "expected_decision": decision,
                "expected_semantic_outcome": outcome,
                "error_family": "BASELINE",
                "subgroup": "core",
                "difficulty": "standard",
                "deduplication_group": f"conf-group-{index:03d}",
                "annotation": {
                    "annotation_scope": "semantic-confirmatory",
                    "annotation_hash": sha256_bytes(canonical_json_bytes(row)),
                    "agreement_fraction": agreements_fraction,
                },
                "evidence_origin": dataset_origin,
            }
        )
        license_rows.append(
            {
                "record_id": record_id,
                "license_id": "CC-BY-4.0",
                "privacy_status": "AUTHORIZED_PUBLIC",
                "source_reference": f"source::{record_id}",
                "authorization_reference": f"authorization::{record_id}",
            }
        )

    payloads: dict[str, object] = {
        "dataset_manifest_v2.json": {
            "schema_version": "POI_MPP_DATASET_MANIFEST_V2",
            "dataset_id": dataset_id,
            "split": "CONFIRMATORY",
            "records": records,
        },
        "annotation_ledger.json": {
            "schema_version": "POI_MPP_E3_V2_ANNOTATION_LEDGER_V1",
            "rows": annotation_rows,
        },
        "annotation_agreement.json": {
            "schema_version": "POI_MPP_E3_V2_ANNOTATION_AGREEMENT_V1",
            "numerator": agreements,
            "denominator": 500,
            "rate": agreements / 500,
        },
        "adjudication_ledger.json": {
            "schema_version": "POI_MPP_E3_V2_ADJUDICATION_LEDGER_V1",
            "rows": adjudication_rows,
        },
        "license_privacy_ledger.json": {
            "schema_version": "POI_MPP_E3_V2_LICENSE_PRIVACY_LEDGER_V1",
            "rows": license_rows,
        },
    }
    return {"payloads": payloads, "bytes": bundle_bytes}


def calibration_freeze_payload(
    *,
    development_dataset_manifest_hash: str,
    runtime_environment_hash: str,
    status: str = "FROZEN_DEVELOPMENT_ONLY",
    support_threshold: float = 0.7,
    reject_threshold: float = 0.3,
) -> dict[str, object]:
    """Build a valid SemanticCalibrationFreezeV2 payload bound to development hashes."""

    payload = {
        "schema_version": "POI_MPP_SEMANTIC_CALIBRATION_FREEZE_V2",
        "status": status,
        "development_dataset_manifest_hash": development_dataset_manifest_hash,
        "claim_spec_hash": hash_token("calibration-claim-spec"),
        "prompt_template_hash": hash_token("calibration-prompt-template"),
        "model_manifest_hash": hash_token("calibration-model-manifest"),
        "runtime_environment_hash": runtime_environment_hash,
        "output_schema_hash": hash_token("calibration-output-schema"),
        "contradiction_policy_hash": hash_token("calibration-contradiction-policy"),
        "error_recovery_policy_hash": hash_token("calibration-error-recovery-policy"),
        "accept_example_count": 50,
        "reject_example_count": 50,
        "abstain_example_count": 20,
        "error_taxonomy_version": SEMANTIC_CALIBRATION_ERROR_TAXONOMY_VERSION,
        "error_taxonomy_hash": semantic_calibration_taxonomy_hash(),
        "support_threshold": support_threshold,
        "reject_threshold": reject_threshold,
        "minimum_calibrated_confidence": 0.1,
        "selection_rule_id": SEMANTIC_CALIBRATION_SELECTION_RULE_V2,
        "example_count": 120,
        "error_ledger_hash": hash_token("calibration-error-ledger"),
        "leakage_report_hash": hash_token("calibration-leakage-report"),
    }
    freeze = SemanticCalibrationFreezeV2.model_validate(payload)
    payload["content_hash"] = freeze.content_hash
    return payload


def write_external_calibration_freeze(path: Path, **kwargs: object) -> Path:
    write_canonical_json(path, calibration_freeze_payload(**kwargs))
    return path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script_module(module_name: str, script_path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def development_report_payload(bundle_root: Path) -> dict[str, object]:
    """Run the canonical development-bundle report builder against a fixture bundle."""

    module = _load_script_module(
        "_e3_v2_development_report_fixture_runtime",
        REPO_ROOT / "scripts" / "build_e3_v2_development_bundle.py",
    )
    return module.build_report(bundle_root)


def confirmatory_lineage_payload(
    bundle_root: Path, development_manifest_path: Path
) -> dict[str, object]:
    """Run the canonical confirmatory-freeze lineage builder against fixture bundles."""

    module = _load_script_module(
        "_e3_v2_confirmatory_lineage_fixture_runtime",
        REPO_ROOT / "scripts" / "freeze_e3_v2_confirmatory_dataset.py",
    )
    return module.build_lineage_report(bundle_root, development_manifest_path)


def write_confirmatory_bundle(
    bundle_root: Path,
    *,
    dataset_origin: str = EvidenceOrigin.REAL_MODEL_EXECUTION.value,
    dataset_id: str = "e3-v2-confirmatory-test-only",
    disagreement_record_ids: Sequence[str] = (),
    canonical_manifest: bool = True,
    manifest_schema_version: str = "POI_MPP_E3_V2_CONFIRMATORY_FREEZE_MANIFEST_V1",
) -> Path:
    rendered = confirmatory_bundle_payloads(
        dataset_origin=dataset_origin,
        dataset_id=dataset_id,
        disagreement_record_ids=disagreement_record_ids,
    )
    payloads = rendered["payloads"]
    bundle_bytes = rendered["bytes"]
    for relative_path, payload in payloads.items():
        write_canonical_json(bundle_root / relative_path, payload)
    for relative_path, raw in bundle_bytes.items():
        path = bundle_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    entries = [
        {"path": path.relative_to(bundle_root).as_posix(), "sha256": sha256_bytes(path.read_bytes())}
        for path in sorted(bundle_root.rglob("*"))
        if path.is_file()
    ]
    manifest = {"schema_version": manifest_schema_version, "files": entries}
    manifest_path = bundle_root / "manifest.json"
    if canonical_manifest:
        manifest_path.write_bytes(canonical_json_bytes(manifest))
    else:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return bundle_root
