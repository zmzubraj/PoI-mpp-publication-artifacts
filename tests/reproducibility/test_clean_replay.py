from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
REPRODUCE = REPO_ROOT / "scripts" / "reproduce.py"
VERIFY_BUNDLE = REPO_ROOT / "scripts" / "verify_bundle.py"


def _run_python(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON), *argv],
        cwd=str(cwd or REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _claim_row(
    *,
    claim_id: str = "C1",
    completeness: str = "COMPLETE",
    disposition: str = "SUPPORTED",
    required_artifacts: tuple[str, ...] = ("T6", "F5"),
    present_artifacts: tuple[str, ...] = ("T6", "F5"),
) -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "completeness": completeness,
        "disposition": disposition,
        "required_artifacts": list(required_artifacts),
        "present_artifacts": list(present_artifacts),
        "paper_language_status": "MATCHES_EVIDENCE",
        "maturity": "REAL_MODEL_EXECUTION",
    }


def _candidate_manifest(
    candidate_root: Path,
    *,
    completeness: str = "INCOMPLETE",
    blockers: list[str] | None = None,
    manual_review_status: str = "MISSING",
    include_sentinel: bool = False,
    claim_rows: list[dict[str, object]] | None = None,
) -> Path:
    report_path = candidate_root / "verification_report.json"
    claim_matrix_path = candidate_root / "claim_support_matrix.json"
    manifest = {
        "schema_version": "POI_MPP_FREEZE_BUNDLE_V1",
        "bundle_kind": "candidate",
        "run_id": "fixture-run",
        "repo_root": str(REPO_ROOT),
        "report_relative_path": report_path.name,
        "claim_matrix_relative_path": claim_matrix_path.name,
        "publication_report_relative_path": "publication/artifact_manifest.json",
        "manual_review_relative_path": "manual_review.json",
        "completeness": completeness,
        "claim_support_overall": "INCONCLUSIVE",
        "blockers": blockers
        if blockers is not None
        else [
            "missing experiment evidence: E1",
            "manual scientific review record is absent",
        ],
        "required_experiments": [f"E{index}" for index in range(1, 9)],
        "experiments": {
            f"E{index}": {
                "status": "MISSING" if index != 7 else "COMPLETE",
                "required_artifacts": [],
                "present_artifacts": [],
            }
            for index in range(1, 9)
        },
        "manual_review": {
            "status": manual_review_status,
            "reviewer_identity": None,
        },
        "sentinel_present": include_sentinel,
        "frozen_manifest_relative_path": None,
        "tool_versions": {
            "python": sys.version.split()[0],
        },
        "argv_contract": {
            "report_all_build": [
                str(PYTHON),
                "scripts/report_all.py",
                "build",
                "--spec",
                "<SPEC>",
            ],
        },
    }
    _write_json(candidate_root / "manifest.json", manifest)
    _write_json(report_path, manifest)
    _write_json(
        claim_matrix_path,
        {
            "schema_version": "POI_MPP_CLAIM_SUPPORT_MATRIX_V1",
            "claims": claim_rows or [_claim_row()],
        },
    )
    _write_json(candidate_root / "manual_review.json", {"schema_version": "POI_MPP_MANUAL_REVIEW_V1", "status": manual_review_status})
    publication_dir = candidate_root / "publication"
    publication_dir.mkdir(parents=True, exist_ok=True)
    _write_json(publication_dir / "artifact_manifest.json", {"schema_version": "TEST_ONLY_NON_EVIDENCE"})
    if include_sentinel:
        (candidate_root / "MPP_ARTIFACT_COMPLETE").write_text("fixture-run\n", encoding="utf-8")
    return candidate_root / "manifest.json"


def test_reproduce_current_workspace_is_incomplete_and_writes_no_frozen_sentinel() -> None:
    completed = _run_python(str(REPRODUCE))
    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "INCOMPLETE"
    candidate_root = REPO_ROOT / payload["candidate_relative_path"]
    assert candidate_root.is_dir()
    manifest = _read_json(candidate_root / "manifest.json")
    assert manifest["completeness"] == "INCOMPLETE"
    blockers = "\n".join(str(item) for item in manifest["blockers"])
    assert "E1" in blockers
    assert "WAITING_LOCAL_MODEL_ARTIFACT" in blockers
    assert "WAITING_EXTERNAL_EVALUATOR_AUTHORITY" in blockers
    assert "manual scientific review record is absent" in blockers
    assert not any((REPO_ROOT / "results" / "frozen").glob("*/MPP_ARTIFACT_COMPLETE"))


