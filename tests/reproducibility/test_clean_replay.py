from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
REPRODUCE = REPO_ROOT / "scripts" / "reproduce.py"
VERIFY_BUNDLE = REPO_ROOT / "scripts" / "verify_bundle.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import verify_bundle as verify_module  # noqa: E402


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


def _digest(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _complete_structural_experiments() -> dict[str, dict[str, object]]:
    mapping = {
        "E1": ("T6", "F5"),
        "E2": ("T7", "F6"),
        "E3": ("T4", "T8", "F7"),
        "E4": ("T9", "F8"),
        "E5": ("T10",),
        "E6": ("T11", "F9", "F10"),
        "E7": ("T12", "F12"),
        "E8": ("T13", "F11"),
    }
    origins = {
        "E3": "REAL_MODEL_EXECUTION",
        "E7": "FOUNDRY_MEASUREMENT",
        "E8": "REPRODUCIBLE_SIMULATION",
    }
    return {
        experiment_id: {
            "status": "COMPLETE",
            "required_artifacts": list(required_artifacts),
            "present_artifacts": list(required_artifacts),
            "origin": origins.get(experiment_id, "REAL_MODEL_EXECUTION"),
        }
        for experiment_id, required_artifacts in mapping.items()
    }


def _complete_structural_claims(*, first_disposition: str = "SUPPORTED") -> list[dict[str, object]]:
    mapping = {
        "C1": ("T6", "F5"),
        "C2": ("T7", "F6"),
        "C3": ("T4", "T8", "F7"),
        "C4": ("T9", "F8"),
        "C5": ("T10",),
        "C6": ("T11", "F9", "F10"),
        "C7": ("T12", "F12"),
        "C8": ("T13", "F11"),
    }
    claims: list[dict[str, object]] = []
    for index, (claim_id, required_artifacts) in enumerate(mapping.items()):
        claims.append(
            {
                "claim_id": claim_id,
                "completeness": "COMPLETE",
                "disposition": first_disposition if index == 0 else "SUPPORTED",
                "required_artifacts": list(required_artifacts),
                "present_artifacts": list(required_artifacts),
                "paper_language_status": "MATCHES_EVIDENCE",
                "maturity": "REAL_MODEL_EXECUTION" if claim_id != "C8" else "REPRODUCIBLE_SIMULATION",
            }
        )
    return claims


def _write_structural_report(candidate_root: Path) -> None:
    summary = verify_module.verify_bundle_structure(candidate_root)
    _write_json(candidate_root / "verification_report.json", summary.model_dump(mode="json"))
    summary = verify_module.verify_bundle_structure(candidate_root)
    _write_json(candidate_root / "verification_report.json", summary.model_dump(mode="json"))


def _build_test_only_structural_candidate(
    candidate_root: Path,
    *,
    first_disposition: str = "SUPPORTED",
    include_extra_file: bool = False,
) -> Path:
    _write_json(candidate_root / "inputs" / "report_spec.json", {"schema_version": "TEST_ONLY_NON_EVIDENCE"})
    _write_json(candidate_root / "inputs" / "task21_local_config.json", {"schema_version": "TEST_ONLY_NON_EVIDENCE"})
    _write_json(candidate_root / "task21" / "task21_blockers.json", {"schema_version": "TEST_ONLY_NON_EVIDENCE"})
    _write_json(
        candidate_root / "manual_review.json",
        {
            "schema_version": "POI_MPP_MANUAL_REVIEW_V1",
            "status": "COMPLETE",
            "reviewer_identity": "independent-reviewer@example.com",
            "review_basis": "external-human-review",
            "review_date": "2026-08-22",
            "reviewed_artifact_hashes": {},
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
    _write_json(
        candidate_root / "claim_support_matrix.json",
        {
            "schema_version": "POI_MPP_CLAIM_SUPPORT_MATRIX_V1",
            "claims": _complete_structural_claims(first_disposition=first_disposition),
        },
    )
    _write_json(candidate_root / "publication" / "artifact_manifest.json", {"schema_version": "TEST_ONLY_NON_EVIDENCE"})
    _write_json(
        candidate_root / "manifest.json",
        {
            "schema_version": "POI_MPP_FREEZE_BUNDLE_V1",
            "bundle_kind": "candidate",
            "run_id": "fixture-run",
            "repo_root": str(REPO_ROOT),
            "report_relative_path": "verification_report.json",
            "claim_matrix_relative_path": "claim_support_matrix.json",
            "publication_report_relative_path": "publication/artifact_manifest.json",
            "manual_review_relative_path": "manual_review.json",
            "authoritative_inputs": {
                "report_spec_relative_path": "inputs/report_spec.json",
                "task21_config_relative_path": "inputs/task21_local_config.json",
                "task21_blocker_relative_path": "task21/task21_blockers.json",
            },
            "completeness": "COMPLETE",
            "claim_support_overall": "INCONCLUSIVE",
            "blockers": [],
            "required_experiments": [f"E{index}" for index in range(1, 9)],
            "experiments": _complete_structural_experiments(),
            "manual_review": {
                "status": "COMPLETE",
                "reviewer_identity": "independent-reviewer@example.com",
                "review_date": "2026-08-22",
            },
            "sentinel_present": False,
            "frozen_manifest_relative_path": None,
            "tool_versions": {"python": sys.version.split()[0]},
            "argv_contract": {
                "report_all_build": [str(PYTHON), "scripts/report_all.py", "build", "--spec", "<SPEC>"],
            },
        },
    )
    _write_json(candidate_root / "verification_report.json", verify_module.VerificationSummary(
        run_id="fixture-run",
        completeness="INCOMPLETE",
        blockers=(),
        claims={},
        sentinel_present=False,
        manual_review_authenticated=False,
    ).model_dump(mode="json"))
    _write_structural_report(candidate_root)
    if include_extra_file:
        (candidate_root / "reviewer-extra.txt").write_text("extra\n", encoding="utf-8")
    return candidate_root


def test_reproduce_current_workspace_is_incomplete_and_writes_no_frozen_sentinel() -> None:
    completed = _run_python(str(REPRODUCE))
    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["status"] == "INCOMPLETE"
    candidate_root = REPO_ROOT / payload["candidate_relative_path"]
    assert candidate_root.is_dir()
    manifest = _read_json(candidate_root / "manifest.json")
    assert manifest["completeness"] == "INCOMPLETE"
    blockers = "\n".join(str(item) for item in payload["blockers"])
    assert "WAITING_LOCAL_MODEL_ARTIFACT" in blockers
    assert "WAITING_EXTERNAL_EVALUATOR_AUTHORITY" in blockers
    assert "manual scientific review record is absent" in blockers
    assert "results/tmp/candidates" in payload["candidate_relative_path"]
    assert not any((REPO_ROOT / "results" / "frozen").glob("*/MPP_ARTIFACT_COMPLETE"))


def test_structural_checker_preserves_negative_claims_when_complete(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate", first_disposition="NOT_SUPPORTED")
    summary = verify_module.verify_bundle_structure(candidate_root)
    assert summary.completeness == "COMPLETE"
    assert summary.claims["C1"] == "NOT_SUPPORTED"


def test_production_verifier_rejects_test_only_promotion_and_forged_complete(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    frozen_root = tmp_path / "frozen"
    completed = _run_python(
        str(VERIFY_BUNDLE),
        "--bundle-root",
        str(candidate_root),
        "--promote-to-frozen",
        "--frozen-root",
        str(frozen_root),
    )
    assert completed.returncode != 0
    assert "TEST_ONLY_NON_EVIDENCE" in completed.stdout
    assert not any(frozen_root.glob("*/MPP_ARTIFACT_COMPLETE"))


def test_structural_checker_rejects_extra_file(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate", include_extra_file=True)
    summary = verify_module.verify_bundle_structure(candidate_root)
    assert summary.completeness == "INCOMPLETE"
    assert "unexpected files" in "\n".join(summary.blockers)


def test_production_verifier_rejects_unsigned_manual_review(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    loader = verify_module._load_bundle(candidate_root, allow_test_only=True)
    reasons, authenticated = verify_module._validate_manual_review(
        loader,
        allowed_signers_path=None,
        signature_path=None,
    )
    assert not authenticated
    assert "manual scientific review signature is absent" in "\n".join(reasons)


def test_production_verifier_rejects_task20_invalid_manifest(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    publication_manifest_path = candidate_root / "publication" / "artifact_manifest.json"
    _write_json(publication_manifest_path, {"schema_version": "POI_MPP_PUBLICATION_REPORT_MANIFEST_V3", "self_digest": "0" * 64})
    completed = _run_python(str(VERIFY_BUNDLE), "--bundle-root", str(candidate_root))
    assert completed.returncode != 0
    assert "artifact manifest" in completed.stdout.lower() or "schema_version" in completed.stdout.lower()


def test_verify_bundle_rejects_symlink_root_on_promotion(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    escaped_root = tmp_path / "escaped"
    escaped_root.symlink_to(candidate_root, target_is_directory=True)
    completed = _run_python(
        str(VERIFY_BUNDLE),
        "--bundle-root",
        str(escaped_root),
        "--promote-to-frozen",
        "--frozen-root",
        str(tmp_path / "frozen"),
    )
    assert completed.returncode != 0
    assert "symlink" in completed.stdout.lower() or "bundle root" in completed.stdout.lower()


def test_reproduce_candidate_report_is_deterministic_and_run_path_matches_returned_run_id() -> None:
    first = _run_python(str(REPRODUCE), "--mode", "candidate-only")
    second = _run_python(str(REPRODUCE), "--mode", "candidate-only")
    assert first.returncode == second.returncode
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload == second_payload
    run_id = first_payload["run_id"]
    assert first_payload["candidate_relative_path"] == f"results/tmp/candidates/{run_id}"
    assert (REPO_ROOT / first_payload["candidate_relative_path"]).is_dir()


def test_promote_bundle_refuses_existing_target_and_cleans_up_simulated_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    frozen_root = tmp_path / "frozen"
    target_root = frozen_root / "fixture-run"
    target_root.mkdir(parents=True)

    complete_summary = verify_module.VerificationSummary(
        run_id="fixture-run",
        completeness="COMPLETE",
        blockers=(),
        claims={"C1": "NOT_SUPPORTED"},
        sentinel_present=False,
        manual_review_authenticated=True,
    )

    monkeypatch.setattr(verify_module, "verify_bundle", lambda *args, **kwargs: complete_summary)

    with pytest.raises(verify_module.BundleVerificationError, match="already exists"):
        verify_module.promote_bundle(candidate_root, frozen_root)

    shutil.rmtree(target_root)
    with pytest.raises(verify_module.BundleVerificationError, match="simulated promotion failure"):
        verify_module.promote_bundle(candidate_root, frozen_root, simulate_failure=True)
    assert not target_root.exists()
