from __future__ import annotations

import json
from pathlib import Path

import pytest

from poi_mpp.evidence.config import config_hash, load_run_config
from poi_mpp.experiments.e7_evm import (
    E7Bundle,
    E7CollectorCapability,
    E7CommandTranscript,
    E7ContractArtifact,
    E7Manifest,
    E7MeasurementRow,
    E7Operation,
    E7ParityVerification,
    E7ReportAuthority,
    row_hash,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_CONFIG_PATH = REPO_ROOT / "configs" / "publication_foundry" / "e7.run.yaml"


def _internal_bundle(tmp_path: Path) -> E7Bundle:
    run_config = load_run_config(RUN_CONFIG_PATH)
    run_config_hash = config_hash(run_config)
    raw_report_hash = "a" * 64
    canonical_report_path = REPO_ROOT / "contracts" / "out" / "e7_foundry_measurements.json"
    row_payload = {
        "run_id": run_config.run_id,
        "experiment_id": "E7",
        "measurement_key": "MODEL_REGISTER:1",
        "operation": E7Operation.MODEL_REGISTER,
        "batch_size": 1,
        "origin": "FOUNDRY_MEASUREMENT",
        "publication_scope": "E7_FOUNDRY_PUBLICATION_V1",
        "gas_used": 21_000,
        "gas_unit": "gas",
        "changed_storage_slot_count": 2,
        "storage_change_upper_bound_bytes": 64,
        "storage_unit": "bytes_upper_bound",
        "test_contract": "GasSnapshots",
        "witness_contract": "GasSnapshotWitness",
        "chain_id": 31_337,
        "block_gas_limit": 30_000_000,
        "compiler_version": "0.8.24+commit.e11b9ed9",
        "optimizer_enabled": True,
        "optimizer_runs": 200,
        "foundry_version": "forge Version: test",
        "git_revision": "1" * 40,
        "raw_report_hash": raw_report_hash,
        "run_config_snapshot": run_config.model_dump(mode="json"),
        "run_config_hash": run_config_hash,
    }
    row = E7MeasurementRow.model_validate(
        {**row_payload, "row_hash": row_hash(row_payload)}
    )
    manifest = E7Manifest(
        contracts_root=str((REPO_ROOT / "contracts").resolve()),
        foundry_version=row.foundry_version,
        compiler_version=row.compiler_version,
        optimizer_enabled=True,
        optimizer_runs=200,
        git_revision=row.git_revision,
        git_dirty=False,
        chain_id=row.chain_id,
        block_gas_limit=row.block_gas_limit,
        raw_report_hash=raw_report_hash,
        canonical_report_path=str(canonical_report_path.resolve()),
        test_contract=row.test_contract,
        witness_contract=row.witness_contract,
        gas_measurement_surface="CALL_BODY_GASLEFT_DELTA_EXCLUDES_TEST_HARNESS",
        storage_measurement_surface="POST_CALL_SLOT_DIFF_VS_FRESH_BASELINE_BYTES_UPPER_BOUND",
        command=(
            str((tmp_path / "external-forge").resolve()),
            str((REPO_ROOT / "contracts" / "test" / "GasSnapshots.t.sol").resolve()),
        ),
        artifacts=(
            E7ContractArtifact(
                contract_name="ModelRegistry",
                source_path=str((REPO_ROOT / "contracts" / "src" / "ModelRegistry.sol").resolve()),
                source_hash="2" * 64,
                creation_bytecode_hash="3" * 64,
                deployed_bytecode_hash="4" * 64,
            ),
        ),
    )
    return E7Bundle(
        raw_report_path=str(canonical_report_path.resolve()),
        raw_report_hash=raw_report_hash,
        collector_capability=E7CollectorCapability(
            report_authority=E7ReportAuthority.CANONICAL_COLLECTOR_REPORT,
            observed_report_path=str(canonical_report_path.resolve()),
            canonical_report_path=str(canonical_report_path.resolve()),
            anchored_no_follow=True,
            symlink_free=True,
        ),
        run_config_snapshot=run_config,
        run_config_hash=run_config_hash,
        rows=(row,),
        manifest=manifest,
    )


def test_public_e7_bundle_is_model_valid_and_contains_no_machine_absolute_paths(tmp_path: Path):
    from poi_mpp.experiments.e7_evm import public_e7_bundle

    internal = _internal_bundle(tmp_path)
    public = public_e7_bundle(internal, repo_root=REPO_ROOT)
    serialized = json.dumps(public.model_dump(mode="json"), sort_keys=True)

    assert E7Bundle.model_validate_json(serialized) == public
    assert str(REPO_ROOT) not in serialized
    assert "/Users/" not in serialized
    assert "file://" not in serialized
    assert public.raw_report_path == "contracts/out/e7_foundry_measurements.json"
    assert public.collector_capability.observed_report_path == public.raw_report_path
    assert public.collector_capability.canonical_report_path == public.manifest.canonical_report_path
    assert public.manifest.contracts_root == "contracts"
    assert public.manifest.artifacts[0].source_path == "contracts/src/ModelRegistry.sol"
    assert public.manifest.command == (
        "external-forge",
        "contracts/test/GasSnapshots.t.sol",
    )
    assert public.rows == internal.rows
    assert public.run_config_hash == internal.run_config_hash


def test_publication_entrypoint_writes_sanitized_bundle_only_after_live_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import poi_mpp.reporting.e7 as reporting

    internal = _internal_bundle(tmp_path)
    output_path = tmp_path / "publication" / "e7_bundle.json"
    observed: list[str] = []

    monkeypatch.setattr(reporting, "assert_cli_authority_boundary", lambda run_config: observed.append("authority"))
    transcript = E7CommandTranscript(
        command=("verification",),
        cwd=".",
        stdout_hash="5" * 64,
        stderr_hash="6" * 64,
        stdout_size=0,
        stderr_size=0,
    )
    parity = E7ParityVerification(
        source_closure_hash="7" * 64,
        source_paths=("src/poi_mpp/evidence/canonical.py",),
        protocol_vectors_path="tests/fixtures/protocol_vectors.json",
        protocol_vectors_hash="8" * 64,
        protocol_witness_path="contracts/out/protocol_witnesses.json",
        protocol_witness_hash="9" * 64,
        export_vectors_transcript=transcript,
        hashvectors_test_transcript=transcript,
        python_parity_transcript=transcript,
    )
    monkeypatch.setattr(reporting, "verify_current_e7_parity", lambda **kwargs: observed.append("parity") or parity)

    def fake_collect(**kwargs):
        observed.append("collect")
        assert kwargs["output_path"] is None
        return internal

    monkeypatch.setattr(reporting, "collect_foundry_measurements", fake_collect)

    def fail_live_checks(*args, **kwargs):
        observed.append("live-checks")
        raise RuntimeError("live verification failed")

    monkeypatch.setattr(reporting, "_live_publication_reasons", fail_live_checks)
    with pytest.raises(RuntimeError, match="live verification failed"):
        reporting.collect_and_summarize_e7_publication(
            contracts_root=REPO_ROOT / "contracts",
            run_config=internal.run_config_snapshot,
            bundle_output_path=output_path,
        )
    assert observed == ["authority", "parity", "collect", "live-checks"]
    assert not output_path.exists()

    monkeypatch.setattr(reporting, "_live_publication_reasons", lambda *args, **kwargs: ())
    result = reporting.collect_and_summarize_e7_publication(
        contracts_root=REPO_ROOT / "contracts",
        run_config=internal.run_config_snapshot,
        bundle_output_path=output_path,
    )

    public = E7Bundle.model_validate_json(output_path.read_text(encoding="utf-8"))
    assert str(REPO_ROOT) not in output_path.read_text(encoding="utf-8")
    assert public.rows == result.bundle.rows == internal.rows
    assert result.bundle.raw_report_path == internal.raw_report_path
