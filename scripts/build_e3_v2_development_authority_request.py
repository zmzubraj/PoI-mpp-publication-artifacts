#!/usr/bin/env python3
"""Build a development-only E3-v2 pre-execution authority request manifest.

This manifest is scoped to the development phase only (120-150 items), binding:

- the sealed development dataset manifest hash,
- the pinned model manifest, deterministic decode policy, and environment manifest,
- the frozen policy inputs (claim spec, prompt, output schema, etc.),
- the requested scope (C3-v2 Wilson support rule adapted for development),

The manifest is unsigned request material: it grants no authority, contains no
evaluator identity or decision, and cannot attest to any future result. It is
deliberately scoped to prevent promotion to the 500-item confirmatory run.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.experiments.e3_v2_development_authority import (  # noqa: E402
    DevelopmentAuthorityError,
    build_development_authority_request_manifest,
    canonical_json_bytes,
)

class DevelopmentAuthorityRequestError(ValueError):
    """Raised when the development authority request cannot be built fail-closed."""


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    probe = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise DevelopmentAuthorityRequestError(f"{label} may not be a symlink")


def build_development_authority_request(
    *,
    bundle_root: Path,
    output_path: Path,
) -> Path:
    """Build the unsigned development-only authority request manifest.

    Parameters
    ----------
    bundle_root
        External path to the validated E3-v2 development bundle (the sealed
        dataset directory containing model/, dataset/, policy/, execution/).
    output_path
        External path where the unsigned manifest will be written (must not
        exist yet).

    Returns
    -------
    The resolved path to the written manifest.
    """
    resolved_output = _require_external_output(output_path, label="development authority request output")
    manifest_payload = build_development_authority_request_manifest(bundle_root)
    _write_atomic(resolved_output, canonical_json_bytes(manifest_payload))
    return resolved_output


def _require_external_output(path: Path | str, *, label: str) -> Path:
    original = Path(path)
    _assert_no_symlink_components(original, label=label)
    resolved_path = original.resolve()
    try:
        resolved_path.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise DevelopmentAuthorityRequestError(f"{label} must live outside the repository")
    if resolved_path.exists():
        raise DevelopmentAuthorityRequestError(f"{label} already exists: {resolved_path}")
    if not resolved_path.parent.is_dir():
        raise DevelopmentAuthorityRequestError(f"{label} parent directory does not exist")
    return resolved_path


def _write_atomic(path: Path, payload: bytes) -> None:
    import os
    import tempfile
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
    parser.add_argument("--bundle-root", type=Path, required=True, help="Path to the sealed E3-v2 development bundle")
    parser.add_argument("--output", type=Path, required=True, help="Output path for the unsigned manifest (must not exist)")
    args = parser.parse_args()
    try:
        result = build_development_authority_request(
            bundle_root=args.bundle_root,
            output_path=args.output,
        )
    except (DevelopmentAuthorityRequestError, DevelopmentAuthorityError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Development authority request manifest written to: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
