"""Reporting helpers for E7 Foundry gas/state evidence."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e7_evm import (
    E7Bundle,
    E7MeasurementContract,
    E7MeasurementRow,
    E7ParityAttachment,
    E7_PUBLICATION_SCOPE,
    PUBLICATION_EVIDENCE_AUTHORIZED,
    load_default_parity_attachment,
    parse_foundry_measurement_report,
    repo_root,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class T12Row(_FrozenModel):
    operation: str
    batch_size: int = Field(gt=0)
    gas_used: int = Field(ge=0)
    storage_delta_bytes: int = Field(ge=0)
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


def _canonical_bundle(bundle: E7Bundle) -> E7Bundle:
    return parse_foundry_measurement_report(
        report_path=Path(bundle.raw_report_path),
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


def publication_precheck_reasons(
    bundle: E7Bundle,
    *,
    contract: E7MeasurementContract | None = None,
    parity_attachment: E7ParityAttachment | None = None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if contract is None:
        reasons.append("E7 publication support requires an explicit measurement contract")
        return tuple(reasons)
    if parity_attachment is None:
        reasons.append("E7 publication support requires a Task 8 parity attachment")
        return tuple(reasons)
    if bundle.run_config_snapshot.origin is not EvidenceOrigin.FOUNDRY_MEASUREMENT:
        reasons.append("bundle.run_config_snapshot.origin must equal FOUNDRY_MEASUREMENT")
    if bundle.run_config_snapshot.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        reasons.append("bundle.run_config_snapshot.authorization_scope must equal PUBLICATION_EVIDENCE_AUTHORIZED")
    if bundle.run_config_snapshot.experiment_id != "E7":
        reasons.append("bundle.run_config_snapshot.experiment_id must equal E7")
    if reasons:
        return tuple(dict.fromkeys(reasons))
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
    if len({row.publication_scope for row in bundle.rows}) != 1 or bundle.rows[0].publication_scope != E7_PUBLICATION_SCOPE:
        reasons.append("rows.publication_scope must exactly match E7_FOUNDRY_PUBLICATION_V1")
    parity_ok, parity_reasons = _verify_parity_attachment(parity_attachment)
    if not parity_ok:
        reasons.extend(parity_reasons)
    if any(row.gas_used > bundle.manifest.block_gas_limit for row in bundle.rows):
        reasons.append("one or more measured operations exceed the local block gas limit")
    return tuple(dict.fromkeys(reasons))


def t12_rows(rows: tuple[E7MeasurementRow, ...] | list[E7MeasurementRow]) -> tuple[T12Row, ...]:
    ordered = sorted(rows, key=lambda row: (row.operation.value, row.batch_size))
    return tuple(
        T12Row(
            operation=row.operation.value,
            batch_size=row.batch_size,
            gas_used=row.gas_used,
            storage_delta_bytes=row.storage_delta_bytes,
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
    parity_ok = not reasons or all("parity" not in reason.lower() and "Task 8" not in reason for reason in reasons)
    return E7Summary(
        claim_id="E7_LOCAL_EVM_BOUNDEDNESS_AND_PARITY",
        measurement_count=len(bundle.rows),
        max_gas_used=max(row.gas_used for row in bundle.rows),
        max_fraction_of_block_limit=max(row.gas_used / row.block_gas_limit for row in bundle.rows),
        block_boundedness_all=block_boundedness_all,
        parity_bound=parity_ok,
        claim_disposition="SUPPORTED" if not reasons and block_boundedness_all else "INCONCLUSIVE",
    )

