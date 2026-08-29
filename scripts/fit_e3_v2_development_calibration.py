#!/usr/bin/env python3
"""Fit and atomically emit the Phase-3 FROZEN_DEVELOPMENT_ONLY calibration freeze.

This CLI consumes:

- the sealed E3-v2 development bundle (dataset manifest, model/prompt/policy),
- raw outputs.jsonl from ``run_e3_v2_development_model.py``,
- the development bundle report (from ``build_e3_v2_development_bundle.py``).

It produces atomically (all-or-nothing):

1. **error ledger** — `CalibrationErrorLedgerV1` (all observations, sorted)
2. **leakage report** — `CalibrationLeakageReportV1` with status
   `NOT_YET_ASSESSABLE` (no confirmatory dataset at Phase-3)
3. **metrics** — threshold selection metrics (exact accuracy, FAR, FRR, coverage)
4. **freeze** — `SemanticCalibrationFreezeV2` with status
   `FROZEN_DEVELOPMENT_ONLY`

The freeze is deterministic: it is derived solely from the observed development
set behavior. It does not claim transport, statistical calibration, or
confirmatory validity.

This CLI is **development-only**. It will fail closed if:

- any observation has an origin other than REAL_MODEL_EXECUTION
- confirmatory material is referenced or present
- the dataset composition is not 50 ACCEPT / 50 REJECT / 20-50 ABSTAIN
- the observation count is outside 120-150
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.auditor.semantic.calibration import fit_development_calibration_v2  # noqa: E402
from poi_mpp.auditor.semantic.models import (  # noqa: E402
    CalibrationErrorLedgerV1,
    CalibrationLeakageReportV1,
    CalibrationLeakageStatus,
    DevelopmentCalibrationFitResultV2,
    SemanticCalibrationFreezeStatus,
    SemanticCalibrationFreezeV2,
    VerificationDecision,
    development_calibration_record_binding_hash,
)
from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.dataset_manifest_v2 import DatasetManifestV2
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
from poi_mpp.worker.model_manifest import PinnedModelManifest
from poi_mpp.worker.development_observation_exporter import (
    DevelopmentObservationExportError,
    build_development_leakage_report,
    export_raw_execution_to_observations,
)
from poi_mpp.experiments.e3_v2_development_authority import (  # noqa: E402
    DevelopmentAuthorityError,
    verify_development_authority,
)
from poi_mpp.experiments.e3_development import (  # noqa: E402
    E3DevelopmentBundleError,
    validate_e3_phase3_development_bundle_materials,
)


class CalibrationCLIError(ValueError):
    """Raised when the Phase-3 calibration CLI fails closed."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    probe = Path(path.anchor)
    for component in path.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise CalibrationCLIError(f"{label} may not be a symlink")


def _require_external_path(path: Path | str, *, label: str, must_exist: bool = True) -> Path:
    _assert_no_symlink_components(Path(path), label=label)
    resolved = Path(path).resolve()
    if must_exist and not resolved.exists():
        raise CalibrationCLIError(f"{label} does not exist: {resolved}")
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise CalibrationCLIError(f"{label} must live outside the repository")
    if must_exist and not resolved.exists():
        raise CalibrationCLIError(f"{label} must exist: {resolved}")
    return resolved


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


