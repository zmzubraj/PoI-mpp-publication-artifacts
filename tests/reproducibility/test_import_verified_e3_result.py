from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_UNDER_TEST = REPO_ROOT / "scripts" / "import_verified_e3_result.py"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest_payload(*, signed: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "TEST_E3_REQUEST_V1",
        "signed_state": signed,
        "requested_scope": {
            "experiment_id": "E3",
            "claim_id": "C3",
            "task_class": "GROUNDED_SEMANTIC_ASSURANCE",
            "evidence_origin": "REAL_MODEL_EXECUTION",
            "metric_scope": ["ABSTAIN", "FAR", "FRR", "calibration", "coverage"],
            "artifact_scope": ["F7", "RAW_E3_EXECUTION", "T4", "T8"],
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["self_digest"] = hashlib.sha256(encoded).hexdigest()
    return payload


def _write_request_manifest(path: Path, *, signed: bool) -> dict[str, object]:
    payload = _manifest_payload(signed=signed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _write_stub_verifiers(scripts_dir: Path) -> None:
    authority_script = """#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-manifest", required=True)
    parser.add_argument("--authority-record", required=True)
    parser.add_argument("--allowed-signers", required=True)
    parser.add_argument("--signature", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.request_manifest).read_text(encoding="utf-8"))
    if manifest.get("signed_state") is not True:
        print("expected signed manifest content", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY",
        "decision": "APPROVED",
        "request_manifest_sha256": "signed-manifest-sha",
        "request_manifest_self_digest": manifest["self_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
    attestation_script = """#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-manifest", required=True)
    parser.add_argument("--authority-record", required=True)
    parser.add_argument("--authority-signature", required=True)
    parser.add_argument("--attestation-record", required=True)
    parser.add_argument("--attestation-signature", required=True)
    parser.add_argument("--allowed-signers", required=True)
    parser.add_argument("--artifact-root", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.request_manifest).read_text(encoding="utf-8"))
    attestation = json.loads(Path(args.attestation_record).read_text(encoding="utf-8"))
    if manifest.get("signed_state") is not True:
        print("expected signed manifest content", file=sys.stderr)
        return 1
    print(json.dumps({
        "schema_version": "POI_MPP_E3_RESULT_ATTESTATION_VERIFICATION_V1",
        "status": "VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION",
        "run_id": attestation["run_id"],
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "authority_decision": "APPROVED",
        "publication_eligibility_status": "COMPLETE_INPUT_SET_REQUIRES_SEPARATE_C3_ADJUDICATION",
        "verified_artifacts": attestation["verified_artifacts"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
    (scripts_dir / "verify_e3_authority.py").write_text(authority_script, encoding="utf-8")
    (scripts_dir / "verify_e3_result_attestation.py").write_text(attestation_script, encoding="utf-8")


def _build_external_package(root: Path) -> tuple[Path, Path]:
    artifact_root = root / "artifacts"
    (artifact_root / "publication/tables").mkdir(parents=True, exist_ok=True)
    (artifact_root / "publication/figures").mkdir(parents=True, exist_ok=True)
    (artifact_root / "results/publication/e3-confirmatory-real-20260824").mkdir(parents=True, exist_ok=True)

    t4_path = artifact_root / "publication/tables/T4_dataset_composition.json"
    t4_payload = {
        "schema_version": "POI_MPP_E3_T4_V1",
        "artifact_role": "DATASET_COMPOSITION",
        "experiment_id": "E3",
        "claim_id": "C3",
        "run_id": "e3-confirmatory-real-20260824",
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "record_count": 8,
        "class_counts": {"invalid": 2, "valid": 6},
    }
    t4_path.write_text(json.dumps(t4_payload, sort_keys=True) + "\n", encoding="utf-8")

    t8_path = artifact_root / "publication/tables/T8_semantic_verification.csv"
    with t8_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value", "sample_count"])
        writer.writeheader()
        writer.writerows(
            [
                {"metric": "ABSTAIN", "value": "0.125", "sample_count": 8},
                {"metric": "FAR", "value": "0.500", "sample_count": 2},
                {"metric": "FRR", "value": "0.167", "sample_count": 6},
                {"metric": "calibration", "value": "0.178", "sample_count": 7},
                {"metric": "coverage", "value": "0.875", "sample_count": 8},
            ]
        )

    f7_path = artifact_root / "publication/figures/F7_semantic_verification_quality.svg"
    f7_path.write_text("<svg xmlns='http://www.w3.org/2000/svg'><rect width='1' height='1'/></svg>\n", encoding="utf-8")

    raw_path = artifact_root / "results/publication/e3-confirmatory-real-20260824/raw_e3_execution.zip"
    with zipfile.ZipFile(raw_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("run_manifest.json", '{"origin":"REAL_MODEL_EXECUTION"}\n')

    attestation_payload = {
        "run_id": "e3-confirmatory-real-20260824",
        "verified_artifacts": [
            {
                "artifact_id": "F7",
                "path": "publication/figures/F7_semantic_verification_quality.svg",
                "sha256": _sha256_bytes(f7_path.read_bytes()),
                "size_bytes": f7_path.stat().st_size,
            },
            {
                "artifact_id": "RAW_E3_EXECUTION",
                "path": "results/publication/e3-confirmatory-real-20260824/raw_e3_execution.zip",
                "sha256": _sha256_bytes(raw_path.read_bytes()),
                "size_bytes": raw_path.stat().st_size,
            },
            {
                "artifact_id": "T4",
                "path": "publication/tables/T4_dataset_composition.json",
                "sha256": _sha256_bytes(t4_path.read_bytes()),
                "size_bytes": t4_path.stat().st_size,
            },
            {
                "artifact_id": "T8",
                "path": "publication/tables/T8_semantic_verification.csv",
                "sha256": _sha256_bytes(t8_path.read_bytes()),
                "size_bytes": t8_path.stat().st_size,
            },
        ],
    }
    attestation_path = root / "attestation.json"
    attestation_path.write_text(
        json.dumps(attestation_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact_root, attestation_path


def _build_temp_repo(tmp_path: Path) -> tuple[Path, str, Path]:
    repo = tmp_path / "repo"
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT_UNDER_TEST, scripts_dir / "import_verified_e3_result.py")
    _write_stub_verifiers(scripts_dir)
    current_manifest = repo / "docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_MANIFEST.json"
    _write_request_manifest(current_manifest, signed=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.org"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
    revision = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
    )
    _write_request_manifest(current_manifest, signed=False)
    return repo, revision, current_manifest


def _run_import(
    repo: Path,
    *,
    revision: str,
    request_manifest: Path,
    authority_record: Path,
    authority_signature: Path,
    allowed_signers: Path,
    attestation_record: Path,
    attestation_signature: Path,
    artifact_root: Path,
) -> subprocess.CompletedProcess[str]:
    script_path = repo / "scripts/import_verified_e3_result.py"
    return subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--request-manifest",
            str(request_manifest),
            "--authority-record",
            str(authority_record),
            "--authority-signature",
            str(authority_signature),
            "--allowed-signers",
            str(allowed_signers),
            "--attestation-record",
            str(attestation_record),
            "--attestation-signature",
            str(attestation_signature),
            "--artifact-root",
            str(artifact_root),
            "--signed-revision",
            revision,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_import_uses_signed_revision_and_writes_receipt(tmp_path: Path) -> None:
    repo, revision, current_manifest = _build_temp_repo(tmp_path)
    external_root = tmp_path / "external"
    external_root.mkdir()
    artifact_root, attestation_path = _build_external_package(external_root)
    authority_record = external_root / "authority.json"
    authority_record.write_text('{"identity":"external"}\n', encoding="utf-8")
    authority_signature = external_root / "authority.sig"
    authority_signature.write_text("sig\n", encoding="utf-8")
    allowed_signers = external_root / "allowed_signers"
    allowed_signers.write_text("allowed\n", encoding="utf-8")
    attestation_signature = external_root / "attestation.sig"
    attestation_signature.write_text("sig\n", encoding="utf-8")

    completed = _run_import(
        repo,
        revision=revision,
        request_manifest=current_manifest,
        authority_record=authority_record,
        authority_signature=authority_signature,
        allowed_signers=allowed_signers,
        attestation_record=attestation_path,
        attestation_signature=attestation_signature,
        artifact_root=artifact_root,
    )

    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["status"] == "VERIFIED_E3_IMPORTED"
    assert receipt["signed_revision"] == revision
    assert receipt["current_request_manifest"]["self_digest"] == _manifest_payload(signed=False)["self_digest"]
    assert receipt["decision"]["alpha_sem"] == "0.25"
    assert receipt["decision"]["c3_disposition"] == "NOT_SUPPORTED"
    assert receipt["metrics"] == {
        "ABSTAIN": "0.125",
        "FAR": "0.500",
        "FRR": "0.167",
        "calibration": "0.178",
        "coverage": "0.875",
    }
    assert receipt["metric_sample_counts"] == {
        "ABSTAIN": 8,
        "FAR": 2,
        "FRR": 6,
        "calibration": 7,
        "coverage": 8,
    }
    assert receipt["dataset_composition"] == {
        "record_count": 8,
        "class_counts": {"invalid": 2, "valid": 6},
    }
    run_root = repo / "results/publication/e3-confirmatory-real-20260824"
    assert (run_root / "source/T4_dataset_composition.json").is_file()
    assert (run_root / "source/T8_semantic_verification.csv").is_file()
    assert (run_root / "source/F7_semantic_verification_quality.svg").is_file()
    assert (run_root / "source/raw_e3_execution.zip").is_file()
    saved_receipt = json.loads((run_root / "verification_receipt.json").read_text(encoding="utf-8"))
    assert saved_receipt["caveats"][0].startswith("Cryptographic verification")


def test_import_rejects_repository_local_allowed_signers(tmp_path: Path) -> None:
    repo, revision, current_manifest = _build_temp_repo(tmp_path)
    external_root = tmp_path / "external"
    external_root.mkdir()
    artifact_root, attestation_path = _build_external_package(external_root)
    authority_record = external_root / "authority.json"
    authority_record.write_text('{"identity":"external"}\n', encoding="utf-8")
    authority_signature = external_root / "authority.sig"
    authority_signature.write_text("sig\n", encoding="utf-8")
    attestation_signature = external_root / "attestation.sig"
    attestation_signature.write_text("sig\n", encoding="utf-8")
    repo_local_allowed_signers = repo / "allowed_signers"
    repo_local_allowed_signers.write_text("allowed\n", encoding="utf-8")

    completed = _run_import(
        repo,
        revision=revision,
        request_manifest=current_manifest,
        authority_record=authority_record,
        authority_signature=authority_signature,
        allowed_signers=repo_local_allowed_signers,
        attestation_record=attestation_path,
        attestation_signature=attestation_signature,
        artifact_root=artifact_root,
    )

    assert completed.returncode == 1
    assert "must live outside the repository" in completed.stderr


def test_import_rejects_existing_divergent_target(tmp_path: Path) -> None:
    repo, revision, current_manifest = _build_temp_repo(tmp_path)
    external_root = tmp_path / "external"
    external_root.mkdir()
    artifact_root, attestation_path = _build_external_package(external_root)
    authority_record = external_root / "authority.json"
    authority_record.write_text('{"identity":"external"}\n', encoding="utf-8")
    authority_signature = external_root / "authority.sig"
    authority_signature.write_text("sig\n", encoding="utf-8")
    allowed_signers = external_root / "allowed_signers"
    allowed_signers.write_text("allowed\n", encoding="utf-8")
    attestation_signature = external_root / "attestation.sig"
    attestation_signature.write_text("sig\n", encoding="utf-8")
    target = repo / "results/publication/e3-confirmatory-real-20260824/source"
    target.mkdir(parents=True, exist_ok=True)
    (target / "T4_dataset_composition.json").write_text("divergent\n", encoding="utf-8")

    completed = _run_import(
        repo,
        revision=revision,
        request_manifest=current_manifest,
        authority_record=authority_record,
        authority_signature=authority_signature,
        allowed_signers=allowed_signers,
        attestation_record=attestation_path,
        attestation_signature=attestation_signature,
        artifact_root=artifact_root,
    )

    assert completed.returncode == 1
    assert "existing target contains divergent content" in completed.stderr


def test_import_rejects_metric_denominator_drift(tmp_path: Path) -> None:
    repo, revision, current_manifest = _build_temp_repo(tmp_path)
    external_root = tmp_path / "external"
    external_root.mkdir()
    artifact_root, attestation_path = _build_external_package(external_root)
    t8_path = artifact_root / "publication/tables/T8_semantic_verification.csv"
    rows = list(csv.DictReader(t8_path.read_text(encoding="utf-8").splitlines()))
    next(row for row in rows if row["metric"] == "FAR")["sample_count"] = "3"
    with t8_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value", "sample_count"])
        writer.writeheader()
        writer.writerows(rows)
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    t8_entry = next(item for item in attestation["verified_artifacts"] if item["artifact_id"] == "T8")
    t8_entry["sha256"] = _sha256_bytes(t8_path.read_bytes())
    t8_entry["size_bytes"] = t8_path.stat().st_size
    attestation_path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    authority_record = external_root / "authority.json"
    authority_record.write_text('{"identity":"external"}\n', encoding="utf-8")
    for name in ("authority.sig", "allowed_signers", "attestation.sig"):
        (external_root / name).write_text("value\n", encoding="utf-8")

    completed = _run_import(
        repo,
        revision=revision,
        request_manifest=current_manifest,
        authority_record=authority_record,
        authority_signature=external_root / "authority.sig",
        allowed_signers=external_root / "allowed_signers",
        attestation_record=attestation_path,
        attestation_signature=external_root / "attestation.sig",
        artifact_root=artifact_root,
    )

    assert completed.returncode == 1
    assert "sample_count" in completed.stderr


def test_import_rejects_dataset_composition_drift(tmp_path: Path) -> None:
    repo, revision, current_manifest = _build_temp_repo(tmp_path)
    external_root = tmp_path / "external"
    external_root.mkdir()
    artifact_root, attestation_path = _build_external_package(external_root)
    t4_path = artifact_root / "publication/tables/T4_dataset_composition.json"
    t4 = json.loads(t4_path.read_text(encoding="utf-8"))
    t4["class_counts"] = {"invalid": 3, "valid": 5}
    t4_path.write_text(json.dumps(t4, sort_keys=True) + "\n", encoding="utf-8")
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    t4_entry = next(item for item in attestation["verified_artifacts"] if item["artifact_id"] == "T4")
    t4_entry["sha256"] = _sha256_bytes(t4_path.read_bytes())
    t4_entry["size_bytes"] = t4_path.stat().st_size
    attestation_path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    authority_record = external_root / "authority.json"
    authority_record.write_text('{"identity":"external"}\n', encoding="utf-8")
    for name in ("authority.sig", "allowed_signers", "attestation.sig"):
        (external_root / name).write_text("value\n", encoding="utf-8")

    completed = _run_import(
        repo,
        revision=revision,
        request_manifest=current_manifest,
        authority_record=authority_record,
        authority_signature=external_root / "authority.sig",
        allowed_signers=external_root / "allowed_signers",
        attestation_record=attestation_path,
        attestation_signature=external_root / "attestation.sig",
        artifact_root=artifact_root,
    )

    assert completed.returncode == 1
    assert "class_counts" in completed.stderr
