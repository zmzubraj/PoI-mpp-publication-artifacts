from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class BundleVerificationError(ValueError):
    def __init__(self, reasons: str | list[str] | tuple[str, ...]):
        if isinstance(reasons, str):
            reasons = [reasons]
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__("; ".join(self.reasons))


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManualReviewChecks(_FrozenModel):
    denominator: bool = False
    interval: bool = False
    negative_results: bool = False
    simulation_labeling: bool = False
    editability: bool = False
    accessibility: bool = False
    claim_language: bool = False


class ManualReviewRecord(_FrozenModel):
    schema_version: str
    status: str
    reviewer_identity: str | None = None
    review_basis: str | None = None
    review_date: str | None = None
    reviewed_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    checks: ManualReviewChecks | None = None


class ClaimSupportRow(_FrozenModel):
    claim_id: str
    completeness: str
    disposition: str
    required_artifacts: tuple[str, ...]
    present_artifacts: tuple[str, ...]
    paper_language_status: str
    maturity: str

    @field_validator("claim_id", "completeness", "disposition", "paper_language_status", "maturity")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("field must not be blank")
        return value


class ClaimSupportMatrix(_FrozenModel):
    schema_version: str
    claims: tuple[ClaimSupportRow, ...]

    @model_validator(mode="after")
    def _unique_claims(self) -> "ClaimSupportMatrix":
        claim_ids = [row.claim_id for row in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("duplicate claim ids are forbidden")
        return self


class ExperimentEntry(_FrozenModel):
    status: str
    required_artifacts: tuple[str, ...] = ()
    present_artifacts: tuple[str, ...] = ()
    origin: str | None = None


class BundleManifest(_FrozenModel):
    schema_version: str
    bundle_kind: str
    run_id: str
    repo_root: str
    report_relative_path: str
    claim_matrix_relative_path: str
    publication_report_relative_path: str
    manual_review_relative_path: str
    completeness: str
    claim_support_overall: str
    blockers: tuple[str, ...]
    required_experiments: tuple[str, ...]
    experiments: dict[str, ExperimentEntry]
    manual_review: dict[str, Any]
    sentinel_present: bool
    frozen_manifest_relative_path: str | None = None
    tool_versions: dict[str, str] = Field(default_factory=dict)
    argv_contract: dict[str, tuple[str, ...]]

    @field_validator(
        "report_relative_path",
        "claim_matrix_relative_path",
        "publication_report_relative_path",
        "manual_review_relative_path",
        mode="before",
    )
    @classmethod
    def _validate_relative_path(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("relative path must not be blank")
        if value.startswith("/") or "\\" in value:
            raise ValueError("relative path must be a canonical POSIX relative path")
        parts = PurePosixPath(value).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("relative path must not contain '.', '..', or empty parts")
        normalized = str(PurePosixPath(value))
        if normalized != value:
            raise ValueError("relative path must already be normalized")
        return value

    @model_validator(mode="after")
    def _validate_experiments(self) -> "BundleManifest":
        required = set(self.required_experiments)
        missing = sorted(required - set(self.experiments))
        if missing:
            raise ValueError(f"missing experiment entries: {', '.join(missing)}")
        return self


class VerificationSummary(_FrozenModel):
    run_id: str
    completeness: str
    blockers: tuple[str, ...]
    claims: dict[str, str]
    sentinel_present: bool


_SENTINEL = "MPP_ARTIFACT_COMPLETE"
_TEST_ONLY_SCHEMA = "TEST_ONLY_NON_EVIDENCE"


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _safe_path(path: Path) -> Path:
    current = path
    while True:
        try:
            metadata = os.lstat(current)
        except OSError as error:
            raise BundleVerificationError(f"unable to stat path component: {current}") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise BundleVerificationError(f"symlinked path component is forbidden: {current}")
        parent = current.parent
        if parent == current:
            break
        current = parent
    return path.resolve(strict=True)


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        resolved = _safe_path(path)
        if not resolved.is_file():
            raise BundleVerificationError(f"path is not a regular file: {path}")
        return json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise BundleVerificationError(f"invalid JSON: {path}") from error


def _resolve_relative(root: Path, relative_path: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        path.relative_to(root)
    except ValueError as error:
        raise BundleVerificationError(f"path escapes bundle root: {relative_path}") from error
    return path


def _load_bundle(bundle_root: Path) -> tuple[BundleManifest, ClaimSupportMatrix, ManualReviewRecord]:
    resolved_root = _safe_path(bundle_root)
    if not resolved_root.is_dir():
        raise BundleVerificationError(f"bundle root must be a directory: {bundle_root}")
    manifest = BundleManifest.model_validate(_safe_read_json(resolved_root / "manifest.json"))
    claim_matrix = ClaimSupportMatrix.model_validate(
        _safe_read_json(_resolve_relative(resolved_root, manifest.claim_matrix_relative_path))
    )
    manual_review = ManualReviewRecord.model_validate(
        _safe_read_json(_resolve_relative(resolved_root, manifest.manual_review_relative_path))
    )
    publication_manifest = _safe_read_json(
        _resolve_relative(resolved_root, manifest.publication_report_relative_path)
    )
    if publication_manifest.get("schema_version") != _TEST_ONLY_SCHEMA and "schema_version" not in publication_manifest:
        raise BundleVerificationError("publication report manifest is missing schema_version")
    return manifest, claim_matrix, manual_review


def _validate_manual_review(manual_review: ManualReviewRecord) -> tuple[str, ...]:
    if manual_review.status != "COMPLETE":
        return ("manual scientific review record is absent",)
    reasons: list[str] = []
    if not manual_review.reviewer_identity:
        reasons.append("manual review requires reviewer_identity")
    if not manual_review.review_basis:
        reasons.append("manual review requires review_basis")
    if not manual_review.review_date:
        reasons.append("manual review requires review_date")
    if manual_review.checks is None:
        reasons.append("manual review requires explicit checks")
    else:
        for key, passed in manual_review.checks.model_dump(mode="json").items():
            if not passed:
                reasons.append(f"manual review check failed: {key}")
    return tuple(reasons)


def verify_bundle(bundle_root: Path) -> VerificationSummary:
    manifest, claim_matrix, manual_review = _load_bundle(bundle_root)
    reasons: list[str] = list(manifest.blockers)
    reasons.extend(_validate_manual_review(manual_review))

    for experiment_id, experiment in sorted(manifest.experiments.items()):
        if experiment.origin == "SYNTHETIC_NON_EVIDENCE":
            reasons.append(f"{experiment_id} synthetic substitution is forbidden")

    claims: dict[str, str] = {}
    for row in claim_matrix.claims:
        claims[row.claim_id] = row.disposition
        if row.completeness != "COMPLETE":
            reasons.append(f"{row.claim_id} is {row.completeness}")
        missing_artifacts = sorted(set(row.required_artifacts) - set(row.present_artifacts))
        if missing_artifacts:
            reasons.append(f"{row.claim_id} missing artifacts: {', '.join(missing_artifacts)}")
        if row.paper_language_status != "MATCHES_EVIDENCE":
            reasons.append(f"{row.claim_id} paper language does not match evidence")

    sentinel_path = bundle_root / _SENTINEL
    sentinel_present = sentinel_path.exists()
    completeness = "COMPLETE" if not reasons else "INCOMPLETE"
    if completeness != "COMPLETE" and sentinel_present:
        reasons.append("sentinel present before verification completed")
        completeness = "INCOMPLETE"

    return VerificationSummary(
        run_id=manifest.run_id,
        completeness=completeness,
        blockers=tuple(dict.fromkeys(reasons)),
        claims=claims,
        sentinel_present=sentinel_present,
    )


def _copy_bundle(source_root: Path, target_root: Path) -> None:
    shutil.copytree(source_root, target_root)


def promote_bundle(bundle_root: Path, frozen_root: Path, *, simulate_failure: bool = False) -> Path:
    summary = verify_bundle(bundle_root)
    if summary.completeness != "COMPLETE":
        raise BundleVerificationError(summary.blockers)

    frozen_root.mkdir(parents=True, exist_ok=True)
    target_root = frozen_root / summary.run_id
    if target_root.exists():
        raise BundleVerificationError(f"frozen target already exists: {target_root}")

    staging_parent = Path(tempfile.mkdtemp(prefix=f".{summary.run_id}.", dir=str(frozen_root)))
    staging_root = staging_parent / summary.run_id
    try:
        _copy_bundle(bundle_root, staging_root)
        sentinel_path = staging_root / _SENTINEL
        if sentinel_path.exists():
            sentinel_path.unlink()
        if simulate_failure:
            raise BundleVerificationError("simulated promotion failure")
        os.replace(staging_root, target_root)
        sentinel_path = target_root / _SENTINEL
        sentinel_path.write_text(f"{summary.run_id}\n", encoding="utf-8")
        return target_root
    except Exception:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise
    finally:
        if staging_parent.exists():
            shutil.rmtree(staging_parent, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify or promote a Task 22 publication bundle candidate.")
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--promote-to-frozen", action="store_true")
    parser.add_argument("--frozen-root")
    parser.add_argument("--simulate-promotion-failure", action="store_true")
    args = parser.parse_args(argv)

    try:
        bundle_root = Path(args.bundle_root).resolve()
        summary = verify_bundle(bundle_root)
        payload: dict[str, object] = summary.model_dump(mode="json")
        if args.promote_to_frozen:
            if not args.frozen_root:
                raise BundleVerificationError("--frozen-root is required when promoting")
            target_root = promote_bundle(
                bundle_root,
                Path(args.frozen_root).resolve(),
                simulate_failure=args.simulate_promotion_failure,
            )
            payload["frozen_root"] = str(target_root)
        _print_json(payload)
        return 0 if summary.completeness == "COMPLETE" and not summary.blockers else 1
    except (BundleVerificationError, ValidationError) as error:
        reasons = error.reasons if isinstance(error, BundleVerificationError) else (str(error),)
        _print_json(
            {
                "completeness": "INCOMPLETE",
                "blockers": list(reasons),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