def _canonical_json_bytes(payload: dict | list) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def run_calibration_cli(
    *,
    bundle_root: Path,
    outputs_path: Path,
    trace_path: Path,
    summary_path: Path,
    execution_manifest_path: Path,
    request_manifest_path: Path,
    authority_record_path: Path,
    allowed_signers_path: Path,
    signature_path: Path,
    development_report_path: Path,
    output_root: Path,
) -> Path:
    """Fit and atomically emit all Phase-3 calibration artifacts.

    Parameters
    ----------
    bundle_root
        External path to the sealed E3-v2 development bundle.
    outputs_path
        External path to outputs.jsonl from ``run_e3_v2_development_model.py``.
    development_report_path
        External path to the development bundle report.
    output_root
        External directory where error ledger, leakage report, metrics, and
        freeze will be written atomically.

    Returns
    -------
    Path to the output directory containing all four artifacts.
    """
    # --- Resolve external paths (fail closed on symlinks, repo-internal) ----
    resolved_bundle = _require_external_path(bundle_root, label="bundle root", must_exist=True)
    resolved_outputs = _require_external_path(outputs_path, label="outputs.jsonl", must_exist=True)
    resolved_trace = _require_external_path(trace_path, label="trace.jsonl", must_exist=True)
    resolved_summary = _require_external_path(summary_path, label="summary.json", must_exist=True)
    resolved_execution_manifest = _require_external_path(
        execution_manifest_path, label="execution manifest", must_exist=True
    )
    resolved_report = _require_external_path(development_report_path, label="development report", must_exist=True)
    resolved_output = _require_external_path(output_root, label="calibration output root", must_exist=False)

    if any("confirmatory" in path.name.lower() for path in resolved_bundle.rglob("*")):
        raise CalibrationCLIError("confirmatory material is forbidden during Phase-3 calibration")
    try:
        materials = validate_e3_phase3_development_bundle_materials(
            bundle_root=resolved_bundle
        )
    except (E3DevelopmentBundleError, OSError) as error:
        raise CalibrationCLIError(f"development bundle validation failed: {error}") from error

    try:
        authority_grant = verify_development_authority(
            request_manifest_path=request_manifest_path,
            authority_record_path=authority_record_path,
            allowed_signers_path=allowed_signers_path,
            signature_path=signature_path,
        )
    except DevelopmentAuthorityError as error:
        raise CalibrationCLIError(f"development authority verification failed: {error}") from error
    required_metrics = {"ABSTAIN", "FAR", "FRR", "calibration", "coverage"}
    if not required_metrics.issubset(set(authority_grant.metric_scope)):
        raise CalibrationCLIError("authority metric scope does not permit the calibration outputs")
    if "RAW_E3_EXECUTION" not in authority_grant.artifact_scope:
        raise CalibrationCLIError("authority artifact scope excludes raw E3 execution")
    expected_authority_bindings = {
        "development_bundle_manifest_sha256": materials.bundle_manifest_sha256,
        "development_dataset_manifest_hash": materials.dataset_manifest.dataset_manifest_hash(),
        "development_model_manifest_hash": materials.policy_input_file_hashes["model_manifest_hash"],
        "development_decode_policy_hash": materials.policy_input_file_hashes["deterministic_decode_policy_hash"],
        "development_environment_manifest_hash": materials.policy_input_file_hashes["runtime_environment_hash"],
    }
    for field_name, expected_value in expected_authority_bindings.items():
        if getattr(authority_grant, field_name, None) != expected_value:
            raise CalibrationCLIError(f"authority binding mismatch for {field_name}")

    # --- Load the development bundle report --------------------------------
    report_raw = resolved_report.read_bytes()
    try:
        report = json.loads(report_raw)
    except json.JSONDecodeError as error:
        raise CalibrationCLIError(f"development report is not valid JSON: {error}") from error

    if not isinstance(report, dict):
        raise CalibrationCLIError("development report must be a JSON object")
    if report.get("schema_version") != "POI_MPP_E3_V2_DEVELOPMENT_BUNDLE_REPORT_V1":
        raise CalibrationCLIError(
            f"development report schema_version mismatch: {report.get('schema_version')!r}"
        )
    if report.get("status") != "MATERIALS_VALIDATED_WAITING_AUTHORITY":
        raise CalibrationCLIError(
            "development report must have status MATERIALS_VALIDATED_WAITING_AUTHORITY"
        )
    if report.get("development_bundle_manifest_sha256") != materials.bundle_manifest_sha256:
        raise CalibrationCLIError("development report bundle manifest binding does not match")

    execution_manifest = json.loads(resolved_execution_manifest.read_bytes())
    authority_lineage = execution_manifest.get("authority", {})
    if authority_lineage.get("authority_record_sha256") != authority_grant.authority_record_sha256:
        raise CalibrationCLIError("execution manifest authority record binding mismatch")
    if authority_lineage.get("signature_sha256") != authority_grant.signature_sha256:
        raise CalibrationCLIError("execution manifest authority signature binding mismatch")

    # --- Load the dataset manifest from the bundle --------------------------
    dataset_manifest_path = resolved_bundle / "dataset" / "dataset_manifest_v2.json"
    dataset_manifest = DatasetManifestV2.model_validate(
        json.loads(dataset_manifest_path.read_bytes())
    )
    if dataset_manifest.split.value != "DEVELOPMENT":
        raise CalibrationCLIError("dataset manifest must use DEVELOPMENT split")

    # Count-check (also validated by the model, but assert explicitly)
    counts = dataset_manifest.decision_counts()
    if counts["ACCEPT"] != 50:
        raise CalibrationCLIError(f"development dataset requires exactly 50 ACCEPT, got {counts['ACCEPT']}")
    if counts["REJECT"] != 50:
        raise CalibrationCLIError(f"development dataset requires exactly 50 REJECT, got {counts['REJECT']}")
    if not (20 <= counts["ABSTAIN"] <= 50):
        raise CalibrationCLIError(
            f"development dataset requires 20-50 ABSTAIN, got {counts['ABSTAIN']}"
        )
    total = sum(counts.values())
    if not (120 <= total <= 150):
        raise CalibrationCLIError(f"development dataset total must be 120-150, got {total}")

    # --- Load model and decode policy from the bundle -----------------------
    model_manifest = PinnedModelManifest.model_validate(
        json.loads((resolved_bundle / "model" / "pinned_model_manifest.json").read_bytes())
    )
    decode_policy = DeterministicDecodePolicy.model_validate(
        json.loads((resolved_bundle / "execution" / "deterministic_decode_policy.json").read_bytes())
    )

    # --- Export observations from raw execution output ----------------------
    try:
        observations = export_raw_execution_to_observations(
            outputs_path=resolved_outputs,
            trace_path=resolved_trace,
            summary_path=resolved_summary,
            execution_manifest_path=resolved_execution_manifest,
            bundle_root=resolved_bundle,
            dataset_manifest=dataset_manifest,
            claim_spec_hash=_sha256_file(resolved_bundle / "policy" / "claim_spec.json"),
            prompt_template_hash=_sha256_file(resolved_bundle / "policy" / "prompt_template.txt"),
            model_manifest_hash=_sha256_file(resolved_bundle / "model" / "pinned_model_manifest.json"),
            runtime_environment_hash=_sha256_file(resolved_bundle / "execution" / "environment_manifest.json"),
            decode_policy_hash=_sha256_file(resolved_bundle / "execution" / "deterministic_decode_policy.json"),
        )
    except DevelopmentObservationExportError as error:
        raise CalibrationCLIError(f"observation export failed: {error}") from error

    # --- Build the development-only leakage report -------------------------
    leakage_report = build_development_leakage_report(
        development_dataset_manifest=dataset_manifest,
    )
    if leakage_report.status is not CalibrationLeakageStatus.NOT_YET_ASSESSABLE:
        raise CalibrationCLIError(
            "Phase-3 calibration requires a NOT_YET_ASSESSABLE leakage report"
        )

    # --- Verify policy input hashes from the report match the bundle ---------
    policy_labels = {
        "claim_spec_hash": "policy/claim_spec.json",
        "prompt_template_hash": "policy/prompt_template.txt",
        "output_schema_hash": "policy/output_schema.json",
        "contradiction_policy_hash": "policy/contradiction_policy.json",
        "error_recovery_policy_hash": "policy/error_recovery_policy.json",
        "error_taxonomy_review_hash": "policy/error_taxonomy_review.json",
    }
    policy_hashes: dict[str, str] = {}
    for key, relative_path in policy_labels.items():
        file_path = resolved_bundle / relative_path
        policy_hashes[key] = _sha256_file(file_path)

    report_policy_digest = report.get("development_policy_inputs_digest")
    expected_policy_digest = _sha256_bytes(_canonical_json_bytes(policy_hashes))
    if report_policy_digest != expected_policy_digest:
        raise CalibrationCLIError(
            "development report policy inputs digest does not match the bundle policy files"
        )

    # --- Fit the calibration (deterministic, fail-closed) -------------------
    try:
        # The freeze must bind the authority-bound model manifest hash from the
        # report, but the on-disk file hash must cross-validate against it.
        model_manifest_hash = report.get("development_model_manifest_hash")
        if model_manifest_hash is None:
            raise CalibrationCLIError(
                "development report is missing development_model_manifest_hash"
            )
        actual_model_manifest_hash = model_manifest.manifest_hash(decode_policy).removeprefix("0x")
        if model_manifest_hash != actual_model_manifest_hash:
            raise CalibrationCLIError(
                "on-disk model manifest hash does not match the authority-bound report hash"
            )
        fit_result: DevelopmentCalibrationFitResultV2 = fit_development_calibration_v2(
            observations=observations,
            development_dataset_manifest=dataset_manifest,
            claim_spec_hash=policy_hashes["claim_spec_hash"],
            prompt_template_hash=policy_hashes["prompt_template_hash"],
            model_manifest_hash=model_manifest_hash,
            runtime_environment_hash=report.get(
                "development_environment_manifest_hash"
            ),
            output_schema_hash=policy_hashes["output_schema_hash"],
            contradiction_policy_hash=policy_hashes["contradiction_policy_hash"],
            error_recovery_policy_hash=policy_hashes["error_recovery_policy_hash"],
            leakage_report=leakage_report,
        )
    except ValueError as error:
        raise CalibrationCLIError(f"calibration fit failed: {error}") from error

    # --- Atomically emit all artifacts --------------------------------------
    if resolved_output.exists():
        raise CalibrationCLIError("calibration output root must not already exist")
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    staging_output = Path(
        tempfile.mkdtemp(prefix=f".{resolved_output.name}.", dir=resolved_output.parent)
    )

    try:
        error_ledger = fit_result.error_ledger
        _write_atomic(
            staging_output / "error_ledger.json",
            _canonical_json_bytes(error_ledger.model_dump(mode="json")),
        )
        _write_atomic(
            staging_output / "leakage_report.json",
            _canonical_json_bytes(leakage_report.model_dump(mode="json")),
        )
        metrics_payload = {
            "schema_version": "POI_MPP_E3_V2_DEVELOPMENT_CALIBRATION_METRICS_V1",
            "exact_accuracy": fit_result.exact_accuracy,
            "false_accept_rate": fit_result.false_accept_rate,
            "false_reject_rate": fit_result.false_reject_rate,
            "coverage": fit_result.coverage,
            "observation_count": len(observations),
            "support_threshold": fit_result.freeze.support_threshold,
            "reject_threshold": fit_result.freeze.reject_threshold,
            "minimum_calibrated_confidence": fit_result.freeze.minimum_calibrated_confidence,
            "selection_rule_id": fit_result.freeze.selection_rule_id,
            "dataset_manifest_hash": dataset_manifest.dataset_manifest_hash(),
            "calibration_freeze_content_hash": fit_result.freeze.content_hash,
        }
        _write_atomic(staging_output / "metrics.json", _canonical_json_bytes(metrics_payload))

        freeze = fit_result.freeze
        if freeze.status is not SemanticCalibrationFreezeStatus.FROZEN_DEVELOPMENT_ONLY:
            raise CalibrationCLIError(
                f"calibration freeze status must be FROZEN_DEVELOPMENT_ONLY, got {freeze.status}"
            )
        _write_atomic(
            staging_output / "calibration_freeze.json",
            _canonical_json_bytes(freeze.model_dump(mode="json")),
        )

        output_manifest = {
            "schema_version": "POI_MPP_E3_V2_DEVELOPMENT_CALIBRATION_BUNDLE_V1",
            "status": "FROZEN_DEVELOPMENT_ONLY",
            "error_ledger_sha256": _sha256_bytes((staging_output / "error_ledger.json").read_bytes()),
            "leakage_report_sha256": _sha256_bytes((staging_output / "leakage_report.json").read_bytes()),
            "metrics_sha256": _sha256_bytes((staging_output / "metrics.json").read_bytes()),
            "calibration_freeze_sha256": _sha256_bytes((staging_output / "calibration_freeze.json").read_bytes()),
            "dataset_manifest_hash": dataset_manifest.dataset_manifest_hash(),
            "calibration_freeze_content_hash": freeze.content_hash,
            "error_ledger_content_hash": error_ledger.content_hash,
            "leakage_report_content_hash": leakage_report.content_hash,
            "authority_record_sha256": authority_grant.authority_record_sha256,
            "authority_signature_sha256": authority_grant.signature_sha256,
            "execution_manifest_sha256": _sha256_file(resolved_execution_manifest),
        }
        output_manifest["self_digest"] = _sha256_bytes(_canonical_json_bytes(output_manifest))
        _write_atomic(
            staging_output / "calibration_bundle_manifest.json",
            _canonical_json_bytes(output_manifest),
        )
        os.replace(staging_output, resolved_output)
    except BaseException:
        shutil.rmtree(staging_output, ignore_errors=True)
        raise

    return resolved_output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle-root", type=Path, required=True,
        help="Sealed E3-v2 development bundle (external path)",
    )
    parser.add_argument(
        "--outputs", type=Path, required=True,
        help="outputs.jsonl from run_e3_v2_development_model.py (external path)",
    )
    parser.add_argument("--trace", type=Path, required=True, help="Hash-bound trace.jsonl")
    parser.add_argument("--summary", type=Path, required=True, help="Hash-bound summary.json")
    parser.add_argument(
        "--execution-manifest", type=Path, required=True,
        help="Self-digested execution_manifest.json",
    )
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--authority-record", type=Path, required=True)
    parser.add_argument("--allowed-signers", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument(
        "--development-report", type=Path, required=True,
        help="Development bundle report from build_e3_v2_development_bundle.py (external path)",
    )
    parser.add_argument(
        "--output-root", type=Path, required=True,
        help="External directory for calibration artifacts (must not exist)",
    )
    args = parser.parse_args()

    try:
        result = run_calibration_cli(
            bundle_root=args.bundle_root,
            outputs_path=args.outputs,
            trace_path=args.trace,
            summary_path=args.summary,
            execution_manifest_path=args.execution_manifest,
            request_manifest_path=args.request_manifest,
            authority_record_path=args.authority_record,
            allowed_signers_path=args.allowed_signers,
            signature_path=args.signature,
            development_report_path=args.development_report,
            output_root=args.output_root,
        )
    except (CalibrationCLIError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1

    print(f"Phase-3 calibration freeze emitted to: {result}")
    print(f"  error_ledger.json")
    print(f"  leakage_report.json")
    print(f"  metrics.json")
    print(f"  calibration_freeze.json")
    print(f"  calibration_bundle_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
