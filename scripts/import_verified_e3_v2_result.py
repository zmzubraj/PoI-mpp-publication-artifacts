#!/usr/bin/env python3
"""Import a verified externally attested E3-v2 result into the repository.

Verifies the complete E3-v2 evidence chain fail-closed:

1. the signed post-execution result attestation (detached SSH signature),
2. the signed pre-execution authority grant (re-verified against the current
   repository inputs bound by the request manifest),
3. the attestation-to-authority chain and artifact hash closure over the raw
   execution evidence,

then recomputes every metric from the attested raw outputs and applies the
frozen C3-v2 Wilson-bound support rule.  This importer is the only component
that decides C3-v2 support; neither the authority grant nor the attestation
determines the disposition.  Installs the raw evidence, the recomputed
T4/T8/F7 artifacts, the adjudication record, and a verification receipt under
``results/publication/<run_id>/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from decimal import Decimal, localcontext
from pathlib import Path
import shutil
import subprocess
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
    E3_V2_SUPPORT_RULE,
    E3V2ScopeError,
    canonical_json_bytes,
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
EXECUTION_SUMMARY_SCHEMA_VERSION = "POI_MPP_E3_V2_EXECUTION_SUMMARY_V1"
ADJUDICATION_SCHEMA_VERSION = "POI_MPP_E3_V2_C3_ADJUDICATION_V1"
COMPOSITION_SCHEMA_VERSION = "POI_MPP_E3_V2_DATASET_COMPOSITION_V1"
RECEIPT_SCHEMA_VERSION = "POI_MPP_E3_V2_VERIFIED_IMPORT_RECEIPT_V1"
CALIBRATION_STATUS = "NOT_APPLICABLE_DECISION_ONLY_OUTPUT"
_ARTIFACT_ROLES = {
    "execution_manifest.json": "EXECUTION_MANIFEST",
    "outputs.jsonl": "MODEL_OUTPUTS",
    "summary.json": "EXECUTION_SUMMARY",
    "trace.jsonl": "EXECUTION_TRACE",
}
_OUTPUT_LINE_KEYS = {
    "record_id",
    "expected_decision",
    "item_hash",
    "prompt_sha256",
    "raw_output",
    "raw_output_sha256",
    "decision",
    "parse_status",
}
_DECISIONS = ("ACCEPT", "REJECT", "ABSTAIN")
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
ADJUDICATION_BOUNDARY = (
    "This adjudication is the sole decision point for claim C3-v2. It applies the frozen "
    "C3-v2 Wilson-bound support rule to the attested raw execution outputs. The pre-execution "
    "authority grant and the post-execution attestation authenticate scope and provenance only; "
    "neither determines support. Calibration is not evaluated: the E3-v2 execution emits "
    "tri-state decisions without a confidence signal, and the frozen rule uses only the FAR and "
    "FRR Wilson upper bounds and coverage."
)
RECEIPT_CAVEATS = [
    "Cryptographic verification authenticates exact signed files and artifact hashes only; it "
    "does not prove real-world identity, independence, or private-key custody.",
    "The post-execution attestation authenticates execution provenance only; the C3-v2 support "
    "disposition is computed solely by the frozen C3-v2 Wilson-bound support rule applied to "
    "the attested raw outputs.",
]


class E3V2ImportError(ValueError):
    """Raised when the E3-v2 verified import fails closed."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _self_digest(payload: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "self_digest"}
    return _sha256_bytes(canonical_json_bytes(unsigned))


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    probe = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise E3V2ImportError(f"{label} may not be a symlink")


def _require_external_file(path: Path, *, label: str) -> Path:
    _assert_no_symlink_components(path, label=label)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise E3V2ImportError(f"{label} is missing: {path}") from error
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise E3V2ImportError(f"{label} must live outside the repository")
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise E3V2ImportError(f"{label} must be a non-empty file")
    return resolved


def _require_external_dir(path: Path, *, label: str) -> Path:
    _assert_no_symlink_components(path, label=label)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise E3V2ImportError(f"{label} is missing: {path}") from error
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise E3V2ImportError(f"{label} must live outside the repository")
    if not resolved.is_dir():
        raise E3V2ImportError(f"{label} must be a directory")
    return resolved


