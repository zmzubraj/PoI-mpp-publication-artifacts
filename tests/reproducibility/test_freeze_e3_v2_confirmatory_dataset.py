from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

from tests.experiments.e3_v2_bundle_fixtures import (
    canonical_json_bytes,
    sha256_bytes,
    write_confirmatory_bundle,
    write_external_development_manifest,
)
from poi_mpp.experiments.e3_confirmatory_freeze import (
    validate_e3_phase4_confirmatory_freeze_materials,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FREEZE_SCRIPT = REPO_ROOT / "scripts" / "freeze_e3_v2_confirmatory_dataset.py"


def _canonical_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    return sha256_bytes(canonical_json_bytes(unsigned))


def _run_freeze(
    bundle_root: Path, development_manifest: Path, output: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(FREEZE_SCRIPT),
            "--bundle-root",
            str(bundle_root),
            "--development-manifest",
            str(development_manifest),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )


def _write_materials(tmp_path: Path, **bundle_kwargs: object) -> tuple[Path, Path]:
    bundle_root = write_confirmatory_bundle(tmp_path / "POI_E3_V2_CONFIRMATORY", **bundle_kwargs)
    development_manifest = write_external_development_manifest(
        tmp_path / "development_dataset_manifest_v2.json"
    )
    return bundle_root, development_manifest


def test_freeze_lineage_report_binds_materials_and_stays_waiting_external(tmp_path: Path) -> None:
    bundle_root, development_manifest = _write_materials(tmp_path)
    output = tmp_path / "confirmatory_freeze_lineage.json"

    completed = _run_freeze(bundle_root, development_manifest, output)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))

    materials = validate_e3_phase4_confirmatory_freeze_materials(
        bundle_root=bundle_root, development_manifest_path=development_manifest
    )

    assert report["schema_version"] == "POI_MPP_E3_V2_CONFIRMATORY_FREEZE_LINEAGE_V1"
    assert report["status"] == "WAITING_EXTERNAL"
    assert report["reason"] == "materials_validated_authority_and_approval_required"
    assert report["missing_inputs"] == [
        "verified_external_authority_binding",
        "accountable_freeze_approval",
    ]
    assert report["material_lineage_hash"] == materials.material_lineage_hash
    assert report["lineage"] == {
        "bundle_manifest_sha256": materials.bundle_manifest_sha256,
        "dataset_manifest_hash": materials.dataset_manifest_hash,
        "development_manifest_hash": materials.development_manifest_hash,
        "annotation_ledger_sha256": materials.annotation_ledger_sha256,
        "annotation_agreement_sha256": materials.annotation_agreement_sha256,
        "adjudication_ledger_sha256": materials.adjudication_ledger_sha256,
        "license_privacy_ledger_sha256": materials.license_privacy_ledger_sha256,
    }
    assert report["decision_counts"] == {"ACCEPT": 200, "REJECT": 200, "ABSTAIN": 100}
    assert report["agreement_summary"] == {"numerator": 500, "denominator": 500, "rate": 1.0}
    assert report["dataset"] == {
        "dataset_id": "e3-v2-confirmatory-test-only",
        "record_count": 500,
    }
    assert report["self_digest"] == _canonical_digest(report)

    second = tmp_path / "confirmatory_freeze_lineage_second.json"
    completed_second = _run_freeze(bundle_root, development_manifest, second)
    assert completed_second.returncode == 0, completed_second.stderr
    assert second.read_bytes() == output.read_bytes()


def test_freeze_lineage_report_reconciles_disagreement_and_adjudication(tmp_path: Path) -> None:
    bundle_root, development_manifest = _write_materials(
        tmp_path, disagreement_record_ids=["e3v2-conf-007"]
    )
    output = tmp_path / "confirmatory_freeze_lineage.json"

    completed = _run_freeze(bundle_root, development_manifest, output)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["agreement_summary"] == {"numerator": 499, "denominator": 500, "rate": 0.998}


def test_freeze_lineage_report_fails_closed_on_missing_bundle(tmp_path: Path) -> None:
    development_manifest = write_external_development_manifest(
        tmp_path / "development_dataset_manifest_v2.json"
    )
    completed = _run_freeze(tmp_path / "missing-bundle", development_manifest, tmp_path / "out.json")
    assert completed.returncode != 0
    assert "E3-v2 confirmatory freeze lineage failed" in completed.stderr
    assert not (tmp_path / "out.json").exists()


def test_freeze_lineage_report_rejects_repository_local_development_manifest(tmp_path: Path) -> None:
    bundle_root = write_confirmatory_bundle(tmp_path / "POI_E3_V2_CONFIRMATORY")
    inside_repo = write_external_development_manifest(
        REPO_ROOT / "tmp-e3-v2-dev-manifest-test-only.json"
    )
    try:
        completed = _run_freeze(bundle_root, inside_repo, tmp_path / "out.json")
        assert completed.returncode != 0
        assert "development manifest must live outside the repository" in completed.stderr
    finally:
        inside_repo.unlink(missing_ok=True)


def test_freeze_lineage_report_rejects_synthetic_confirmatory_dataset(tmp_path: Path) -> None:
    bundle_root, development_manifest = _write_materials(
        tmp_path, dataset_origin="SYNTHETIC_NON_EVIDENCE"
    )
    completed = _run_freeze(bundle_root, development_manifest, tmp_path / "out.json")
    assert completed.returncode != 0
    assert "synthetic non-evidence cannot enter development or confirmatory datasets" in completed.stderr


def test_freeze_lineage_report_rejects_repository_local_output(tmp_path: Path) -> None:
    bundle_root, development_manifest = _write_materials(tmp_path)
    inside_repo = REPO_ROOT / "tmp-e3-v2-freeze-output-test-only.json"
    try:
        completed = _run_freeze(bundle_root, development_manifest, inside_repo)
        assert completed.returncode != 0
        assert "must live outside the repository" in completed.stderr
        assert not inside_repo.exists()
    finally:
        inside_repo.unlink(missing_ok=True)
