"""Reporting helpers for E7 Foundry gas/state evidence."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e7_evm import (
    E7Bundle,
    E7CommandTranscript,
    E7ParityVerification,
    E7MeasurementContract,
    E7MeasurementRow,
    E7ParityAttachment,
    PUBLICATION_EVIDENCE_AUTHORIZED,
    _path_hash,
    assert_cli_authority_boundary,
    collect_foundry_measurements,
    current_e7_parity_source_closure_hash,
    default_measurement_contract,
    load_default_parity_attachment,
    parse_foundry_measurement_report,
    repo_root,
    verify_current_e7_parity,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class T12Row(_FrozenModel):
    operation: str
    batch_size: int = Field(gt=0)
    gas_used: int = Field(ge=0)
    changed_storage_slot_count: int = Field(ge=0)
    storage_change_upper_bound_bytes: int = Field(ge=0)
    fraction_of_block_limit: float = Field(ge=0.0)


class F12Point(_FrozenModel):
    operation: str
    batch_size: int = Field(gt=0)
    gas_used: int = Field(ge=0)


class E7Summary(_FrozenModel):
    schema_version: str = "POI_MPP_E7_SUMMARY_V1"
    claim_id: str
    measurement_count: int = Field(gt=0)
    max_gas_used: int = Field(ge=0)
    max_fraction_of_block_limit: float = Field(ge=0.0)
    block_boundedness_all: bool
    parity_bound: bool
    claim_disposition: str


class E7PublicationResult(_FrozenModel):
    schema_version: str = "POI_MPP_E7_PUBLICATION_RESULT_V1"
    bundle: E7Bundle
    parity_verification: E7ParityVerification
    summary: E7Summary


def _canonical_bundle(bundle: E7Bundle) -> E7Bundle:
    return parse_foundry_measurement_report(
        report_path=Path(bundle.collector_capability.canonical_report_path),
        contracts_root=Path(bundle.manifest.contracts_root),
        run_config=bundle.run_config_snapshot,
    )


def _verify_parity_attachment(attachment: E7ParityAttachment) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    vectors_path = Path(attachment.protocol_vectors_path)
    report_path = Path(attachment.task8_report_path)
    if not vectors_path.is_file():
        reasons.append("Task 8 protocol vectors path is missing")
    if not report_path.is_file():
        reasons.append("Task 8 report path is missing")
    if reasons:
        return False, tuple(reasons)
    from poi_mpp.experiments.e7_evm import load_default_parity_attachment

    canonical = load_default_parity_attachment(repo_root())
    if canonical.protocol_vectors_hash != attachment.protocol_vectors_hash:
        reasons.append("Task 8 protocol vectors hash does not match canonical parity attachment")
    if canonical.task8_report_hash != attachment.task8_report_hash:
        reasons.append("Task 8 report hash does not match canonical parity attachment")
    return (not reasons, tuple(reasons))


def _verify_live_parity(parity: E7ParityVerification) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    vectors_path = Path(parity.protocol_vectors_path)
    witness_path = Path(parity.protocol_witness_path)
    if not vectors_path.is_file():
        reasons.append("current Task 8 vectors file is missing")
    if not witness_path.is_file():
        reasons.append("current Task 8 witness file is missing")
    try:
        current_closure = current_e7_parity_source_closure_hash(repo_root())
    except Exception as error:
        reasons.append(f"unable to recompute current parity source closure: {error}")
        return False, tuple(dict.fromkeys(reasons))
    if current_closure != parity.source_closure_hash:
        reasons.append("current parity source closure hash does not match the live verification result")
    if vectors_path.is_file() and parity.protocol_vectors_hash != _path_hash(vectors_path):
        reasons.append("current Task 8 vectors hash does not match the live verification result")
    if witness_path.is_file() and parity.protocol_witness_hash != _path_hash(witness_path):
        reasons.append("current Task 8 witness hash does not match the live verification result")
    transcripts: tuple[E7CommandTranscript, ...] = (
        parity.export_vectors_transcript,
        parity.hashvectors_test_transcript,
        parity.python_parity_transcript,
    )
    if any(transcript.returncode != 0 for transcript in transcripts):
        reasons.append("all live parity transcripts must have returncode 0")
    return (not reasons, tuple(dict.fromkeys(reasons)))


def _metadata_only_reasons(
    bundle: E7Bundle,
    *,
    contract: E7MeasurementContract | None = None,
    parity_attachment: E7ParityAttachment | None = None,
) -> tuple[str, ...]:
    reasons = [
        "stored E7 bundle metadata cannot mint SUPPORTED; rerun collect_and_summarize_e7_publication for any publication claim",
    ]
    if contract is None:
        reasons.append("E7 publication support requires an explicit measurement contract")
        return tuple(reasons)
    if parity_attachment is None:
        reasons.append("serialized Task 8 parity attachment is metadata only and cannot authorize support")
        return tuple(reasons)
    if not _verify_parity_attachment(parity_attachment)[0]:
        reasons.extend(_verify_parity_attachment(parity_attachment)[1])
    if bundle.run_config_snapshot.origin is not EvidenceOrigin.FOUNDRY_MEASUREMENT:
        reasons.append("bundle.run_config_snapshot.origin must equal FOUNDRY_MEASUREMENT")
    if bundle.run_config_snapshot.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        reasons.append("bundle.run_config_snapshot.authorization_scope must equal PUBLICATION_EVIDENCE_AUTHORIZED")
    if bundle.run_config_snapshot.experiment_id != "E7":
        reasons.append("bundle.run_config_snapshot.experiment_id must equal E7")
    try:
        canonical = _canonical_bundle(bundle)
    except Exception as error:
        reasons.append(f"unable to reparse canonical E7 bundle from raw report: {error}")
        return tuple(dict.fromkeys(reasons))
    if canonical.model_dump(mode="json") != bundle.model_dump(mode="json"):
        reasons.append("bundle does not match canonical E7 reparse from raw report")
    expected_keys = {item.key for item in contract.expected_measurements}
    observed_keys = {row.measurement_key for row in bundle.rows}
    if expected_keys != observed_keys:
        reasons.append("rows.measurement_key set must exactly close against the measurement contract")
    return tuple(dict.fromkeys(reasons))


def _live_publication_reasons(
    bundle: E7Bundle,
    *,
    contract: E7MeasurementContract,
    parity_verification: E7ParityVerification,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if bundle.run_config_snapshot.origin is not EvidenceOrigin.FOUNDRY_MEASUREMENT:
        reasons.append("bundle.run_config_snapshot.origin must equal FOUNDRY_MEASUREMENT")
    if bundle.run_config_snapshot.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        reasons.append("bundle.run_config_snapshot.authorization_scope must equal PUBLICATION_EVIDENCE_AUTHORIZED")
    if bundle.run_config_snapshot.experiment_id != "E7":
        reasons.append("bundle.run_config_snapshot.experiment_id must equal E7")
    try:
        canonical = _canonical_bundle(bundle)
    except Exception as error:
        reasons.append(f"unable to reparse canonical E7 bundle from raw report: {error}")
        return tuple(dict.fromkeys(reasons))
    if canonical.model_dump(mode="json") != bundle.model_dump(mode="json"):
        reasons.append("bundle does not match canonical E7 reparse from raw report")
    expected_keys = {item.key for item in contract.expected_measurements}
    observed_keys = {row.measurement_key for row in bundle.rows}
    if expected_keys != observed_keys:
        reasons.append("rows.measurement_key set must exactly close against the measurement contract")
    if bundle.manifest.test_contract != contract.required_test_contract:
        reasons.append("manifest.test_contract must exactly match the measurement contract")
    if bundle.manifest.witness_contract != contract.required_witness_contract:
        reasons.append("manifest.witness_contract must exactly match the measurement contract")
    if bundle.manifest.raw_report_hash != bundle.raw_report_hash:
        reasons.append("manifest.raw_report_hash must exactly match bundle.raw_report_hash")
    if any(row.gas_used > bundle.manifest.block_gas_limit for row in bundle.rows):
        reasons.append("one or more measured operations exceed the local block gas limit")
    parity_ok, parity_reasons = _verify_live_parity(parity_verification)
    if not parity_ok:
        reasons.extend(parity_reasons)
    return tuple(dict.fromkeys(reasons))


def publication_precheck_reasons(
    bundle: E7Bundle,
    *,
    contract: E7MeasurementContract | None = None,
    parity_attachment: E7ParityAttachment | None = None,
) -> tuple[str, ...]:
    return _metadata_only_reasons(bundle, contract=contract, parity_attachment=parity_attachment)


def t12_rows(rows: tuple[E7MeasurementRow, ...] | list[E7MeasurementRow]) -> tuple[T12Row, ...]:
    ordered = sorted(rows, key=lambda row: (row.operation.value, row.batch_size))
    return tuple(
        T12Row(
            operation=row.operation.value,
            batch_size=row.batch_size,
            gas_used=row.gas_used,
            changed_storage_slot_count=row.changed_storage_slot_count,
            storage_change_upper_bound_bytes=row.storage_change_upper_bound_bytes,
            fraction_of_block_limit=row.gas_used / row.block_gas_limit,
        )
        for row in ordered
    )


def f12_points(rows: tuple[E7MeasurementRow, ...] | list[E7MeasurementRow]) -> tuple[F12Point, ...]:
    return tuple(
        F12Point(
            operation=row.operation.value,
            batch_size=row.batch_size,
            gas_used=row.gas_used,
        )
        for row in sorted(rows, key=lambda item: (item.operation.value, item.batch_size))
    )


def summarize_e7_bundle(
    bundle: E7Bundle,
    *,
    contract: E7MeasurementContract | None = None,
    parity_attachment: E7ParityAttachment | None = None,
) -> E7Summary:
    reasons = publication_precheck_reasons(bundle, contract=contract, parity_attachment=parity_attachment)
    block_boundedness_all = all(row.gas_used <= row.block_gas_limit for row in bundle.rows)
    parity_ok = False
    return E7Summary(
        claim_id="E7_LOCAL_EVM_BOUNDEDNESS_AND_PARITY",
        measurement_count=len(bundle.rows),
        max_gas_used=max(row.gas_used for row in bundle.rows),
        max_fraction_of_block_limit=max(row.gas_used / row.block_gas_limit for row in bundle.rows),
        block_boundedness_all=block_boundedness_all,
        parity_bound=parity_ok,
        claim_disposition="INCONCLUSIVE",
    )


def collect_and_summarize_e7_publication(
    *,
    contracts_root: str | Path,
    run_config,
    bundle_output_path: str | Path,
    contract: E7MeasurementContract | None = None,
    timeout: int = 120,
) -> E7PublicationResult:
    assert_cli_authority_boundary(run_config)
    measurement_contract = E7MeasurementContract.model_validate(
        (default_measurement_contract() if contract is None else contract).model_dump(mode="json")
    )
    parity_verification = verify_current_e7_parity(
        repo_root=repo_root(),
        contracts_root=contracts_root,
        timeout=timeout,
    )
    bundle = collect_foundry_measurements(
        contracts_root=contracts_root,
        run_config=run_config,
        output_path=bundle_output_path,
        measurement_contract=measurement_contract,
        timeout=timeout,
    )
    reasons = _live_publication_reasons(
        bundle,
        contract=measurement_contract,
        parity_verification=parity_verification,
    )
    summary = E7Summary(
        claim_id="E7_LOCAL_EVM_BOUNDEDNESS_AND_PARITY",
        measurement_count=len(bundle.rows),
        max_gas_used=max(row.gas_used for row in bundle.rows),
        max_fraction_of_block_limit=max(row.gas_used / row.block_gas_limit for row in bundle.rows),
        block_boundedness_all=all(row.gas_used <= row.block_gas_limit for row in bundle.rows),
        parity_bound=not any("parity" in reason.lower() for reason in reasons),
        claim_disposition="SUPPORTED" if not reasons else "INCONCLUSIVE",
    )
    return E7PublicationResult(
        bundle=bundle,
        parity_verification=parity_verification,
        summary=summary,
    )
