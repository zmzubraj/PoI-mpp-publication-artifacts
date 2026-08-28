#!/usr/bin/env python3
"""Build the deterministic E3-v2 development bundle validation report.

Validates an external E3-v2 development bundle's materials and emits a
canonical JSON report carrying the exact hash bindings that a later E3-v2
authority request must bind. The report grants no authority, creates no
evidence, and never promotes the bundle to execution.
"""

from __future__ import annotations

import argparse
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

from poi_mpp.experiments.e3_development import (  # noqa: E402
    E3DevelopmentBundleError,
    validate_e3_phase3_development_bundle_materials,
)


REPORT_SCHEMA_VERSION = "POI_MPP_E3_V2_DEVELOPMENT_BUNDLE_REPORT_V1"
_POLICY_BINDING_KEYS = (
    "claim_spec_hash",
    "prompt_template_hash",
    "output_schema_hash",
    "contradiction_policy_hash",
    "error_recovery_policy_hash",
    "error_taxonomy_review_hash",
)


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    probe = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise E3DevelopmentBundleError(f"{label} may not be a symlink")


def _require_external_output(path: Path) -> Path:
    _assert_no_symlink_components(path, label="report output")
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise E3DevelopmentBundleError("development bundle report must live outside the repository")


def build_report(bundle_root: Path | str) -> dict[str, Any]:
    materials = validate_e3_phase3_development_bundle_materials(bundle_root=bundle_root)
    policy_bindings = {
        key: materials.policy_input_file_hashes[key] for key in _POLICY_BINDING_KEYS
    }
    counts = materials.dataset_manifest.decision_counts()
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "MATERIALS_VALIDATED_WAITING_AUTHORITY",
        "development_bundle_manifest_sha256": materials.bundle_manifest_sha256,
        "development_dataset_manifest_hash": materials.dataset_manifest.dataset_manifest_hash(),
        "development_model_manifest_hash": materials.policy_input_file_hashes["model_manifest_hash"],
        "development_decode_policy_hash": materials.policy_input_file_hashes[
            "deterministic_decode_policy_hash"
        ],
        "development_environment_manifest_hash": materials.policy_input_file_hashes[
            "runtime_environment_hash"
        ],
        "development_policy_inputs_digest": _sha256(_canonical_bytes(policy_bindings)),
        "policy_input_file_hashes": dict(materials.policy_input_file_hashes),
        "dataset": {
            "dataset_id": materials.dataset_manifest.dataset_id,
            "record_count": len(materials.dataset_manifest.records),
            "decision_counts": {key: counts[key] for key in sorted(counts)},
        },
        "model": {
            "model_id": materials.model_manifest.model_id,
            "revision": materials.model_manifest.revision,
            "tokenizer_id": materials.model_manifest.tokenizer_id,
            "tokenizer_revision": materials.model_manifest.tokenizer_revision,
            "parameter_scale": materials.model_manifest.parameter_scale,
            "quantization": materials.model_manifest.quantization,
        },
        "decode_policy": {
            "seed": materials.decode_policy.seed,
            "max_new_tokens": materials.decode_policy.max_new_tokens,
        },
        "owner_declaration": {
            "owner_id": materials.owner_declaration.owner_id,
            "accountable_reviewer_id": materials.owner_declaration.accountable_reviewer_id,
        },
        "authority_boundary": (
            "This report only records fail-closed validation of external E3-v2 development "
            "bundle materials. It grants no authority, binds no execution, and is not evidence."
        ),
    }
    report["self_digest"] = _sha256(_canonical_bytes(report))
    return report


def serialized_report(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = _require_external_output(args.output)
        report = build_report(args.bundle_root)
    except (E3DevelopmentBundleError, FileNotFoundError) as error:
        print(f"E3-v2 development bundle report failed: {error}", file=sys.stderr)
        return 1
    _write_atomic(output, serialized_report(report))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
