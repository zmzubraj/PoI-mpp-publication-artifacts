#!/usr/bin/env python3
"""Build an unsigned E3-v2 post-execution result attestation draft.

Produces the hash-bound draft that the external semantic evaluator reviews
and signs after an authorized E3-v2 execution.  The draft binds the verified
pre-execution authority record, the request manifest, and the exact execution
artifacts.  It never decides C3-v2 support: the disposition is computed only
by the importer under the frozen Wilson-bound rule.  Pipeline self-test
executions are refused.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from poi_mpp.experiments.e3_v2_scope import (  # noqa: E402
    E3V2ScopeError,
    parse_authority_record,
)
from verify_e3_v2_authority import (  # noqa: E402
    AuthorityVerificationError,
    verify_authority,
)


ATTESTATION_SCHEMA_VERSION = "POI_MPP_E3_RESULT_ATTESTATION_V2"
ATTESTATION_STATUS = "DRAFT_UNSIGNED_POST_EXECUTION_ATTESTATION"
AUTHORIZED_EVIDENCE_ORIGIN = "REAL_MODEL_EXECUTION"
EXECUTION_MANIFEST_SCHEMA_VERSION = "POI_MPP_E3_V2_EXECUTION_MANIFEST_V1"
ATTESTATION_NOTES = (
    "The identified external semantic evaluator attests that the hash-bound execution "
    "artifacts listed here are the unmodified products of the authorized E3-v2 execution "
    "performed under the verified pre-execution authority record, within the approved "
    "scope and privacy constraints. This attestation authenticates execution provenance "
    "only; it does not determine support for claim C3-v2, which is computed solely by the "
    "frozen C3-v2 Wilson-bound support rule."
)
_ARTIFACT_ROLES = {
    "execution_manifest.json": "EXECUTION_MANIFEST",
    "outputs.jsonl": "MODEL_OUTPUTS",
    "summary.json": "EXECUTION_SUMMARY",
    "trace.jsonl": "EXECUTION_TRACE",
}
_BINDING_FIELDS = (
    "development_bundle_manifest_sha256",
    "development_dataset_manifest_hash",
    "development_model_manifest_hash",
    "development_decode_policy_hash",
    "development_environment_manifest_hash",
    "development_policy_inputs_digest",
    "confirmatory_freeze_material_lineage_hash",
    "confirmatory_dataset_manifest_hash",
    "confirmatory_development_manifest_hash",
    "calibration_freeze_content_hash",
)


class E3V2AttestationError(ValueError):
    """Raised when the E3-v2 attestation draft cannot be built fail-closed."""


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _self_digest(payload: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "self_digest"}
    return _sha256_bytes(_canonical_json_bytes(unsigned))


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    probe = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise E3V2AttestationError(f"{label} may not be a symlink")


def _require_external(path: Path, *, label: str) -> Path:
    _assert_no_symlink_components(path, label=label)
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise E3V2AttestationError(f"{label} must live outside the repository")
    return resolved


def _require_external_dir(path: Path, *, label: str) -> Path:
    resolved = _require_external(path, label=label)
    if not resolved.is_dir():
        raise E3V2AttestationError(f"{label} must be an existing directory")
    return resolved


def _read_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    _assert_no_symlink_components(path, label=label)
    try:
        raw = path.resolve(strict=True).read_bytes()
    except (FileNotFoundError, OSError) as error:
        raise E3V2AttestationError(f"{label} is missing or unreadable: {path}") from error
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise E3V2AttestationError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise E3V2AttestationError(f"{label} must be a JSON object")
    return payload, raw


def _read_run_member(run_dir: Path, name: str) -> bytes:
    member = run_dir / name
    if member.is_symlink():
        raise E3V2AttestationError(f"execution artifact {name} may not be a symlink")
    try:
        resolved = member.resolve(strict=True)
    except FileNotFoundError as error:
        raise E3V2AttestationError(f"execution artifact {name} is missing") from error
    try:
        resolved.relative_to(run_dir)
    except ValueError as error:
        raise E3V2AttestationError(f"execution artifact {name} escapes the run directory") from error
    return resolved.read_bytes()


def _strict_iso_date(value: str) -> str:
    if len(value) != 10:
        raise E3V2AttestationError("attestation date must use strict ISO YYYY-MM-DD format")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise E3V2AttestationError("attestation date must use strict ISO YYYY-MM-DD format") from error
    if parsed.isoformat() != value:
        raise E3V2AttestationError("attestation date must use strict ISO YYYY-MM-DD format")
    return value


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_attestation_draft(
    *,
    run_dir: Path,
    request_manifest_path: Path,
    authority_record_path: Path,
    allowed_signers_path: Path,
    signature_path: Path,
    attestation_date: str,
    output_path: Path,
) -> Path:
    attestation_date = _strict_iso_date(attestation_date)
    resolved_run_dir = _require_external_dir(run_dir, label="run directory")
    resolved_output = _require_external(output_path, label="attestation draft output")
    if resolved_output.exists():
        raise E3V2AttestationError(f"attestation draft already exists: {resolved_output}")
    if not resolved_output.parent.is_dir():
        raise E3V2AttestationError("attestation draft output directory does not exist")

    manifest, manifest_bytes = _read_json_object(
        resolved_run_dir / "execution_manifest.json", label="execution manifest"
    )
    if manifest.get("schema_version") != EXECUTION_MANIFEST_SCHEMA_VERSION:
        raise E3V2AttestationError("execution manifest schema_version is not the E3-v2 contract")
    if manifest.get("self_digest") != _self_digest(manifest):
        raise E3V2AttestationError("execution manifest self_digest mismatch")

    evidence_origin = manifest.get("evidence_origin")
    if evidence_origin == "PIPELINE_SELF_TEST":
        raise E3V2AttestationError("pipeline self-test executions cannot be attested")
    if evidence_origin != AUTHORIZED_EVIDENCE_ORIGIN:
        raise E3V2AttestationError("execution evidence_origin must be REAL_MODEL_EXECUTION")

    artifact_hashes: dict[str, tuple[str, int]] = {}
    for name in sorted(_ARTIFACT_ROLES):
        blob = _read_run_member(resolved_run_dir, name)
        if not blob:
            raise E3V2AttestationError(f"execution artifact {name} is empty")
        artifact_hashes[name] = (_sha256_bytes(blob), len(blob))
        if name != "execution_manifest.json":
            expected = manifest.get(f"{name.split('.')[0]}_sha256")
            if expected != artifact_hashes[name][0]:
                raise E3V2AttestationError(f"{name} does not match the execution manifest")

    summary = json.loads(_read_run_member(resolved_run_dir, "summary.json").decode("utf-8"))
    if summary.get("self_digest") != _self_digest(summary):
        raise E3V2AttestationError("execution summary self_digest mismatch")
    outputs_bytes = _read_run_member(resolved_run_dir, "outputs.jsonl")
    record_count = manifest.get("record_count")
    if outputs_bytes.count(b"\n") != record_count or summary.get("record_count") != record_count:
        raise E3V2AttestationError("execution record counts do not agree across artifacts")

    try:
        grant = verify_authority(
            request_manifest_path,
            authority_record_path,
            allowed_signers_path=allowed_signers_path,
            signature_path=signature_path,
        )
    except AuthorityVerificationError as error:
        raise E3V2AttestationError(f"pre-execution authority verification failed: {error}") from error
    if grant.decision != "APPROVED":
        raise E3V2AttestationError("authority decision must be APPROVED to attest an execution")

    authority = manifest.get("authority")
    grant_bindings = {field: getattr(grant, field) for field in _BINDING_FIELDS}
    if (
        not isinstance(authority, dict)
        or authority.get("authority_record_sha256") != grant.authority_record_sha256
        or authority.get("request_manifest_sha256") != grant.request_manifest_sha256
        or authority.get("authority_identity") != grant.authority_identity
        or authority.get("decision") != grant.decision
        or manifest.get("bindings") != grant_bindings
    ):
        raise E3V2AttestationError("execution manifest does not chain to the verified authority")

    record_payload, _ = _read_json_object(authority_record_path, label="E3-v2 authority record")
    try:
        record = parse_authority_record(record_payload)
    except E3V2ScopeError as error:
        raise E3V2AttestationError(f"E3-v2 authority record schema validation failed: {error}") from error
    resolved_request = _require_external(request_manifest_path, label="E3-v2 request manifest")

    artifacts = [
        {
            "artifact_id": "RAW_E3_EXECUTION",
            "artifact_role": _ARTIFACT_ROLES[name],
            "path": name,
            "sha256": artifact_hashes[name][0],
            "size_bytes": artifact_hashes[name][1],
        }
        for name in sorted(_ARTIFACT_ROLES)
    ]

    draft: dict[str, Any] = {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "record_type": "POST_EXECUTION_RESULT_ATTESTATION",
        "status": ATTESTATION_STATUS,
        "authority_identity": grant.authority_identity,
        "authority_basis": record.authority_basis,
        "expertise_scope": record.expertise_scope,
        "pre_execution_authority_record": {
            "path": Path(authority_record_path).name,
            "sha256": grant.authority_record_sha256,
        },
        "reviewed_request_manifest": {
            "path": resolved_request.name,
            "sha256": grant.request_manifest_sha256,
            "self_digest": grant.request_manifest_self_digest,
        },
        "result_scope": {
            "experiment_id": grant.experiment_id,
            "experiment_generation": grant.experiment_generation,
            "claim_id": grant.claim_id,
            "claim_generation": grant.claim_generation,
            "task_class": grant.task_class,
            "run_id": manifest.get("run_id"),
            "evidence_origin": grant.evidence_origin,
            "metric_scope": list(grant.metric_scope),
            "artifact_scope": list(grant.artifact_scope),
            "execution_bindings": {
                "authority_record_sha256": grant.authority_record_sha256,
                "request_manifest_sha256": grant.request_manifest_sha256,
                "execution_manifest_sha256": _sha256_bytes(manifest_bytes),
                "outputs_sha256": artifact_hashes["outputs.jsonl"][0],
                "trace_sha256": artifact_hashes["trace.jsonl"][0],
                "summary_sha256": artifact_hashes["summary.json"][0],
                "prompt_template_sha256": manifest.get("prompt_template_sha256"),
                "record_count": record_count,
                "material_bindings": grant_bindings,
            },
        },
        "artifacts": artifacts,
        "results_disposition": "ATTESTED_AS_REPORTED",
        "attestation_notes": ATTESTATION_NOTES,
        "attestation_date": attestation_date,
        "publication_support_decision_status": "NOT_EVALUATED_BY_THIS_ATTESTATION",
        "external_signature_required": True,
        "signature_namespace": "file",
        "signature_reference": "external://e3-v2-result-attestation.sig",
        "allowed_signers_reference": "external://e3-v2-result-attestation-allowed-signers",
    }
    draft["self_digest"] = _self_digest(draft)
    _write_atomic(resolved_output, _canonical_json_bytes(draft))
    return resolved_output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--authority-record", type=Path, required=True)
    parser.add_argument("--allowed-signers", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--attestation-date", type=str, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = build_attestation_draft(
            run_dir=args.run_dir,
            request_manifest_path=args.request_manifest,
            authority_record_path=args.authority_record,
            allowed_signers_path=args.allowed_signers,
            signature_path=args.signature,
            attestation_date=args.attestation_date,
            output_path=args.output,
        )
    except (E3V2AttestationError, E3V2ScopeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
