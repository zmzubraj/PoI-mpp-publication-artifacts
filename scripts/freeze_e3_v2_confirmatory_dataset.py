#!/usr/bin/env python3
"""Build the deterministic E3-v2 confirmatory freeze lineage report.

Validates an external E3-v2 confirmatory bundle (500 dual-annotated items)
against the frozen Phase-4 contract and emits a canonical JSON lineage report.
The report always remains WAITING_EXTERNAL: verified external authority
binding and accountable freeze approval are separate inputs owned by later
orchestration, and this script can never promote the bundle to execution.
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

from poi_mpp.experiments.e3_confirmatory_freeze import (  # noqa: E402
    E3ConfirmatoryFreezeError,
    prepare_e3_phase4_confirmatory_freeze,
    validate_e3_phase4_confirmatory_freeze_materials,
)


LINEAGE_SCHEMA_VERSION = "POI_MPP_E3_V2_CONFIRMATORY_FREEZE_LINEAGE_V1"


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
            raise E3ConfirmatoryFreezeError(f"{label} may not be a symlink")


def _require_external_output(path: Path) -> Path:
    _assert_no_symlink_components(path, label="lineage report output")
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise E3ConfirmatoryFreezeError("confirmatory freeze lineage report must live outside the repository")


def build_lineage_report(bundle_root: Path | str, development_manifest_path: Path | str) -> dict[str, Any]:
    materials = validate_e3_phase4_confirmatory_freeze_materials(
        bundle_root=bundle_root,
        development_manifest_path=development_manifest_path,
    )
    waiting = prepare_e3_phase4_confirmatory_freeze(
        bundle_root=bundle_root,
        development_manifest_path=development_manifest_path,
    )
    counts = materials.decision_counts
    report: dict[str, Any] = {
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "status": waiting.status.value,
        "reason": waiting.reason,
        "missing_inputs": list(waiting.missing_inputs),
        "material_lineage_hash": materials.material_lineage_hash,
        "lineage": {
            "bundle_manifest_sha256": materials.bundle_manifest_sha256,
            "dataset_manifest_hash": materials.dataset_manifest_hash,
            "development_manifest_hash": materials.development_manifest_hash,
            "annotation_ledger_sha256": materials.annotation_ledger_sha256,
            "annotation_agreement_sha256": materials.annotation_agreement_sha256,
            "adjudication_ledger_sha256": materials.adjudication_ledger_sha256,
            "license_privacy_ledger_sha256": materials.license_privacy_ledger_sha256,
        },
        "decision_counts": {key: counts[key] for key in sorted(counts)},
        "agreement_summary": {
            "numerator": materials.agreement_summary["numerator"],
            "denominator": materials.agreement_summary["denominator"],
            "rate": materials.agreement_summary["rate"],
        },
        "dataset": {
            "dataset_id": materials.dataset_manifest.dataset_id,
            "record_count": len(materials.dataset_manifest.records),
        },
        "freeze_boundary": (
            "This report only records fail-closed validation of external E3-v2 confirmatory "
            "materials. It remains WAITING_EXTERNAL: it grants no authority, records no freeze "
            "approval, and cannot promote the bundle to execution."
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
    parser.add_argument("--development-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = _require_external_output(args.output)
        report = build_lineage_report(args.bundle_root, args.development_manifest)
    except (E3ConfirmatoryFreezeError, FileNotFoundError) as error:
        print(f"E3-v2 confirmatory freeze lineage failed: {error}", file=sys.stderr)
        return 1
    _write_atomic(output, serialized_report(report))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
