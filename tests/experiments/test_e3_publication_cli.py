from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "experiments" / "e3_semantic_eval.py"
BUILD_REQUEST = REPO_ROOT / "scripts" / "build_e3_authority_request.py"


def _semantic_fixture_module():
    path = REPO_ROOT / "tests" / "experiments" / "test_e3_semantic.py"
    spec = importlib.util.spec_from_file_location("e3_semantic_test_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _signed_authority(
    tmp_path: Path,
    *,
    metric_scope: list[str] | None = None,
    artifact_scope: list[str] | None = None,
) -> tuple[Path, Path, Path, Path]:
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required for detached signature verification")
    request_path = tmp_path / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    subprocess.run(
        [sys.executable, str(BUILD_REQUEST), "--output", str(request_path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    requested_scope = request["requested_scope"]
    record = {
        "schema_version": "POI_MPP_E3_AUTHORITY_RECORD_V2",
        "record_type": "PRE_EXECUTION_SCOPE_AUTHORIZATION",
        "authority_identity": "external-evaluator@example.org",
        "authority_basis": "Accountable external semantic-evaluation lead",
        "expertise_scope": "Grounded semantic evaluation, calibration, and privacy review",
        "authorized_scope": {
            "experiment_id": "E3",
            "claim_id": "C3",
            "task_class": requested_scope["task_class"],
            "evidence_origin": requested_scope["evidence_origin"],
            "metric_scope": metric_scope or requested_scope["metric_scope"],
            "artifact_scope": artifact_scope or requested_scope["artifact_scope"],
            "privacy_scope": "No prompt text may leave the approved evaluator environment",
            "request_scope_digest": request["requested_scope_digest"],
        },
        "reviewed_request_manifest": {
            "path": request_path.name,
            "sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
            "self_digest": request["self_digest"],
        },
        "decision": "LIMITED_SCOPE" if metric_scope is not None or artifact_scope is not None else "APPROVED",
        "decision_notes": "Authorization is limited to the hash-bound E3 pre-execution scope.",
        "authorization_date": "2026-08-24",
        "result_attestation_status": "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION",
        "external_signature_required": True,
        "signature_reference": "external://e3-authority-record.sig",
        "allowed_signers_reference": "external://e3-authority-allowed-signers",
    }
    record_path = tmp_path / "authority_record.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    private_key = tmp_path / "authority_key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
        capture_output=True,
    )
    pubkey = Path(f"{private_key}.pub").read_text(encoding="utf-8").strip()
    allowed_signers = tmp_path / "allowed_signers"
    allowed_signers.write_text(
        f'{record["authority_identity"]} namespaces="file" {pubkey}\n', encoding="utf-8"
    )
    subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(private_key), "-n", "file", str(record_path)],
        check=True,
        capture_output=True,
    )
    return request_path, record_path, Path(f"{record_path}.sig"), allowed_signers