def _require_publication_root(path: Path, *, label: str) -> Path:
    _assert_no_symlink_components(path, label=label)
    resolved = path.resolve()
    if resolved.exists() and not resolved.is_dir():
        raise E3V2ImportError(f"{label} must be a directory")
    return resolved


def _read_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    _assert_no_symlink_components(path, label=label)
    try:
        raw = path.resolve(strict=True).read_bytes()
    except (FileNotFoundError, OSError) as error:
        raise E3V2ImportError(f"{label} is missing or unreadable: {path}") from error
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise E3V2ImportError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise E3V2ImportError(f"{label} must be a JSON object")
    return payload, raw


def _read_run_member(run_dir: Path, name: str) -> bytes:
    member = run_dir / name
    if member.is_symlink():
        raise E3V2ImportError(f"execution artifact {name} may not be a symlink")
    try:
        resolved = member.resolve(strict=True)
    except FileNotFoundError as error:
        raise E3V2ImportError(f"execution artifact {name} is missing") from error
    try:
        resolved.relative_to(run_dir)
    except ValueError as error:
        raise E3V2ImportError(f"execution artifact {name} escapes the run directory") from error
    return resolved.read_bytes()


def _verify_detached_signature(
    *,
    record_bytes: bytes,
    identity: str,
    allowed_signers_path: Path,
    signature_path: Path,
    label: str,
) -> None:
    allowed_signers = _require_external_file(allowed_signers_path, label=f"{label} allowed-signers file")
    signature = _require_external_file(signature_path, label=f"{label} detached signature")
    completed = subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "verify",
            "-f",
            str(allowed_signers),
            "-I",
            identity,
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
        raise E3V2ImportError(
            f"{label} signature verification failed: {detail or 'unknown failure'}"
        )


