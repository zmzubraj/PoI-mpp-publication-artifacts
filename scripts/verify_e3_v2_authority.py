#!/usr/bin/env python3
"""Verify a real externally signed E3-v2 pre-execution authority record.

This verifier only authenticates the hash-bound permission to execute the
E3-v2 scope (500 frozen confirmatory items under the C3-v2 Wilson support
rule). It deliberately does not validate or attest to post-execution results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.experiments.e3_v2_authority import (  # noqa: E402
    VerifiedE3V2AuthorityGrant,
)
from poi_mpp.experiments.e3_v2_scope import (  # noqa: E402
    E3_V2_SUPPORT_RULE,
    E3V2AuthorityRecord,
    E3V2ScopeError,
    build_manifest,
    parse_authority_record,
    validate_request_manifest_structure,
)


class AuthorityVerificationError(ValueError):
    pass


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
    try:
        validate_request_manifest_structure(payload)
    except E3V2ScopeError as error:
        raise AuthorityVerificationError(f"E3-v2 request manifest is invalid: {error}") from error
    bound_documents = payload["bound_documents"]
    try:
        expected = build_manifest(
            development_report_path=bound_documents["development_report"],
            confirmatory_lineage_path=bound_documents["confirmatory_lineage"],
            calibration_freeze_path=bound_documents["calibration_freeze"],
        )
    except E3V2ScopeError as error:
        raise AuthorityVerificationError(
            f"E3-v2 request manifest cannot be re-derived from its bound documents: {error}"
        ) from error
    if payload != expected:
        raise AuthorityVerificationError(
            "E3-v2 request manifest is stale, tampered, or non-canonical"
        )


def _validate_scope(record: E3V2AuthorityRecord, request: dict[str, Any]) -> None:
    scope = record.authorized_scope
    requested = request["requested_scope"]
    if scope.request_scope_digest != request["requested_scope_digest"]:
        raise AuthorityVerificationError("authority request_scope_digest mismatch")
    if scope.support_rule.model_dump() != E3_V2_SUPPORT_RULE:
        raise AuthorityVerificationError(
            "authority support rule must equal the frozen C3-v2 Wilson support rule"
        )
    fixed_matches = (
        scope.experiment_id == requested["experiment_id"]
        and scope.experiment_generation == requested["experiment_generation"]
        and scope.claim_id == requested["claim_id"]
        and scope.claim_generation == requested["claim_generation"]
        and scope.task_class == requested["task_class"]
        and scope.evidence_origin == requested["evidence_origin"]
    )
    if not fixed_matches:
        raise AuthorityVerificationError(
            "authority scope does not match the canonical E3-v2 request"
        )
    if record.bound_materials.model_dump() != request["bound_materials"]:
        raise AuthorityVerificationError(
            "authority record bound_materials do not echo the request manifest"
        )
    metric_scope = set(scope.metric_scope)
    artifact_scope = set(scope.artifact_scope)
    requested_metrics = set(requested["metric_scope"])
    requested_artifacts = set(requested["artifact_scope"])
    if record.decision == "APPROVED" and (
        metric_scope != requested_metrics or artifact_scope != requested_artifacts
    ):
        raise AuthorityVerificationError(
            "approved authority scope must exactly match the canonical E3-v2 request"
        )
    if record.decision == "LIMITED_SCOPE" and (
        not metric_scope.issubset(requested_metrics)
        or not artifact_scope.issubset(requested_artifacts)
    ):
        raise AuthorityVerificationError(
            "limited authority scope must be a subset of the canonical E3-v2 request"
        )
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
) -> VerifiedE3V2AuthorityGrant:
    request_path = _external_file(request_path, label="E3-v2 request manifest")
    request, request_bytes = _read_json(request_path, label="E3-v2 request manifest")
    _validate_request(request)
    authority_record_path = _external_file(authority_record_path, label="E3-v2 authority record")
    record_payload, record_bytes = _read_json(authority_record_path, label="E3-v2 authority record")
    try:
        record = parse_authority_record(record_payload)
    except E3V2ScopeError as error:
        raise AuthorityVerificationError(
            f"E3-v2 authority record schema validation failed: {error}"
        ) from error
    reviewed = record.reviewed_request_manifest
    accepted_reviewed_paths = {request_path.name, request_path.as_posix()}
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
        raise AuthorityVerificationError(
            f"external E3-v2 authority signature verification failed: {detail or 'unknown failure'}"
        )
    scope = record.authorized_scope
    materials = record.bound_materials
    support_rule = scope.support_rule

    class _VerifiedAuthorityTranscript:
        __slots__ = ("record_bytes",)

        def __init__(self, signed_record_bytes: bytes) -> None:
            self.record_bytes = signed_record_bytes

    verification_transcript = _VerifiedAuthorityTranscript(record_bytes)
    return VerifiedE3V2AuthorityGrant(
        experiment_id=scope.experiment_id,
        experiment_generation=scope.experiment_generation,
        claim_id=scope.claim_id,
        claim_generation=scope.claim_generation,
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
        development_bundle_manifest_sha256=materials.development_bundle_manifest_sha256,
        development_dataset_manifest_hash=materials.development_dataset_manifest_hash,
        development_model_manifest_hash=materials.development_model_manifest_hash,
        development_decode_policy_hash=materials.development_decode_policy_hash,
        development_environment_manifest_hash=materials.development_environment_manifest_hash,
        development_policy_inputs_digest=materials.development_policy_inputs_digest,
        confirmatory_freeze_material_lineage_hash=(
            materials.confirmatory_freeze_material_lineage_hash
        ),
        confirmatory_dataset_manifest_hash=materials.confirmatory_dataset_manifest_hash,
        confirmatory_development_manifest_hash=materials.confirmatory_development_manifest_hash,
        calibration_freeze_content_hash=materials.calibration_freeze_content_hash,
        support_rule_id=support_rule.rule_id,
        wilson_z_value=support_rule.wilson_z_value,
        far_wilson_upper_bound_max=support_rule.far_wilson_upper_bound_max,
        frr_wilson_upper_bound_max=support_rule.frr_wilson_upper_bound_max,
        coverage_min=support_rule.coverage_min,
        confirmatory_composition=support_rule.confirmatory_composition,
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