def _verify_programmatically(
    request: Path, record: Path, signature: Path, allowed_signers: Path
):
    scripts_path = str(REPO_ROOT / "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    from verify_e3_authority import verify_authority

    return verify_authority(
        request,
        record,
        allowed_signers_path=allowed_signers,
        signature_path=signature,
    )


def _base_command(
    *,
    request: Path,
    record: Path,
    signature: Path,
    allowed_signers: Path,
    config: Path,
    model_manifest: Path,
    raw_config: Path,
    inputs: Path,
    outputs: Path,
    trace: Path,
    provenance: Path,
    artifact_root: Path,
) -> list[str]:
    return [
        str(REPO_ROOT / ".venv" / "bin" / "python"),
        str(CLI),
        "--request-manifest",
        str(request),
        "--authority-record",
        str(record),
        "--authority-signature",
        str(signature),
        "--allowed-signers",
        str(allowed_signers),
        "--confirmatory-config",
        str(config),
        "--model-manifest",
        str(model_manifest),
        "--raw-config",
        str(raw_config),
        "--inputs",
        str(inputs),
        "--outputs",
        str(outputs),
        "--trace",
        str(trace),
        "--provenance",
        str(provenance),
        "--artifact-root",
        str(artifact_root),
    ]


def _write_execution_inputs(tmp_path: Path, *, grant) -> dict[str, Path]:
    fixtures = _semantic_fixture_module()
    from poi_mpp.datasets.manifests import DatasetManifest, DatasetSplit
    from poi_mpp.worker.model_manifest import PinnedModelManifest

    first = fixtures._confirmatory_row()
    second = first.model_copy(
        update={
            "case_id": "case-2",
            "frozen_reference_valid": False,
            "frozen_reference_outcome": fixtures.SemanticOutcome.CONTRADICTORY,
            "verifier_decision": fixtures.VerificationDecision.REJECT,
            "verifier_outcome": fixtures.SemanticOutcome.CONTRADICTORY,
            "source_record_id": "source-case-2",
            "source_content_hash": fixtures._hash(
                "DATASET_CONTENT", f"{DatasetSplit.CONFIRMATORY.value}:case-2:content"
            ),
            "annotation_record_id": "annotation-case-2",
            "annotation_hash": fixtures._hash(
                "DATASET_CONTENT", f"{DatasetSplit.CONFIRMATORY.value}:case-2:content"
            ),
        }
    )
    config = fixtures._confirmatory_config().model_copy(
        update={
            "provenance_bundle": fixtures._provenance_bundle(),
            "authority_privacy_scope": grant.privacy_scope,
            "authority_request_scope_digest": grant.request_scope_digest,
            "pre_execution_authority_record_sha256": grant.authority_record_sha256,
        }
    )
    manifests = config.manifests
    config = config.model_copy(
        update={
            "manifests": manifests.model_copy(
                update={
                    "case_manifest": DatasetManifest(
                        dataset_id=manifests.case_manifest.dataset_id,
                        split=DatasetSplit.CONFIRMATORY,
                        records=manifests.case_manifest.records
                        + (
                            fixtures._record(
                                record_id="case-2",
                                split=DatasetSplit.CONFIRMATORY,
                                origin=first.origin,
                                salt="case-2",
                            ),
                        ),
                    ),
                    "source_manifest": DatasetManifest(
                        dataset_id=manifests.source_manifest.dataset_id,
                        split=DatasetSplit.CONFIRMATORY,
                        records=manifests.source_manifest.records
                        + (
                            fixtures._record(
                                record_id="source-case-2",
                                split=DatasetSplit.CONFIRMATORY,
                                origin=first.origin,
                                salt="case-2",
                            ),
                        ),
                    ),
                    "annotation_manifest": DatasetManifest(
                        dataset_id=manifests.annotation_manifest.dataset_id,
                        split=DatasetSplit.CONFIRMATORY,
                        records=manifests.annotation_manifest.records
                        + (
                            fixtures._record(
                                record_id="annotation-case-2",
                                split=DatasetSplit.CONFIRMATORY,
                                origin=first.origin,
                                salt="case-2",
                            ),
                        ),
                    ),
                }
            )
        }
    )
    model = PinnedModelManifest(
        model_id="local-e3-test-1p5b",
        repository="Qwen/Qwen2.5-1.5B-Instruct",
        revision="1" * 40,
        tokenizer_id="Qwen/Qwen2.5-1.5B-Instruct",
        tokenizer_revision="1" * 40,
        license_id="apache-2.0",
        parameter_scale="1.5B",
        precision="bfloat16",
        quantization="none",
        runtime_name="transformers",
        runtime_version="5.14.1",
        model_file_hashes={"model.safetensors": "a" * 64},
        tokenizer_file_hashes={"tokenizer.json": "b" * 64},
    )
    paths = {
        "config": tmp_path / "confirmatory-config.json",
        "model_manifest": tmp_path / "model-manifest.json",
        "raw_config": tmp_path / "raw-config.json",
        "inputs": tmp_path / "inputs.jsonl",
        "outputs": tmp_path / "outputs.jsonl",
        "trace": tmp_path / "trace.jsonl",
        "provenance": tmp_path / "provenance.json",
        "artifact_root": tmp_path / "artifacts",
    }
    paths["config"].write_text(config.model_dump_json(indent=2), encoding="utf-8")
    paths["model_manifest"].write_text(model.model_dump_json(indent=2), encoding="utf-8")
    paths["raw_config"].write_text(
        json.dumps(config.run_config.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["inputs"].write_text(
        "".join(
            json.dumps(
                {
                    "case_id": row.case_id,
                    "experiment_id": row.experiment_id,
                    "run_id": row.run_id,
                    "source_record_id": row.source_record_id,
                },
                sort_keys=True,
            )
            + "\n"
            for row in (first, second)
        ),
        encoding="utf-8",
    )
    paths["outputs"].write_text(
        "".join(
            json.dumps(row.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"
            for row in (first, second)
        ),
        encoding="utf-8",
    )
    paths["trace"].write_text(
        "".join(
            json.dumps(
                {
                    "case_id": row.case_id,
                    "experiment_id": row.experiment_id,
                    "run_id": row.run_id,
                    "trace_root": "c" * 64,
                }
            )
            + "\n"
            for row in (first, second)
        ),
        encoding="utf-8",
    )
    paths["provenance"].write_text(
        json.dumps(
            {
                "experiment_id": config.run_config.experiment_id,
                "origin": config.run_config.origin.value,
                "run_id": config.run_config.run_id,
                "config": config.provenance_bundle.config.model_dump(mode="json"),
                "environment": config.provenance_bundle.environment.model_dump(mode="json"),
                "manifest": config.provenance_bundle.manifest.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return paths


def test_cli_verifies_authority_before_reading_evaluated_rows(tmp_path: Path) -> None:
    request, record, signature, allowed_signers = _signed_authority(tmp_path)
    record.write_text(record.read_text(encoding="utf-8") + " ", encoding="utf-8")
    missing = tmp_path / "missing-execution-file"
    completed = subprocess.run(
        _base_command(
            request=request,
            record=record,
            signature=signature,
            allowed_signers=allowed_signers,
            config=missing,
            model_manifest=missing,
            raw_config=missing,
            inputs=missing,
            outputs=missing,
            trace=missing,
            provenance=missing,
            artifact_root=tmp_path / "artifacts",
        ),
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "signature verification failed" in completed.stderr
    assert "missing-execution-file" not in completed.stderr
    assert not (tmp_path / "artifacts").exists()


def test_verified_grant_exposes_read_only_exact_scope_and_authority_record_hash(tmp_path: Path) -> None:
    request, record, signature, allowed_signers = _signed_authority(tmp_path)
    grant = _verify_programmatically(request, record, signature, allowed_signers)

    assert grant.experiment_id == "E3"
    assert grant.claim_id == "C3"
    assert grant.evidence_origin == "REAL_MODEL_EXECUTION"
    assert grant.metric_scope == ("ABSTAIN", "FAR", "FRR", "calibration", "coverage")
    assert grant.artifact_scope == ("F7", "RAW_E3_EXECUTION", "T4", "T8")
    assert grant.authority_record_sha256 == hashlib.sha256(record.read_bytes()).hexdigest()
    with pytest.raises(AttributeError):
        grant.decision = "LIMITED_SCOPE"


def test_confirmatory_rejects_verified_grant_when_config_scope_is_not_exact(tmp_path: Path) -> None:
    request, record, signature, allowed_signers = _signed_authority(
        tmp_path,
        metric_scope=["ABSTAIN", "FAR"],
        artifact_scope=["RAW_E3_EXECUTION", "T8"],
    )
    grant = _verify_programmatically(request, record, signature, allowed_signers)
    fixtures = _semantic_fixture_module()
    from poi_mpp.experiments.e3_semantic import PublicationEligibilityError, run_confirmatory_semantic

    with pytest.raises(PublicationEligibilityError, match="metric_scope must exactly match verified authority grant"):
        run_confirmatory_semantic(
            config=fixtures._confirmatory_config().model_copy(
                update={
                    "provenance_bundle": fixtures._provenance_bundle(),
                    "authority_privacy_scope": grant.privacy_scope,
                    "authority_request_scope_digest": grant.request_scope_digest,
                    "pre_execution_authority_record_sha256": grant.authority_record_sha256,
                }
            ),
            rows=(fixtures._confirmatory_row(),),
            authority_grant=grant,
        )


def test_cli_requires_all_external_authority_inputs() -> None:
    completed = subprocess.run(
        [str(REPO_ROOT / ".venv" / "bin" / "python"), str(CLI)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "--request-manifest" in completed.stderr
    assert "--authority-record" in completed.stderr
    assert "--authority-signature" in completed.stderr
    assert "--allowed-signers" in completed.stderr
    assert "--confirmatory-config" in completed.stderr
    assert "--model-manifest" in completed.stderr
    assert "--raw-config" in completed.stderr
    assert "--inputs" in completed.stderr
    assert "--outputs" in completed.stderr
    assert "--trace" in completed.stderr
    assert "--provenance" in completed.stderr
    assert "--artifact-root" in completed.stderr


def test_cli_signed_grant_exports_receipt_and_nonadjudicating_summary(tmp_path: Path) -> None:
    request, record, signature, allowed_signers = _signed_authority(tmp_path)
    grant = _verify_programmatically(request, record, signature, allowed_signers)
    paths = _write_execution_inputs(tmp_path, grant=grant)

    completed = subprocess.run(
        _base_command(
            request=request,
            record=record,
            signature=signature,
            allowed_signers=allowed_signers,
            config=paths["config"],
            model_manifest=paths["model_manifest"],
            raw_config=paths["raw_config"],
            inputs=paths["inputs"],
            outputs=paths["outputs"],
            trace=paths["trace"],
            provenance=paths["provenance"],
            artifact_root=paths["artifact_root"],
        ),
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["summary"]["denominator"] == 2
    assert payload["export_receipt"]["completeness"] == "COMPLETE_INPUT_SET"
    assert len(payload["export_receipt"]["artifact_paths"]) == 4
    assert paths["artifact_root"].is_dir()
    assert "signature" not in payload
    assert "claim_support" not in payload
    assert "publication_decision" not in payload


def test_cli_rejects_authority_hash_mismatch_without_partial_output(tmp_path: Path) -> None:
    request, record, signature, allowed_signers = _signed_authority(tmp_path)
    grant = _verify_programmatically(request, record, signature, allowed_signers)
    paths = _write_execution_inputs(tmp_path, grant=grant)
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    config["pre_execution_authority_record_sha256"] = "0" * 64
    paths["config"].write_text(json.dumps(config), encoding="utf-8")

    completed = subprocess.run(
        _base_command(
            request=request,
            record=record,
            signature=signature,
            allowed_signers=allowed_signers,
            config=paths["config"],
            model_manifest=paths["model_manifest"],
            raw_config=paths["raw_config"],
            inputs=paths["inputs"],
            outputs=paths["outputs"],
            trace=paths["trace"],
            provenance=paths["provenance"],
            artifact_root=paths["artifact_root"],
        ),
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "pre_execution_authority_record_sha256" in completed.stderr
    assert not paths["artifact_root"].exists()


def test_cli_rejects_authority_scope_mismatch_without_partial_output(tmp_path: Path) -> None:
    request, record, signature, allowed_signers = _signed_authority(
        tmp_path,
        metric_scope=["ABSTAIN", "FAR"],
        artifact_scope=["RAW_E3_EXECUTION", "T8"],
    )
    grant = _verify_programmatically(request, record, signature, allowed_signers)
    paths = _write_execution_inputs(tmp_path, grant=grant)

    completed = subprocess.run(
        _base_command(
            request=request,
            record=record,
            signature=signature,
            allowed_signers=allowed_signers,
            config=paths["config"],
            model_manifest=paths["model_manifest"],
            raw_config=paths["raw_config"],
            inputs=paths["inputs"],
            outputs=paths["outputs"],
            trace=paths["trace"],
            provenance=paths["provenance"],
            artifact_root=paths["artifact_root"],
        ),
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "metric_scope must exactly match verified authority grant" in completed.stderr
    assert not paths["artifact_root"].exists()


def test_cli_rejects_model_outside_1b_8b_contract_without_partial_output(tmp_path: Path) -> None:
    request, record, signature, allowed_signers = _signed_authority(tmp_path)
    grant = _verify_programmatically(request, record, signature, allowed_signers)
    paths = _write_execution_inputs(tmp_path, grant=grant)
    model = json.loads(paths["model_manifest"].read_text(encoding="utf-8"))
    model["parameter_scale"] = "70B"
    paths["model_manifest"].write_text(json.dumps(model), encoding="utf-8")

    completed = subprocess.run(
        _base_command(
            request=request,
            record=record,
            signature=signature,
            allowed_signers=allowed_signers,
            config=paths["config"],
            model_manifest=paths["model_manifest"],
            raw_config=paths["raw_config"],
            inputs=paths["inputs"],
            outputs=paths["outputs"],
            trace=paths["trace"],
            provenance=paths["provenance"],
            artifact_root=paths["artifact_root"],
        ),
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "parameter_scale" in completed.stderr
    assert not paths["artifact_root"].exists()
