#!/usr/bin/env python3
"""Build the deterministic, unsigned external-reproduction input manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "paper_artifacts"
    / "final"
    / "external_reproduction"
    / "EXTERNAL_REPRODUCTION_MANIFEST.json"
)

EXACT_INPUTS = (
    "Makefile",
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "publication/artifact_manifest.json",
    "publication/tables/claim_matrix.json",
    "publication/tables/omissions.json",
    "scripts/reproduce.py",
    "scripts/report_all.py",
    "scripts/verify_bundle.py",
    "scripts/build_paper_figures.py",
    "scripts/build_paper_docx.js",
    "scripts/build_external_reproduction_package.py",
    "scripts/build_novelty_package.py",
    "docs/paper_artifacts/final/manuscript/POI_SUBMISSION_MANUSCRIPT.md",
    "docs/paper_artifacts/final/review/E1_E2_CLAIM_NARROWING_AUDIT.md",
    "docs/paper_artifacts/final/review/FIGURE_TABLE_FIDELITY_LEDGER.csv",
    "docs/paper_artifacts/final/review/FIGURE_TABLE_INTEGRITY_QA.md",
    "docs/paper_artifacts/final/review/figure_table_external_review_record.schema.json",
    "docs/paper_artifacts/final/novelty/README.md",
    "docs/paper_artifacts/final/novelty/NOVELTY_CASE.md",
    "docs/paper_artifacts/final/novelty/SEARCH_QUERIES.md",
    "docs/paper_artifacts/final/novelty/screening_ledger.csv",
    "docs/paper_artifacts/final/novelty/closest_predecessor_matrix.csv",
    "docs/paper_artifacts/final/novelty/citation_chaining.csv",
    "docs/paper_artifacts/final/novelty/contradiction_ledger.csv",
    "docs/paper_artifacts/final/novelty/NOVELTY_MANIFEST.json",
    "docs/paper_artifacts/final/review/SUBMISSION_READINESS_VALIDATION.md",
    "docs/paper_artifacts/final/external_reproduction/README.md",
    "docs/paper_artifacts/final/external_reproduction/CLEAN_ROOM_PROTOCOL.md",
    "docs/paper_artifacts/final/external_reproduction/discrepancy_report.schema.json",
    "docs/paper_artifacts/final/external_reproduction/external_reproduction_attestation.schema.json",
)

GLOB_INPUTS = (
    "configs/confirmatory/*.yaml",
    "contracts/src/*.sol",
    "contracts/test/*.t.sol",
    "docs/algorithms/A*.md",
    "docs/paper_artifacts/final/tables/*.csv",
    "docs/paper_artifacts/final/tables/*.md",
    "docs/paper_artifacts/final/visuals_algorithms/F*.mmd",
    "experiments/e[1-8]_*.py",
    "src/poi_mpp/**/*.py",
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _selected_paths() -> tuple[str, ...]:
    tracked_process = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    tracked_paths = {
        path
        for path in tracked_process.stdout.decode("utf-8").split("\0")
        if path
    }
    missing_exact = sorted(set(EXACT_INPUTS) - tracked_paths)
    if missing_exact:
        raise ValueError(
            "required reproduction inputs are not Git-tracked: "
            + ", ".join(missing_exact)
        )

    selected = set(EXACT_INPUTS)
    for pattern in GLOB_INPUTS:
        matches = sorted(REPO_ROOT.glob(pattern))
        if not matches:
            raise ValueError(f"reproduction input pattern matched no files: {pattern}")
        for match in matches:
            if match.is_file():
                relative_path = match.relative_to(REPO_ROOT).as_posix()
                if relative_path in tracked_paths:
                    selected.add(relative_path)
    return tuple(sorted(selected))


def _validated_file(relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe reproduction input path: {relative_path}")
    candidate = REPO_ROOT.joinpath(*pure.parts)
    if candidate.is_symlink():
        raise ValueError(f"reproduction input may not be a symlink: {relative_path}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except (FileNotFoundError, ValueError) as error:
        raise ValueError(
            f"reproduction input is missing or escapes repository root: {relative_path}"
        ) from error
    if not resolved.is_file():
        raise ValueError(f"reproduction input is not a file: {relative_path}")
    return resolved


def build_manifest() -> dict[str, Any]:
    inputs: list[dict[str, Any]] = []
    for relative_path in _selected_paths():
        artifact = _validated_file(relative_path)
        payload = artifact.read_bytes()
        inputs.append(
            {
                "path": relative_path,
                "sha256": _sha256(payload),
                "size_bytes": len(payload),
            }
        )

    publication_manifest = _validated_file("publication/artifact_manifest.json")
    manifest: dict[str, Any] = {
        "schema_version": "POI_MPP_EXTERNAL_REPRODUCTION_PACKAGE_V1",
        "status": "WAITING_EXTERNAL_REPRODUCTION",
        "independent_reproduction_complete": False,
        "canonical_publication_manifest_sha256": _sha256(publication_manifest.read_bytes()),
        "input_count": len(inputs),
        "inputs": inputs,
        "required_external_returns": [
            "completed discrepancy report",
            "external reproduction attestation bound to this manifest",
            "detached signature",
            "external allowed-signers file",
            "raw command logs and output hashes",
        ],
        "authority_boundary": (
            "This manifest packages inputs only. It does not prove execution, identity, "
            "independence, agreement, scientific validity, or publication readiness."
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
            print(f"external reproduction manifest is stale or non-canonical: {output}", file=sys.stderr)
            return 1
        print(output)
        return 0
    _write_atomic(output, expected)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