def test_verify_bundle_preserves_negative_claims_when_bundle_is_complete(tmp_path: Path) -> None:
    candidate_root = tmp_path / "candidate"
    _candidate_manifest(
        candidate_root,
        completeness="COMPLETE",
        blockers=[],
        manual_review_status="COMPLETE",
        claim_rows=[
            _claim_row(disposition="NOT_SUPPORTED"),
        ],
    )
    manual_review = {
        "schema_version": "POI_MPP_MANUAL_REVIEW_V1",
        "status": "COMPLETE",
        "reviewer_identity": "independent-reviewer",
        "review_basis": "independent-human-review",
        "review_date": "2026-08-22",
        "reviewed_artifact_hashes": {"claim_support_matrix.json": "deadbeef"},
        "checks": {
            "denominator": True,
            "interval": True,
            "negative_results": True,
            "simulation_labeling": True,
            "editability": True,
            "accessibility": True,
            "claim_language": True,
        },
    }
    _write_json(candidate_root / "manual_review.json", manual_review)
    completed = _run_python(str(VERIFY_BUNDLE), "--bundle-root", str(candidate_root))
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["completeness"] == "COMPLETE"
    assert payload["claims"]["C1"] == "NOT_SUPPORTED"


def test_verify_bundle_rejects_missing_manual_review(tmp_path: Path) -> None:
    candidate_root = tmp_path / "candidate"
    _candidate_manifest(candidate_root, completeness="COMPLETE", blockers=[], manual_review_status="MISSING")
    completed = _run_python(str(VERIFY_BUNDLE), "--bundle-root", str(candidate_root))
    assert completed.returncode != 0
    assert "manual scientific review record is absent" in completed.stdout


def test_verify_bundle_rejects_synthetic_substitution_and_path_escape(tmp_path: Path) -> None:
    candidate_root = tmp_path / "candidate"
    _candidate_manifest(candidate_root, completeness="COMPLETE", blockers=[], manual_review_status="COMPLETE")
    manifest = _read_json(candidate_root / "manifest.json")
    manifest["experiments"]["E8"]["status"] = "COMPLETE"
    manifest["experiments"]["E8"]["origin"] = "SYNTHETIC_NON_EVIDENCE"
    _write_json(candidate_root / "manifest.json", manifest)
    completed = _run_python(str(VERIFY_BUNDLE), "--bundle-root", str(candidate_root))
    assert completed.returncode != 0
    assert "synthetic" in completed.stdout.lower()

    escaped_root = tmp_path / "escaped"
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped_root.symlink_to(outside, target_is_directory=True)
    completed = _run_python(str(VERIFY_BUNDLE), "--bundle-root", str(escaped_root))
    assert completed.returncode != 0
    assert "symlink" in completed.stdout.lower() or "path" in completed.stdout.lower()


def test_reproduce_candidate_report_is_deterministic_and_argv_is_frozen(tmp_path: Path) -> None:
    env = os.environ.copy()
    run_root = tmp_path / "repo-copy"
    shutil.copytree(REPO_ROOT, run_root, dirs_exist_ok=True)

    first = subprocess.run(
        [str(PYTHON), str(run_root / "scripts" / "reproduce.py"), "--mode", "candidate-only"],
        cwd=str(run_root),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    second = subprocess.run(
        [str(PYTHON), str(run_root / "scripts" / "reproduce.py"), "--mode", "candidate-only"],
        cwd=str(run_root),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert first.returncode == second.returncode
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload == second_payload
    manifest = _read_json(run_root / first_payload["candidate_relative_path"] / "manifest.json")
    assert manifest["argv_contract"]["report_all_build"][1:] == [
        "scripts/report_all.py",
        "build",
        "--spec",
        "<SPEC>",
    ]


def test_verify_bundle_refuses_existing_frozen_target_and_atomic_promotion_failure(tmp_path: Path) -> None:
    candidate_root = tmp_path / "candidate"
    frozen_root = tmp_path / "frozen"
    target_root = frozen_root / "fixture-run"
    _candidate_manifest(candidate_root, completeness="COMPLETE", blockers=[], manual_review_status="COMPLETE")
    _write_json(
        candidate_root / "manual_review.json",
        {
            "schema_version": "POI_MPP_MANUAL_REVIEW_V1",
            "status": "COMPLETE",
            "reviewer_identity": "independent-reviewer",
            "review_basis": "independent-human-review",
            "review_date": "2026-08-22",
            "reviewed_artifact_hashes": {"claim_support_matrix.json": "deadbeef"},
            "checks": {
                "denominator": True,
                "interval": True,
                "negative_results": True,
                "simulation_labeling": True,
                "editability": True,
                "accessibility": True,
                "claim_language": True,
            },
        },
    )
    target_root.mkdir(parents=True)
    completed = _run_python(
        str(VERIFY_BUNDLE),
        "--bundle-root",
        str(candidate_root),
        "--promote-to-frozen",
        "--frozen-root",
        str(frozen_root),
    )
    assert completed.returncode != 0
    assert "already exists" in completed.stdout

    shutil.rmtree(target_root)
    completed = _run_python(
        str(VERIFY_BUNDLE),
        "--bundle-root",
        str(candidate_root),
        "--promote-to-frozen",
        "--frozen-root",
        str(frozen_root),
        "--simulate-promotion-failure",
    )
    assert completed.returncode != 0
    assert not target_root.exists()
