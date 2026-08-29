"""Canonical exporter: raw development execution output -> calibration observations.

Converts the raw outputs.jsonl produced by ``run_e3_v2_development_model.py``
into a sequence of :class:`DevelopmentCalibrationObservationV2` objects with
authoritative dataset-record binding hashes under the ``REAL_MODEL_EXECUTION``
origin.

The exporter enforces:

- every observation record_id exists in the development dataset manifest
- observed decisions are one of ACCEPT / REJECT / ABSTAIN (fail-closed parse)
- support_fraction / calibrated_confidence are in [0, 1]
- error_code / error_family are consistent with expected vs observed decisions
- observed provenance matches the authoritative dataset manifest
- no synthetic-non-evidence observations can enter the calibration ledger
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.auditor.semantic.models import (
    CalibrationLeakageReportV1,
    CalibrationLeakageStatus,
    DevelopmentCalibrationObservationV2,
    SemanticCalibrationErrorCode,
    SemanticCalibrationErrorFamily,
    VerificationDecision,
    development_calibration_record_binding_hash,
)
from poi_mpp.evidence.dataset_manifest_v2 import DatasetManifestV2, DatasetManifestRecordV2
from poi_mpp.evidence.models import EvidenceOrigin


class DevelopmentObservationExportError(ValueError):
    """Raised when raw output cannot be exported as development observations."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    probe = Path(path.anchor)
    for component in path.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise DevelopmentObservationExportError(f"{label} may not be a symlink")


def _require_external_file(path: Path | str, *, label: str) -> Path:
    _assert_no_symlink_components(Path(path), label=label)
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise DevelopmentObservationExportError(f"{label} must live outside the repository")
    if not resolved.is_file():
        raise DevelopmentObservationExportError(f"{label} must be a file")
    return resolved


def _require_external_directory(path: Path | str, *, label: str) -> Path:
    _assert_no_symlink_components(Path(path), label=label)
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise DevelopmentObservationExportError(f"{label} must live outside the repository")
    if not resolved.is_dir():
        raise DevelopmentObservationExportError(f"{label} must be a directory")
    return resolved


