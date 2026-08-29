from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from poi_mpp.evidence.dataset_manifest_v2 import DatasetManifestV2
from poi_mpp.experiments.e3_development import (
    E3DevelopmentBundleStatus,
    validate_e3_phase3_development_bundle_materials,
)
from poi_mpp.worker.development_observation_exporter import (
    DevelopmentObservationExportError,
    export_raw_execution_to_observations,
)
from tests.experiments.e3_v2_bundle_fixtures import (
    _load_script_module,
    canonical_json_bytes,
    development_report_payload,
    sha256_bytes,
    write_development_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_SCRIPT = REPO_ROOT / "scripts" / "run_e3_v2_development_model.py"
CALIBRATION_SCRIPT = REPO_ROOT / "scripts" / "fit_e3_v2_development_calibration.py"


def _runner():
    return _load_script_module("_phase3_development_runner_red", RUNNER_SCRIPT)


def _calibration():
    return _load_script_module("_phase3_development_calibration_red", CALIBRATION_SCRIPT)


def _prepared_bundle(tmp_path: Path):
    bundle = write_development_bundle(tmp_path / "development-bundle")
    materials = validate_e3_phase3_development_bundle_materials(bundle_root=bundle)
    bindings = materials.policy_input_file_hashes
    grant = SimpleNamespace(
        experiment_id="E3",
        claim_id="C3",
        evidence_origin="REAL_MODEL_EXECUTION",
        decision="APPROVED",
        authority_identity="external-test-only",
        metric_scope=("ABSTAIN", "FAR", "FRR", "calibration", "coverage"),
        artifact_scope=("RAW_E3_EXECUTION",),
        request_scope_digest="a" * 64,
        authority_record_sha256="b" * 64,
        request_manifest_sha256="c" * 64,
        request_manifest_self_digest="d" * 64,
        allowed_signers_sha256="e" * 64,
        signature_sha256="f" * 64,
        development_bundle_manifest_sha256=materials.bundle_manifest_sha256,
        development_dataset_manifest_hash=materials.dataset_manifest.dataset_manifest_hash(),
        development_model_manifest_hash=bindings["model_manifest_hash"],
        development_decode_policy_hash=bindings["deterministic_decode_policy_hash"],
        development_environment_manifest_hash=bindings["runtime_environment_hash"],
        development_policy_inputs_digest="1" * 64,
    )
    prepared = SimpleNamespace(
        status=E3DevelopmentBundleStatus.READY_FOR_EXECUTION,
        authority_grant=grant,
        bundle_root=materials.bundle_root,
        dataset_manifest=materials.dataset_manifest,
        model_manifest=materials.model_manifest,
        decode_policy=materials.decode_policy,
        environment_manifest=materials.environment_manifest,
    )
    return bundle, materials, prepared


def _run_with_prepared(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    module = _runner()
    bundle, materials, prepared = _prepared_bundle(tmp_path)
    monkeypatch.setattr(module, "prepare_e3_phase3_development_bundle", lambda **_: prepared)
    monkeypatch.setattr(
        module,
        "verify_development_authority",
        lambda **_: (_ for _ in ()).throw(AssertionError("duplicate authority verification")),
    )
    output_root = tmp_path / "run-output"
    output_root.mkdir()
    run_dir = module.run_development_execution(
        bundle_root=bundle,
        request_manifest_path=tmp_path / "request.json",
        authority_record_path=tmp_path / "authority.json",
        allowed_signers_path=tmp_path / "allowed_signers",
        signature_path=tmp_path / "authority.sig",
        output_root=output_root,
        run_id="phase3-test-run",
        adapter_name="stub",
    )
    return module, materials, prepared, run_dir


def test_runner_consumes_one_verified_prepared_grant_and_records_full_authority_lineage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, prepared, run_dir = _run_with_prepared(monkeypatch, tmp_path)
    manifest = json.loads((run_dir / "execution_manifest.json").read_bytes())
    grant = prepared.authority_grant
    assert manifest["authority"] == {
        "authority_identity": grant.authority_identity,
        "authority_record_sha256": grant.authority_record_sha256,
        "decision": "APPROVED",
        "metric_scope": list(grant.metric_scope),
        "artifact_scope": ["RAW_E3_EXECUTION"],
        "request_manifest_sha256": grant.request_manifest_sha256,
        "request_manifest_self_digest": grant.request_manifest_self_digest,
        "allowed_signers_sha256": grant.allowed_signers_sha256,
        "signature_sha256": grant.signature_sha256,
    }
    unsigned = dict(manifest)
    self_digest = unsigned.pop("self_digest")
    assert self_digest == sha256_bytes(canonical_json_bytes(unsigned))


def test_runner_never_leaves_partial_final_run_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _runner()
    bundle, _, prepared = _prepared_bundle(tmp_path)
    monkeypatch.setattr(module, "prepare_e3_phase3_development_bundle", lambda **_: prepared)
    monkeypatch.setattr(module, "verify_development_authority", lambda **_: prepared.authority_grant)
    calls = 0
    original_write = module._write_atomic

    def fail_second_write(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected partial-write failure")
        original_write(path, payload)

    monkeypatch.setattr(module, "_write_atomic", fail_second_write)
    output_root = tmp_path / "run-output"
    output_root.mkdir()
    with pytest.raises(OSError, match="injected partial-write failure"):
        module.run_development_execution(
            bundle_root=bundle,
            request_manifest_path=tmp_path / "request.json",
            authority_record_path=tmp_path / "authority.json",
            allowed_signers_path=tmp_path / "allowed_signers",
            signature_path=tmp_path / "authority.sig",
            output_root=output_root,
            run_id="phase3-test-run",
            adapter_name="stub",
        )
    assert not (output_root / "phase3-test-run").exists()


def _execution_files(tmp_path: Path):
    bundle = write_development_bundle(tmp_path / "development-bundle")
    dataset = DatasetManifestV2.model_validate(
        json.loads((bundle / "dataset" / "dataset_manifest_v2.json").read_bytes())
    )
    template = (bundle / "policy" / "prompt_template.txt").read_bytes()
    rows = []
    traces = []
    for record in dataset.records:
        item = (bundle / "dataset" / record.item_path).read_bytes()
        raw_output = record.expected_decision.value
        row = {
            "record_id": record.record_id,
            "expected_decision": record.expected_decision.value,
            "item_hash": record.item_hash,
            "prompt_sha256": sha256_bytes(template + item),
            "raw_output": raw_output,
            "raw_output_sha256": sha256_bytes(raw_output.encode()),
            "decision": record.expected_decision.value,
            "parse_status": "OK",
            "adapter": "transformers-pinned-v1",
            "evidence_origin": "REAL_MODEL_EXECUTION",
        }
        rows.append(row)
        traces.append(
            {
                "record_id": record.record_id,
                "prompt_sha256": row["prompt_sha256"],
                "raw_output_sha256": row["raw_output_sha256"],
                "adapter": row["adapter"],
                "seed": 7,
                "max_new_tokens": 96,
            }
        )
    outputs = tmp_path / "outputs.jsonl"
    trace = tmp_path / "trace.jsonl"
    summary = tmp_path / "summary.json"
    outputs.write_bytes(b"".join(canonical_json_bytes(row) + b"\n" for row in rows))
    trace.write_bytes(b"".join(canonical_json_bytes(row) + b"\n" for row in traces))
    summary_payload = {
        "schema_version": "POI_MPP_E3_V2_DEVELOPMENT_EXECUTION_SUMMARY_V1",
        "run_id": "phase3-real-test",
        "adapter": "transformers-pinned-v1",
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "item_count": len(rows),
    }
    summary.write_bytes(canonical_json_bytes(summary_payload))
    manifest_payload = {
        "schema_version": "POI_MPP_E3_V2_DEVELOPMENT_EXECUTION_MANIFEST_V1",
        "run_id": "phase3-real-test",
        "adapter": "transformers-pinned-v1",
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "output_files": {
            "outputs": sha256_bytes(outputs.read_bytes()),
            "trace": sha256_bytes(trace.read_bytes()),
            "summary": sha256_bytes(summary.read_bytes()),
        },
    }
    manifest_payload["self_digest"] = sha256_bytes(canonical_json_bytes(manifest_payload))
    execution_manifest = tmp_path / "execution_manifest.json"
    execution_manifest.write_bytes(canonical_json_bytes(manifest_payload))
    return bundle, dataset, rows, outputs, trace, summary, execution_manifest


def _export(bundle: Path, dataset: DatasetManifestV2, outputs: Path, trace: Path, summary: Path, manifest: Path):
    return export_raw_execution_to_observations(
        outputs_path=outputs,
        trace_path=trace,
        summary_path=summary,
        execution_manifest_path=manifest,
        bundle_root=bundle,
        dataset_manifest=dataset,
        claim_spec_hash="1" * 64,
        prompt_template_hash=sha256_bytes((bundle / "policy" / "prompt_template.txt").read_bytes()),
        model_manifest_hash="2" * 64,
        runtime_environment_hash="3" * 64,
        decode_policy_hash="4" * 64,
    )


@pytest.mark.parametrize("mutation", ["missing-row", "prompt-hash", "raw-output-hash"])
def test_exporter_requires_complete_hash_bound_execution_closure(
    tmp_path: Path, mutation: str
) -> None:
    bundle, dataset, rows, outputs, trace, summary, manifest = _execution_files(tmp_path)
    if mutation == "missing-row":
        rows.pop()
    elif mutation == "prompt-hash":
        rows[0]["prompt_sha256"] = "0" * 64
    else:
        rows[0]["raw_output_sha256"] = "0" * 64
    outputs.write_bytes(b"".join(canonical_json_bytes(row) + b"\n" for row in rows))
    manifest_payload = json.loads(manifest.read_bytes())
    manifest_payload["output_files"]["outputs"] = sha256_bytes(outputs.read_bytes())
    manifest_payload.pop("self_digest")
    manifest_payload["self_digest"] = sha256_bytes(canonical_json_bytes(manifest_payload))
    manifest.write_bytes(canonical_json_bytes(manifest_payload))
    with pytest.raises(DevelopmentObservationExportError):
        _export(bundle, dataset, outputs, trace, summary, manifest)


def test_calibration_requires_verified_authority_and_execution_manifest_inputs() -> None:
    parameters = inspect.signature(_calibration().run_calibration_cli).parameters
    assert {
        "execution_manifest_path",
        "request_manifest_path",
        "authority_record_path",
        "allowed_signers_path",
        "signature_path",
    }.issubset(parameters)


def test_transformers_adapter_rehashes_pinned_local_model_bytes_before_load(
    tmp_path: Path,
) -> None:
    module = _runner()
    bundle = write_development_bundle(tmp_path / "development-bundle")
    materials = validate_e3_phase3_development_bundle_materials(bundle_root=bundle)
    snapshot = tmp_path / "model-snapshot"
    snapshot.mkdir()
    for filename in {
        *materials.model_manifest.model_file_hashes,
        *materials.model_manifest.tokenizer_file_hashes,
    }:
        path = snapshot / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tampered-model-byte")

    with pytest.raises(module.E3V2DevelopmentExecutionError, match="hash mismatch"):
        module._verify_snapshot_files(snapshot, materials.model_manifest)


def test_real_output_parser_requires_exact_decision_support_and_confidence() -> None:
    module = _runner()
    assert module.parse_model_output(
        '{"decision":"ACCEPT","support_fraction":0.75,"calibrated_confidence":0.8}',
        require_structured=True,
    ) == ("ACCEPT", 0.75, 0.8, "OK")
    assert module.parse_model_output(
        '{"decision":"ACCEPT","support_fraction":2,"calibrated_confidence":0.8}',
        require_structured=True,
    ) == ("ABSTAIN", 0.0, 0.0, "UNPARSEABLE_FAIL_CLOSED")


def _calibration_inputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    bundle, dataset, _, outputs, trace, summary, manifest = _execution_files(tmp_path)
    materials = validate_e3_phase3_development_bundle_materials(bundle_root=bundle)
    grant = SimpleNamespace(
        metric_scope=("ABSTAIN", "FAR", "FRR", "calibration", "coverage"),
        artifact_scope=("RAW_E3_EXECUTION",),
        authority_record_sha256="a" * 64,
        signature_sha256="b" * 64,
        development_bundle_manifest_sha256=materials.bundle_manifest_sha256,
        development_dataset_manifest_hash=dataset.dataset_manifest_hash(),
        development_model_manifest_hash=materials.policy_input_file_hashes["model_manifest_hash"],
        development_decode_policy_hash=materials.policy_input_file_hashes["deterministic_decode_policy_hash"],
        development_environment_manifest_hash=materials.policy_input_file_hashes["runtime_environment_hash"],
    )
    manifest_payload = json.loads(manifest.read_bytes())
    manifest_payload["authority"] = {
        "authority_record_sha256": grant.authority_record_sha256,
        "signature_sha256": grant.signature_sha256,
    }
    manifest_payload.pop("self_digest")
    manifest_payload["self_digest"] = sha256_bytes(canonical_json_bytes(manifest_payload))
    manifest.write_bytes(canonical_json_bytes(manifest_payload))
    report = tmp_path / "development-report.json"
    report.write_bytes(canonical_json_bytes(development_report_payload(bundle)))
    module = _calibration()
    monkeypatch.setattr(module, "verify_development_authority", lambda **_: grant)
    return module, bundle, outputs, trace, summary, manifest, report


def _run_calibration(module, tmp_path, bundle, outputs, trace, summary, manifest, report, output):
    return module.run_calibration_cli(
        bundle_root=bundle,
        outputs_path=outputs,
        trace_path=trace,
        summary_path=summary,
        execution_manifest_path=manifest,
        request_manifest_path=tmp_path / "request.json",
        authority_record_path=tmp_path / "authority.json",
        allowed_signers_path=tmp_path / "allowed_signers",
        signature_path=tmp_path / "authority.sig",
        development_report_path=report,
        output_root=output,
    )


def test_calibration_bundle_is_transactional_and_self_digested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args = _calibration_inputs(monkeypatch, tmp_path)
    module, bundle, outputs, trace, summary, manifest, report = args
    output = tmp_path / "calibration-output"
    _run_calibration(module, tmp_path, bundle, outputs, trace, summary, manifest, report, output)
    emitted = json.loads((output / "calibration_bundle_manifest.json").read_bytes())
    unsigned = dict(emitted)
    assert unsigned.pop("self_digest") == sha256_bytes(canonical_json_bytes(unsigned))


def test_calibration_partial_write_never_publishes_final_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    args = _calibration_inputs(monkeypatch, tmp_path)
    module, bundle, outputs, trace, summary, manifest, report = args
    real_write = module._write_atomic
    calls = 0

    def fail_second(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected calibration write failure")
        real_write(path, payload)

    monkeypatch.setattr(module, "_write_atomic", fail_second)
    output = tmp_path / "calibration-output"
    with pytest.raises(OSError, match="injected calibration write failure"):
        _run_calibration(module, tmp_path, bundle, outputs, trace, summary, manifest, report, output)
    assert not output.exists()
