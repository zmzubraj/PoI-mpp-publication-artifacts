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
)
from tests.experiments.test_e3_v2_scope import _write_authority_inputs
from tests.reproducibility.test_e3_v2_authority_contract import (
    IDENTITY,
    _authority_record,
    _sign_record,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SCRIPT = REPO_ROOT / "scripts" / "run_e3_v2_real_model.py"
RUN_ID = "e3v2-run-test"

_OUTPUT_LINE_KEYS = {
    "record_id",
    "expected_decision",
    "item_hash",
    "prompt_sha256",
    "raw_output",
    "raw_output_sha256",
    "decision",
    "parse_status",
}
_TRACE_LINE_KEYS = {
    "record_id",
    "prompt_sha256",
    "seed",
    "max_new_tokens",
    "adapter",
    "raw_output_sha256",
}


def _canonical_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    return sha256_bytes(canonical_json_bytes(unsigned))


def _write_execution_inputs(tmp_path: Path) -> dict[str, Path]:
    from poi_mpp.experiments.e3_v2_scope import build_manifest

    inputs = _write_authority_inputs(tmp_path)
    manifest = build_manifest(
        development_report_path=inputs["development_report"],
        confirmatory_lineage_path=inputs["confirmatory_lineage"],
        calibration_freeze_path=inputs["calibration_freeze"],
    )
    request_path = tmp_path / "e3_v2_authority_request.json"
    request_path.write_bytes(canonical_json_bytes(manifest))
    record = _authority_record(request_path, manifest)
    record_path = tmp_path / "e3_v2_authority_record.json"
    record_path.write_bytes(canonical_json_bytes(record))
    allowed_signers, signature = _sign_record(tmp_path, record_path, IDENTITY)
    return {
        "development_bundle": tmp_path / "POI_E3_V2_DEVELOPMENT",
        "confirmatory_bundle": tmp_path / "POI_E3_V2_CONFIRMATORY",
        "development_manifest": tmp_path / "development_dataset_manifest_v2.json",
        "request_manifest": request_path,
        "authority_record": record_path,
        "allowed_signers": allowed_signers,
        "signature": signature,
    }


def _run_runner(
    paths: dict[str, Path],
    output_root: Path,
    *,
    run_id: str = RUN_ID,
    adapter: str = "stub",
    signature: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    signature_path = paths["signature"] if signature is None else signature
    command = [
        sys.executable,
        str(RUN_SCRIPT),
        "--development-bundle-root",
        str(paths["development_bundle"]),
        "--confirmatory-bundle-root",
        str(paths["confirmatory_bundle"]),
        "--development-manifest",
        str(paths["development_manifest"]),
        "--request-manifest",
        str(paths["request_manifest"]),
        "--authority-record",
        str(paths["authority_record"]),
        "--allowed-signers",
        str(paths["allowed_signers"]),
        "--signature",
        str(signature_path),
        "--output-root",
        str(output_root),
        "--run-id",
        run_id,
        "--adapter",
        adapter,
    ]
    return subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_run_e3_v2_stub_execution_produces_hash_bound_evidence(tmp_path: Path) -> None:
    paths = _write_execution_inputs(tmp_path)
    output_root = tmp_path / "E3V2_RUN_OUTPUT"

    completed = _run_runner(paths, output_root)
    assert completed.returncode == 0, completed.stderr

    run_dir = output_root / RUN_ID
    outputs_path = run_dir / "outputs.jsonl"
    trace_path = run_dir / "trace.jsonl"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "execution_manifest.json"
    assert outputs_path.is_file() and trace_path.is_file()
    assert summary_path.is_file() and manifest_path.is_file()

    confirmatory_manifest = json.loads(
        (paths["confirmatory_bundle"] / "dataset_manifest_v2.json").read_text(encoding="utf-8")
    )
    records = confirmatory_manifest["records"]
    template = (paths["development_bundle"] / "policy" / "prompt_template.txt").read_bytes()

    outputs = _read_jsonl(outputs_path)
    assert len(outputs) == 500
    for line, record in zip(outputs, records):
        assert set(line) == _OUTPUT_LINE_KEYS
        assert line["record_id"] == record["record_id"]
        assert line["expected_decision"] == record["expected_decision"]
        assert line["item_hash"] == record["item_hash"]
        item = (paths["confirmatory_bundle"] / record["item_path"]).read_bytes()
        assert line["prompt_sha256"] == sha256_bytes(template + item)
        assert line["decision"] in {"ACCEPT", "REJECT", "ABSTAIN"}
        assert line["parse_status"] == "OK"
        assert line["raw_output_sha256"] == sha256_bytes(str(line["raw_output"]).encode("utf-8"))

    trace = _read_jsonl(trace_path)
    assert len(trace) == 500
    for line, record in zip(trace, records):
        assert set(line) == _TRACE_LINE_KEYS
        assert line["record_id"] == record["record_id"]
        assert line["seed"] == 7
        assert line["max_new_tokens"] == 96
        assert line["adapter"] == "stub-self-test-v1"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["schema_version"] == "POI_MPP_E3_V2_EXECUTION_SUMMARY_V1"
    assert summary["run_id"] == RUN_ID
    assert summary["record_count"] == 500
    assert sum(summary["model_decision_counts"].values()) == 500
    false_accepts = sum(
        1
        for line in outputs
        if line["expected_decision"] == "REJECT" and line["decision"] == "ACCEPT"
    )
    false_rejects = sum(
        1
        for line in outputs
        if line["expected_decision"] == "ACCEPT" and line["decision"] == "REJECT"
    )
    decisive = sum(1 for line in outputs if line["decision"] != "ABSTAIN")
    assert summary["comparison"]["false_accept_count"] == false_accepts
    assert summary["comparison"]["false_reject_count"] == false_rejects
    assert summary["comparison"]["decisive_count"] == decisive
    assert summary["self_digest"] == _canonical_digest(summary)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    request_bytes = paths["request_manifest"].read_bytes()
    request = json.loads(request_bytes)
    assert manifest["schema_version"] == "POI_MPP_E3_V2_EXECUTION_MANIFEST_V1"
    assert manifest["run_id"] == RUN_ID
    assert manifest["evidence_origin"] == "PIPELINE_SELF_TEST"
    assert manifest["adapter"] == "stub-self-test-v1"
    assert manifest["authority"] == {
        "authority_record_sha256": sha256_bytes(paths["authority_record"].read_bytes()),
        "request_manifest_sha256": sha256_bytes(request_bytes),
        "decision": "APPROVED",
        "authority_identity": IDENTITY,
    }
    assert manifest["bindings"] == request["bound_materials"]
    assert manifest["model"]["model_id"] == "qwen25-1p5b-test-only"
    assert manifest["model"]["parameter_scale"] == "1.5B"
    assert manifest["decode_policy"] == {"seed": 7, "max_new_tokens": 96}
    assert manifest["prompt_template_sha256"] == sha256_bytes(template)
    assert manifest["record_count"] == 500
    assert manifest["outputs_sha256"] == sha256_bytes(outputs_path.read_bytes())
    assert manifest["trace_sha256"] == sha256_bytes(trace_path.read_bytes())
    assert manifest["summary_sha256"] == sha256_bytes(summary_path.read_bytes())
    assert manifest["self_digest"] == _canonical_digest(manifest)

    second_root = tmp_path / "E3V2_RUN_OUTPUT_SECOND"
    completed_second = _run_runner(paths, second_root)
    assert completed_second.returncode == 0, completed_second.stderr
    assert (second_root / RUN_ID / "outputs.jsonl").read_bytes() == outputs_path.read_bytes()
    assert (second_root / RUN_ID / "trace.jsonl").read_bytes() == trace_path.read_bytes()
    assert (second_root / RUN_ID / "summary.json").read_bytes() == summary_path.read_bytes()


def test_run_e3_v2_refuses_without_verified_authority(tmp_path: Path) -> None:
    paths = _write_execution_inputs(tmp_path)
    output_root = tmp_path / "E3V2_RUN_OUTPUT"

    completed = _run_runner(paths, output_root, signature=tmp_path / "missing.sig")
    assert completed.returncode != 0
    assert "not authorized" in completed.stderr
    assert not (output_root / RUN_ID).exists()


def test_run_e3_v2_refuses_unbound_confirmatory_bundle(tmp_path: Path) -> None:
    paths = _write_execution_inputs(tmp_path)
    foreign_bundle = write_confirmatory_bundle(
        tmp_path / "POI_E3_V2_CONFIRMATORY_FOREIGN",
        dataset_id="e3-v2-confirmatory-foreign-test-only",
    )
    paths = dict(paths)
    paths["confirmatory_bundle"] = foreign_bundle

    completed = _run_runner(paths, tmp_path / "E3V2_RUN_OUTPUT")
    assert completed.returncode != 0
    assert "confirmatory" in completed.stderr
    assert not (tmp_path / "E3V2_RUN_OUTPUT" / RUN_ID).exists()


def test_run_e3_v2_refuses_repository_local_output_root(tmp_path: Path) -> None:
    paths = _write_execution_inputs(tmp_path)
    inside_repo = REPO_ROOT / "tmp-e3-v2-run-output-test-only"
    try:
        completed = _run_runner(paths, inside_repo)
        assert completed.returncode != 0
        assert "must live outside the repository" in completed.stderr
        assert not inside_repo.exists()
    finally:
        shutil.rmtree(inside_repo, ignore_errors=True)


def test_run_e3_v2_refuses_existing_run_directory(tmp_path: Path) -> None:
    paths = _write_execution_inputs(tmp_path)
    output_root = tmp_path / "E3V2_RUN_OUTPUT"
    (output_root / RUN_ID).mkdir(parents=True)

    completed = _run_runner(paths, output_root)
    assert completed.returncode != 0
    assert "already exists" in completed.stderr


def test_run_e3_v2_limited_scope_authority_is_waiting(tmp_path: Path) -> None:
    from poi_mpp.experiments.e3_v2_scope import build_manifest

    inputs = _write_authority_inputs(tmp_path)
    manifest = build_manifest(
        development_report_path=inputs["development_report"],
        confirmatory_lineage_path=inputs["confirmatory_lineage"],
        calibration_freeze_path=inputs["calibration_freeze"],
    )
    request_path = tmp_path / "e3_v2_authority_request.json"
    request_path.write_bytes(canonical_json_bytes(manifest))
    record = _authority_record(
        request_path,
        manifest,
        decision="LIMITED_SCOPE",
        metric_scope=["FAR", "FRR"],
        artifact_scope=["RAW_E3_EXECUTION", "T8"],
    )
    record_path = tmp_path / "e3_v2_authority_record.json"
    record_path.write_bytes(canonical_json_bytes(record))
    allowed_signers, signature = _sign_record(tmp_path, record_path, IDENTITY)
    paths = {
        "development_bundle": tmp_path / "POI_E3_V2_DEVELOPMENT",
        "confirmatory_bundle": tmp_path / "POI_E3_V2_CONFIRMATORY",
        "development_manifest": tmp_path / "development_dataset_manifest_v2.json",
        "request_manifest": request_path,
        "authority_record": record_path,
        "allowed_signers": allowed_signers,
        "signature": signature,
    }

    completed = _run_runner(paths, tmp_path / "E3V2_RUN_OUTPUT")
    assert completed.returncode != 0
    assert "limited_scope_runner_not_implemented" in completed.stderr


def test_run_e3_v2_refuses_invalid_run_id(tmp_path: Path) -> None:
    paths = _write_execution_inputs(tmp_path)
    completed = _run_runner(paths, tmp_path / "E3V2_RUN_OUTPUT", run_id="Bad_Run_ID")
    assert completed.returncode != 0
    assert "run-id" in completed.stderr
