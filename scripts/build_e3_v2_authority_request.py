#!/usr/bin/env python3
"""Build the unsigned E3-v2 pre-execution authority request manifest.

Deterministically derives the canonical request manifest from the three
external E3-v2 documents (development bundle report, confirmatory freeze
lineage report, semantic calibration freeze).  The manifest binds the frozen
C3-v2 Wilson support rule, the material hashes, and the tracked repository
input files.  It is unsigned request material: it grants no authority,
contains no evaluator identity or decision, and cannot attest to any result.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.experiments.e3_v2_scope import (  # noqa: E402
    E3V2ScopeError,
    build_manifest,
    canonical_json_bytes,
)


class E3V2AuthorityRequestError(ValueError):
    """Raised when the E3-v2 authority request cannot be built fail-closed."""


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    probe = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise E3V2AuthorityRequestError(f"{label} may not be a symlink")


def _require_external_output(path: Path) -> Path:
    _assert_no_symlink_components(path, label="authority request output")
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise E3V2AuthorityRequestError(
            "authority request output must live outside the repository"
        )
    if resolved.exists():
        raise E3V2AuthorityRequestError(f"authority request already exists: {resolved}")
    if not resolved.parent.is_dir():
        raise E3V2AuthorityRequestError("authority request output directory does not exist")
    return resolved


def _write_atomic(path: Path, payload: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_authority_request(
    *,
    development_report_path: Path,
    confirmatory_lineage_path: Path,
    calibration_freeze_path: Path,
    output_path: Path,
) -> Path:
    resolved_output = _require_external_output(output_path)
    manifest = build_manifest(
        development_report_path=development_report_path,
        confirmatory_lineage_path=confirmatory_lineage_path,
        calibration_freeze_path=calibration_freeze_path,
    )
    _write_atomic(resolved_output, canonical_json_bytes(manifest))
    return resolved_output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-report", type=Path, required=True)
    parser.add_argument("--confirmatory-lineage", type=Path, required=True)
    parser.add_argument("--calibration-freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = build_authority_request(
            development_report_path=args.development_report,
            confirmatory_lineage_path=args.confirmatory_lineage,
            calibration_freeze_path=args.calibration_freeze,
            output_path=args.output,
        )
    except (E3V2AuthorityRequestError, E3V2ScopeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
