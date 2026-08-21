from __future__ import annotations

import json
from pathlib import Path

import pytest

from poi_mpp.evidence import ArtifactValidationError
from poi_mpp.evidence.config import RunConfig, approved_schema_hash
from poi_mpp.evidence.models import EvidenceOrigin


def _run_config(
    *,
    run_id: str = "run-e7",
    authorization_scope: str = "PUBLICATION_EVIDENCE_AUTHORIZED",
    origin: EvidenceOrigin = EvidenceOrigin.FOUNDRY_MEASUREMENT,
) -> RunConfig:
    return RunConfig.model_validate(
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": run_id,
            "experiment_id": "E7",
            "origin": origin,
            "authorization_scope": authorization_scope,
            "model_hash": "5" * 64,
            "dataset_hash": "6" * 64,
            "parent_hashes": (),
            "data_availability": {
                "total_shards": 16,
                "samples": 8,
                "replacement": False,
            },
        }
    )


def _contracts_root() -> Path:
    return Path(__file__).resolve().parents[2] / "contracts"


def _measurement(operation: str, batch_size: int, gas_used: int, changed_slot_count: int) -> dict[str, object]:
    return {
        "operation": operation,
        "batch_size": batch_size,
        "gas_used": gas_used,
        "changed_storage_slot_count": changed_slot_count,
        "storage_change_upper_bound_bytes": changed_slot_count * 32,
    }


