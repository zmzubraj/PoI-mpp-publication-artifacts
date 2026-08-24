#!/usr/bin/env python3
"""Build a deterministic, unsigned external-review handoff manifest.

The manifest binds the exact manuscript, deliverables, evidence index, tables,
figures, algorithms, and request schemas that an external evaluator or reviewer
is asked to inspect. It never creates authority, a review verdict, or a
signature.
"""

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
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "paper_artifacts"
    / "final"
    / "external_review"
    / "EXTERNAL_REVIEW_HANDOFF_MANIFEST.json"
)

EXACT_INPUTS = (
    "Makefile",
    "package.json",
    "package-lock.json",
    "publication/artifact_manifest.json",
    "publication/tables/claim_matrix.json",
    "publication/tables/omissions.json",
    "docs/MAIN_RESULTS_TARGETS.md",
    "docs/PAPER_ARTIFACT_MAP.md",
    "docs/EXPERIMENT_ARTIFACT_MATRIX.md",
    "docs/paper_artifacts/final/manuscript/POI_SUBMISSION_MANUSCRIPT.md",
    "docs/paper_artifacts/final/manuscript/REFERENCES_AUDIT.md",
    "docs/paper_artifacts/final/deliverables/POI_MPP_EVIDENCE_BOUND_MANUSCRIPT.docx",
    "docs/paper_artifacts/final/deliverables/POI_MPP_EVIDENCE_BOUND_MANUSCRIPT.pdf",
    "docs/paper_artifacts/final/review/MPP_ALIGNMENT_AND_SCORECARD.md",
    "docs/paper_artifacts/final/review/MPP_ALIGNMENT_EXPLANATION_BN.md",
    "docs/paper_artifacts/final/review/PROVISIONAL_NOVELTY_AND_OVERALL_ASSESSMENT.md",
    "docs/paper_artifacts/final/review/SUBMISSION_READINESS_VALIDATION.md",
    "docs/paper_artifacts/final/review/TARGET_VENUE_PORTFOLIO.md",
    "docs/paper_artifacts/final/external_review/README.md",
    "docs/paper_artifacts/final/external_review/ACCOUNTABLE_AUTHOR_SUBMISSION_INPUT.md",
    "docs/paper_artifacts/final/external_review/E3_SEMANTIC_EVALUATOR_AUTHORITY_REQUEST_CHECKLIST.md",
    "docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_MANIFEST.json",
    "docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_PACKAGE.zip",
    "docs/paper_artifacts/final/external_review/E3_MISSING_ARTIFACTS_TRACKER.md",
    "docs/paper_artifacts/final/external_review/E3_STALE_SIGNATURE_HANDOFF_NOTE.md",
    "docs/paper_artifacts/final/external_review/INDEPENDENT_DOMAIN_EXPERT_REVIEW_PACKET.md",
    "docs/paper_artifacts/final/external_review/e3_result_attestation_record.schema.json",
    "docs/paper_artifacts/final/external_review/semantic_evaluator_authority_record.schema.json",
    "docs/paper_artifacts/final/external_review/independent_domain_expert_review_record.schema.json",
    "configs/confirmatory/e3.schema.yaml",
    "experiments/e3_semantic_eval.py",
    "docs/paper_artifacts/final/visuals_algorithms/A_final_paper_algorithms.md",
    "docs/paper_artifacts/final/visuals_algorithms/README.md",
    "docs/paper_artifacts/final/visuals_algorithms/rendered/quantitative/README.md",
    "scripts/build_paper_docx.js",
    "scripts/build_paper_figures.py",
    "scripts/build_e3_authority_request.py",
    "scripts/build_e3_authority_package.py",
    "scripts/build_external_review_handoff.py",
    "scripts/verify_e3_authority.py",
    "scripts/verify_e3_result_attestation.py",
    "src/poi_mpp/experiments/e3_semantic.py",
    "src/poi_mpp/reporting/e3_artifacts.py",
)

