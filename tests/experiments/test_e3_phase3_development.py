from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from poi_mpp.evidence.dataset_manifest_v2 import DatasetExpectedDecision
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e3_development import (
    E3DevelopmentBundleError,
    E3DevelopmentMaterialBundle,
    E3DevelopmentBundleStatus,
    prepare_e3_phase3_development_bundle,
    validate_e3_phase3_development_bundle_materials,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _write_canonical_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json_bytes(payload))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _hash_token(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _bundle_payloads(
    *,
    parameter_scale: str = "1.5B",
    environment_parameter_count: float = 1.5,
    dataset_origin: str = EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value,
    owner_id: str = "owner-test-only",
    accountable_reviewer_id: str = "reviewer-test-only",
    manifest_mutator: callable | None = None,
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
            "model.safetensors": _hash_token("model.safetensors"),
            "POI_MODEL_REVISION.json": _hash_token("sidecar"),
        },
        "tokenizer_file_hashes": {
            "tokenizer.json": _hash_token("tokenizer.json"),
            "POI_MODEL_REVISION.json": _hash_token("sidecar"),
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
            "model_weights_hash": _hash_token("weights-root"),
            "tokenizer_id": model_manifest["tokenizer_id"],
            "tokenizer_revision": model_manifest["tokenizer_revision"],
            "tokenizer_hash": _hash_token("tokenizer-root"),
            "weight_access": "OPEN_WEIGHT",
            "parameter_count_billions": environment_parameter_count,
        },
        "runtime": {
            "python_version": "3.12.9",
            "framework_name": "transformers",
            "framework_version": "5.14.1",
            "dependency_lock_hash": _hash_token("dependency-lock"),
            "environment_sbom_digest": _hash_token("sbom"),
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
            "artifact_exporter": _hash_token("artifact-exporter"),
            "runner": _hash_token("runner"),
        },
        "config_hashes": {
            "experiment_protocol": _hash_token("experiment-protocol"),
            "generation_config": _hash_token("generation-config"),
        },
        "network_access": "LOCAL_ONLY",
        "external_services": [],
    }

    records: list[dict[str, object]] = []
    for index in range(120):
        if index < 50:
            expected = DatasetExpectedDecision.ACCEPT.value
            outcome = "SUPPORTED_GROUNDS"
        elif index < 100:
            expected = DatasetExpectedDecision.REJECT.value
            outcome = "REJECTED_GROUNDS"
        else:
            expected = DatasetExpectedDecision.ABSTAIN.value
            outcome = "ABSTAIN_GROUNDS"
        record_id = f"test-only-{index:03d}"
        item_bytes = f"item::{record_id}".encode("utf-8")
        label_bytes = _canonical_json_bytes({"expected_decision": expected, "record_id": record_id})
        records.append(
            {
                "record_id": record_id,
                "item_path": f"items/{record_id}.txt",
                "label_path": f"labels/{record_id}.json",
                "item_hash": _sha256_bytes(item_bytes),
                "label_hash": _sha256_bytes(label_bytes),
                "content_hash": _hash_token(f"content::{record_id}"),
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
                    "annotation_hash": _hash_token(f"annotation::{record_id}"),
                    "agreement_fraction": 1.0,
                },
                "evidence_origin": dataset_origin,
            }
        )
    dataset_manifest = {
        "schema_version": "POI_MPP_DATASET_MANIFEST_V2",
        "dataset_id": "e3-v2-development-test-only",
        "split": "DEVELOPMENT",
        "records": records,
    }

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
    annotation_blob = _canonical_json_bytes({"records": 120, "schema_version": "POI_MPP_TEST_ONLY_ANNOTATIONS_V1"})
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
        record_id = record["record_id"]
        bundle_bytes[f"dataset/items/{record_id}.txt"] = f"item::{record_id}".encode("utf-8")
        bundle_bytes[f"dataset/labels/{record_id}.json"] = _canonical_json_bytes(
            {"expected_decision": record["expected_decision"], "record_id": record_id}
        )

    manifest_entries = []
    for relative_path, payload in payloads.items():
        manifest_entries.append({"path": relative_path, "sha256": _sha256_bytes(_canonical_json_bytes(payload))})
    for relative_path, raw in bundle_bytes.items():
        manifest_entries.append({"path": relative_path, "sha256": _sha256_bytes(raw)})
    manifest_entries.sort(key=lambda item: item["path"])
    if manifest_mutator is not None:
        manifest_entries = manifest_mutator(manifest_entries)
    payloads["manifest.json"] = {
        "schema_version": "POI_MPP_E3_V2_DEVELOPMENT_BUNDLE_MANIFEST_V1",
        "files": manifest_entries,
    }
    return {"payloads": payloads, "bytes": bundle_bytes}