def _write_report(path: Path, *, measurements: list[dict[str, object]]) -> Path:
    payload = {
        "schema_version": "POI_MPP_E7_FOUNDRY_REPORT_V1",
        "test_contract": "GasSnapshots",
        "witness_contract": "GasSnapshotWitness",
        "chain_id": 31337,
        "block_gas_limit": 30_000_000,
        "measurements": measurements,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_empty_foundry_report_is_not_success(tmp_path: Path):
    from poi_mpp.experiments.e7_evm import parse_foundry_measurement_report

    report = tmp_path / "empty.json"
    report.write_text("", encoding="utf-8")

    with pytest.raises(ArtifactValidationError):
        parse_foundry_measurement_report(
            report_path=report,
            contracts_root=_contracts_root(),
            run_config=_run_config(),
        )


def test_duplicate_measurement_keys_are_rejected(tmp_path: Path):
    from poi_mpp.experiments.e7_evm import parse_foundry_measurement_report

    report = _write_report(
        tmp_path / "duplicate.json",
        measurements=[
            _measurement("MODEL_REGISTER", 1, 21_000, 4),
            _measurement("MODEL_REGISTER", 1, 22_000, 4),
        ],
    )

    with pytest.raises(ArtifactValidationError, match="duplicate"):
        parse_foundry_measurement_report(
            report_path=report,
            contracts_root=_contracts_root(),
            run_config=_run_config(),
        )


def test_plumbing_report_parses_but_stays_non_authoritative(tmp_path: Path):
    from poi_mpp.experiments.e7_evm import (
        E7ReportAuthority,
        default_measurement_contract,
        parse_foundry_measurement_report,
    )

    contract = default_measurement_contract()
    report = _write_report(
        tmp_path / "valid.json",
        measurements=[
            _measurement(item.operation, item.batch_size, 20_000 + index, index + 1)
            for index, item in enumerate(contract.expected_measurements)
        ],
    )

    bundle = parse_foundry_measurement_report(
        report_path=report,
        contracts_root=_contracts_root(),
        run_config=_run_config(),
    )

    assert bundle.rows
    assert all(row.gas_unit == "gas" and row.storage_unit == "bytes_upper_bound" for row in bundle.rows)
    assert bundle.manifest.compiler_version == "0.8.24+commit.e11b9ed9"
    assert bundle.manifest.optimizer_enabled is True
    assert bundle.manifest.optimizer_runs == 200
    assert bundle.collector_capability.report_authority is E7ReportAuthority.PLUMBING_FIXTURE
    assert bundle.manifest.gas_measurement_surface == "CALL_BODY_GASLEFT_DELTA_EXCLUDES_TEST_HARNESS"
    assert bundle.manifest.storage_measurement_surface == "POST_CALL_SLOT_DIFF_VS_FRESH_BASELINE_BYTES_UPPER_BOUND"


def test_publication_support_requires_canonical_collector_contract_parity_and_authorized_config(tmp_path: Path):
    from poi_mpp.experiments.e7_evm import (
        default_measurement_contract,
        load_default_parity_attachment,
        parse_foundry_measurement_report,
    )
    from poi_mpp.reporting.e7 import publication_precheck_reasons, summarize_e7_bundle

    contract = default_measurement_contract()
    report = _write_report(
        tmp_path / "support.json",
        measurements=[
            _measurement(item.operation, item.batch_size, 25_000 + index, index + 2)
            for index, item in enumerate(contract.expected_measurements)
        ],
    )

    bundle = parse_foundry_measurement_report(
        report_path=report,
        contracts_root=_contracts_root(),
        run_config=_run_config(),
    )

    assert "measurement contract" in publication_precheck_reasons(bundle)[0].lower()
    parity = load_default_parity_attachment(Path(__file__).resolve().parents[2])
    reasons = publication_precheck_reasons(bundle, contract=contract, parity_attachment=parity)
    assert any("canonical collector-owned" in reason for reason in reasons)
    assert summarize_e7_bundle(bundle, contract=contract, parity_attachment=parity).claim_disposition == "INCONCLUSIVE"

    unauthorized_bundle = parse_foundry_measurement_report(
        report_path=report,
        contracts_root=_contracts_root(),
        run_config=_run_config(authorization_scope="LOCAL_TEST_ONLY"),
    )
    assert "authorization_scope" in " ".join(
        publication_precheck_reasons(
            unauthorized_bundle,
            contract=contract,
            parity_attachment=parity,
        )
    )


def test_symlinked_report_is_rejected(tmp_path: Path):
    from poi_mpp.experiments.e7_evm import default_measurement_contract, parse_foundry_measurement_report

    target = _write_report(
        tmp_path / "target.json",
        measurements=[
            _measurement(item.operation, item.batch_size, 31_000 + index, 2)
            for index, item in enumerate(default_measurement_contract().expected_measurements)
        ],
    )
    symlink_path = tmp_path / "symlink.json"
    symlink_path.symlink_to(target)

    with pytest.raises(ArtifactValidationError, match="symlink"):
        parse_foundry_measurement_report(
            report_path=symlink_path,
            contracts_root=_contracts_root(),
            run_config=_run_config(),
        )


def test_forged_rows_do_not_mint_support(tmp_path: Path):
    from poi_mpp.experiments.e7_evm import (
        default_measurement_contract,
        load_default_parity_attachment,
        parse_foundry_measurement_report,
    )
    from poi_mpp.reporting.e7 import publication_precheck_reasons

    contract = default_measurement_contract()
    report = _write_report(
        tmp_path / "forged.json",
        measurements=[
            _measurement(item.operation, item.batch_size, 31_000 + index, 2)
            for index, item in enumerate(contract.expected_measurements)
        ],
    )
    bundle = parse_foundry_measurement_report(
        report_path=report,
        contracts_root=_contracts_root(),
        run_config=_run_config(),
    )
    forged_row = bundle.rows[0].model_copy(update={"gas_used": bundle.rows[0].gas_used + 1})
    forged_bundle = bundle.model_copy(update={"rows": (forged_row, *bundle.rows[1:])})

    reasons = publication_precheck_reasons(
        forged_bundle,
        contract=contract,
        parity_attachment=load_default_parity_attachment(Path(__file__).resolve().parents[2]),
    )
    assert any("canonical" in reason.lower() or "raw report" in reason.lower() for reason in reasons)


def test_gas_harness_has_no_pre_measurement_vm_load():
    contract_path = _contracts_root() / "test" / "GasSnapshots.t.sol"
    contents = contract_path.read_text(encoding="utf-8")

    witness_names = (
        "witnessModelRegister",
        "witnessTaskCreate",
        "witnessCommitResponse",
        "witnessAuditOpen",
        "witnessAuditRecordResult",
        "witnessAuditRecordDa",
        "witnessOpenChallenge",
        "witnessReceiptMintPending",
        "witnessReceiptActivate",
        "witnessReceiptMarkChallenged",
        "witnessReceiptSlash",
        "witnessCreditAllocate",
    )
    for witness_name in witness_names:
        start = contents.index(f"function {witness_name}")
        gas_before = contents.index("uint256 gasBefore = gasleft();", start)
        assert "vm.load(" not in contents[start:gas_before], f"{witness_name} must not pre-warm measured storage"


@pytest.mark.skipif(not (_contracts_root() / "foundry.toml").is_file(), reason="contracts workspace unavailable")
def test_local_collection_runs_with_foundry(tmp_path: Path):
    from poi_mpp.experiments.e7_evm import (
        E7ReportAuthority,
        collect_foundry_measurements,
        default_measurement_contract,
    )

    bundle = collect_foundry_measurements(
        contracts_root=_contracts_root(),
        run_config=_run_config(),
        output_path=tmp_path / "bundle.json",
        measurement_contract=default_measurement_contract(),
    )

    assert len(bundle.rows) == len(default_measurement_contract().expected_measurements)
    assert all(row.origin is EvidenceOrigin.FOUNDRY_MEASUREMENT for row in bundle.rows)
    assert bundle.manifest.foundry_version.startswith("forge Version:")
    assert bundle.collector_capability.report_authority is E7ReportAuthority.CANONICAL_COLLECTOR_REPORT
    assert bundle.collector_capability.anchored_no_follow is True
    assert bundle.collector_capability.symlink_free is True
