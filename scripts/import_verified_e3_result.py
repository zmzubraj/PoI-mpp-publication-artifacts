#!/usr/bin/env python3
"""Import a verified externally attested E3 result into the local repository."""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ARTIFACT_IDS = ("F7", "RAW_E3_EXECUTION", "T4", "T8")
TARGET_FILENAMES = {
    "F7": "F7_semantic_verification_quality.svg",
    "RAW_E3_EXECUTION": "raw_e3_execution.zip",
    "T4": "T4_dataset_composition.json",
    "T8": "T8_semantic_verification.csv",
}
REQUIRED_METRICS = ("ABSTAIN", "FAR", "FRR", "calibration", "coverage")
EXPECTED_METRIC_SAMPLE_COUNTS = {
    "ABSTAIN": 8,
    "FAR": 2,
    "FRR": 6,
    "calibration": 7,
    "coverage": 8,
}
EXPECTED_CLASS_COUNTS = {"invalid": 2, "valid": 6}
EXPECTED_RECORD_COUNT = 8
ALPHA_SEM = Decimal("0.25")


class ImportVerifiedE3Error(ValueError):
    pass


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(REPO_ROOT.resolve(strict=True)).as_posix()
    except ValueError as error:
        raise ImportVerifiedE3Error(f"path must live inside repository: {path}") from error


