#!/usr/bin/env python3
"""Build the deterministic strongest-prior-art novelty package manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
NOVELTY_ROOT = REPO_ROOT / "docs" / "paper_artifacts" / "final" / "novelty"
DEFAULT_OUTPUT = NOVELTY_ROOT / "NOVELTY_MANIFEST.json"

PACKAGE_INPUTS = (
    "docs/paper_artifacts/final/novelty/README.md",
    "docs/paper_artifacts/final/novelty/NOVELTY_CASE.md",
    "docs/paper_artifacts/final/novelty/SEARCH_QUERIES.md",
    "docs/paper_artifacts/final/novelty/screening_ledger.csv",
    "docs/paper_artifacts/final/novelty/closest_predecessor_matrix.csv",
    "docs/paper_artifacts/final/novelty/citation_chaining.csv",
    "docs/paper_artifacts/final/novelty/contradiction_ledger.csv",
)

RAW_GLOBS = (
    "docs/paper_artifacts/final/novelty/raw/*.json",
    "docs/paper_artifacts/final/novelty/raw/*.xml",
    "docs/paper_artifacts/final/novelty/raw/*.html",
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _validated_file(relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe novelty package path: {relative_path}")
    candidate = REPO_ROOT.joinpath(*pure.parts)
    if candidate.is_symlink():
        raise ValueError(f"novelty package input may not be a symlink: {relative_path}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except (FileNotFoundError, ValueError) as error:
        raise ValueError(f"novelty package input is missing or escapes repository root: {relative_path}") from error
    if not resolved.is_file():
        raise ValueError(f"novelty package input is not a file: {relative_path}")
    return resolved


def _selected_raw_paths() -> tuple[str, ...]:
    selected: set[str] = set()
    for pattern in RAW_GLOBS:
        matches = sorted(REPO_ROOT.glob(pattern))
        if not matches:
            raise ValueError(f"novelty raw glob matched no files: {pattern}")
        for match in matches:
            if match.is_file():
                selected.add(match.relative_to(REPO_ROOT).as_posix())
    return tuple(sorted(selected))


def build_manifest() -> dict[str, Any]:
    package_inputs: list[dict[str, Any]] = []
    for relative_path in PACKAGE_INPUTS:
        artifact = _validated_file(relative_path)
        payload = artifact.read_bytes()
        package_inputs.append(
            {
                "path": relative_path,
                "sha256": _sha256(payload),
                "size_bytes": len(payload),
            }
        )

    raw_snapshots: list[dict[str, Any]] = []
    for relative_path in _selected_raw_paths():
        artifact = _validated_file(relative_path)
        payload = artifact.read_bytes()
        raw_snapshots.append(
            {
                "path": relative_path,
                "sha256": _sha256(payload),
                "size_bytes": len(payload),
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": "POI_MPP_NOVELTY_PACKAGE_V1",
        "status": "NOVELTY_UNRESOLVED",
        "independent_challenge_status": "WAITING_EXTERNAL_INDEPENDENT_CHALLENGE",
        "cutoff_date": "2026-08-25",
        "scope_freeze": {
            "included": "1B-8B open-weight model + local EVM/Foundry + E1-E8 reproducible artifacts",
            "deferred": "70B/MoE, confidential GPU/TEE, and production-grade dispute VM",
        },
        "known_item_recovery": {
            "CommitLLM": "RECOVERED",
            "opML": "RECOVERED",
            "zkGPT": "RECOVERED",
            "EigenAI": "RECOVERED",
        },
        "package_input_count": len(package_inputs),
        "package_inputs": package_inputs,
        "raw_snapshot_count": len(raw_snapshots),
        "raw_snapshots": raw_snapshots,
        "authority_boundary": (
            "This package records a bounded primary search only. It does not prove universal novelty, "
            "close patents or standards exhaustively, or satisfy the required differently owned independent challenge."
        ),
    }
    manifest["self_digest"] = _sha256(_canonical_bytes(manifest))
    return manifest


def _serialized_manifest() -> bytes:
    return (json.dumps(build_manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


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
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    expected = _serialized_manifest()
    output = args.output.resolve()
    if args.check:
        if not output.is_file() or output.read_bytes() != expected:
            print(f"novelty package is stale or non-canonical: {output}", file=sys.stderr)
            return 1
        print(output)
        return 0
    _write_atomic(output, expected)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