def _validate_attestation_record(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != ATTESTATION_SCHEMA_VERSION:
        raise E3V2ImportError("attestation record schema_version is not the E3-v2 contract")
    if payload.get("record_type") != "POST_EXECUTION_RESULT_ATTESTATION":
        raise E3V2ImportError("attestation record_type must be POST_EXECUTION_RESULT_ATTESTATION")
    if payload.get("status") != ATTESTATION_STATUS:
        raise E3V2ImportError("attestation status must be the unsigned draft awaiting signature")
    if payload.get("results_disposition") != "ATTESTED_AS_REPORTED":
        raise E3V2ImportError("attestation results_disposition must be ATTESTED_AS_REPORTED")
    if payload.get("publication_support_decision_status") != "NOT_EVALUATED_BY_THIS_ATTESTATION":
        raise E3V2ImportError("attestation must not evaluate publication support")
    if payload.get("external_signature_required") is not True:
        raise E3V2ImportError("attestation must require an external signature")
    if payload.get("signature_namespace") != "file":
        raise E3V2ImportError("attestation signature_namespace must be file")
    if not isinstance(payload.get("authority_identity"), str) or not payload["authority_identity"]:
        raise E3V2ImportError("attestation authority_identity must be a non-empty string")
    if payload.get("self_digest") != _self_digest(payload):
        raise E3V2ImportError("attestation record self_digest mismatch")


def _wilson_upper_bound(successes: int, trials: int, z: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        n = Decimal(trials)
        p = Decimal(successes) / n
        center = p + z * z / (2 * n)
        margin = z * (p * (1 - p) / n + z * z / (4 * n * n)).sqrt()
        return (center + margin) / (1 + z * z / n)


def _outcome(expected: str, decision: str) -> str:
    if decision == "ABSTAIN":
        return "ABSTAIN"
    if expected == decision:
        return "CORRECT"
    if expected == "REJECT" and decision == "ACCEPT":
        return "FALSE_ACCEPT"
    if expected == "ACCEPT" and decision == "REJECT":
        return "FALSE_REJECT"
    return "DECISIVE_ON_GOLD_ABSTAIN"


def _recompute_outputs(
    outputs_bytes: bytes, *, record_count: int, composition: dict[str, int]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lines = outputs_bytes.decode("utf-8").splitlines()
    if len(lines) != record_count:
        raise E3V2ImportError("outputs.jsonl record count does not match the execution manifest")
    records: list[dict[str, Any]] = []
    gold_counts = {"ACCEPT": 0, "REJECT": 0, "ABSTAIN": 0}
    decision_counts = {"ACCEPT": 0, "REJECT": 0, "ABSTAIN": 0}
    parse_status_counts: dict[str, int] = {}
    false_accept_count = 0
    false_reject_count = 0
    decisive_count = 0
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise E3V2ImportError(f"outputs.jsonl contains an invalid JSON line: {error}") from error
        if not isinstance(record, dict) or set(record) != _OUTPUT_LINE_KEYS:
            raise E3V2ImportError("outputs.jsonl line does not match the E3-v2 output contract")
        expected = record["expected_decision"]
        decision = record["decision"]
        if expected not in _DECISIONS or decision not in _DECISIONS:
            raise E3V2ImportError("outputs.jsonl line contains an unknown decision token")
        records.append(record)
        gold_counts[expected] += 1
        decision_counts[decision] += 1
        parse_status_counts[record["parse_status"]] = (
            parse_status_counts.get(record["parse_status"], 0) + 1
        )
        if decision != "ABSTAIN":
            decisive_count += 1
        if expected == "REJECT" and decision == "ACCEPT":
            false_accept_count += 1
        if expected == "ACCEPT" and decision == "REJECT":
            false_reject_count += 1
    if gold_counts != {
        "ACCEPT": composition.get("ACCEPT"),
        "REJECT": composition.get("REJECT"),
        "ABSTAIN": composition.get("ABSTAIN"),
    }:
        raise E3V2ImportError(
            "confirmatory composition does not match the frozen C3-v2 support rule"
        )
    comparison = {
        "false_accept_count": false_accept_count,
        "false_reject_count": false_reject_count,
        "decisive_count": decisive_count,
        "parse_status_counts": {key: parse_status_counts[key] for key in sorted(parse_status_counts)},
    }
    return records, {
        "model_decision_counts": {key: decision_counts[key] for key in sorted(decision_counts)},
        "comparison": comparison,
    }


def _build_f7_svg(*, run_id: str, metrics: dict[str, Any], verdict: str) -> bytes:
    def bar_width(value: Decimal, scale_max: Decimal) -> int:
        ratio = min(value / scale_max, Decimal(1))
        return int((ratio * 500).to_integral_value())

    rows = [
        ("FAR Wilson upper bound", metrics["far_wilson_upper_bound"], Decimal("0.25"), Decimal("0.5")),
        ("FRR Wilson upper bound", metrics["frr_wilson_upper_bound"], Decimal("0.25"), Decimal("0.5")),
        ("Coverage", metrics["coverage"], Decimal("0.50"), Decimal("1.0")),
    ]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="320" viewBox="0 0 720 320">',
        f"<title>E3-v2 C3-v2 support metrics for {run_id}</title>",
        '<rect width="720" height="320" fill="#ffffff"/>',
        f'<text x="24" y="36" font-family="monospace" font-size="18" fill="#111111">'
        f"E3-v2 C3-v2 adjudication: {verdict} (run {run_id})</text>",
    ]
    for index, (label, raw_value, threshold, scale_max) in enumerate(rows):
        top = 70 + index * 70
        value = Decimal(raw_value)
        passed = value <= threshold if label != "Coverage" else value >= threshold
        color = "#2e7d32" if passed else "#c62828"
        width = bar_width(value, scale_max)
        tick_x = 190 + int((threshold / scale_max * 500).to_integral_value())
        quantized = format(value.quantize(Decimal("0.0001")), "f")
        parts.extend(
            [
                f'<text x="24" y="{top + 20}" font-family="monospace" font-size="13" '
                f'fill="#111111">{label}</text>',
                f'<rect x="190" y="{top + 6}" width="{width}" height="20" fill="{color}"/>',
                f'<line x1="{tick_x}" y1="{top}" x2="{tick_x}" y2="{top + 32}" '
                f'stroke="#111111" stroke-width="2" stroke-dasharray="4,3"/>',
                f'<text x="696" y="{top + 20}" font-family="monospace" font-size="13" '
                f'fill="#111111" text-anchor="end">{quantized}</text>',
            ]
        )
    parts.append(
        f'<text x="24" y="296" font-family="monospace" font-size="12" fill="#444444">'
        f"Rule {E3_V2_SUPPORT_RULE['rule_id']}: FAR/FRR Wilson UB &lt;= "
        f"{E3_V2_SUPPORT_RULE['far_wilson_upper_bound_max']}, coverage &gt;= "
        f"{E3_V2_SUPPORT_RULE['coverage_min']}. Dashed line = threshold.</text>"
    )
    parts.append("</svg>")
    return ("\n".join(parts) + "\n").encode("utf-8")


def _ensure_target_compatibility(
    run_root: Path, expected_files: dict[str, bytes], receipt_bytes: bytes
) -> bool:
    if not run_root.exists():
        return False
    for relative_path, payload in expected_files.items():
        candidate = run_root / relative_path
        if not candidate.is_file() or candidate.read_bytes() != payload:
            raise E3V2ImportError("existing target contains divergent content")
    receipt_path = run_root / "verification_receipt.json"
    if not receipt_path.is_file() or receipt_path.read_bytes() != receipt_bytes:
        raise E3V2ImportError("existing target contains divergent content")
    return True


def import_verified_e3_v2_result(
    *,
    request_manifest_path: Path,
    authority_record_path: Path,
    authority_allowed_signers_path: Path,
    authority_signature_path: Path,
    attestation_record_path: Path,
    attestation_allowed_signers_path: Path,
    attestation_signature_path: Path,
    run_dir_path: Path,
    publication_root: Path,
) -> dict[str, Any]:
    resolved_publication_root = _require_publication_root(
        publication_root, label="publication root"
    )

    # 1. Verify the signed post-execution attestation.
    attestation_path = _require_external_file(attestation_record_path, label="attestation record")
    attestation, attestation_bytes = _read_json_object(attestation_path, label="attestation record")
    _validate_attestation_record(attestation)
    _verify_detached_signature(
        record_bytes=attestation_bytes,
        identity=attestation["authority_identity"],
        allowed_signers_path=attestation_allowed_signers_path,
        signature_path=attestation_signature_path,
        label="attestation",
    )

    # 2. Re-verify the pre-execution authority grant against current inputs.
    try:
        grant = verify_authority(
            request_manifest_path,
            authority_record_path,
            allowed_signers_path=authority_allowed_signers_path,
            signature_path=authority_signature_path,
        )
    except AuthorityVerificationError as error:
        raise E3V2ImportError(f"pre-execution authority verification failed: {error}") from error
    if grant.decision != "APPROVED":
        raise E3V2ImportError("authority decision must be APPROVED to import a publication result")

    # 3. Chain the attestation to the verified authority grant.
    if attestation["authority_identity"] != grant.authority_identity:
        raise E3V2ImportError("attestation identity does not match the verified authority")
    authority_reference = attestation.get("pre_execution_authority_record")
    reviewed_reference = attestation.get("reviewed_request_manifest")
    if (
        not isinstance(authority_reference, dict)
        or authority_reference.get("sha256") != grant.authority_record_sha256
        or not isinstance(reviewed_reference, dict)
        or reviewed_reference.get("sha256") != grant.request_manifest_sha256
        or reviewed_reference.get("self_digest") != grant.request_manifest_self_digest
    ):
        raise E3V2ImportError("attestation does not chain to the verified authority record")
    result_scope = attestation.get("result_scope")
    if not isinstance(result_scope, dict):
        raise E3V2ImportError("attestation is missing result_scope")
    if (
        result_scope.get("experiment_id") != grant.experiment_id
        or result_scope.get("experiment_generation") != grant.experiment_generation
        or result_scope.get("claim_id") != grant.claim_id
        or result_scope.get("claim_generation") != grant.claim_generation
        or result_scope.get("task_class") != grant.task_class
        or result_scope.get("evidence_origin") != grant.evidence_origin
    ):
        raise E3V2ImportError("attestation result_scope does not match the verified authority scope")
    bindings = result_scope.get("execution_bindings")
    if not isinstance(bindings, dict):
        raise E3V2ImportError("attestation is missing execution_bindings")
    if (
        bindings.get("authority_record_sha256") != grant.authority_record_sha256
        or bindings.get("request_manifest_sha256") != grant.request_manifest_sha256
        or bindings.get("material_bindings")
        != {field: getattr(grant, field) for field in _BINDING_FIELDS}
    ):
        raise E3V2ImportError("attestation execution_bindings do not match the verified authority")

    # 4. Verify artifact hash closure over the raw execution evidence.
    run_dir = _require_external_dir(run_dir_path, label="run directory")
    attested_artifacts = attestation.get("artifacts")
    if not isinstance(attested_artifacts, list) or len(attested_artifacts) != len(_ARTIFACT_ROLES):
        raise E3V2ImportError("attestation must bind exactly the four raw execution artifacts")
    artifact_blobs: dict[str, bytes] = {}
    seen_paths: set[str] = set()
    for artifact in attested_artifacts:
        if not isinstance(artifact, dict) or artifact.get("artifact_id") != "RAW_E3_EXECUTION":
            raise E3V2ImportError("attested artifacts must be RAW_E3_EXECUTION entries")
        name = artifact.get("path")
        if name not in _ARTIFACT_ROLES or name in seen_paths:
            raise E3V2ImportError(f"attestation binds an unexpected artifact path: {name}")
        seen_paths.add(name)
        if artifact.get("artifact_role") != _ARTIFACT_ROLES[name]:
            raise E3V2ImportError(f"artifact {name} role does not match the E3-v2 contract")
        blob = _read_run_member(run_dir, name)
        if artifact.get("sha256") != _sha256_bytes(blob) or artifact.get("size_bytes") != len(blob):
            raise E3V2ImportError(f"artifact {name} does not match the attested hash closure")
        artifact_blobs[name] = blob

    # 5. Validate the execution manifest against the grant and the attestation.
    manifest = json.loads(artifact_blobs["execution_manifest.json"].decode("utf-8"))
    if manifest.get("schema_version") != EXECUTION_MANIFEST_SCHEMA_VERSION:
        raise E3V2ImportError("execution manifest schema_version is not the E3-v2 contract")
    if manifest.get("self_digest") != _self_digest(manifest):
        raise E3V2ImportError("execution manifest self_digest mismatch")
    evidence_origin = manifest.get("evidence_origin")
    if evidence_origin == "PIPELINE_SELF_TEST":
        raise E3V2ImportError("pipeline self-test executions cannot be imported as publication evidence")
    if evidence_origin != AUTHORIZED_EVIDENCE_ORIGIN:
        raise E3V2ImportError("execution evidence_origin must be REAL_MODEL_EXECUTION")
    authority_block = manifest.get("authority")
    if (
        not isinstance(authority_block, dict)
        or authority_block.get("authority_record_sha256") != grant.authority_record_sha256
        or authority_block.get("request_manifest_sha256") != grant.request_manifest_sha256
        or authority_block.get("authority_identity") != grant.authority_identity
        or authority_block.get("decision") != grant.decision
        or manifest.get("bindings") != {field: getattr(grant, field) for field in _BINDING_FIELDS}
    ):
        raise E3V2ImportError("execution manifest does not chain to the verified authority")
    run_id = manifest.get("run_id")
    if result_scope.get("run_id") != run_id:
        raise E3V2ImportError("attestation run_id does not match the execution manifest")
    composition = grant.confirmatory_composition
    record_count = manifest.get("record_count")
    if record_count != composition.get("total"):
        raise E3V2ImportError("execution record count does not match the frozen C3-v2 composition")
    if (
        manifest.get("outputs_sha256") != _sha256_bytes(artifact_blobs["outputs.jsonl"])
        or manifest.get("trace_sha256") != _sha256_bytes(artifact_blobs["trace.jsonl"])
        or manifest.get("summary_sha256") != _sha256_bytes(artifact_blobs["summary.json"])
        or manifest.get("prompt_template_sha256") != bindings.get("prompt_template_sha256")
        or bindings.get("record_count") != record_count
    ):
        raise E3V2ImportError("attestation execution_bindings do not match the execution manifest")

    # 6. Validate the execution summary and recompute metrics from raw outputs.
    summary = json.loads(artifact_blobs["summary.json"].decode("utf-8"))
    if summary.get("schema_version") != EXECUTION_SUMMARY_SCHEMA_VERSION:
        raise E3V2ImportError("execution summary schema_version is not the E3-v2 contract")
    if summary.get("self_digest") != _self_digest(summary):
        raise E3V2ImportError("execution summary self_digest mismatch")
    if summary.get("run_id") != run_id or summary.get("record_count") != record_count:
        raise E3V2ImportError("execution summary does not match the execution manifest")
    records, recomputed = _recompute_outputs(
        artifact_blobs["outputs.jsonl"], record_count=record_count, composition=composition
    )
    if (
        summary.get("model_decision_counts") != recomputed["model_decision_counts"]
        or summary.get("comparison") != recomputed["comparison"]
    ):
        raise E3V2ImportError("execution summary does not match recomputed outputs")

    # 7. Apply the frozen C3-v2 Wilson-bound support rule (sole decision point).
    rule = E3_V2_SUPPORT_RULE
    if (
        grant.support_rule_id != rule["rule_id"]
        or grant.wilson_z_value != rule["wilson_z_value"]
        or grant.far_wilson_upper_bound_max != rule["far_wilson_upper_bound_max"]
        or grant.frr_wilson_upper_bound_max != rule["frr_wilson_upper_bound_max"]
        or grant.coverage_min != rule["coverage_min"]
        or grant.confirmatory_composition != rule["confirmatory_composition"]
    ):
        raise E3V2ImportError("authority grant does not bind the frozen C3-v2 support rule")
    comparison = recomputed["comparison"]
    z = Decimal(rule["wilson_z_value"])
    gold_accept = composition["ACCEPT"]
    gold_reject = composition["REJECT"]
    total = composition["total"]
    far_wilson_upper_bound = _wilson_upper_bound(
        comparison["false_accept_count"], gold_reject, z
    )
    frr_wilson_upper_bound = _wilson_upper_bound(
        comparison["false_reject_count"], gold_accept, z
    )
    with localcontext() as context:
        context.prec = 50
        far_point = Decimal(comparison["false_accept_count"]) / Decimal(gold_reject)
        frr_point = Decimal(comparison["false_reject_count"]) / Decimal(gold_accept)
        coverage = Decimal(comparison["decisive_count"]) / Decimal(total)
    far_ok = far_wilson_upper_bound <= Decimal(rule["far_wilson_upper_bound_max"])
    frr_ok = frr_wilson_upper_bound <= Decimal(rule["frr_wilson_upper_bound_max"])
    coverage_ok = coverage >= Decimal(rule["coverage_min"])
    verdict = "SUPPORTED" if (far_ok and frr_ok and coverage_ok) else "NOT_SUPPORTED"
    if verdict == "SUPPORTED":
        reason = (
            "FAR Wilson upper bound, FRR Wilson upper bound, and coverage all satisfy the "
            f"frozen rule {rule['rule_id']}"
        )
    else:
        failed = [
            name
            for name, ok in (
                ("FAR Wilson upper bound within maximum", far_ok),
                ("FRR Wilson upper bound within maximum", frr_ok),
                ("coverage meets minimum", coverage_ok),
            )
            if not ok
        ]
        reason = "frozen rule conditions not satisfied: " + "; ".join(failed)

    metrics = {
        "far_point_estimate": format(far_point, "f"),
        "frr_point_estimate": format(frr_point, "f"),
        "coverage": format(coverage, "f"),
        "far_wilson_upper_bound": format(far_wilson_upper_bound, "f"),
        "frr_wilson_upper_bound": format(frr_wilson_upper_bound, "f"),
    }
    adjudication: dict[str, Any] = {
        "schema_version": ADJUDICATION_SCHEMA_VERSION,
        "record_type": "C3_V2_SUPPORT_ADJUDICATION",
        "experiment_id": grant.experiment_id,
        "experiment_generation": grant.experiment_generation,
        "claim_id": grant.claim_id,
        "claim_generation": grant.claim_generation,
        "run_id": run_id,
        "support_rule": dict(rule),
        "counts": {
            "false_accept_count": comparison["false_accept_count"],
            "false_reject_count": comparison["false_reject_count"],
            "decisive_count": comparison["decisive_count"],
            "record_count": record_count,
            "gold_accept_count": gold_accept,
            "gold_reject_count": gold_reject,
            "gold_abstain_count": composition["ABSTAIN"],
        },
        "metrics": metrics,
        "conditions": {
            "far_wilson_upper_bound_within_max": far_ok,
            "frr_wilson_upper_bound_within_max": frr_ok,
            "coverage_meets_minimum": coverage_ok,
        },
        "verdict": verdict,
        "reason": reason,
        "calibration_status": CALIBRATION_STATUS,
        "adjudication_boundary": ADJUDICATION_BOUNDARY,
    }
    adjudication["self_digest"] = _self_digest(adjudication)
    adjudication_bytes = canonical_json_bytes(adjudication)

    # 8. Build the recomputed publication artifacts.
    t4_payload: dict[str, Any] = {
        "schema_version": COMPOSITION_SCHEMA_VERSION,
        "evidence_origin": grant.evidence_origin,
        "run_id": run_id,
        "record_count": record_count,
        "gold_decision_counts": {
            "ACCEPT": composition["ACCEPT"],
            "ABSTAIN": composition["ABSTAIN"],
            "REJECT": composition["REJECT"],
        },
        "model_decision_counts": recomputed["model_decision_counts"],
    }
    t4_bytes = canonical_json_bytes(t4_payload)
    t8_lines = ["record_id,expected_decision,decision,parse_status,outcome"]
    for record in records:
        t8_lines.append(
            ",".join(
                [
                    record["record_id"],
                    record["expected_decision"],
                    record["decision"],
                    record["parse_status"],
                    _outcome(record["expected_decision"], record["decision"]),
                ]
            )
        )
    t8_bytes = ("\n".join(t8_lines) + "\n").encode("utf-8")
    f7_bytes = _build_f7_svg(run_id=run_id, metrics=metrics, verdict=verdict)

    # 9. Assemble the receipt and install atomically.
    request_manifest, request_bytes = _read_json_object(
        _require_external_file(request_manifest_path, label="E3-v2 request manifest"),
        label="E3-v2 request manifest",
    )
    authority_record_payload, authority_record_bytes = _read_json_object(
        _require_external_file(authority_record_path, label="E3-v2 authority record"),
        label="E3-v2 authority record",
    )
    try:
        authority_record = parse_authority_record(authority_record_payload)
    except E3V2ScopeError as error:
        raise E3V2ImportError(f"E3-v2 authority record schema validation failed: {error}") from error

    installed_files: dict[str, bytes] = {
        "source/execution_manifest.json": artifact_blobs["execution_manifest.json"],
        "source/outputs.jsonl": artifact_blobs["outputs.jsonl"],
        "source/summary.json": artifact_blobs["summary.json"],
        "source/trace.jsonl": artifact_blobs["trace.jsonl"],
        "source/T4_dataset_composition.json": t4_bytes,
        "source/T8_semantic_verification.csv": t8_bytes,
        "source/F7_semantic_verification_quality.svg": f7_bytes,
        "c3_v2_adjudication.json": adjudication_bytes,
    }
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "VERIFIED_E3_V2_IMPORTED",
        "run_id": run_id,
        "request_manifest": {
            "path": Path(request_manifest_path).name,
            "sha256": _sha256_bytes(request_bytes),
            "self_digest": request_manifest.get("self_digest"),
        },
        "authority_verification": grant.verification_summary,
        "authority_record": {
            "path": Path(authority_record_path).name,
            "sha256": _sha256_bytes(authority_record_bytes),
            "authority_basis": authority_record.authority_basis,
            "expertise_scope": authority_record.expertise_scope,
            "authorization_date": authority_record.authorization_date,
        },
        "attestation": {
            "path": attestation_path.name,
            "sha256": _sha256_bytes(attestation_bytes),
            "self_digest": attestation["self_digest"],
            "authority_identity": attestation["authority_identity"],
            "attestation_date": attestation.get("attestation_date"),
            "results_disposition": attestation["results_disposition"],
        },
        "execution": {
            "run_id": run_id,
            "adapter": manifest.get("adapter"),
            "evidence_origin": manifest["evidence_origin"],
            "model_id": manifest.get("model", {}).get("model_id"),
            "record_count": record_count,
            "execution_manifest_sha256": _sha256_bytes(artifact_blobs["execution_manifest.json"]),
            "outputs_sha256": _sha256_bytes(artifact_blobs["outputs.jsonl"]),
            "trace_sha256": _sha256_bytes(artifact_blobs["trace.jsonl"]),
            "summary_sha256": _sha256_bytes(artifact_blobs["summary.json"]),
        },
        "imported_artifacts": [
            {
                "artifact_role": _ARTIFACT_ROLES[name],
                "source_path": name,
                "target_path": f"source/{name}",
                "sha256": _sha256_bytes(artifact_blobs[name]),
                "size_bytes": len(artifact_blobs[name]),
            }
            for name in sorted(_ARTIFACT_ROLES)
        ],
        "computed_artifacts": [
            {
                "path": "source/T4_dataset_composition.json",
                "sha256": _sha256_bytes(t4_bytes),
                "size_bytes": len(t4_bytes),
            },
            {
                "path": "source/T8_semantic_verification.csv",
                "sha256": _sha256_bytes(t8_bytes),
                "size_bytes": len(t8_bytes),
            },
            {
                "path": "source/F7_semantic_verification_quality.svg",
                "sha256": _sha256_bytes(f7_bytes),
                "size_bytes": len(f7_bytes),
            },
            {
                "path": "c3_v2_adjudication.json",
                "sha256": _sha256_bytes(adjudication_bytes),
                "size_bytes": len(adjudication_bytes),
            },
        ],
        "adjudication": adjudication,
        "caveats": list(RECEIPT_CAVEATS),
    }
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")

    run_root = resolved_publication_root / str(run_id)
    if _ensure_target_compatibility(run_root, installed_files, receipt_bytes):
        return receipt
    if run_root.exists():
        raise E3V2ImportError("existing target contains divergent content")
    run_root.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(
        tempfile.mkdtemp(prefix=f".tmp-import-{run_id}-", dir=run_root.parent)
    )
    try:
        for relative_path, payload in installed_files.items():
            destination = temp_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        (temp_root / "verification_receipt.json").write_bytes(receipt_bytes)
        try:
            os.replace(temp_root, run_root)
        except OSError as error:
            raise E3V2ImportError(
                f"failed to atomically install verified E3-v2 import: {error}"
            ) from error
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--authority-record", type=Path, required=True)
    parser.add_argument("--authority-allowed-signers", type=Path, required=True)
    parser.add_argument("--authority-signature", type=Path, required=True)
    parser.add_argument("--attestation-record", type=Path, required=True)
    parser.add_argument("--attestation-allowed-signers", type=Path, required=True)
    parser.add_argument("--attestation-signature", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--publication-root",
        type=Path,
        default=REPO_ROOT / "results" / "publication",
    )
    args = parser.parse_args()
    try:
        receipt = import_verified_e3_v2_result(
            request_manifest_path=args.request_manifest,
            authority_record_path=args.authority_record,
            authority_allowed_signers_path=args.authority_allowed_signers,
            authority_signature_path=args.authority_signature,
            attestation_record_path=args.attestation_record,
            attestation_allowed_signers_path=args.attestation_allowed_signers,
            attestation_signature_path=args.attestation_signature,
            run_dir_path=args.run_dir,
            publication_root=args.publication_root,
        )
    except (E3V2ImportError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
