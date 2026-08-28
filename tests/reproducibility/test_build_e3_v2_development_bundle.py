from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

from tests.experiments.e3_v2_bundle_fixtures import (
    canonical_json_bytes,
    sha256_bytes,
    write_development_bundle,
)
from poi_mpp.experiments.e3_development import validate_e3_phase3_development_bundle_materials


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_e3_v2_development_bundle.py"

_POLICY_BINDING_KEYS = (
    "claim_spec_hash",
    "prompt_template_hash",
    "output_schema_hash",
    "contradiction_policy_hash",
    "error_recovery_policy_hash",
    "error_taxonomy_review_hash",
)


def _canonical_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    return sha256_bytes(canonical_json_bytes(unsigned))


def _run_builder(bundle_root: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(BUILD_SCRIPT),
            "--bundle-root",
            str(bundle_root),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )


def test_development_bundle_report_binds_material_hashes_deterministically(tmp_path: Path) -> None:
    bundle_root = write_development_bundle(tmp_path / "POI_E3_V2_DEVELOPMENT")
    output = tmp_path / "development_bundle_report.json"

    completed = _run_builder(bundle_root, output)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))

    materials = validate_e3_phase3_development_bundle_materials(bundle_root=bundle_root)
    policy_bindings = {key: materials.policy_input_file_hashes[key] for key in _POLICY_BINDING_KEYS}

    assert report["schema_version"] == "POI_MPP_E3_V2_DEVELOPMENT_BUNDLE_REPORT_V1"
    assert report["status"] == "MATERIALS_VALIDATED_WAITING_AUTHORITY"
    assert report["development_bundle_manifest_sha256"] == materials.bundle_manifest_sha256
    assert report["development_dataset_manifest_hash"] == materials.dataset_manifest.dataset_manifest_hash()
    assert (
        report["development_model_manifest_hash"]
        == materials.policy_input_file_hashes["model_manifest_hash"]
    )
    assert (
        report["development_decode_policy_hash"]
        == materials.policy_input_file_hashes["deterministic_decode_policy_hash"]
    )
    assert (
        report["development_environment_manifest_hash"]
        == materials.policy_input_file_hashes["runtime_environment_hash"]
    )
    assert report["development_policy_inputs_digest"] == sha256_bytes(
        canonical_json_bytes(policy_bindings)
    )
    assert report["policy_input_file_hashes"] == dict(materials.policy_input_file_hashes)
    assert report["dataset"] == {
        "dataset_id": "e3-v2-development-test-only",
        "record_count": 120,
        "decision_counts": {"ACCEPT": 50, "ABSTAIN": 20, "REJECT": 50},
    }
    assert report["model"]["model_id"] == "qwen25-1p5b-test-only"
    assert report["model"]["revision"] == "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
    assert report["model"]["parameter_scale"] == "1.5B"
    assert report["model"]["quantization"] == "none"
    assert report["decode_policy"] == {"seed": 7, "max_new_tokens": 96}
    assert report["owner_declaration"] == {
        "owner_id": "owner-test-only",
        "accountable_reviewer_id": "reviewer-test-only",
    }
    assert report["self_digest"] == _canonical_digest(report)

    second = tmp_path / "development_bundle_report_second.json"
    completed_second = _run_builder(bundle_root, second)
    assert completed_second.returncode == 0, completed_second.stderr
    assert second.read_bytes() == output.read_bytes()


def test_development_bundle_report_fails_closed_on_missing_bundle(tmp_path: Path) -> None:
    completed = _run_builder(tmp_path / "missing-bundle", tmp_path / "report.json")
    assert completed.returncode != 0
    assert "E3-v2 development bundle report failed" in completed.stderr
    assert not (tmp_path / "report.json").exists()


def test_development_bundle_report_rejects_repository_local_bundle_root(tmp_path: Path) -> None:
    bundle_root = write_development_bundle(REPO_ROOT / "tmp-e3-v2-report-test-only")
    try:
        completed = _run_builder(bundle_root, tmp_path / "report.json")
        assert completed.returncode != 0
        assert "bundle root must live outside the repository" in completed.stderr
    finally:
        shutil.rmtree(bundle_root, ignore_errors=True)


def test_development_bundle_report_rejects_synthetic_dataset(tmp_path: Path) -> None:
    bundle_root = write_development_bundle(
        tmp_path / "POI_E3_V2_DEVELOPMENT",
        dataset_origin="SYNTHETIC_NON_EVIDENCE",
    )
    completed = _run_builder(bundle_root, tmp_path / "report.json")
    assert completed.returncode != 0
    assert "synthetic non-evidence cannot enter development" in completed.stderr


def test_development_bundle_report_rejects_repository_local_output(tmp_path: Path) -> None:
    bundle_root = write_development_bundle(tmp_path / "POI_E3_V2_DEVELOPMENT")
    inside_repo = REPO_ROOT / "tmp-e3-v2-report-output-test-only.json"
    try:
        completed = _run_builder(bundle_root, inside_repo)
        assert completed.returncode != 0
        assert "must live outside the repository" in completed.stderr
        assert not inside_repo.exists()
    finally:
        inside_repo.unlink(missing_ok=True)


def test_development_bundle_report_rejects_tampered_bundle_member(tmp_path: Path) -> None:
    bundle_root = write_development_bundle(tmp_path / "POI_E3_V2_DEVELOPMENT")
    target = bundle_root / "policy" / "claim_spec.json"
    target.write_bytes(target.read_bytes() + b" ")
    completed = _run_builder(bundle_root, tmp_path / "report.json")
    assert completed.returncode != 0
    assert "hash mismatch" in completed.stderr
