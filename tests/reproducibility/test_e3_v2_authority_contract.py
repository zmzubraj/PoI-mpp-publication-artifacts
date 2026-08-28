from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.experiments.e3_v2_bundle_fixtures import (
    _load_script_module,
    canonical_json_bytes,
    sha256_bytes,
)
from tests.experiments.test_e3_v2_scope import _write_authority_inputs


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_e3_v2_authority.py"
IDENTITY = "external-evaluator@example.org"


def _canonical_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    return sha256_bytes(canonical_json_bytes(unsigned))


def _build_request(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    from poi_mpp.experiments.e3_v2_scope import build_manifest

    inputs = _write_authority_inputs(tmp_path)
    manifest = build_manifest(
        development_report_path=inputs["development_report"],
        confirmatory_lineage_path=inputs["confirmatory_lineage"],
        calibration_freeze_path=inputs["calibration_freeze"],
    )
    request_path = tmp_path / "e3_v2_authority_request.json"
    request_path.write_bytes(canonical_json_bytes(manifest))
    return request_path, manifest


def _authority_record(
    request_path: Path,
    request: dict[str, object],
    *,
    decision: str = "APPROVED",
    metric_scope: list[str] | None = None,
    artifact_scope: list[str] | None = None,
    bound_materials: dict[str, str] | None = None,
) -> dict[str, object]:
    requested = request["requested_scope"]
    assert isinstance(requested, dict)
    return {
        "schema_version": "POI_MPP_E3_AUTHORITY_RECORD_V3",
        "record_type": "PRE_EXECUTION_SCOPE_AUTHORIZATION",
        "authority_identity": IDENTITY,
        "authority_basis": "Accountable external semantic-evaluation lead",
        "expertise_scope": "Grounded semantic evaluation, calibration, and privacy review",
        "authorized_scope": {
            "experiment_id": "E3",
            "experiment_generation": "E3_V2",
            "claim_id": "C3",
            "claim_generation": "C3_V2",
            "task_class": requested["task_class"],
            "evidence_origin": requested["evidence_origin"],
            "metric_scope": metric_scope if metric_scope is not None else requested["metric_scope"],
            "artifact_scope": (
                artifact_scope if artifact_scope is not None else requested["artifact_scope"]
            ),
            "privacy_scope": "No prompt text may leave the approved evaluator environment",
            "request_scope_digest": request["requested_scope_digest"],
            "support_rule": requested["support_rule"],
        },
        "bound_materials": bound_materials
        if bound_materials is not None
        else dict(request["bound_materials"]),
        "reviewed_request_manifest": {
            "path": request_path.name,
            "sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
            "self_digest": request["self_digest"],
        },
        "decision": decision,
        "decision_notes": "Authorization is limited to the hash-bound E3-v2 pre-execution scope.",
        "authorization_date": "2026-08-25",
        "result_attestation_status": "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION",
        "external_signature_required": True,
        "signature_reference": "external://e3-v2-authority-record.sig",
        "allowed_signers_reference": "external://e3-v2-authority-allowed-signers",
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


def _write_signed_record(
    tmp_path: Path,
    request_path: Path,
    request: dict[str, object],
    **record_kwargs: object,
) -> tuple[Path, Path, Path, dict[str, object]]:
    record = _authority_record(request_path, request, **record_kwargs)
    record_path = tmp_path / "e3_v2_authority_record.json"
    record_path.write_bytes(canonical_json_bytes(record))
    allowed_signers, signature = _sign_record(tmp_path, record_path, IDENTITY)
    return record_path, allowed_signers, signature, record


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


def test_verify_e3_v2_authority_accepts_valid_signed_record(tmp_path: Path) -> None:
    request_path, request = _build_request(tmp_path)
    record_path, allowed_signers, signature, _ = _write_signed_record(tmp_path, request_path, request)

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["schema_version"] == "POI_MPP_E3_AUTHORITY_VERIFICATION_V2"
    assert summary["status"] == "VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY"
    assert summary["experiment_id"] == "E3"
    assert summary["experiment_generation"] == "E3_V2"
    assert summary["claim_id"] == "C3"
    assert summary["claim_generation"] == "C3_V2"
    assert summary["decision"] == "APPROVED"
    assert summary["authority_identity"] == IDENTITY
    assert summary["request_manifest_sha256"] == hashlib.sha256(request_path.read_bytes()).hexdigest()
    assert summary["request_manifest_self_digest"] == request["self_digest"]
    assert summary["authority_record_sha256"] == hashlib.sha256(record_path.read_bytes()).hexdigest()
    assert summary["result_attestation_status"] == "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION"


def test_verify_authority_emits_authentic_v2_grant(tmp_path: Path) -> None:
    from poi_mpp.experiments.e3_v2_authority import _grant_is_authentic

    request_path, request = _build_request(tmp_path)
    record_path, allowed_signers, signature, _ = _write_signed_record(tmp_path, request_path, request)
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required for detached signature verification")
    verifier = _load_script_module("_poi_mpp_verify_e3_v2_authority_runtime", VERIFY_SCRIPT)

    grant = verifier.verify_authority(
        request_path,
        record_path,
        allowed_signers_path=allowed_signers,
        signature_path=signature,
    )

    assert _grant_is_authentic(grant) is True
    assert grant.decision == "APPROVED"
    assert grant["decision"] == "APPROVED"
    assert grant.experiment_generation == "E3_V2"
    assert grant.claim_generation == "C3_V2"
    bound = request["bound_materials"]
    assert grant.development_bundle_manifest_sha256 == bound["development_bundle_manifest_sha256"]
    assert grant.development_policy_inputs_digest == bound["development_policy_inputs_digest"]
    assert (
        grant.confirmatory_freeze_material_lineage_hash
        == bound["confirmatory_freeze_material_lineage_hash"]
    )
    assert grant.calibration_freeze_content_hash == bound["calibration_freeze_content_hash"]
    assert grant.support_rule_id == "C3_V2_WILSON_SUPPORT_V1"
    assert grant.far_wilson_upper_bound_max == "0.25"
    assert grant.confirmatory_composition == {
        "ACCEPT": 200,
        "REJECT": 200,
        "ABSTAIN": 100,
        "total": 500,
    }
    assert grant.authority_record_sha256 == hashlib.sha256(record_path.read_bytes()).hexdigest()


def test_verify_e3_v2_authority_rejects_tampered_record(tmp_path: Path) -> None:
    request_path, request = _build_request(tmp_path)
    record_path, allowed_signers, signature, record = _write_signed_record(
        tmp_path, request_path, request
    )
    tampered = dict(record)
    tampered["decision_notes"] = "Authorization expanded after signing."
    record_path.write_bytes(canonical_json_bytes(tampered))

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode != 0
    assert "signature verification failed" in completed.stderr


def test_verify_e3_v2_authority_rejects_tampered_request_manifest(tmp_path: Path) -> None:
    request_path, request = _build_request(tmp_path)
    record_path, allowed_signers, signature, _ = _write_signed_record(tmp_path, request_path, request)

    stale = json.loads(request_path.read_text(encoding="utf-8"))
    stale["bound_materials"]["development_bundle_manifest_sha256"] = "0" * 64
    stale["bound_materials_digest"] = sha256_bytes(canonical_json_bytes(stale["bound_materials"]))
    stale["self_digest"] = _canonical_digest(stale)
    request_path.write_bytes(canonical_json_bytes(stale))

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode != 0
    assert "stale, tampered, or non-canonical" in completed.stderr


def test_verify_e3_v2_authority_rejects_bound_materials_echo_mismatch(tmp_path: Path) -> None:
    request_path, request = _build_request(tmp_path)
    wrong_echo = dict(request["bound_materials"])
    wrong_echo["calibration_freeze_content_hash"] = "b" * 64
    record_path, allowed_signers, signature, _ = _write_signed_record(
        tmp_path, request_path, request, bound_materials=wrong_echo
    )

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode != 0
    assert "bound_materials" in completed.stderr


def test_verify_e3_v2_authority_rejects_missing_signature_inputs(tmp_path: Path) -> None:
    request_path, request = _build_request(tmp_path)
    record = _authority_record(request_path, request)
    record_path = tmp_path / "e3_v2_authority_record.json"
    record_path.write_bytes(canonical_json_bytes(record))

    completed = _run_verifier(request_path, record_path, None, None)
    assert completed.returncode != 0
    assert "detached signature and allowed-signers file are required" in completed.stderr


def test_verify_e3_v2_authority_rejects_repository_local_authority_record(tmp_path: Path) -> None:
    request_path, request = _build_request(tmp_path)
    record_path, allowed_signers, signature, _ = _write_signed_record(tmp_path, request_path, request)
    inside_repo = REPO_ROOT / "tmp-e3-v2-authority-record-test-only.json"
    inside_repo.write_bytes(record_path.read_bytes())
    try:
        completed = _run_verifier(request_path, inside_repo, allowed_signers, signature)
        assert completed.returncode != 0
        assert "must live outside the repository" in completed.stderr
    finally:
        inside_repo.unlink(missing_ok=True)


def test_verify_e3_v2_authority_rejects_request_manifest_with_symlinked_parent(
    tmp_path: Path,
) -> None:
    request_path, request = _build_request(tmp_path)
    record_path, allowed_signers, signature, _ = _write_signed_record(
        tmp_path, request_path, request
    )
    linked_parent = tmp_path / "linked-request-parent"
    linked_parent.symlink_to(request_path.parent, target_is_directory=True)

    completed = _run_verifier(
        linked_parent / request_path.name,
        record_path,
        allowed_signers,
        signature,
    )
    assert completed.returncode != 0
    assert "request manifest may not be a symlink" in completed.stderr


def test_verify_e3_v2_authority_rejects_allowed_signers_with_symlinked_parent(
    tmp_path: Path,
) -> None:
    request_path, request = _build_request(tmp_path)
    record_path, allowed_signers, signature, _ = _write_signed_record(
        tmp_path, request_path, request
    )
    linked_parent = tmp_path / "linked-allowed-signers-parent"
    linked_parent.symlink_to(allowed_signers.parent, target_is_directory=True)

    completed = _run_verifier(
        request_path,
        record_path,
        linked_parent / allowed_signers.name,
        signature,
    )
    assert completed.returncode != 0
    assert "allowed-signers file may not be a symlink" in completed.stderr


def test_verify_e3_v2_authority_limited_scope_requires_minimum_core(tmp_path: Path) -> None:
    request_path, request = _build_request(tmp_path)
    record_path, allowed_signers, signature, _ = _write_signed_record(
        tmp_path,
        request_path,
        request,
        decision="LIMITED_SCOPE",
        metric_scope=["FAR", "FRR"],
        artifact_scope=["RAW_E3_EXECUTION", "T8"],
    )
    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["decision"] == "LIMITED_SCOPE"


def test_verify_e3_v2_authority_limited_scope_without_t8_is_refused(tmp_path: Path) -> None:
    request_path, request = _build_request(tmp_path)
    record_path, allowed_signers, signature, _ = _write_signed_record(
        tmp_path,
        request_path,
        request,
        decision="LIMITED_SCOPE",
        metric_scope=["FAR", "FRR"],
        artifact_scope=["RAW_E3_EXECUTION"],
    )
    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode != 0
    assert "must include RAW_E3_EXECUTION and T8" in completed.stderr


def test_verify_e3_v2_authority_rejects_wrong_scope_digest(tmp_path: Path) -> None:
    request_path, request = _build_request(tmp_path)
    record = _authority_record(request_path, request)
    record["authorized_scope"]["request_scope_digest"] = "c" * 64
    record_path = tmp_path / "e3_v2_authority_record.json"
    record_path.write_bytes(canonical_json_bytes(record))
    allowed_signers, signature = _sign_record(tmp_path, record_path, IDENTITY)

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode != 0
    assert "request_scope_digest mismatch" in completed.stderr


def test_verify_e3_v2_authority_rejects_relaxed_support_rule(tmp_path: Path) -> None:
    request_path, request = _build_request(tmp_path)
    record = _authority_record(request_path, request)
    relaxed = dict(request["requested_scope"]["support_rule"])
    relaxed["far_wilson_upper_bound_max"] = "0.30"
    record["authorized_scope"]["support_rule"] = relaxed
    record_path = tmp_path / "e3_v2_authority_record.json"
    record_path.write_bytes(canonical_json_bytes(record))
    allowed_signers, signature = _sign_record(tmp_path, record_path, IDENTITY)

    completed = _run_verifier(request_path, record_path, allowed_signers, signature)
    assert completed.returncode != 0
    assert "support rule" in completed.stderr
