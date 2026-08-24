#!/usr/bin/env python3
"""Verify a real externally signed E3 pre-execution authority record.

This verifier only authenticates the hash-bound permission to execute the E3
scope. It deliberately does not validate or attest to post-execution results.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from build_e3_authority_request import REPO_ROOT, build_manifest

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.experiments.e3_semantic import (  # noqa: E402
    VerifiedE3AuthorityGrant,
)


class AuthorityVerificationError(ValueError):
    pass


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorizedScope(_FrozenModel):
    experiment_id: Literal["E3"]
    claim_id: Literal["C3"]
    task_class: str = Field(min_length=1)
    evidence_origin: Literal["REAL_MODEL_EXECUTION"]
    metric_scope: tuple[Literal["FAR", "FRR", "ABSTAIN", "coverage", "calibration"], ...]
    artifact_scope: tuple[Literal["T4", "T8", "F7", "RAW_E3_EXECUTION"], ...]
    privacy_scope: str = Field(min_length=1)
    request_scope_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("metric_scope", "artifact_scope")
    @classmethod
    def _nonempty_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("scope must be non-empty and contain unique values")
        return value


class ReviewedRequestManifest(_FrozenModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    self_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("path")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("path must be a safe relative path")
        return value


class AuthorityRecord(_FrozenModel):
    schema_version: Literal["POI_MPP_E3_AUTHORITY_RECORD_V2"]
    record_type: Literal["PRE_EXECUTION_SCOPE_AUTHORIZATION"]
    authority_identity: str = Field(min_length=1)
    authority_basis: str = Field(min_length=1)
    expertise_scope: str = Field(min_length=1)
    authorized_scope: AuthorizedScope
    reviewed_request_manifest: ReviewedRequestManifest
    decision: Literal["APPROVED", "LIMITED_SCOPE"]
    decision_notes: str = Field(min_length=1)
    authorization_date: str
    result_attestation_status: Literal["NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION"]
    external_signature_required: Literal[True]
    signature_reference: str = Field(min_length=1)
    allowed_signers_reference: str = Field(min_length=1)

    @field_validator(
        "authority_identity",
        "authority_basis",
        "expertise_scope",
        "decision_notes",
        "signature_reference",
        "allowed_signers_reference",
    )
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value

    @field_validator("authorization_date")
    @classmethod
    def _strict_iso_date(cls, value: str) -> str:
        if len(value) != 10:
            raise ValueError("authorization_date must use strict ISO YYYY-MM-DD format")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("authorization_date must use strict ISO YYYY-MM-DD format") from error
        if parsed.isoformat() != value:
            raise ValueError("authorization_date must use strict ISO YYYY-MM-DD format")
        return value


def _canonical_digest(payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise AuthorityVerificationError(f"{label} may not be a symlink")
    try:
        raw = path.resolve(strict=True).read_bytes()
    except (FileNotFoundError, OSError) as error:
        raise AuthorityVerificationError(f"{label} is missing or unreadable: {path}") from error
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AuthorityVerificationError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise AuthorityVerificationError(f"{label} must be a JSON object")
    return payload, raw


def _external_file(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise AuthorityVerificationError(f"{label} may not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise AuthorityVerificationError(f"{label} is missing: {path}") from error
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise AuthorityVerificationError(f"{label} must live outside the repository")
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise AuthorityVerificationError(f"{label} must be a non-empty file")
    return resolved


def _validate_request(payload: dict[str, Any]) -> None:
    expected = build_manifest()
    if payload != expected:
        raise AuthorityVerificationError("E3 request manifest is stale, tampered, or non-canonical")
    if payload.get("self_digest") != _canonical_digest(payload):
        raise AuthorityVerificationError("E3 request manifest self_digest mismatch")


def _validate_scope(record: AuthorityRecord, request: dict[str, Any]) -> None:
    scope = record.authorized_scope
    requested = request["requested_scope"]
    if scope.request_scope_digest != request["requested_scope_digest"]:
        raise AuthorityVerificationError("authority request_scope_digest mismatch")
    fixed_matches = (
        scope.experiment_id == requested["experiment_id"]
        and scope.claim_id == requested["claim_id"]
        and scope.task_class == requested["task_class"]
        and scope.evidence_origin == requested["evidence_origin"]
    )
    if not fixed_matches:
        raise AuthorityVerificationError("authority scope does not match the canonical E3 request")
    metric_scope = set(scope.metric_scope)
    artifact_scope = set(scope.artifact_scope)
    requested_metrics = set(requested["metric_scope"])
    requested_artifacts = set(requested["artifact_scope"])
    if record.decision == "APPROVED" and (
        metric_scope != requested_metrics or artifact_scope != requested_artifacts
    ):
        raise AuthorityVerificationError("approved authority scope must exactly match the canonical E3 request")
    if record.decision == "LIMITED_SCOPE" and (
        not metric_scope.issubset(requested_metrics) or not artifact_scope.issubset(requested_artifacts)
    ):
        raise AuthorityVerificationError("limited authority scope must be a subset of the canonical E3 request")
    if record.decision == "LIMITED_SCOPE" and not {
        "RAW_E3_EXECUTION",
        "T8",
    }.issubset(artifact_scope):
        raise AuthorityVerificationError(
            "limited authority scope must include RAW_E3_EXECUTION and T8"
        )


def verify_authority(
    request_path: Path,
    authority_record_path: Path,
    *,
    allowed_signers_path: Path | None,
    signature_path: Path | None,
) -> VerifiedE3AuthorityGrant:
    request, request_bytes = _read_json(request_path, label="E3 request manifest")
    _validate_request(request)
    record_payload, record_bytes = _read_json(authority_record_path, label="E3 authority record")
    try:
        record = AuthorityRecord.model_validate(record_payload)
    except ValidationError as error:
        raise AuthorityVerificationError(f"E3 authority record schema validation failed: {error}") from error
    reviewed = record.reviewed_request_manifest
    accepted_reviewed_paths = {request_path.name}
    try:
        accepted_reviewed_paths.add(
            request_path.resolve(strict=True).relative_to(REPO_ROOT.resolve(strict=True)).as_posix()
        )
    except ValueError:
        pass
    if reviewed.path not in accepted_reviewed_paths:
        raise AuthorityVerificationError("reviewed request manifest path mismatch")
    if reviewed.sha256 != hashlib.sha256(request_bytes).hexdigest():
        raise AuthorityVerificationError("request manifest sha256 mismatch")
    if reviewed.self_digest != request["self_digest"]:
        raise AuthorityVerificationError("request manifest self_digest mismatch")
    _validate_scope(record, request)
    if allowed_signers_path is None or signature_path is None:
        raise AuthorityVerificationError("detached signature and allowed-signers file are required")
    allowed_signers = _external_file(allowed_signers_path, label="allowed-signers file")
    signature = _external_file(signature_path, label="detached signature")
    completed = subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "verify",
            "-f",
            str(allowed_signers),
            "-I",
            record.authority_identity,
            "-n",
            "file",
            "-s",
            str(signature),
        ],
        input=record_bytes,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).decode("utf-8", errors="replace").strip()
        raise AuthorityVerificationError(f"external E3 authority signature verification failed: {detail or 'unknown failure'}")
    scope = record.authorized_scope
    class _VerifiedAuthorityTranscript:
        __slots__ = ("record_bytes",)

        def __init__(self, signed_record_bytes: bytes) -> None:
            self.record_bytes = signed_record_bytes

    verification_transcript = _VerifiedAuthorityTranscript(record_bytes)
    return VerifiedE3AuthorityGrant(
        experiment_id=scope.experiment_id,
        claim_id=scope.claim_id,
        task_class=scope.task_class,
        evidence_origin=scope.evidence_origin,
        metric_scope=scope.metric_scope,
        artifact_scope=scope.artifact_scope,
        privacy_scope=scope.privacy_scope,
        request_scope_digest=scope.request_scope_digest,
        authority_record_sha256=hashlib.sha256(record_bytes).hexdigest(),
        decision=record.decision,
        authority_identity=record.authority_identity,
        request_manifest_sha256=hashlib.sha256(request_bytes).hexdigest(),
        request_manifest_self_digest=request["self_digest"],
        result_attestation_status=record.result_attestation_status,
        _verification_transcript=verification_transcript,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--authority-record", type=Path, required=True)
    parser.add_argument("--allowed-signers", type=Path)
    parser.add_argument("--signature", type=Path)
    args = parser.parse_args()
    try:
        result = verify_authority(
            args.request_manifest,
            args.authority_record,
            allowed_signers_path=args.allowed_signers,
            signature_path=args.signature,
        )
    except (AuthorityVerificationError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result.verification_summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
