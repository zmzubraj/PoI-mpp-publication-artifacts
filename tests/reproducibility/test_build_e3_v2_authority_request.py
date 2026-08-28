from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

from tests.experiments.e3_v2_bundle_fixtures import canonical_json_bytes
from tests.experiments.test_e3_v2_scope import _write_authority_inputs


REPO_ROOT = Path(__file__).resolve().parents[2]
REQUEST_SCRIPT = REPO_ROOT / "scripts" / "build_e3_v2_authority_request.py"


def _run_request_builder(
    inputs: dict[str, Path],
    output_path: Path,
    *,
    development_report: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    report = inputs["development_report"] if development_report is None else development_report
    command = [
        sys.executable,
        str(REQUEST_SCRIPT),
        "--development-report",
        str(report),
        "--confirmatory-lineage",
        str(inputs["confirmatory_lineage"]),
        "--calibration-freeze",
        str(inputs["calibration_freeze"]),
        "--output",
        str(output_path),
    ]
    return subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)


def test_authority_request_cli_emits_canonical_unsigned_manifest(tmp_path: Path) -> None:
    from poi_mpp.experiments.e3_v2_scope import build_manifest

    inputs = _write_authority_inputs(tmp_path)
    output_path = tmp_path / "e3_v2_authority_request.json"

    completed = _run_request_builder(inputs, output_path)
    assert completed.returncode == 0, completed.stderr

    expected = build_manifest(
        development_report_path=inputs["development_report"],
        confirmatory_lineage_path=inputs["confirmatory_lineage"],
        calibration_freeze_path=inputs["calibration_freeze"],
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload == expected
    assert output_path.read_bytes() == canonical_json_bytes(expected)
    assert payload["schema_version"] == "POI_MPP_E3_AUTHORITY_REQUEST_V2"
    assert payload["status"] == "UNSIGNED_PRE_EXECUTION_SCOPE_REQUEST"
    assert completed.stdout.strip() == str(output_path)


def test_authority_request_cli_refuses_repository_local_output(tmp_path: Path) -> None:
    inputs = _write_authority_inputs(tmp_path)
    inside_repo = REPO_ROOT / "tmp-e3-v2-authority-request-test-only.json"
    try:
        completed = _run_request_builder(inputs, inside_repo)
        assert completed.returncode != 0
        assert "must live outside the repository" in completed.stderr
        assert not inside_repo.exists()
    finally:
        shutil.rmtree(inside_repo, ignore_errors=True)
        inside_repo.unlink(missing_ok=True)


def test_authority_request_cli_refuses_overwrite(tmp_path: Path) -> None:
    inputs = _write_authority_inputs(tmp_path)
    output_path = tmp_path / "e3_v2_authority_request.json"
    output_path.write_text("existing", encoding="utf-8")

    completed = _run_request_builder(inputs, output_path)
    assert completed.returncode != 0
    assert "already exists" in completed.stderr
    assert output_path.read_text(encoding="utf-8") == "existing"


def test_authority_request_cli_refuses_tampered_development_report(tmp_path: Path) -> None:
    inputs = _write_authority_inputs(tmp_path)
    tampered_report = tmp_path / "tampered_development_report.json"
    report = json.loads(inputs["development_report"].read_text(encoding="utf-8"))
    report["development_bundle_manifest_sha256"] = "0" * 64
    tampered_report.write_bytes(canonical_json_bytes(report))
    output_path = tmp_path / "e3_v2_authority_request.json"

    completed = _run_request_builder(inputs, output_path, development_report=tampered_report)
    assert completed.returncode != 0
    assert not output_path.exists()
