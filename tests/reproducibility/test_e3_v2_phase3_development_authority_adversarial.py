from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from poi_mpp.experiments.e3_v2_development_authority import (
    DevelopmentAuthorityError,
    verify_development_authority,
)
from tests.experiments.e3_v2_bundle_fixtures import (
    _load_script_module,
    canonical_json_bytes,
    sha256_bytes,
    write_development_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_e3_v2_development_authority_request.py"
IDENTITY = "phase3-authority-test@example.org"


def _builder():
    return _load_script_module("_phase3_development_authority_request_red", BUILD_SCRIPT)


def _request(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    bundle = write_development_bundle(tmp_path / "development-bundle")
    request_path = tmp_path / "development-authority-request.json"
    _builder().build_development_authority_request(
        bundle_root=bundle,
        output_path=request_path,
    )
    return request_path, json.loads(request_path.read_bytes())


def _record(
    request_path: Path,
    request: dict[str, object],
    *,
    decision: str = "APPROVED",
    authorization_date: str | None = None,
    metric_scope: list[str] | None = None,
) -> dict[str, object]:
    requested = request["requested_scope"]
    assert isinstance(requested, dict)
    support_rule = requested["support_rule"]
    assert isinstance(support_rule, dict)
    return {
        "schema_version": "POI_MPP_E3_V2_DEVELOPMENT_AUTHORITY_RECORD_V1",
        "record_type": "DEVELOPMENT_PRE_EXECUTION_SCOPE_AUTHORIZATION",
        "authority_identity": IDENTITY,
        "authority_basis": "Accountable external development evaluator",
        "expertise_scope": "Grounded semantic calibration",
        "authorized_scope": {
            "experiment_id": requested["experiment_id"],
            "experiment_generation": requested["experiment_generation"],
            "claim_id": requested["claim_id"],
            "claim_generation": requested["claim_generation"],
            "task_class": requested["task_class"],
            "evidence_origin": requested["evidence_origin"],
            "metric_scope": metric_scope or requested["metric_scope"],
            "artifact_scope": requested["artifact_scope"],
            "scope_scope": "DEVELOPMENT",
            "development_composition": support_rule["development_composition"],
            "request_scope_digest": request["requested_scope_digest"],
        },
        "bound_materials": request["bound_materials"],
        "reviewed_request_manifest": {
            "path": request_path.name,
            "sha256": sha256_bytes(request_path.read_bytes()),
            "self_digest": request["self_digest"],
        },
        "decision": decision,
        "decision_notes": "Hash-bound development-only authorization.",
        "authorization_date": authorization_date or date.today().isoformat(),
        "result_attestation_status": "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION",
        "external_signature_required": True,
        "signature_reference": "external://development-authority.sig",
        "allowed_signers_reference": "external://development-allowed-signers",
    }


def _write_trust_inputs(
    tmp_path: Path,
    request_path: Path,
    request: dict[str, object],
    **record_kwargs: object,
) -> tuple[Path, Path, Path]:
    record_path = tmp_path / "development-authority-record.json"
    record_path.write_bytes(canonical_json_bytes(_record(request_path, request, **record_kwargs)))
    allowed_signers = tmp_path / "allowed_signers"
    allowed_signers.write_text("test-only external trust material\n", encoding="utf-8")
    signature = tmp_path / "development-authority-record.sig"
    signature.write_text("test-only detached signature\n", encoding="utf-8")
    return record_path, allowed_signers, signature


def _signature_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=b"Good signature", stderr=b""),
    )


def test_request_builder_rejects_member_tampered_after_manifest_seal(tmp_path: Path) -> None:
    bundle = write_development_bundle(tmp_path / "development-bundle")
    (bundle / "policy" / "prompt_template.txt").write_text(
        "tampered after manifest sealing\n", encoding="utf-8"
    )

    with pytest.raises(Exception, match="manifest|hash|tamper"):
        _builder().build_development_authority_request(
            bundle_root=bundle,
            output_path=tmp_path / "request.json",
        )


def test_request_builder_rejects_symlinked_bundle_root(tmp_path: Path) -> None:
    bundle = write_development_bundle(tmp_path / "development-bundle")
    linked_bundle = tmp_path / "linked-development-bundle"
    linked_bundle.symlink_to(bundle, target_is_directory=True)

    with pytest.raises(Exception, match="symlink"):
        _builder().build_development_authority_request(
            bundle_root=linked_bundle,
            output_path=tmp_path / "request.json",
        )


def test_verifier_rederives_requested_scope_digest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    request_path, request = _request(tmp_path)
    request["requested_scope_digest"] = "0" * 64
    unsigned = dict(request)
    unsigned.pop("self_digest", None)
    request["self_digest"] = sha256_bytes(canonical_json_bytes(unsigned))
    request_path.write_bytes(canonical_json_bytes(request))
    record_path, allowed_signers, signature = _write_trust_inputs(
        tmp_path, request_path, request
    )
    _signature_succeeds(monkeypatch)

    with pytest.raises(DevelopmentAuthorityError, match="requested scope digest"):
        verify_development_authority(
            request_manifest_path=request_path,
            authority_record_path=record_path,
            allowed_signers_path=allowed_signers,
            signature_path=signature,
        )


def test_verifier_rejects_stale_authorization(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    request_path, request = _request(tmp_path)
    stale_date = (date.today() - timedelta(days=366)).isoformat()
    record_path, allowed_signers, signature = _write_trust_inputs(
        tmp_path,
        request_path,
        request,
        authorization_date=stale_date,
    )
    _signature_succeeds(monkeypatch)

    with pytest.raises(DevelopmentAuthorityError, match="stale"):
        verify_development_authority(
            request_manifest_path=request_path,
            authority_record_path=record_path,
            allowed_signers_path=allowed_signers,
            signature_path=signature,
        )


def test_limited_scope_must_be_a_strict_narrowing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request_path, request = _request(tmp_path)
    record_path, allowed_signers, signature = _write_trust_inputs(
        tmp_path,
        request_path,
        request,
        decision="LIMITED_SCOPE",
    )
    _signature_succeeds(monkeypatch)

    with pytest.raises(DevelopmentAuthorityError, match="LIMITED_SCOPE"):
        verify_development_authority(
            request_manifest_path=request_path,
            authority_record_path=record_path,
            allowed_signers_path=allowed_signers,
            signature_path=signature,
        )


def test_verifier_rejects_repository_local_and_symlinked_trust_files(tmp_path: Path) -> None:
    request_path, request = _request(tmp_path)
    record_path, allowed_signers, signature = _write_trust_inputs(tmp_path, request_path, request)
    repository_signers = REPO_ROOT / "tmp-phase3-allowed-signers-test-only"
    repository_signers.write_bytes(allowed_signers.read_bytes())
    linked_parent = tmp_path / "linked-trust-parent"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)
    try:
        with pytest.raises(DevelopmentAuthorityError, match="outside the repository"):
            verify_development_authority(
                request_manifest_path=request_path,
                authority_record_path=record_path,
                allowed_signers_path=repository_signers,
                signature_path=signature,
            )
        with pytest.raises(DevelopmentAuthorityError, match="symlink"):
            verify_development_authority(
                request_manifest_path=request_path,
                authority_record_path=record_path,
                allowed_signers_path=linked_parent / allowed_signers.name,
                signature_path=signature,
            )
    finally:
        repository_signers.unlink(missing_ok=True)