GLOB_INPUTS = (
    "docs/algorithms/A*.md",
    "docs/paper_artifacts/final/tables/*.csv",
    "docs/paper_artifacts/final/tables/*.md",
    "docs/paper_artifacts/final/visuals_algorithms/F*.mmd",
    "docs/paper_artifacts/final/visuals_algorithms/F*_caption.md",
    "docs/paper_artifacts/final/visuals_algorithms/rendered/F[1-4]_*.png",
    "docs/paper_artifacts/final/visuals_algorithms/rendered/quantitative/F5_*.png",
    "docs/paper_artifacts/final/visuals_algorithms/rendered/quantitative/F6_*.png",
    "docs/paper_artifacts/final/visuals_algorithms/rendered/quantitative/F8_*.png",
    "docs/paper_artifacts/final/visuals_algorithms/rendered/quantitative/F9_*.png",
    "docs/paper_artifacts/final/visuals_algorithms/rendered/quantitative/F10_*.png",
    "docs/paper_artifacts/final/visuals_algorithms/rendered/quantitative/F11_*.png",
    "docs/paper_artifacts/final/visuals_algorithms/rendered/quantitative/F12_*.png",
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _role(relative_path: str) -> str:
    if relative_path.startswith("publication/"):
        return "CANONICAL_PUBLICATION_EVIDENCE_INDEX"
    if "/deliverables/" in relative_path:
        return "RENDERED_MANUSCRIPT_DELIVERABLE"
    if "/manuscript/" in relative_path:
        return "MANUSCRIPT_SOURCE_OR_CITATION_AUDIT"
    if "/tables/" in relative_path:
        return "EDITABLE_MANUSCRIPT_TABLE"
    if "/visuals_algorithms/" in relative_path or relative_path.startswith("docs/algorithms/"):
        return "FIGURE_OR_ALGORITHM_SOURCE_OR_DERIVATIVE"
    if "/external_review/" in relative_path:
        return "UNSIGNED_EXTERNAL_REVIEW_REQUEST_OR_SCHEMA"
    if "/review/" in relative_path:
        return "DEVELOPMENTAL_REVIEW_CONTEXT"
    if relative_path.startswith("scripts/"):
        return "REPRODUCIBILITY_GENERATOR"
    return "CLAIM_AND_ARTIFACT_MAPPING"


def _selected_paths() -> tuple[str, ...]:
    selected = set(EXACT_INPUTS)
    for pattern in GLOB_INPUTS:
        matches = sorted(REPO_ROOT.glob(pattern))
        if not matches:
            raise ValueError(f"handoff input pattern matched no files: {pattern}")
        for match in matches:
            selected.add(match.relative_to(REPO_ROOT).as_posix())
    return tuple(sorted(selected))


def _validated_file(relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe handoff input path: {relative_path}")
    candidate = REPO_ROOT.joinpath(*pure.parts)
    if candidate.is_symlink():
        raise ValueError(f"handoff input may not be a symlink: {relative_path}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except (FileNotFoundError, ValueError) as error:
        raise ValueError(f"handoff input is missing or escapes repository root: {relative_path}") from error
    if not resolved.is_file():
        raise ValueError(f"handoff input is not a file: {relative_path}")
    return resolved


def build_manifest() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for relative_path in _selected_paths():
        artifact = _validated_file(relative_path)
        payload = artifact.read_bytes()
        entries.append(
            {
                "path": relative_path,
                "role": _role(relative_path),
                "sha256": _sha256(payload),
                "size_bytes": len(payload),
            }
        )

    publication_manifest = _validated_file("publication/artifact_manifest.json")
    manifest: dict[str, Any] = {
        "schema_version": "POI_MPP_EXTERNAL_REVIEW_HANDOFF_V1",
        "status": "UNSIGNED_REVIEW_INPUT_ONLY",
        "canonical_publication_manifest_sha256": _sha256(publication_manifest.read_bytes()),
        "review_input_count": len(entries),
        "review_inputs": entries,
        "external_gates": {
            "e3_semantic_evaluator_authority": "WAITING_EXTERNAL",
            "independent_domain_expert_review": "WAITING_EXTERNAL",
            "publication_freeze_sentinel": "BLOCKED_UNTIL_EXTERNAL_GATES_CLOSE",
        },
        "authority_boundary": (
            "This manifest binds review inputs only; it does not create evaluator authority, "
            "independent review, a signature, or publication readiness."
        ),
    }
    manifest["self_digest"] = _sha256(_canonical_bytes(manifest))
    return manifest


def _serialized_manifest() -> bytes:
    return (json.dumps(build_manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


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
    parser.add_argument("--check", action="store_true", help="Fail unless output exactly matches current inputs")
    args = parser.parse_args()
    expected = _serialized_manifest()
    output = args.output.resolve()
    if args.check:
        if not output.is_file() or output.read_bytes() != expected:
            print(f"external review handoff is stale or non-canonical: {output}", file=sys.stderr)
            return 1
        print(output)
        return 0
    _write_atomic(output, expected)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
