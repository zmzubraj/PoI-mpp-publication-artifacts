from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from poi_mpp.experiments.e3_development import (
    E3DevelopmentBundleStatus,
    validate_e3_phase3_development_bundle_materials,
)
from tests.experiments.e3_v2_bundle_fixtures import (
    _load_script_module,
    hash_token,
    write_development_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SCRIPT = REPO_ROOT / "scripts" / "run_e3_v2_development_model.py"


def _runner():
    return _load_script_module("_phase3_development_runner_red", RUN_SCRIPT)


def _install_valid_gates(monkeypatch: pytest.MonkeyPatch, runner, tmp_path: Path):
    material = validate_e3_phase3_development_bundle_materials(
        bundle_root=write_development_bundle(tmp_path / "development-bundle")
    )
    bound = SimpleNamespace(
        experiment_id="E3",
        claim_id="C3",
        evidence_origin="REAL_MODEL_EXECUTION",
        authority_identity="external-test-authority",
        decision="APPROVED",
        metric_scope=("FAR", "FRR", "ABSTAIN", "coverage", "calibration"),
        artifact_scope=("RAW_E3_EXECUTION",),
        request_scope_digest=hash_token("request-scope"),
        authority_record_sha256=hash_token("authority-record"),
        request_manifest_sha256=hash_token("authority-request"),
        request_manifest_self_digest=hash_token("authority-self-digest"),
        allowed_signers_sha256=hash_token("allowed-signers"),
        signature_sha256=hash_token("signature"),
        development_bundle_manifest_sha256=material.bundle_manifest_sha256,
        development_dataset_manifest_hash=material.dataset_manifest.dataset_manifest_hash(),
        development_model_manifest_hash=hash_token("model-manifest"),
        development_decode_policy_hash=hash_token("decode-policy"),
        development_environment_manifest_hash=hash_token("environment"),
        development_policy_inputs_digest=hash_token("policy-inputs"),
    )
    prepared = SimpleNamespace(
        status=E3DevelopmentBundleStatus.READY_FOR_EXECUTION,
        authority_grant=bound,
        environment_manifest=SimpleNamespace(network_access="LOCAL_ONLY", external_services=()),
        dataset_manifest=material.dataset_manifest,
        decode_policy=material.decode_policy,
        model_manifest=material.model_manifest,
        bundle_root=material.bundle_root,
        missing_inputs=(),
    )
    monkeypatch.setattr(runner, "prepare_e3_phase3_development_bundle", lambda **kwargs: prepared)
    trust = tmp_path / "trust"
    trust.mkdir()
    paths = []
    for name in ("request.json", "record.json", "allowed_signers", "record.sig"):
        path = trust / name
        path.write_text("test-only\n", encoding="utf-8")
        paths.append(path)
    return material, bound, bound, paths


def _run(runner, tmp_path: Path, paths: list[Path], *, run_id: str = "phase3-red-run") -> Path:
    output_root = tmp_path / "output"
    output_root.mkdir()
    return runner.run_development_execution(
        bundle_root=tmp_path / "ignored-by-prepared-gate",
        request_manifest_path=paths[0],
        authority_record_path=paths[1],
        allowed_signers_path=paths[2],
        signature_path=paths[3],
        output_root=output_root,
        run_id=run_id,
        adapter_name="stub",
    )


def test_execution_manifest_binds_the_verified_development_authority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _runner()
    _, _, dev_grant, paths = _install_valid_gates(monkeypatch, runner, tmp_path)

    run_dir = _run(runner, tmp_path, paths)
    manifest = json.loads((run_dir / "execution_manifest.json").read_bytes())

    assert manifest["authority"] == {
        "authority_identity": dev_grant.authority_identity,
        "decision": "APPROVED",
        "authority_record_sha256": dev_grant.authority_record_sha256,
        "metric_scope": list(dev_grant.metric_scope),
        "artifact_scope": list(dev_grant.artifact_scope),
        "request_manifest_sha256": dev_grant.request_manifest_sha256,
        "request_manifest_self_digest": dev_grant.request_manifest_self_digest,
        "allowed_signers_sha256": dev_grant.allowed_signers_sha256,
        "signature_sha256": dev_grant.signature_sha256,
    }


def test_stub_execution_is_explicitly_synthetic_non_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _runner()
    _, _, _, paths = _install_valid_gates(monkeypatch, runner, tmp_path)

    run_dir = _run(runner, tmp_path, paths)
    manifest = json.loads((run_dir / "execution_manifest.json").read_bytes())
    outputs = [json.loads(line) for line in (run_dir / "outputs.jsonl").read_text().splitlines()]

    assert manifest["evidence_origin"] == "SYNTHETIC_NON_EVIDENCE"
    assert {row["evidence_origin"] for row in outputs} == {"SYNTHETIC_NON_EVIDENCE"}


def test_partial_write_failure_removes_the_entire_run_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _runner()
    _, _, _, paths = _install_valid_gates(monkeypatch, runner, tmp_path)
    real_write = runner._write_atomic
    calls = 0

    def fail_second_write(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected partial write failure")
        real_write(path, payload)

    monkeypatch.setattr(runner, "_write_atomic", fail_second_write)
    output_root = tmp_path / "output"
    output_root.mkdir()

    with pytest.raises(OSError, match="injected partial write failure"):
        runner.run_development_execution(
            bundle_root=tmp_path / "ignored",
            request_manifest_path=paths[0],
            authority_record_path=paths[1],
            allowed_signers_path=paths[2],
            signature_path=paths[3],
            output_root=output_root,
            run_id="phase3-atomic-red",
            adapter_name="stub",
        )

    assert not (output_root / "phase3-atomic-red").exists()


def test_runner_has_no_confirmatory_input_surface() -> None:
    runner = _runner()
    parameters = runner.run_development_execution.__annotations__
    assert "confirmatory_bundle_root" not in parameters
    assert "confirmatory_manifest_path" not in parameters
