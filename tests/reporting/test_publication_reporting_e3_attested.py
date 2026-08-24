from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from poi_mpp.reporting.load import PublicationEligibilityError, ReportBuildSpec, load_publication_inputs
from poi_mpp.reporting.manifest import build_publication_report, validate_existing_manifest


REPO_ROOT = Path(
    "/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts"
)
BUILD_REQUEST_SCRIPT = REPO_ROOT / "scripts" / "build_e3_authority_request.py"
VERIFY_RESULT_SCRIPT = REPO_ROOT / "scripts" / "verify_e3_result_attestation.py"
RUN_ID = "e3-confirmatory-real-20260824"
EXPECTED_METRICS = {
    "FAR": ("0.5", 2),
    "FRR": ("0.16666666666666666", 6),
    "ABSTAIN": ("0.125", 8),
    "coverage": ("0.875", 8),
    "calibration": ("0.17840000000000003", 7),
}
RAW_MEMBER_PAYLOADS = {
    "model_hash": ("model_manifest.json", b'{"model_id":"local-open-weight-1b"}\n'),
    "config_hash": ("config.json", b'{"temperature":0,"seed":11}\n'),
    "input_hash": ("inputs.jsonl", b'{"case_id":"e3-1"}\n{"case_id":"e3-2"}\n'),
    "output_hash": ("outputs.jsonl", b'{"case_id":"e3-1","decision":"accept"}\n'),
    "trace_hash": ("trace.jsonl", b'{"case_id":"e3-1","step":1}\n'),
    "provenance_hash": ("provenance.json", b'{"origin":"REAL_MODEL_EXECUTION"}\n'),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_exact_artifacts(destination_root: Path, *, authority_sha256: str) -> dict[str, Path]:
    bindings = {
        logical_name: hashlib.sha256(payload).hexdigest()
        for logical_name, (_, payload) in RAW_MEMBER_PAYLOADS.items()
    }
    bindings["pre_execution_authority_record_sha256"] = authority_sha256

    t4_path = destination_root / "publication" / "tables" / "T4_dataset_composition.json"
    t4_path.parent.mkdir(parents=True, exist_ok=True)
    t4_payload = {
        "schema_version": "POI_MPP_E3_T4_V1",
        "artifact_role": "DATASET_COMPOSITION",
        "experiment_id": "E3",
        "claim_id": "C3",
        "run_id": RUN_ID,
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "record_count": 8,
        "class_counts": {"invalid": 2, "valid": 6},
        "execution_bindings": bindings,
    }
    t4_path.write_text(json.dumps(t4_payload, sort_keys=True) + "\n", encoding="utf-8")

    t8_path = destination_root / "publication" / "tables" / "T8_semantic_verification.csv"
    t8_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "schema_version",
        "artifact_role",
        "experiment_id",
        "claim_id",
        "run_id",
        "evidence_origin",
        "metric",
        "value",
        "sample_count",
        *bindings.keys(),
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for metric, (value, sample_count) in EXPECTED_METRICS.items():
        writer.writerow(
            {
                "schema_version": "POI_MPP_E3_T8_V1",
                "artifact_role": "SEMANTIC_METRICS",
                "experiment_id": "E3",
                "claim_id": "C3",
                "run_id": RUN_ID,
                "evidence_origin": "REAL_MODEL_EXECUTION",
                "metric": metric,
                "value": value,
                "sample_count": str(sample_count),
                **bindings,
            }
        )
    t8_path.write_text(stream.getvalue(), encoding="utf-8")

    f7_path = destination_root / "publication" / "figures" / "F7_semantic_verification_quality.svg"
    f7_path.parent.mkdir(parents=True, exist_ok=True)
    f7_metadata = {
        "schema_version": "POI_MPP_E3_F7_METADATA_V1",
        "artifact_role": "SEMANTIC_QUALITY_FIGURE",
        "experiment_id": "E3",
        "claim_id": "C3",
        "run_id": RUN_ID,
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "metric_scope": list(EXPECTED_METRICS),
        "source_t8_sha256": _sha256(t8_path),
        "execution_bindings": bindings,
    }
    f7_path.write_text(
        (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"120\" height=\"40\" viewBox=\"0 0 120 40\">"
            f"<metadata id=\"poi-e3-attestation\">{json.dumps(f7_metadata, sort_keys=True)}</metadata>"
            "<rect width=\"120\" height=\"40\" fill=\"#ffffff\"/>"
            "<text x=\"8\" y=\"24\" font-size=\"10\">E3 semantic metrics</text>"
            "</svg>\n"
        ),
        encoding="utf-8",
    )

    raw_path = destination_root / "results" / "publication" / RUN_ID / "raw_e3_execution.zip"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_manifest = {
        "schema_version": "POI_MPP_E3_RAW_EXECUTION_V1",
        "artifact_role": "RAW_EXECUTION_BUNDLE",
        "experiment_id": "E3",
        "claim_id": "C3",
        "run_id": RUN_ID,
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "metric_scope": list(EXPECTED_METRICS),
        "execution_bindings": bindings,
        "files": {
            logical_name: {
                "path": relative_path,
                "sha256": bindings[logical_name],
                "size_bytes": len(payload),
            }
            for logical_name, (relative_path, payload) in RAW_MEMBER_PAYLOADS.items()
        },
    }
    with zipfile.ZipFile(raw_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for _, (member_path, payload) in RAW_MEMBER_PAYLOADS.items():
            archive.writestr(member_path, payload)
        archive.writestr("run_manifest.json", json.dumps(raw_manifest, sort_keys=True))
    return {
        "T4": t4_path,
        "T8": t8_path,
        "F7": f7_path,
        "RAW_E3_EXECUTION": raw_path,
    }


def _execution_bindings(t4_path: Path) -> dict[str, str]:
    payload = json.loads(t4_path.read_text(encoding="utf-8"))
    return dict(payload["execution_bindings"])


def _build_request(path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(BUILD_REQUEST_SCRIPT), "--output", str(path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(path.read_text(encoding="utf-8"))


def _key_material(tmp_path: Path) -> tuple[Path, Path]:
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required for detached signature verification")
    private_key = tmp_path / "e3_attestor_key"
    public_key = tmp_path / "e3_attestor_key.pub"
    allowed_signers = tmp_path / "allowed_signers"
    completed = subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    allowed_signers.write_text(
        f'test-evaluator@example.org namespaces="file" {public_key.read_text(encoding="utf-8").strip()}\n',
        encoding="utf-8",
    )
    return private_key, allowed_signers


def _sign(private_key: Path, record_path: Path) -> Path:
    completed = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(private_key), "-n", "file", str(record_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return Path(f"{record_path}.sig")


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _authority_record(request_path: Path, request: dict[str, object]) -> dict[str, object]:
    requested_scope = request["requested_scope"]
    assert isinstance(requested_scope, dict)
    return {
        "schema_version": "POI_MPP_E3_AUTHORITY_RECORD_V2",
        "record_type": "PRE_EXECUTION_SCOPE_AUTHORIZATION",
        "authority_identity": "test-evaluator@example.org",
        "authority_basis": "Detached-signature test evaluator for reporting import receipts",
        "expertise_scope": "Grounded semantic evaluation, calibration, and publication import verification",
        "authorized_scope": {
            "experiment_id": "E3",
            "claim_id": "C3",
            "task_class": requested_scope["task_class"],
            "evidence_origin": "REAL_MODEL_EXECUTION",
            "metric_scope": requested_scope["metric_scope"],
            "artifact_scope": requested_scope["artifact_scope"],
            "privacy_scope": "No prompt text leaves the approved evaluator environment",
            "request_scope_digest": request["requested_scope_digest"],
        },
        "reviewed_request_manifest": {
            "path": request_path.name,
            "sha256": _sha256(request_path),
            "self_digest": request["self_digest"],
        },
        "decision": "APPROVED",
        "decision_notes": "Full E3 publication-scope import is authorized for receipt verification.",
        "authorization_date": "2026-08-24",
        "result_attestation_status": "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION",
        "external_signature_required": True,
        "signature_reference": "external://authority.sig",
        "allowed_signers_reference": "external://allowed_signers",
    }


def _attestation_record(
    *,
    source_root: Path,
    request_path: Path,
    request: dict[str, object],
    authority_path: Path,
    artifacts: dict[str, Path],
) -> dict[str, object]:
    bindings = _execution_bindings(artifacts["T4"])
    entries = []
    roles = {
        "T4": "DATASET_COMPOSITION",
        "T8": "SEMANTIC_METRICS",
        "F7": "SEMANTIC_QUALITY_FIGURE",
        "RAW_E3_EXECUTION": "RAW_EXECUTION_BUNDLE",
    }
    ordered_artifacts = ("T4", "T8", "F7", "RAW_E3_EXECUTION")
    for artifact_id in ordered_artifacts:
        path = artifacts[artifact_id]
        entries.append(
            {
                "artifact_id": artifact_id,
                "artifact_role": roles[artifact_id],
                "path": path.relative_to(source_root).as_posix(),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
                "experiment_id": "E3",
                "claim_id": "C3",
                "run_id": RUN_ID,
                "evidence_origin": "REAL_MODEL_EXECUTION",
            }
        )
    return {
        "schema_version": "POI_MPP_E3_RESULT_ATTESTATION_V1",
        "record_type": "POST_EXECUTION_RESULT_ATTESTATION",
        "authority_identity": "test-evaluator@example.org",
        "authority_basis": "Detached-signature test evaluator for reporting import receipts",
        "expertise_scope": "Grounded semantic evaluation, calibration, and publication import verification",
        "pre_execution_authority_record": {
            "path": authority_path.name,
            "sha256": _sha256(authority_path),
        },
        "reviewed_request_manifest": {
            "path": request_path.name,
            "sha256": _sha256(request_path),
            "self_digest": request["self_digest"],
        },
        "result_scope": {
            "experiment_id": "E3",
            "claim_id": "C3",
            "task_class": "GROUNDED_SEMANTIC_ASSURANCE",
            "run_id": RUN_ID,
            "evidence_origin": "REAL_MODEL_EXECUTION",
            "metric_scope": ["ABSTAIN", "FAR", "FRR", "calibration", "coverage"],
            "artifact_scope": ["F7", "RAW_E3_EXECUTION", "T4", "T8"],
            "execution_bindings": bindings,
        },
        "artifacts": entries,
        "results_disposition": "ATTESTED_AS_REPORTED",
        "attestation_notes": (
            "Receipt fixture authenticates the exact attested E3 artifacts only; publication support stays "
            "separately adjudicated as NOT_SUPPORTED."
        ),
        "attestation_date": "2026-08-24",
        "publication_support_decision_status": "NOT_EVALUATED_BY_THIS_ATTESTATION",
        "external_signature_required": True,
        "signature_namespace": "file",
        "signature_reference": "external://result.sig",
        "allowed_signers_reference": "external://allowed_signers",
    }


def _verification_receipt(
    *,
    tmp_path: Path,
    source_root: Path,
) -> dict[str, object]:
    request_path = tmp_path / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    request = _build_request(request_path)
    authority_path = _write_json(tmp_path / "authority_record.json", _authority_record(request_path, request))
    artifacts = _write_exact_artifacts(source_root, authority_sha256=_sha256(authority_path))
    attestation_path = _write_json(
        tmp_path / "result_attestation.json",
        _attestation_record(
            source_root=source_root,
            request_path=request_path,
            request=request,
            authority_path=authority_path,
            artifacts=artifacts,
        ),
    )
    private_key, allowed_signers = _key_material(tmp_path)
    authority_signature = _sign(private_key, authority_path)
    attestation_signature = _sign(private_key, attestation_path)
    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFY_RESULT_SCRIPT),
            "--request-manifest",
            str(request_path),
            "--authority-record",
            str(authority_path),
            "--authority-signature",
            str(authority_signature),
            "--attestation-record",
            str(attestation_path),
            "--attestation-signature",
            str(attestation_signature),
            "--allowed-signers",
            str(allowed_signers),
            "--artifact-root",
            str(source_root),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _stage_verified_source_set(tmp_path: Path) -> tuple[ReportBuildSpec, Path]:
    artifact_root = tmp_path / "inputs"
    source_root = artifact_root / "results" / "publication" / RUN_ID / "artifacts"
    receipt = _verification_receipt(tmp_path=tmp_path, source_root=source_root)
    receipt_path = artifact_root / "results" / "publication" / RUN_ID / "e3_result_attestation_verification.json"
    _write_json(receipt_path, receipt)
    spec = ReportBuildSpec.model_validate(
        {
            "artifact_root": str(artifact_root.resolve()),
            "output_root": str((tmp_path / "out").resolve()),
            "sources": {
                "E3": {
                    "artifact_root_path": "results/publication/e3-confirmatory-real-20260824/artifacts",
                    "verified_receipt_path": "results/publication/e3-confirmatory-real-20260824/e3_result_attestation_verification.json",
                }
            },
        }
    )
    return spec, source_root


def _wrap_import_receipt(direct: dict[str, object]) -> dict[str, object]:
    authority = {
        "status": "VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY",
        "decision": "APPROVED",
    }
    canonical = lambda payload: hashlib.sha256(  # noqa: E731 - compact fixture helper
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    filenames = {
        "F7": "F7_semantic_verification_quality.svg",
        "RAW_E3_EXECUTION": "raw_e3_execution.zip",
        "T4": "T4_dataset_composition.json",
        "T8": "T8_semantic_verification.csv",
    }
    imported_artifacts = [
        {
            "artifact_id": item["artifact_id"],
            "source_path": item["path"],
            "target_path": f"results/publication/{RUN_ID}/source/{filenames[item['artifact_id']]}",
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
        }
        for item in direct["verified_artifacts"]
    ]
    return {
        "schema_version": "POI_MPP_E3_VERIFIED_IMPORT_RECEIPT_V1",
        "status": "VERIFIED_E3_IMPORTED",
        "run_id": RUN_ID,
        "authority_verification": authority,
        "authority_verification_sha256": canonical(authority),
        "attestation_verification": direct,
        "attestation_verification_sha256": canonical(direct),
        "imported_artifacts": imported_artifacts,
        "metrics": {
            "FAR": "0.500",
            "FRR": "0.167",
            "ABSTAIN": "0.125",
            "coverage": "0.875",
            "calibration": "0.178",
        },
        "metric_sample_counts": {
            "FAR": 2,
            "FRR": 6,
            "ABSTAIN": 8,
            "coverage": 8,
            "calibration": 7,
        },
        "dataset_composition": {
            "record_count": 8,
            "class_counts": {"invalid": 2, "valid": 6},
        },
        "decision": {
            "alpha_sem": "0.25",
            "c3_disposition": "NOT_SUPPORTED",
            "reason": "FAR exceeds the frozen alpha_sem threshold",
        },
        "caveats": [
            "Cryptographic verification authenticates exact signed files and artifact hashes only; it does not prove real-world identity, independence, or private-key custody."
        ],
    }


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_loader_accepts_verified_e3_receipt_and_materializes_exact_attested_bytes(tmp_path: Path) -> None:
    spec, source_root = _stage_verified_source_set(tmp_path)

    bundle = load_publication_inputs(spec)
    e3 = next(experiment for experiment in bundle.experiments if experiment.experiment_id == "E3")

    assert e3.disposition == "NOT_SUPPORTED"
    assert e3.origin == "REAL_MODEL_EXECUTION"
    assert e3.scope == "E3_CONFIRMATORY_PUBLICATION_V1"
    assert e3.run_id == RUN_ID
    assert isinstance(e3.config_hash, str) and len(e3.config_hash) == 64
    assert e3.sample_size == 8
    assert e3.summary == {
        "alpha_sem": 0.25,
        "artifact_scope": ["F7", "RAW_E3_EXECUTION", "T4", "T8"],
        "attestation_status": "VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION",
        "authority_decision": "APPROVED",
        "calibration": 0.17840000000000003,
        "claim_id": "C3",
        "claim_disposition": "NOT_SUPPORTED",
        "coverage": 0.875,
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "far": 0.5,
        "frr": 0.16666666666666666,
        "invalid_count": 2,
        "metric_scope": ["ABSTAIN", "FAR", "FRR", "calibration", "coverage"],
        "record_count": 8,
        "run_id": RUN_ID,
        "sample_note": "n=8 with invalid class n=2; no general semantic-reliability claim is admissible.",
    }
    assert e3.table_rows == ()
    assert e3.figure_points == ()
    assert e3.omission_reason is None
    assert {output.artifact_id for output in e3.generated_outputs} == {"T4", "T8", "F7", "RAW_E3_EXECUTION"}

    manifest = build_publication_report(spec)
    output_root = Path(spec.output_root)
    assert validate_existing_manifest(output_root).manifest_sha256 == manifest.manifest_sha256

    output_paths = {
        "T4": output_root / "tables" / "T4_dataset_composition.json",
        "T8": output_root / "tables" / "T8_semantic_verification.csv",
        "F7": output_root / "figures" / "F7_semantic_verification_quality.svg",
        "RAW_E3_EXECUTION": output_root / "results" / "publication" / RUN_ID / "raw_e3_execution.zip",
    }
    source_paths = {
        "T4": source_root / "publication" / "tables" / "T4_dataset_composition.json",
        "T8": source_root / "publication" / "tables" / "T8_semantic_verification.csv",
        "F7": source_root / "publication" / "figures" / "F7_semantic_verification_quality.svg",
        "RAW_E3_EXECUTION": source_root / "results" / "publication" / RUN_ID / "raw_e3_execution.zip",
    }
    for artifact_id, output_path in output_paths.items():
        assert output_path.read_bytes() == source_paths[artifact_id].read_bytes()

    claim_rows = json.loads((output_root / "tables" / "claim_matrix.json").read_text(encoding="utf-8"))
    e3_rows = [row for row in claim_rows if row["experiment_id"] == "E3"]
    assert {row["artifact_id"] for row in e3_rows} == {"T4", "T8"}
    assert {row["disposition"] for row in e3_rows} == {"NOT_SUPPORTED"}
    assert {row["origin"] for row in e3_rows} == {"REAL_MODEL_EXECUTION"}
    assert {row["run_id"] for row in e3_rows} == {RUN_ID}

    omissions = json.loads((output_root / "tables" / "omissions.json").read_text(encoding="utf-8"))
    assert not [row for row in omissions if row["experiment_id"] == "E3"]


def test_loader_accepts_canonical_verified_import_receipt(tmp_path: Path) -> None:
    spec, source_root = _stage_verified_source_set(tmp_path)
    receipt_path = Path(spec.artifact_root) / "results" / "publication" / RUN_ID / "e3_result_attestation_verification.json"
    direct = json.loads(receipt_path.read_text(encoding="utf-8"))
    filenames = {
        "F7": "F7_semantic_verification_quality.svg",
        "RAW_E3_EXECUTION": "raw_e3_execution.zip",
        "T4": "T4_dataset_composition.json",
        "T8": "T8_semantic_verification.csv",
    }
    for item in direct["verified_artifacts"]:
        shutil.copy2(source_root / item["path"], source_root / filenames[item["artifact_id"]])
    _write_json(receipt_path, _wrap_import_receipt(direct))

    bundle = load_publication_inputs(spec)
    e3 = next(experiment for experiment in bundle.experiments if experiment.experiment_id == "E3")
    assert e3.disposition == "NOT_SUPPORTED"
    assert e3.sample_size == 8


def test_loader_rejects_incomplete_or_limited_scope_e3_receipt(tmp_path: Path) -> None:
    spec, _ = _stage_verified_source_set(tmp_path)
    receipt_path = Path(spec.artifact_root) / "results" / "publication" / RUN_ID / "e3_result_attestation_verification.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["status"] = "VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION_INCOMPLETE"
    receipt["authority_decision"] = "LIMITED_SCOPE"
    receipt["publication_eligibility_status"] = "INCOMPLETE_NONPUBLICATION"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicationEligibilityError, match="complete publication-scope E3 receipt"):
        build_publication_report(spec)


def test_loader_rejects_e3_metric_drift_even_when_receipt_hashes_are_updated(tmp_path: Path) -> None:
    spec, source_root = _stage_verified_source_set(tmp_path)
    t8_path = source_root / "publication" / "tables" / "T8_semantic_verification.csv"
    old_hash = _source_hash(t8_path)
    rows = list(csv.DictReader(io.StringIO(t8_path.read_text(encoding="utf-8"), newline="")))
    for row in rows:
        if row["metric"] == "FAR":
            row["value"] = "0.2"
    fieldnames = list(rows[0])
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    t8_path.write_text(stream.getvalue(), encoding="utf-8")

    f7_path = source_root / "publication" / "figures" / "F7_semantic_verification_quality.svg"
    svg = f7_path.read_text(encoding="utf-8")
    new_hash = _source_hash(t8_path)
    f7_path.write_text(svg.replace(old_hash, new_hash), encoding="utf-8")

    receipt_path = Path(spec.artifact_root) / "results" / "publication" / RUN_ID / "e3_result_attestation_verification.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for artifact in receipt["verified_artifacts"]:
        if artifact["artifact_id"] == "T8":
            artifact["sha256"] = _source_hash(t8_path)
            artifact["size_bytes"] = t8_path.stat().st_size
        if artifact["artifact_id"] == "F7":
            artifact["sha256"] = _source_hash(f7_path)
            artifact["size_bytes"] = f7_path.stat().st_size
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicationEligibilityError, match="E3 metric values"):
        build_publication_report(spec)
