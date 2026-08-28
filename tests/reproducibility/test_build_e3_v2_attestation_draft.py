from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

from tests.experiments.e3_v2_bundle_fixtures import canonical_json_bytes, sha256_bytes
from tests.reproducibility.test_e3_v2_authority_contract import IDENTITY
from tests.reproducibility.test_run_e3_v2_real_model import (
    RUN_ID,
    _run_runner,
    _write_execution_inputs,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DRAFT_SCRIPT = REPO_ROOT / "scripts" / "build_e3_v2_attestation_draft.py"


def _canonical_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    return sha256_bytes(canonical_json_bytes(unsigned))


def _promote_to_authorized(run_dir: Path) -> dict[str, object]:
    """Rewrite a stub manifest as authorized real-model execution evidence."""

    manifest_path = run_dir / "execution_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evidence_origin"] = "REAL_MODEL_EXECUTION"
    manifest["adapter"] = "transformers-pinned-v1"
    manifest.pop("self_digest", None)
    manifest["self_digest"] = _canonical_digest(manifest)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    return manifest


def _run_draft_builder(
    paths: dict[str, Path],
    run_dir: Path,
    output_path: Path,
    *,
    attestation_date: str = "2026-08-25",
    signature: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    signature_path = paths["signature"] if signature is None else signature
    command = [
        sys.executable,
        str(DRAFT_SCRIPT),
        "--run-dir",
        str(run_dir),
        "--request-manifest",
        str(paths["request_manifest"]),
        "--authority-record",
        str(paths["authority_record"]),
        "--allowed-signers",
        str(paths["allowed_signers"]),
        "--signature",
        str(signature_path),
        "--attestation-date",
        attestation_date,
        "--output",
        str(output_path),
    ]
    return subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)


def _stub_run(tmp_path: Path) -> tuple[dict[str, Path], Path]:
    paths = _write_execution_inputs(tmp_path)
    output_root = tmp_path / "E3V2_RUN_OUTPUT"
    completed = _run_runner(paths, output_root)
    assert completed.returncode == 0, completed.stderr
    return paths, output_root / RUN_ID


def test_attestation_draft_binds_authorized_execution(tmp_path: Path) -> None:
    paths, run_dir = _stub_run(tmp_path)
    manifest = _promote_to_authorized(run_dir)
    draft_path = tmp_path / "e3_v2_result_attestation_draft.json"

    completed = _run_draft_builder(paths, run_dir, draft_path)
    assert completed.returncode == 0, completed.stderr

    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["schema_version"] == "POI_MPP_E3_RESULT_ATTESTATION_V2"
    assert draft["record_type"] == "POST_EXECUTION_RESULT_ATTESTATION"
    assert draft["status"] == "DRAFT_UNSIGNED_POST_EXECUTION_ATTESTATION"
    assert draft["authority_identity"] == IDENTITY
    assert draft["attestation_date"] == "2026-08-25"
    assert draft["pre_execution_authority_record"] == {
        "path": "e3_v2_authority_record.json",
        "sha256": sha256_bytes(paths["authority_record"].read_bytes()),
    }
    request = json.loads(paths["request_manifest"].read_text(encoding="utf-8"))
    assert draft["reviewed_request_manifest"] == {
        "path": "e3_v2_authority_request.json",
        "sha256": sha256_bytes(paths["request_manifest"].read_bytes()),
        "self_digest": request["self_digest"],
    }

    scope = draft["result_scope"]
    assert scope["experiment_id"] == "E3"
    assert scope["experiment_generation"] == "E3_V2"
    assert scope["claim_id"] == "C3"
    assert scope["claim_generation"] == "C3_V2"
    assert scope["run_id"] == RUN_ID
    assert scope["evidence_origin"] == "REAL_MODEL_EXECUTION"
    assert set(scope["metric_scope"]) == {"ABSTAIN", "FAR", "FRR", "calibration", "coverage"}
    assert set(scope["artifact_scope"]) == {"F7", "RAW_E3_EXECUTION", "T4", "T8"}

    bindings = scope["execution_bindings"]
    assert bindings["authority_record_sha256"] == sha256_bytes(paths["authority_record"].read_bytes())
    assert bindings["request_manifest_sha256"] == sha256_bytes(paths["request_manifest"].read_bytes())
    assert bindings["execution_manifest_sha256"] == sha256_bytes(
        (run_dir / "execution_manifest.json").read_bytes()
    )
    assert bindings["outputs_sha256"] == sha256_bytes((run_dir / "outputs.jsonl").read_bytes())
    assert bindings["trace_sha256"] == sha256_bytes((run_dir / "trace.jsonl").read_bytes())
    assert bindings["summary_sha256"] == sha256_bytes((run_dir / "summary.json").read_bytes())
    assert bindings["prompt_template_sha256"] == manifest["prompt_template_sha256"]
    assert bindings["record_count"] == 500
    assert bindings["material_bindings"] == request["bound_materials"]

    artifacts = {artifact["path"]: artifact for artifact in draft["artifacts"]}
    assert set(artifacts) == {"execution_manifest.json", "outputs.jsonl", "summary.json", "trace.jsonl"}
    for name, artifact in artifacts.items():
        blob = (run_dir / name).read_bytes()
        assert artifact["artifact_id"] == "RAW_E3_EXECUTION"
        assert artifact["sha256"] == sha256_bytes(blob)
        assert artifact["size_bytes"] == len(blob)

    assert draft["results_disposition"] == "ATTESTED_AS_REPORTED"
    assert draft["publication_support_decision_status"] == "NOT_EVALUATED_BY_THIS_ATTESTATION"
    assert draft["external_signature_required"] is True
    assert draft["self_digest"] == _canonical_digest(draft)
    assert "verdict" not in draft
    assert "support_rule" not in draft


