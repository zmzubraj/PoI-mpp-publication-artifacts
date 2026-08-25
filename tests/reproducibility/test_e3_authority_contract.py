from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_e3_authority_request.py"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_e3_authority.py"


def _canonical_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_request(output: Path) -> dict[str, object]:
    subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output", str(output)],
        cwd=REPO_ROOT,
        check=True,
    )
    return json.loads(output.read_text(encoding="utf-8"))


def _authority_record(request_path: Path, request: dict[str, object]) -> dict[str, object]:
    requested_scope = request["requested_scope"]
    assert isinstance(requested_scope, dict)
    return {
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
            "metric_scope": requested_scope["metric_scope"],
            "artifact_scope": requested_scope["artifact_scope"],
            "privacy_scope": "No prompt text may leave the approved evaluator environment",
            "request_scope_digest": request["requested_scope_digest"],
        },
        "reviewed_request_manifest": {
            "path": request_path.name,
            "sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
            "self_digest": request["self_digest"],
        },
        "decision": "APPROVED",
        "decision_notes": "Authorization is limited to the hash-bound E3 pre-execution scope.",
        "authorization_date": "2026-08-24",
        "result_attestation_status": "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION",
        "external_signature_required": True,
        "signature_reference": "external://e3-authority-record.sig",
        "allowed_signers_reference": "external://e3-authority-allowed-signers",
    }


def _sign_record(tmp_path: Path, record_path: Path, identity: str) -> tuple[Path, Path]:
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required for detached signature verification")
    private_key = tmp_path / "authority_key"
    public_key = tmp_path / "authority_key.pub"
    allowed_signers = tmp_path / "allowed_signers"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
        capture_output=True,
    )
    pubkey = public_key.read_text(encoding="utf-8").strip()
    allowed_signers.write_text(f'{identity} namespaces="file" {pubkey}\n', encoding="utf-8")
    subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(private_key), "-n", "file", str(record_path)],
        check=True,
        capture_output=True,
    )
    return allowed_signers, Path(f"{record_path}.sig")


def _run_verifier(
    request_path: Path,
    record_path: Path,
    allowed_signers: Path | None,
    signature: Path | None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(VERIFY_SCRIPT),
        "--request-manifest",
        str(request_path),
        "--authority-record",
        str(record_path),
    ]
    if allowed_signers is not None:
        command.extend(["--allowed-signers", str(allowed_signers)])
    if signature is not None:
        command.extend(["--signature", str(signature)])
    return subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)


def test_e3_request_manifest_is_deterministic_hash_closed_and_e3_only(tmp_path: Path) -> None:
    output = tmp_path / "request.json"
    payload = _build_request(output)

    assert payload["schema_version"] == "POI_MPP_E3_AUTHORITY_REQUEST_V1"
    assert payload["status"] == "UNSIGNED_PRE_EXECUTION_SCOPE_REQUEST"
    assert payload["current_e3_status"] == "NOT_SUPPORTED_SIGNED_REVISION_CURRENT_CHAIN_DRIFT"
    assert payload["requested_scope"] == {
        "experiment_id": "E3",
        "claim_id": "C3",
        "task_class": "GROUNDED_SEMANTIC_ASSURANCE",
        "metric_scope": ["ABSTAIN", "FAR", "FRR", "calibration", "coverage"],
        "artifact_scope": ["F7", "RAW_E3_EXECUTION", "T4", "T8"],
        "evidence_origin": "REAL_MODEL_EXECUTION",
    }
    assert payload["result_attestation_status"] == "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION"
    assert payload["self_digest"] == _canonical_digest(payload)

    paths = {entry["path"] for entry in payload["request_inputs"]}
    assert "publication/artifact_manifest.json" in paths
    assert "publication/tables/omissions.json" in paths
    assert "docs/paper_artifacts/final/external_review/semantic_evaluator_authority_record.schema.json" in paths
    assert "docs/paper_artifacts/final/external_review/e3_result_attestation_record.schema.json" in paths
    assert "scripts/build_e3_authority_package.py" in paths
    assert "scripts/verify_e3_result_attestation.py" in paths
    assert all(not Path(path).is_absolute() and ".." not in Path(path).parts for path in paths)
    for entry in payload["request_inputs"]:
        artifact = REPO_ROOT / entry["path"]
        assert entry["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert entry["size_bytes"] == artifact.stat().st_size

    second = tmp_path / "request-second.json"
    _build_request(second)
    assert second.read_bytes() == output.read_bytes()
    subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output", str(output), "--check"],
        cwd=REPO_ROOT,
        check=True,
    )