def _write_bundle(
    bundle_root: Path,
    *,
    parameter_scale: str = "1.5B",
    environment_parameter_count: float = 1.5,
    dataset_origin: str = EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value,
    owner_id: str = "owner-test-only",
    accountable_reviewer_id: str = "reviewer-test-only",
    manifest_mutator: callable | None = None,
    canonical_manifest: bool = True,
) -> Path:
    rendered = _bundle_payloads(
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
            _write_canonical_json(path, payload)
    for relative_path, raw in bundle_bytes.items():
        path = bundle_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return bundle_root


def test_prepare_returns_waiting_external_when_bundle_or_authority_inputs_are_missing(tmp_path: Path) -> None:
    result = prepare_e3_phase3_development_bundle(
        bundle_root=tmp_path / "missing-bundle",
        request_manifest_path=tmp_path / "unused-request.json",
        authority_record_path=None,
        allowed_signers_path=None,
        signature_path=None,
    )

    assert result.status is E3DevelopmentBundleStatus.WAITING_EXTERNAL
    assert result.missing_inputs == (
        "bundle_root",
        "authority_record",
        "allowed_signers",
        "signature",
    )
    assert result.reason == "missing_external_inputs"


def test_materials_reject_repository_local_bundle_root() -> None:
    bundle_root = REPO_ROOT / "tmp-e3-phase3-test-only"
    _write_bundle(bundle_root)
    try:
        with pytest.raises(E3DevelopmentBundleError, match="bundle root must live outside the repository"):
            validate_e3_phase3_development_bundle_materials(bundle_root=bundle_root)
    finally:
        shutil.rmtree(bundle_root, ignore_errors=True)


def test_materials_reject_symlink_bundle_member(tmp_path: Path) -> None:
    bundle_root = _write_bundle(tmp_path / "POI_E3_V2_DEVELOPMENT")
    target = bundle_root / "policy" / "output_schema.json"
    target.unlink()
    target.symlink_to(bundle_root / "policy" / "claim_spec.json")

    with pytest.raises(E3DevelopmentBundleError, match="output_schema.json may not be a symlink"):
        validate_e3_phase3_development_bundle_materials(bundle_root=bundle_root)


def test_materials_reject_noncanonical_manifest_and_unknown_duplicate_paths(tmp_path: Path) -> None:
    bundle_root = _write_bundle(
        tmp_path / "POI_E3_V2_DEVELOPMENT",
        canonical_manifest=False,
        manifest_mutator=lambda entries: entries
        + [entries[0], {"path": "unexpected.txt", "sha256": _hash_token("unexpected")}],
    )

    with pytest.raises(E3DevelopmentBundleError, match="manifest.json must use canonical JSON serialization"):
        validate_e3_phase3_development_bundle_materials(bundle_root=bundle_root)


def test_materials_reject_path_traversal_manifest_entry(tmp_path: Path) -> None:
    bundle_root = _write_bundle(
        tmp_path / "POI_E3_V2_DEVELOPMENT",
        manifest_mutator=lambda entries: entries + [{"path": "../escape.json", "sha256": _hash_token("escape")}],
    )

    with pytest.raises(E3DevelopmentBundleError, match="manifest.json schema validation failed"):
        validate_e3_phase3_development_bundle_materials(bundle_root=bundle_root)


def test_materials_reject_out_of_scope_primary_model_before_dataset_realness(tmp_path: Path) -> None:
    bundle_root = _write_bundle(
        tmp_path / "POI_E3_V2_DEVELOPMENT",
        parameter_scale="7B",
        environment_parameter_count=7.0,
    )

    with pytest.raises(E3DevelopmentBundleError, match="primary E3-v2 development model must stay within 1B-3B"):
        validate_e3_phase3_development_bundle_materials(bundle_root=bundle_root)


def test_materials_reject_same_owner_and_accountable_reviewer(tmp_path: Path) -> None:
    bundle_root = _write_bundle(
        tmp_path / "POI_E3_V2_DEVELOPMENT",
        owner_id="same-person",
        accountable_reviewer_id="same-person",
    )

    with pytest.raises(E3DevelopmentBundleError, match="owner declaration must separate owner_id and accountable_reviewer_id"):
        validate_e3_phase3_development_bundle_materials(bundle_root=bundle_root)


def test_materials_reject_synthetic_development_dataset(tmp_path: Path) -> None:
    bundle_root = _write_bundle(tmp_path / "POI_E3_V2_DEVELOPMENT")

    with pytest.raises(E3DevelopmentBundleError, match="synthetic non-evidence cannot enter development"):
        validate_e3_phase3_development_bundle_materials(bundle_root=bundle_root)


def test_prepare_stays_waiting_external_when_generic_v1_authority_lacks_bundle_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text("{}", encoding="utf-8")
    authority_record = tmp_path / "authority_record.txt"
    allowed_signers = tmp_path / "allowed_signers.txt"
    signature = tmp_path / "signature.txt"
    candidate_bundle = tmp_path / "candidate-bundle"
    candidate_bundle.mkdir()
    for path in (authority_record, allowed_signers, signature):
        path.write_text("placeholder", encoding="utf-8")

    stub_bundle = E3DevelopmentMaterialBundle(
        bundle_root=tmp_path / "POI_E3_V2_DEVELOPMENT",
        owner_declaration=object(),  # type: ignore[arg-type]
        dataset_manifest=type(
            "StubDatasetManifest",
            (),
            {"dataset_manifest_hash": lambda self: "d" * 64},
        )(),
        model_manifest=object(),  # type: ignore[arg-type]
        decode_policy=object(),  # type: ignore[arg-type]
        environment_manifest=object(),  # type: ignore[arg-type]
        policy_input_file_hashes={
            "model_manifest_hash": "m" * 64,
            "deterministic_decode_policy_hash": "d" * 64,
            "runtime_environment_hash": "e" * 64,
            "claim_spec_hash": "1" * 64,
            "prompt_template_hash": "2" * 64,
            "output_schema_hash": "3" * 64,
            "contradiction_policy_hash": "4" * 64,
            "error_recovery_policy_hash": "5" * 64,
            "error_taxonomy_review_hash": "6" * 64,
        },
        bundle_manifest_hashes={},
        bundle_manifest_sha256="b" * 64,
    )

    class _GenericV1Grant:
        experiment_id = "E3"
        claim_id = "C3"
        evidence_origin = "REAL_MODEL_EXECUTION"
        decision = "APPROVED"

    called = {"authority": 0}

    monkeypatch.setattr(
        "poi_mpp.experiments.e3_development.validate_e3_phase3_development_bundle_materials",
        lambda *, bundle_root: stub_bundle,
    )

    def _stub_require_authority(**kwargs):
        called["authority"] += 1
        return _GenericV1Grant()

    monkeypatch.setattr(
        "poi_mpp.experiments.e3_development._require_authority",
        _stub_require_authority,
    )

    result = prepare_e3_phase3_development_bundle(
        bundle_root=candidate_bundle,
        request_manifest_path=request_path,
        authority_record_path=authority_record,
        allowed_signers_path=allowed_signers,
        signature_path=signature,
    )

    assert called["authority"] == 1
    assert result.status is E3DevelopmentBundleStatus.WAITING_EXTERNAL
    assert result.missing_inputs == ()
    assert result.reason == "authority_request_does_not_bind_development_bundle"


def test_prepare_never_broadens_limited_scope_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = tmp_path / "request.json"
    authority_record = tmp_path / "authority.json"
    allowed_signers = tmp_path / "allowed_signers"
    signature = tmp_path / "authority.sig"
    candidate_bundle = tmp_path / "candidate-bundle"
    candidate_bundle.mkdir()
    for path in (request_path, authority_record, allowed_signers, signature):
        path.write_text("test-only", encoding="utf-8")

    class _LimitedGrant:
        experiment_id = "E3"
        claim_id = "C3"
        evidence_origin = "REAL_MODEL_EXECUTION"
        decision = "LIMITED_SCOPE"
        metric_scope = ("FAR",)
        artifact_scope = ("RAW_E3_EXECUTION", "T8")

    monkeypatch.setattr(
        "poi_mpp.experiments.e3_development.validate_e3_phase3_development_bundle_materials",
        lambda *, bundle_root: object(),
    )
    monkeypatch.setattr(
        "poi_mpp.experiments.e3_development._require_authority",
        lambda **kwargs: _LimitedGrant(),
    )

    result = prepare_e3_phase3_development_bundle(
        bundle_root=candidate_bundle,
        request_manifest_path=request_path,
        authority_record_path=authority_record,
        allowed_signers_path=allowed_signers,
        signature_path=signature,
    )

    assert result.status is E3DevelopmentBundleStatus.WAITING_EXTERNAL
    assert result.reason == "limited_scope_runner_not_implemented"