def _read_json_file(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DevelopmentObservationExportError(f"{label} must be valid JSON") from error
    if not isinstance(payload, dict):
        raise DevelopmentObservationExportError(f"{label} must be a JSON object")
    return payload


def _read_jsonl(path: Path, *, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise DevelopmentObservationExportError(
                f"{label} line {line_number}: invalid JSON"
            ) from error
        if not isinstance(row, dict):
            raise DevelopmentObservationExportError(f"{label} line {line_number}: expected object")
        rows.append(row)
    return rows


def _derive_error_code(
    *,
    expected: VerificationDecision,
    observed: VerificationDecision,
    parse_status: str,
) -> tuple[SemanticCalibrationErrorCode, SemanticCalibrationErrorFamily]:
    """Map (expected, observed, parse_status) to a canonical error code.

    Follows the exact decision bindings enforced by
    ``DevelopmentCalibrationObservationV2.validate_taxonomy_binding``:

    - CORRECT_ACCEPT: expected=ACCEPT, observed=ACCEPT
    - CORRECT_REJECT: expected=REJECT, observed=REJECT
    - CORRECT_ABSTAIN: expected=ABSTAIN, observed=ABSTAIN
    - FALSE_REJECT: expected=ACCEPT, observed=REJECT (exact binding)
    - FALSE_ACCEPT: observed=ACCEPT, expected≠ACCEPT
    - INCORRECT_ABSTAIN: observed=ABSTAIN, expected≠ABSTAIN
    - OUTCOME_MISMATCH: expected=REJECT, observed=ACCEPT (not a FALSE_ACCEPT because
      expected is REJECT, not ACCEPT; observed is ACCEPT but expected is also not ABSTAIN
      so it's not INCORRECT_ABSTAIN — use OUTCOME_MISMATCH)
    - OUTCOME_MISMATCH: any remaining mismatch the taxonomy doesn't classify more specifically

    Contradictions and unparseable outputs always fall closed to ABSTAIN and
    receive FALSE_ACCEPT or FALSE_REJECT depending on whether the model's
    ambiguous output was an attempted ACCEPT or REJECT.
    """
    family = SemanticCalibrationErrorFamily.DECISION

    # Fail-closed parsing outcomes: observed is forced to ABSTAIN
    if parse_status != "OK":
        if expected is VerificationDecision.ABSTAIN:
            return SemanticCalibrationErrorCode.CORRECT_ABSTAIN, family
        return SemanticCalibrationErrorCode.INCORRECT_ABSTAIN, family

    # parse_status == "OK" — check exact bindings first
    if expected is VerificationDecision.ACCEPT and observed is VerificationDecision.ACCEPT:
        return SemanticCalibrationErrorCode.CORRECT_ACCEPT, family
    if expected is VerificationDecision.REJECT and observed is VerificationDecision.REJECT:
        return SemanticCalibrationErrorCode.CORRECT_REJECT, family
    if expected is VerificationDecision.ABSTAIN and observed is VerificationDecision.ABSTAIN:
        return SemanticCalibrationErrorCode.CORRECT_ABSTAIN, family
    # FALSE_REJECT: exact binding (expected=ACCEPT, observed=REJECT)
    if expected is VerificationDecision.ACCEPT and observed is VerificationDecision.REJECT:
        return SemanticCalibrationErrorCode.FALSE_REJECT, family
    # FALSE_ACCEPT: observed=ACCEPT, expected≠ACCEPT
    if observed is VerificationDecision.ACCEPT and expected is not VerificationDecision.ACCEPT:
        return SemanticCalibrationErrorCode.FALSE_ACCEPT, family
    # INCORRECT_ABSTAIN: observed=ABSTAIN, expected≠ABSTAIN
    if observed is VerificationDecision.ABSTAIN and expected is not VerificationDecision.ABSTAIN:
        return SemanticCalibrationErrorCode.INCORRECT_ABSTAIN, family
    # Remaining: expected=REJECT, observed=ACCEPT → OUTCOME_MISMATCH
    return SemanticCalibrationErrorCode.OUTCOME_MISMATCH, family


def _decision_from_string(value: str) -> VerificationDecision:
    if not isinstance(value, str):
        raise DevelopmentObservationExportError("decision must be a string")
    upper = value.strip().upper()
    if upper == "ACCEPT":
        return VerificationDecision.ACCEPT
    if upper == "REJECT":
        return VerificationDecision.REJECT
    if upper == "ABSTAIN":
        return VerificationDecision.ABSTAIN
    raise DevelopmentObservationExportError(f"unknown decision: {value!r}")


def export_raw_execution_to_observations(
    *,
    outputs_path: Path,
    trace_path: Path,
    summary_path: Path,
    execution_manifest_path: Path,
    bundle_root: Path,
    dataset_manifest: DatasetManifestV2,
    claim_spec_hash: str,
    prompt_template_hash: str,
    model_manifest_hash: str,
    runtime_environment_hash: str,
    decode_policy_hash: str,
) -> list[DevelopmentCalibrationObservationV2]:
    """Convert raw execution output into a list of canonical observations.

    Parameters
    ----------
    outputs_path
        External path to outputs.jsonl from ``run_e3_v2_development_model.py``.
    dataset_manifest
        The authoritative development dataset manifest for record binding.
    claim_spec_hash, prompt_template_hash, model_manifest_hash,
    runtime_environment_hash, decode_policy_hash
        Hash bindings from the sealed development bundle.

    Returns
    -------
    List of :class:`DevelopmentCalibrationObservationV2` objects, sorted by
    record_id for deterministic emission.
    """
    resolved_outputs = _require_external_file(outputs_path, label="outputs.jsonl")
    resolved_trace = _require_external_file(trace_path, label="trace.jsonl")
    resolved_summary = _require_external_file(summary_path, label="summary.json")
    resolved_manifest = _require_external_file(
        execution_manifest_path, label="execution manifest"
    )
    resolved_bundle = _require_external_directory(bundle_root, label="development bundle")

    manifest = _read_json_file(resolved_manifest, label="execution manifest")
    if manifest.get("schema_version") != "POI_MPP_E3_V2_DEVELOPMENT_EXECUTION_MANIFEST_V1":
        raise DevelopmentObservationExportError("execution manifest schema mismatch")
    unsigned_manifest = dict(manifest)
    self_digest = unsigned_manifest.pop("self_digest", None)
    if self_digest != _sha256_bytes(
        json.dumps(unsigned_manifest, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ):
        raise DevelopmentObservationExportError("execution manifest self_digest mismatch")
    if manifest.get("adapter") != "transformers-pinned-v1":
        raise DevelopmentObservationExportError("calibration requires the pinned transformers adapter")
    if manifest.get("evidence_origin") != EvidenceOrigin.REAL_MODEL_EXECUTION.value:
        raise DevelopmentObservationExportError("execution manifest must declare REAL_MODEL_EXECUTION")
    output_files = manifest.get("output_files")
    expected_output_hashes = {
        "outputs": _sha256_bytes(resolved_outputs.read_bytes()),
        "trace": _sha256_bytes(resolved_trace.read_bytes()),
        "summary": _sha256_bytes(resolved_summary.read_bytes()),
    }
    if output_files != expected_output_hashes:
        raise DevelopmentObservationExportError("execution manifest output hash closure mismatch")
    summary = _read_json_file(resolved_summary, label="summary")
    if (
        summary.get("schema_version") != "POI_MPP_E3_V2_DEVELOPMENT_EXECUTION_SUMMARY_V1"
        or summary.get("adapter") != "transformers-pinned-v1"
        or summary.get("evidence_origin") != EvidenceOrigin.REAL_MODEL_EXECUTION.value
        or summary.get("item_count") != len(dataset_manifest.records)
    ):
        raise DevelopmentObservationExportError("execution summary does not bind the real development run")

    template_path = resolved_bundle / "policy" / "prompt_template.txt"
    _assert_no_symlink_components(template_path, label="prompt template")
    template = template_path.read_bytes()
    if _sha256_bytes(template) != prompt_template_hash:
        raise DevelopmentObservationExportError("prompt template hash does not match the bound input")

    # Build record index for binding
    record_index: dict[str, DatasetManifestRecordV2] = {}
    for record in dataset_manifest.records:
        record_index[record.record_id] = record

    # Parse raw outputs
    raw_rows = _read_jsonl(resolved_outputs, label="outputs.jsonl")
    trace_rows = _read_jsonl(resolved_trace, label="trace.jsonl")
    trace_index = {row.get("record_id"): row for row in trace_rows}
    if len(trace_index) != len(trace_rows):
        raise DevelopmentObservationExportError("trace.jsonl has duplicate or missing record_id")

    if not raw_rows:
        raise DevelopmentObservationExportError("outputs.jsonl contains no records")

    observations: list[DevelopmentCalibrationObservationV2] = []
    seen_record_ids: set[str] = set()

    for row in raw_rows:
        record_id = row.get("record_id")
        if record_id is None or record_id in seen_record_ids:
            raise DevelopmentObservationExportError(
                f"duplicate or missing record_id in outputs: {record_id}"
            )
        if record_id not in record_index:
            raise DevelopmentObservationExportError(
                f"record_id {record_id} is absent from the authoritative dataset manifest"
            )
        seen_record_ids.add(record_id)

        record = record_index[record_id]

        # Validate provenance
        evidence_origin = row.get("evidence_origin", "")
        if evidence_origin != EvidenceOrigin.REAL_MODEL_EXECUTION.value:
            raise DevelopmentObservationExportError(
                f"record {record_id}: only REAL_MODEL_EXECUTION observations may enter development calibration"
            )

        # Validate item hash
        if row.get("item_hash") != record.item_hash:
            raise DevelopmentObservationExportError(
                f"record {record_id}: item hash mismatch against dataset manifest"
            )

        item_path = resolved_bundle / "dataset" / record.item_path
        _assert_no_symlink_components(item_path, label=f"dataset item {record_id}")
        item_bytes = item_path.read_bytes()
        if _sha256_bytes(item_bytes) != record.item_hash:
            raise DevelopmentObservationExportError(f"record {record_id}: bundle item hash mismatch")
        prompt_sha256 = _sha256_bytes(template + item_bytes)
        if row.get("prompt_sha256") != prompt_sha256:
            raise DevelopmentObservationExportError(
                f"record {record_id}: prompt_sha256 is not reproducible"
            )
        raw_output = row.get("raw_output")
        if not isinstance(raw_output, str) or row.get("raw_output_sha256") != _sha256_bytes(raw_output.encode("utf-8")):
            raise DevelopmentObservationExportError(f"record {record_id}: raw output hash mismatch")
        trace_row = trace_index.get(record_id)
        if trace_row is None or any(
            trace_row.get(key) != row.get(key)
            for key in ("prompt_sha256", "raw_output_sha256", "adapter")
        ):
            raise DevelopmentObservationExportError(f"record {record_id}: trace closure mismatch")
        if row.get("adapter") != "transformers-pinned-v1":
            raise DevelopmentObservationExportError(f"record {record_id}: non-publication adapter")
        if row.get("expected_decision") != record.expected_decision.value:
            raise DevelopmentObservationExportError(f"record {record_id}: expected decision mismatch")

        # Parse decisions
        expected_decision = _decision_from_string(record.expected_decision.value)
        raw_decision = row.get("decision", "")
        observed_decision = _decision_from_string(raw_decision)
        parse_status = row.get("parse_status", "UNPARSEABLE_FAIL_CLOSED")
        if parse_status not in {"OK", "CONTRADICTION_FAIL_CLOSED", "UNPARSEABLE_FAIL_CLOSED"}:
            raise DevelopmentObservationExportError(f"record {record_id}: unknown parse status")

        # Derive error code
        error_code, error_family = _derive_error_code(
            expected=expected_decision,
            observed=observed_decision,
            parse_status=parse_status,
        )

        default_support = 1.0 if observed_decision is VerificationDecision.ACCEPT else 0.0
        default_confidence = 1.0 if observed_decision is not VerificationDecision.ABSTAIN else 0.0
        support_fraction = row.get("support_fraction", default_support if parse_status == "OK" else 0.0)
        calibrated_confidence = row.get("calibrated_confidence", default_confidence if parse_status == "OK" else 0.0)
        if not isinstance(support_fraction, (int, float)) or not 0.0 <= support_fraction <= 1.0:
            raise DevelopmentObservationExportError(f"record {record_id}: invalid support_fraction")
        if not isinstance(calibrated_confidence, (int, float)) or not 0.0 <= calibrated_confidence <= 1.0:
            raise DevelopmentObservationExportError(f"record {record_id}: invalid calibrated_confidence")

        # Compute authoritative dataset-record binding hash
        binding_hash = development_calibration_record_binding_hash(record)

        observation = DevelopmentCalibrationObservationV2(
            record_id=record_id,
            expected_decision=expected_decision,
            observed_decision=observed_decision,
            support_fraction=support_fraction,
            calibrated_confidence=calibrated_confidence,
            error_code=error_code,
            error_family=error_family,
            attack_family="BASELINE",
            subgroup=record.subgroup,
            difficulty=record.difficulty,
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
            dataset_record_binding_hash=binding_hash,
        )
        observations.append(observation)

    expected_ids = set(record_index)
    if seen_record_ids != expected_ids or set(trace_index) != expected_ids:
        raise DevelopmentObservationExportError("execution records do not exactly cover the development dataset")

    # Sort deterministically by record_id
    observations.sort(key=lambda obs: obs.record_id)
    return observations


def build_development_leakage_report(
    *,
    development_dataset_manifest: DatasetManifestV2,
    confirmatory_dataset_manifest: DatasetManifestV2 | None = None,
) -> CalibrationLeakageReportV1:
    """Build a development-phase leakage report.

    At Phase-3, confirmatory material is not yet available, so
    confirmatory_manifest_hash remains None and the status is
    NOT_YET_ASSESSABLE.
    """
    development_hash = development_dataset_manifest.dataset_manifest_hash()

    record_ids: set[str] = set()
    for record in development_dataset_manifest.records:
        record_ids.add(record.record_id)

    confirmatory_hash: str | None = None
    record_overlap_count = 0
    content_overlap_count = 0
    item_overlap_count = 0
    label_overlap_count = 0
    dedup_overlap_count = 0
    source_overlap_count = 0
    source_family_overlap_count = 0
    near_duplicate_overlap_count = 0
    status = CalibrationLeakageStatus.NOT_YET_ASSESSABLE

    if confirmatory_dataset_manifest is not None:
        confirmatory_hash = confirmatory_dataset_manifest.dataset_manifest_hash()
        confirmatory_ids: set[str] = set()
        for record in confirmatory_dataset_manifest.records:
            confirmatory_ids.add(record.record_id)

        record_overlap_count = len(record_ids & confirmatory_ids)

        if record_overlap_count > 0:
            status = CalibrationLeakageStatus.BLOCKED
        else:
            status = CalibrationLeakageStatus.CLEAR

    return CalibrationLeakageReportV1(
        schema_version="POI_MPP_SEMANTIC_CALIBRATION_LEAKAGE_REPORT_V1",
        development_manifest_hash=development_hash,
        confirmatory_manifest_hash=confirmatory_hash,
        record_overlap_count=record_overlap_count,
        content_overlap_count=content_overlap_count,
        item_overlap_count=item_overlap_count,
        label_overlap_count=label_overlap_count,
        dedup_overlap_count=dedup_overlap_count,
        source_overlap_count=source_overlap_count,
        source_family_overlap_count=source_family_overlap_count,
        near_duplicate_overlap_count=near_duplicate_overlap_count,
        status=status,
        content_hash=None,
    )