def test_e3_request_check_rejects_stale_output(tmp_path: Path) -> None:
    output = tmp_path / "request.json"
    payload = _build_request(output)
    payload["status"] = "APPROVED"
    output.write_text(json.dumps(payload), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output", str(output), "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0
    assert "stale or non-canonical" in completed.stderr


def test_e3_authority_verifier_accepts_real_external_detached_signature(tmp_path: Path) -> None:
    request_path = tmp_path / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    request = _build_request(request_path)
    record = _authority_record(request_path, request)
    record_path = tmp_path / "authority_record.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    allowed_signers, signature = _sign_record(tmp_path, record_path, str(record["authority_identity"]))

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY"
    assert result["experiment_id"] == "E3"
    assert result["result_attestation_status"] == "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION"


def test_e3_authority_verifier_accepts_documented_repo_relative_request_path(
    tmp_path: Path,
) -> None:
    request_path = (
        REPO_ROOT
        / "docs"
        / "paper_artifacts"
        / "final"
        / "external_review"
        / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    record = _authority_record(request_path, request)
    record["reviewed_request_manifest"]["path"] = request_path.relative_to(REPO_ROOT).as_posix()
    record_path = tmp_path / "authority_record.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    allowed_signers, signature = _sign_record(tmp_path, record_path, str(record["authority_identity"]))

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode == 0, completed.stderr


def test_e3_authority_verifier_accepts_hash_bound_limited_scope(tmp_path: Path) -> None:
    request_path = tmp_path / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    request = _build_request(request_path)
    record = _authority_record(request_path, request)
    record["decision"] = "LIMITED_SCOPE"
    record["authorized_scope"]["metric_scope"] = ["ABSTAIN", "FAR"]
    record["authorized_scope"]["artifact_scope"] = ["RAW_E3_EXECUTION", "T8"]
    record_path = tmp_path / "authority_record.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    allowed_signers, signature = _sign_record(tmp_path, record_path, str(record["authority_identity"]))

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["decision"] == "LIMITED_SCOPE"


@pytest.mark.parametrize(
    "artifact_scope",
    (
        ["T4"],
        ["RAW_E3_EXECUTION", "T4"],
        ["T8", "F7"],
    ),
)
def test_e3_authority_verifier_rejects_limited_scope_without_minimum_attestable_core(
    tmp_path: Path, artifact_scope: list[str]
) -> None:
    request_path = tmp_path / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    request = _build_request(request_path)
    record = _authority_record(request_path, request)
    record["decision"] = "LIMITED_SCOPE"
    record["authorized_scope"]["metric_scope"] = ["FAR"]
    record["authorized_scope"]["artifact_scope"] = artifact_scope
    record_path = tmp_path / "authority_record.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    allowed_signers, signature = _sign_record(tmp_path, record_path, str(record["authority_identity"]))

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode != 0
    assert "limited authority scope must include RAW_E3_EXECUTION and T8" in completed.stderr


def test_e3_authority_verifier_rejects_record_changed_after_signature(tmp_path: Path) -> None:
    request_path = tmp_path / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    request = _build_request(request_path)
    record = _authority_record(request_path, request)
    record_path = tmp_path / "authority_record.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    allowed_signers, signature = _sign_record(tmp_path, record_path, str(record["authority_identity"]))
    record["decision_notes"] = "Changed after signing"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode != 0
    assert "signature verification failed" in completed.stderr


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("blank_identity", "authority_identity"),
        ("invalid_decision", "decision"),
        ("manifest_hash_mismatch", "request manifest sha256 mismatch"),
        ("scope_mismatch", "approved authority scope must exactly match"),
    ),
)
def test_e3_authority_verifier_fails_closed_on_invalid_record(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    request_path = tmp_path / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    request = _build_request(request_path)
    record = _authority_record(request_path, request)
    if mutation == "blank_identity":
        record["authority_identity"] = ""
    elif mutation == "invalid_decision":
        record["decision"] = "DECLINED"
    elif mutation == "manifest_hash_mismatch":
        record["reviewed_request_manifest"]["sha256"] = "0" * 64
    elif mutation == "scope_mismatch":
        record["authorized_scope"] = deepcopy(record["authorized_scope"])
        record["authorized_scope"]["metric_scope"] = ["FAR"]
    record_path = tmp_path / "authority_record.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    allowed_signers, signature = _sign_record(tmp_path, record_path, "external-evaluator@example.org")

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode != 0
    assert expected in completed.stderr


def test_e3_authority_verifier_requires_external_signature_inputs(tmp_path: Path) -> None:
    request_path = tmp_path / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    request = _build_request(request_path)
    record = _authority_record(request_path, request)
    record_path = tmp_path / "authority_record.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    completed = _run_verifier(request_path, record_path, None, None)
    assert completed.returncode != 0
    assert "detached signature and allowed-signers file are required" in completed.stderr


def test_e3_authority_verifier_rejects_allowed_signers_inside_repository(tmp_path: Path) -> None:
    request_path = tmp_path / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    request = _build_request(request_path)
    record = _authority_record(request_path, request)
    record_path = tmp_path / "authority_record.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    external_signers, signature = _sign_record(tmp_path, record_path, "external-evaluator@example.org")
    inside_repo = REPO_ROOT / ".e3-test-allowed-signers"
    try:
        inside_repo.write_bytes(external_signers.read_bytes())
        completed = _run_verifier(request_path, record_path, inside_repo, signature)
        assert completed.returncode != 0
        assert "must live outside the repository" in completed.stderr
    finally:
        inside_repo.unlink(missing_ok=True)
