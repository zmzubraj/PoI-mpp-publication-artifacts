#!/usr/bin/env python3
"""Build the deterministic unsigned pre-execution authority request for E3.

The output fixes the exact E3 request scope and the repository inputs shown to
an external evaluator. It is not an authority record, an execution result, or
a post-execution attestation.
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
    / "E3_AUTHORITY_REQUEST_MANIFEST.json"
)

REQUEST_INPUTS = (
    "Makefile",
    "docs/EXPERIMENT_PLAN.md",
    "docs/EXPERIMENT_ARTIFACT_MATRIX.md",
    "docs/PAPER_ARTIFACT_MAP.md",
    "docs/MAIN_RESULTS_TARGETS.md",
    "docs/paper_artifacts/final/manuscript/POI_SUBMISSION_MANUSCRIPT.md",
    "docs/paper_artifacts/final/tables/T4_experiment_design_and_current_status.md",
    "docs/paper_artifacts/final/tables/T7_limitations_and_nonclaims.md",
    "docs/paper_artifacts/final/external_review/E3_SEMANTIC_EVALUATOR_AUTHORITY_REQUEST_CHECKLIST.md",
    "docs/paper_artifacts/final/external_review/e3_result_attestation_record.schema.json",
    "docs/paper_artifacts/final/external_review/semantic_evaluator_authority_record.schema.json",
    "configs/confirmatory/e3.schema.yaml",
    "experiments/e3_semantic_eval.py",
    "publication/artifact_manifest.json",
    "publication/tables/claim_matrix.json",
    "publication/tables/omissions.json",
    "scripts/build_e3_authority_request.py",
    "scripts/build_e3_authority_package.py",
    "scripts/verify_e3_authority.py",
    "scripts/verify_e3_result_attestation.py",
    "src/poi_mpp/experiments/e3_semantic.py",
    "src/poi_mpp/reporting/e3_artifacts.py",
)

REQUESTED_SCOPE: dict[str, Any] = {
    "experiment_id": "E3",
    "claim_id": "C3",
    "task_class": "GROUNDED_SEMANTIC_ASSURANCE",
    "metric_scope": ["ABSTAIN", "FAR", "FRR", "calibration", "coverage"],
    "artifact_scope": ["F7", "RAW_E3_EXECUTION", "T4", "T8"],
    "evidence_origin": "REAL_MODEL_EXECUTION",
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validated_repo_file(relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe E3 request input path: {relative_path}")
    candidate = REPO_ROOT.joinpath(*pure.parts)
    if candidate.is_symlink():
        raise ValueError(f"E3 request input may not be a symlink: {relative_path}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except (FileNotFoundError, ValueError) as error:
        raise ValueError(f"E3 request input is missing or escapes repository root: {relative_path}") from error
    if not resolved.is_file():
        raise ValueError(f"E3 request input is not a file: {relative_path}")
    return resolved


def build_manifest() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for relative_path in sorted(REQUEST_INPUTS):
        artifact = _validated_repo_file(relative_path)
        payload = artifact.read_bytes()
        entries.append(
            {
                "path": relative_path,
                "sha256": _sha256(payload),
                "size_bytes": len(payload),
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": "POI_MPP_E3_AUTHORITY_REQUEST_V1",
        "status": "UNSIGNED_PRE_EXECUTION_SCOPE_REQUEST",
        "current_e3_status": "NOT_SUPPORTED_SIGNED_REVISION_CURRENT_CHAIN_DRIFT",
        "requested_scope": REQUESTED_SCOPE,
        "requested_scope_digest": _sha256(_canonical_bytes(REQUESTED_SCOPE)),
        "request_input_count": len(entries),
        "request_inputs": entries,
        "allowed_authority_decisions": ["APPROVED", "LIMITED_SCOPE"],
        "result_attestation_status": "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION",
        "authority_boundary": (
            "This unsigned manifest requests external pre-execution scope authorization for E3 only. "
            "It grants no authority and contains no evaluator identity, decision, signature, or result."
        ),
        "post_execution_boundary": (
            "Generated E3 evidence can only be bound by a separate post-execution result attestation "
            "created after authorized execution; this request cannot attest to future artifacts."
        ),
    }
    manifest["self_digest"] = _sha256(_canonical_bytes(manifest))
    return manifest


def serialized_manifest() -> bytes:
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
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail unless the output matches current inputs")
    args = parser.parse_args()
    expected = serialized_manifest()
    output = args.output.resolve()
    if args.check:
        if not output.is_file() or output.read_bytes() != expected:
            print(f"E3 authority request is stale or non-canonical: {output}", file=sys.stderr)
            return 1
        print(output)
        return 0
    _write_atomic(output, expected)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