def _safe_external_file(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ImportVerifiedE3Error(f"{label} may not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise ImportVerifiedE3Error(f"{label} is missing: {path}") from error
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise ImportVerifiedE3Error(f"{label} must live outside the repository")
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise ImportVerifiedE3Error(f"{label} must be a non-empty file")
    return resolved


def _safe_external_dir(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ImportVerifiedE3Error(f"{label} may not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise ImportVerifiedE3Error(f"{label} is missing: {path}") from error
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise ImportVerifiedE3Error(f"{label} must live outside the repository")
    if not resolved.is_dir():
        raise ImportVerifiedE3Error(f"{label} must be a directory")
    return resolved


def _read_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise ImportVerifiedE3Error(f"{label} may not be a symlink")
    try:
        raw = path.resolve(strict=True).read_bytes()
    except (FileNotFoundError, OSError) as error:
        raise ImportVerifiedE3Error(f"{label} is missing or unreadable: {path}") from error
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ImportVerifiedE3Error(f"{label} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ImportVerifiedE3Error(f"{label} must be a JSON object")
    return payload, raw


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _run_json_script(script_path: Path, args: list[Path | str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(script_path), *[str(item) for item in args]],
        cwd=script_path.parent.parent,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown verifier failure"
        raise ImportVerifiedE3Error(detail)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ImportVerifiedE3Error(f"verifier did not emit valid JSON: {script_path.name}") from error
    if not isinstance(payload, dict):
        raise ImportVerifiedE3Error(f"verifier output must be a JSON object: {script_path.name}")
    return payload


def _verified_worktree(repo_root: Path, revision: str) -> tuple[Path, str]:
    revision_check = _run_git(["rev-parse", "--verify", f"{revision}^{{commit}}"], cwd=repo_root)
    if revision_check.returncode != 0:
        raise ImportVerifiedE3Error(f"signed revision is not a valid commit: {revision}")
    resolved_revision = revision_check.stdout.strip()
    temp_dir = Path(tempfile.mkdtemp(prefix="poi-signed-e3-"))
    add_completed = _run_git(["worktree", "add", "--detach", str(temp_dir), resolved_revision], cwd=repo_root)
    if add_completed.returncode != 0:
        shutil.rmtree(temp_dir, ignore_errors=True)
        detail = add_completed.stderr.strip() or add_completed.stdout.strip() or "git worktree add failed"
        raise ImportVerifiedE3Error(detail)
    return temp_dir, resolved_revision


def _cleanup_worktree(repo_root: Path, worktree: Path) -> None:
    _run_git(["worktree", "remove", "--force", str(worktree)], cwd=repo_root)
    shutil.rmtree(worktree, ignore_errors=True)


def _check_worktree_clean(worktree: Path, *, expected_revision: str) -> None:
    head = _run_git(["rev-parse", "HEAD"], cwd=worktree)
    if head.returncode != 0 or head.stdout.strip() != expected_revision:
        raise ImportVerifiedE3Error("temporary signed worktree does not match the requested revision")
    status = _run_git(["status", "--porcelain"], cwd=worktree)
    if status.returncode != 0:
        raise ImportVerifiedE3Error("failed to inspect temporary signed worktree status")
    if status.stdout.strip():
        raise ImportVerifiedE3Error("temporary signed worktree is dirty")


def _verified_artifact_source(artifact_root: Path, artifact: dict[str, Any]) -> tuple[Path, bytes]:
    artifact_id = artifact.get("artifact_id")
    if artifact_id not in TARGET_FILENAMES:
        raise ImportVerifiedE3Error(f"unexpected artifact id from attestation verifier: {artifact_id}")
    path_text = artifact.get("path")
    if not isinstance(path_text, str) or not path_text:
        raise ImportVerifiedE3Error(f"artifact {artifact_id} path is invalid")
    relative = PurePosixPath(path_text)
    if relative.is_absolute() or ".." in relative.parts or "\\" in path_text:
        raise ImportVerifiedE3Error(f"artifact {artifact_id} path is unsafe")
    cursor = artifact_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ImportVerifiedE3Error(f"artifact {artifact_id} may not traverse symlinks")
    candidate = artifact_root.joinpath(*relative.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(artifact_root)
    except (FileNotFoundError, ValueError) as error:
        raise ImportVerifiedE3Error(f"artifact {artifact_id} escapes artifact root") from error
    if not resolved.is_file():
        raise ImportVerifiedE3Error(f"artifact {artifact_id} must be a regular file")
    payload = resolved.read_bytes()
    expected_sha = artifact.get("sha256")
    expected_size = artifact.get("size_bytes")
    if not isinstance(expected_sha, str) or _sha256_bytes(payload) != expected_sha:
        raise ImportVerifiedE3Error(f"artifact {artifact_id} sha256 mismatch")
    if not isinstance(expected_size, int) or len(payload) != expected_size:
        raise ImportVerifiedE3Error(f"artifact {artifact_id} size mismatch")
    return resolved, payload


def _parse_metrics(t8_payload: bytes) -> tuple[dict[str, str], dict[str, int]]:
    try:
        text = t8_payload.decode("utf-8")
        reader = csv.DictReader(text.splitlines())
    except UnicodeDecodeError as error:
        raise ImportVerifiedE3Error("T8 artifact is not valid UTF-8") from error
    fieldnames = set(reader.fieldnames or [])
    if not {"metric", "value", "sample_count"}.issubset(fieldnames):
        raise ImportVerifiedE3Error("T8 artifact does not expose metric/value/sample_count columns")
    metrics: dict[str, str] = {}
    sample_counts: dict[str, int] = {}
    for row in reader:
        metric = row.get("metric")
        value = row.get("value")
        if metric not in REQUIRED_METRICS or value is None:
            continue
        try:
            decimal = Decimal(value)
        except InvalidOperation as error:
            raise ImportVerifiedE3Error(f"T8 metric {metric} is not a valid decimal") from error
        if not decimal.is_finite() or decimal < 0 or decimal > 1:
            raise ImportVerifiedE3Error(f"T8 metric {metric} is outside [0,1]")
        try:
            sample_count = int(row.get("sample_count", ""))
        except ValueError as error:
            raise ImportVerifiedE3Error(f"T8 metric {metric} sample_count is invalid") from error
        if sample_count != EXPECTED_METRIC_SAMPLE_COUNTS[metric]:
            raise ImportVerifiedE3Error(
                f"T8 metric {metric} sample_count drifted from the attested E3 scope"
            )
        metrics[metric] = format(decimal.quantize(Decimal("0.001")), "f")
        sample_counts[metric] = sample_count
    if set(metrics) != set(REQUIRED_METRICS):
        raise ImportVerifiedE3Error("T8 metrics drift from the required E3 publication scope")
    return (
        {metric: metrics[metric] for metric in REQUIRED_METRICS},
        {metric: sample_counts[metric] for metric in REQUIRED_METRICS},
    )


def _parse_dataset_composition(t4_payload: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(t4_payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ImportVerifiedE3Error("T4 artifact is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ImportVerifiedE3Error("T4 artifact must be a JSON object")
    if payload.get("evidence_origin") != "REAL_MODEL_EXECUTION":
        raise ImportVerifiedE3Error("T4 evidence_origin must be REAL_MODEL_EXECUTION")
    if payload.get("record_count") != EXPECTED_RECORD_COUNT:
        raise ImportVerifiedE3Error("T4 record_count drifted from the attested E3 scope")
    if payload.get("class_counts") != EXPECTED_CLASS_COUNTS:
        raise ImportVerifiedE3Error("T4 class_counts drifted from the attested E3 scope")
    return {
        "record_count": EXPECTED_RECORD_COUNT,
        "class_counts": EXPECTED_CLASS_COUNTS,
    }


def _decision_from_metrics(metrics: dict[str, str]) -> dict[str, str]:
    far = Decimal(metrics["FAR"])
    if far <= ALPHA_SEM:
        raise ImportVerifiedE3Error("E3 import only accepts the attested NOT_SUPPORTED confirmatory outcome")
    return {
        "alpha_sem": format(ALPHA_SEM, "f"),
        "c3_disposition": "NOT_SUPPORTED",
        "reason": "FAR exceeds the frozen alpha_sem threshold",
    }


def _ensure_target_compatibility(target: Path, expected: dict[str, bytes], receipt_payload: dict[str, Any]) -> bool:
    source_dir = target / "source"
    receipt_path = target / "verification_receipt.json"
    if not target.exists():
        return False
    if not source_dir.is_dir():
        raise ImportVerifiedE3Error("existing target contains divergent content")
    for filename, payload in expected.items():
        candidate = source_dir / filename
        if not candidate.is_file() or candidate.read_bytes() != payload:
            raise ImportVerifiedE3Error("existing target contains divergent content")
    if not receipt_path.is_file():
        raise ImportVerifiedE3Error("existing target contains divergent content")
    try:
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImportVerifiedE3Error("existing target contains divergent content") from error
    if existing != receipt_payload:
        raise ImportVerifiedE3Error("existing target contains divergent content")
    return True


def import_verified_e3_result(
    *,
    request_manifest_path: Path,
    authority_record_path: Path,
    authority_signature_path: Path,
    allowed_signers_path: Path,
    attestation_record_path: Path,
    attestation_signature_path: Path,
    artifact_root_path: Path,
    signed_revision: str,
) -> dict[str, Any]:
    request_manifest, request_bytes = _read_json_object(request_manifest_path, label="current request manifest")
    current_request = {
        "path": _repo_relative(request_manifest_path),
        "sha256": _sha256_bytes(request_bytes),
        "self_digest": request_manifest.get("self_digest"),
    }
    if not isinstance(current_request["self_digest"], str) or not current_request["self_digest"]:
        raise ImportVerifiedE3Error("current request manifest self_digest is missing")

    authority_record = _safe_external_file(authority_record_path, label="authority record")
    authority_signature = _safe_external_file(authority_signature_path, label="authority signature")
    allowed_signers = _safe_external_file(allowed_signers_path, label="allowed-signers file")
    attestation_record = _safe_external_file(attestation_record_path, label="attestation record")
    attestation_signature = _safe_external_file(attestation_signature_path, label="attestation signature")
    artifact_root = _safe_external_dir(artifact_root_path, label="artifact root")

    signed_worktree, resolved_revision = _verified_worktree(REPO_ROOT, signed_revision)
    try:
        _check_worktree_clean(signed_worktree, expected_revision=resolved_revision)
        signed_request_path = signed_worktree / current_request["path"]
        if not signed_request_path.is_file():
            raise ImportVerifiedE3Error("signed revision does not contain the requested manifest path")
        authority_script = signed_worktree / "scripts" / "verify_e3_authority.py"
        attestation_script = signed_worktree / "scripts" / "verify_e3_result_attestation.py"
        if not authority_script.is_file() or not attestation_script.is_file():
            raise ImportVerifiedE3Error("signed revision is missing the canonical E3 verifier scripts")

        authority_verification = _run_json_script(
            authority_script,
            [
                "--request-manifest",
                signed_request_path,
                "--authority-record",
                authority_record,
                "--allowed-signers",
                allowed_signers,
                "--signature",
                authority_signature,
            ],
        )
        attestation_verification = _run_json_script(
            attestation_script,
            [
                "--request-manifest",
                signed_request_path,
                "--authority-record",
                authority_record,
                "--authority-signature",
                authority_signature,
                "--attestation-record",
                attestation_record,
                "--attestation-signature",
                attestation_signature,
                "--allowed-signers",
                allowed_signers,
                "--artifact-root",
                artifact_root,
            ],
        )
        signed_request_payload, signed_request_bytes = _read_json_object(
            signed_request_path, label="signed request manifest"
        )
    finally:
        _cleanup_worktree(REPO_ROOT, signed_worktree)

    if authority_verification.get("status") != "VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY":
        raise ImportVerifiedE3Error("authority verification did not return the required verified status")
    if authority_verification.get("decision") != "APPROVED":
        raise ImportVerifiedE3Error("authority verification did not return APPROVED")
    if attestation_verification.get("status") != "VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION":
        raise ImportVerifiedE3Error("attestation verification did not return the required verified status")
    if attestation_verification.get("authority_decision") != "APPROVED":
        raise ImportVerifiedE3Error("attestation verification did not preserve APPROVED authority scope")
    if attestation_verification.get("evidence_origin") != "REAL_MODEL_EXECUTION":
        raise ImportVerifiedE3Error("attestation verification evidence_origin must be REAL_MODEL_EXECUTION")
    if attestation_verification.get("publication_eligibility_status") != (
        "COMPLETE_INPUT_SET_REQUIRES_SEPARATE_C3_ADJUDICATION"
    ):
        raise ImportVerifiedE3Error("attestation verification did not authenticate the complete E3 publication scope")

    verified_artifacts = attestation_verification.get("verified_artifacts")
    if not isinstance(verified_artifacts, list):
        raise ImportVerifiedE3Error("attestation verifier did not return a verified artifact list")
    artifact_by_id: dict[str, dict[str, Any]] = {}
    for artifact in verified_artifacts:
        if not isinstance(artifact, dict):
            raise ImportVerifiedE3Error("verified artifact entries must be JSON objects")
        artifact_id = artifact.get("artifact_id")
        if artifact_id in artifact_by_id:
            raise ImportVerifiedE3Error("verified artifact list contains duplicate artifact ids")
        artifact_by_id[str(artifact_id)] = artifact
    if tuple(sorted(artifact_by_id)) != REQUIRED_ARTIFACT_IDS:
        raise ImportVerifiedE3Error("artifact scope drifted from the signed E3 publication contract")

    imported_payloads: dict[str, bytes] = {}
    imported_records: list[dict[str, Any]] = []
    for artifact_id in REQUIRED_ARTIFACT_IDS:
        source_path, payload = _verified_artifact_source(artifact_root, artifact_by_id[artifact_id])
        imported_payloads[TARGET_FILENAMES[artifact_id]] = payload
        imported_records.append(
            {
                "artifact_id": artifact_id,
                "source_path": str(artifact_by_id[artifact_id]["path"]),
                "target_path": f"results/publication/{attestation_verification['run_id']}/source/{TARGET_FILENAMES[artifact_id]}",
                "sha256": _sha256_bytes(payload),
                "size_bytes": len(payload),
            }
        )
    metrics, metric_sample_counts = _parse_metrics(imported_payloads[TARGET_FILENAMES["T8"]])
    dataset_composition = _parse_dataset_composition(imported_payloads[TARGET_FILENAMES["T4"]])
    decision = _decision_from_metrics(metrics)

    authority_output = json.dumps(authority_verification, sort_keys=True, separators=(",", ":")).encode("utf-8")
    attestation_output = json.dumps(attestation_verification, sort_keys=True, separators=(",", ":")).encode("utf-8")
    receipt = {
        "schema_version": "POI_MPP_E3_VERIFIED_IMPORT_RECEIPT_V1",
        "status": "VERIFIED_E3_IMPORTED",
        "run_id": attestation_verification["run_id"],
        "signed_revision": resolved_revision,
        "current_request_manifest": current_request,
        "signed_request_manifest": {
            "path": current_request["path"],
            "sha256": _sha256_bytes(signed_request_bytes),
            "self_digest": signed_request_payload.get("self_digest"),
        },
        "authority_verification": authority_verification,
        "authority_verification_sha256": _sha256_bytes(authority_output),
        "attestation_verification": attestation_verification,
        "attestation_verification_sha256": _sha256_bytes(attestation_output),
        "imported_artifacts": sorted(imported_records, key=lambda item: item["artifact_id"]),
        "metrics": metrics,
        "metric_sample_counts": metric_sample_counts,
        "dataset_composition": dataset_composition,
        "decision": decision,
        "caveats": [
            "Cryptographic verification authenticates exact signed files and artifact hashes only; it does not prove real-world identity, independence, or private-key custody.",
        ],
    }

    run_root = REPO_ROOT / "results" / "publication" / str(attestation_verification["run_id"])
    if _ensure_target_compatibility(run_root, imported_payloads, receipt):
        return receipt

    source_dir = run_root / "source"
    if source_dir.exists():
        raise ImportVerifiedE3Error("existing target contains divergent content")
    run_root.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(
        tempfile.mkdtemp(prefix=f".tmp-import-{attestation_verification['run_id']}-", dir=run_root.parent)
    )
    try:
        temp_source = temp_root / "source"
        temp_source.mkdir(parents=True, exist_ok=True)
        for filename, payload in imported_payloads.items():
            destination = temp_source / filename
            destination.write_bytes(payload)
        receipt_path = temp_root / "verification_receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            os.replace(temp_root, run_root)
        except OSError as error:
            raise ImportVerifiedE3Error(f"failed to atomically install verified E3 import: {error}") from error
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--authority-record", type=Path, required=True)
    parser.add_argument("--authority-signature", type=Path, required=True)
    parser.add_argument("--allowed-signers", type=Path, required=True)
    parser.add_argument("--attestation-record", type=Path, required=True)
    parser.add_argument("--attestation-signature", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--signed-revision", required=True)
    args = parser.parse_args()

    try:
        receipt = import_verified_e3_result(
            request_manifest_path=args.request_manifest,
            authority_record_path=args.authority_record,
            authority_signature_path=args.authority_signature,
            allowed_signers_path=args.allowed_signers,
            attestation_record_path=args.attestation_record,
            attestation_signature_path=args.attestation_signature,
            artifact_root_path=args.artifact_root,
            signed_revision=args.signed_revision,
        )
    except (ImportVerifiedE3Error, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1

    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