def test_attestation_draft_refuses_pipeline_self_test(tmp_path: Path) -> None:
    paths, run_dir = _stub_run(tmp_path)
    draft_path = tmp_path / "e3_v2_result_attestation_draft.json"

    completed = _run_draft_builder(paths, run_dir, draft_path)
    assert completed.returncode != 0
    assert "self-test" in completed.stderr
    assert not draft_path.exists()


def test_attestation_draft_refuses_legacy_authorized_model_origin(tmp_path: Path) -> None:
    paths, run_dir = _stub_run(tmp_path)
    manifest_path = run_dir / "execution_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evidence_origin"] = "AUTHORIZED_MODEL_EXECUTION"
    manifest["adapter"] = "transformers-pinned-v1"
    manifest.pop("self_digest", None)
    manifest["self_digest"] = _canonical_digest(manifest)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    draft_path = tmp_path / "e3_v2_result_attestation_draft.json"

    completed = _run_draft_builder(paths, run_dir, draft_path)
    assert completed.returncode != 0
    assert "REAL_MODEL_EXECUTION" in completed.stderr
    assert not draft_path.exists()


def test_attestation_draft_refuses_tampered_outputs(tmp_path: Path) -> None:
    paths, run_dir = _stub_run(tmp_path)
    _promote_to_authorized(run_dir)
    outputs_path = run_dir / "outputs.jsonl"
    outputs_path.write_bytes(outputs_path.read_bytes() + b" ")
    draft_path = tmp_path / "e3_v2_result_attestation_draft.json"

    completed = _run_draft_builder(paths, run_dir, draft_path)
    assert completed.returncode != 0
    assert "outputs" in completed.stderr
    assert not draft_path.exists()


def test_attestation_draft_refuses_unverified_authority(tmp_path: Path) -> None:
    paths, run_dir = _stub_run(tmp_path)
    _promote_to_authorized(run_dir)
    draft_path = tmp_path / "e3_v2_result_attestation_draft.json"

    completed = _run_draft_builder(paths, run_dir, draft_path, signature=tmp_path / "missing.sig")
    assert completed.returncode != 0
    assert not draft_path.exists()


def test_attestation_draft_refuses_broken_authority_chain(tmp_path: Path) -> None:
    paths, run_dir = _stub_run(tmp_path)
    manifest = _promote_to_authorized(run_dir)
    manifest["authority"]["authority_record_sha256"] = "f" * 64
    manifest.pop("self_digest", None)
    manifest["self_digest"] = _canonical_digest(manifest)
    (run_dir / "execution_manifest.json").write_bytes(canonical_json_bytes(manifest))
    draft_path = tmp_path / "e3_v2_result_attestation_draft.json"

    completed = _run_draft_builder(paths, run_dir, draft_path)
    assert completed.returncode != 0
    assert "authority" in completed.stderr
    assert not draft_path.exists()


def test_attestation_draft_refuses_repository_local_output(tmp_path: Path) -> None:
    paths, run_dir = _stub_run(tmp_path)
    _promote_to_authorized(run_dir)
    inside_repo = REPO_ROOT / "tmp-e3-v2-attestation-draft-test-only.json"
    try:
        completed = _run_draft_builder(paths, run_dir, inside_repo)
        assert completed.returncode != 0
        assert "must live outside the repository" in completed.stderr
        assert not inside_repo.exists()
    finally:
        shutil.rmtree(inside_repo, ignore_errors=True)
        inside_repo.unlink(missing_ok=True)


def test_attestation_draft_refuses_overwrite(tmp_path: Path) -> None:
    paths, run_dir = _stub_run(tmp_path)
    _promote_to_authorized(run_dir)
    draft_path = tmp_path / "e3_v2_result_attestation_draft.json"
    draft_path.write_text("existing", encoding="utf-8")

    completed = _run_draft_builder(paths, run_dir, draft_path)
    assert completed.returncode != 0
    assert "already exists" in completed.stderr
    assert draft_path.read_text(encoding="utf-8") == "existing"


def test_attestation_draft_refuses_invalid_date(tmp_path: Path) -> None:
    paths, run_dir = _stub_run(tmp_path)
    _promote_to_authorized(run_dir)
    draft_path = tmp_path / "e3_v2_result_attestation_draft.json"

    completed = _run_draft_builder(paths, run_dir, draft_path, attestation_date="25-08-2026")
    assert completed.returncode != 0
    assert "date" in completed.stderr
    assert not draft_path.exists()
