"""Fail-closed loading for deterministic publication reporting."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any
from xml.etree import ElementTree
import zipfile

import pyarrow.parquet as pq
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence import (
    ArtifactValidationError,
    EvidenceOrigin,
    collect_environment,
    load_run_config,
    publication_build_environment_hash,
)
from poi_mpp.evidence.canonical import digest
from poi_mpp.experiments.e1_cost import E1MeasurementRow
from poi_mpp.experiments.e2_tamper import E2ReceiptRow
from poi_mpp.experiments.e4_da import E4ScenarioRow
from poi_mpp.experiments.e5_watcher import E5ScenarioRow, load_e5_confirmatory_contract
from poi_mpp.experiments.e6_sybil import E6ScenarioRow, load_e6_confirmatory_contract
from poi_mpp.experiments.e7_evm import E7Bundle, E7ParityAttachment, default_measurement_contract
from poi_mpp.experiments.e8_consensus import E8ScenarioRow, load_e8_confirmatory_contract
from poi_mpp.reporting.e1 import summarize_e1_rows
from poi_mpp.reporting.e2 import summarize_e2_rows
from poi_mpp.reporting.e3 import semantic_metrics
from poi_mpp.reporting.e4 import f8_points, summarize_e4_rows, t9_rows
from poi_mpp.reporting.e5 import summarize_e5_rows, t10_rows
from poi_mpp.reporting.e6 import f10_points, f9_points, summarize_e6_rows, t11_rows
from poi_mpp.reporting.e7 import collect_and_summarize_e7_publication, f12_points, summarize_e7_bundle, t12_rows
from poi_mpp.reporting.e8 import f11_points, summarize_e8_rows, t13_rows


E1_PUBLICATION_SCOPE = "E1_REAL_MODEL_PUBLICATION_V1"
E2_PUBLICATION_SCOPE = "E2_REAL_MODEL_PUBLICATION_V1"
E2_MEASUREMENT_DESIGN = "NARROW_SCOPE_PILOT"
E2_CLAIM_DISPOSITION_REASON = (
    "NARROW_SCOPE_PILOT is methodologically capped at INCONCLUSIVE; "
    "one model, one task, one layer, one token, one 4x4 activation slice, "
    "and four attack observations cannot support paper claim C2"
)
E2_FROZEN_SCOPE = {
    "model_count": 1,
    "task_count": 1,
    "layer_count": 1,
    "token_count": 1,
    "activation_slice": "4x4",
    "attack_observation_count": 4,
}
E3_PUBLICATION_SCOPE = "E3_CONFIRMATORY_PUBLICATION_V1"
E3_WAITING_EXTERNAL_REASON = "WAITING_EXTERNAL_EVALUATOR_AUTHORITY"
E3_EXPECTED_METRICS = {
    "FAR": (Decimal("0.5"), 2),
    "FRR": (Decimal("0.16666666666666666"), 6),
    "ABSTAIN": (Decimal("0.125"), 8),
    "coverage": (Decimal("0.875"), 8),
    "calibration": (Decimal("0.17840000000000003"), 7),
}
E3_EXPECTED_ARTIFACT_PATHS = {
    "T4": "publication/tables/T4_dataset_composition.json",
    "T8": "publication/tables/T8_semantic_verification.csv",
    "F7": "publication/figures/F7_semantic_verification_quality.svg",
}
E3_EXPECTED_RAW_MEMBER_PATHS = {
    "model_hash": "model_manifest.json",
    "config_hash": "config.json",
    "input_hash": "inputs.jsonl",
    "output_hash": "outputs.jsonl",
    "trace_hash": "trace.jsonl",
    "provenance_hash": "provenance.json",
}
E3_FORBIDDEN_MARKERS = (
    b"WAITING_EXTERNAL",
    b"SYNTHETIC_NON_EVIDENCE",
    b'"origin": null',
)
E3_RESULT_NOTE = "n=8 with invalid class n=2; no general semantic-reliability claim is admissible."
E4_PUBLICATION_SCOPE = "E4_CONFIRMATORY_PUBLICATION_V1"
E4_METHOD_BOUNDARY = "DECLARED_OUTCOME_PLAYBACK"
E4_INCONCLUSIVE_REASON = "DECLARED_OUTCOME_PLAYBACK_NOT_EXECUTED_RECONSTRUCTION"
_PUBLICATION_DISPOSITIONS = frozenset({"SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE", "MISSING", "WAITING_EXTERNAL"})
ARTIFACT_PLAN = {
    "E1": {"tables": ("T6",), "figures": ("F5",)},
    "E2": {"tables": ("T7",), "figures": ("F6",)},
    "E3": {"tables": ("T4", "T8"), "figures": ("F7",)},
    "E4": {"tables": ("T9",), "figures": ("F8",)},
    "E5": {"tables": ("T10",), "figures": ()},
    "E6": {"tables": ("T11",), "figures": ("F9", "F10")},
    "E7": {"tables": ("T12",), "figures": ("F12",)},
    "E8": {"tables": ("T13",), "figures": ("F11",)},
}
ARTIFACT_FILENAMES = {
    "T4": "tables/T4_dataset_composition.status.json",
    "T6": "tables/T6_single_pass_cost.csv",
    "T7": "tables/T7_execution_audit_security.csv",
    "T8": "tables/T8_semantic_verification.csv",
    "T9": "tables/T9_data_availability.csv",
    "T10": "tables/T10_watcher_dispute_economics.csv",
    "T11": "tables/T11_sybil_economics.csv",
    "T12": "tables/T12_evm_boundedness.csv",
    "T13": "tables/T13_consensus_safety.csv",
    "F5": "figures/F5_single_pass_cost.svg",
    "F6": "figures/F6_audit_soundness.svg",
    "F7": "figures/F7_semantic_verification_quality.svg",
    "F8": "figures/F8_da_withholding.svg",
    "F9": "figures/F9_sybil_advantage.svg",
    "F10": "figures/F10_economic_security.svg",
    "F11": "figures/F11_consensus_dynamics.svg",
    "F12": "figures/F12_evm_gas_state_scaling.svg",
}


class PublicationEligibilityError(ValueError):
    """Deterministic publication-build rejection."""

    def __init__(self, reasons: tuple[str, ...] | list[str] | str):
        if isinstance(reasons, str):
            reasons = (reasons,)
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__("; ".join(self.reasons))


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExperimentSource(_FrozenModel):
    rows_path: str | None = None
    summary_path: str | None = None
    metadata_path: str | None = None
    verified_receipt_path: str | None = None
    artifact_root_path: str | None = None
    run_config_path: str | None = None
    contract_path: str | None = None
    bundle_path: str | None = None
    parity_attachment_path: str | None = None
    replay_context_path: str | None = None
    contracts_root: str | None = None
    timeout_seconds: int = Field(default=120, ge=1, le=900)

    @model_validator(mode="after")
    def validate_known_shape(self) -> "ExperimentSource":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("experiment source must declare at least one path or timeout")
        return self


class ReportBuildSpec(_FrozenModel):
    artifact_root: str
    output_root: str
    sources: dict[str, ExperimentSource]
    write_status_figures: bool = True

    @field_validator("artifact_root", "output_root")
    @classmethod
    def require_nonblank_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("paths must not be blank")
        return value

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: dict[str, ExperimentSource]) -> dict[str, ExperimentSource]:
        unknown = sorted(set(value) - set(ARTIFACT_PLAN))
        if unknown:
            raise ValueError(f"unknown experiment source keys: {', '.join(unknown)}")
        return value


@dataclass(frozen=True)
class InputEntry:
    experiment_id: str
    input_role: str
    relative_path: str
    sha256: str
    schema_version: str | None
    origin: str | None
    disposition: str
    run_id: str | None
    config_hash: str | None
    paper_artifact_ids: tuple[str, ...]


@dataclass(frozen=True)
class GeneratedOutput:
    artifact_id: str
    relative_path: str
    kind: str
    schema_version: str | None
    run_id: str | None
    config_hash: str | None
    source_closure_hash: str | None
    derives_to_artifact_ids: tuple[str, ...]
    derived_from_input_paths: tuple[str, ...]


@dataclass(frozen=True)
class LoadedExperiment:
    experiment_id: str
    table_ids: tuple[str, ...]
    figure_ids: tuple[str, ...]
    claim_id: str
    origin: str | None
    disposition: str
    scope: str | None
    maturity: str
    run_id: str | None
    config_hash: str | None
    source_hashes: tuple[str, ...]
    table_rows: tuple[dict[str, Any], ...]
    figure_points: tuple[dict[str, Any], ...]
    summary: dict[str, Any] | None
    sample_size: int | None
    uncertainty: str | None
    limits: tuple[str, ...]
    omission_reason: str | None
    input_entries: tuple[InputEntry, ...]
    generated_outputs: tuple[GeneratedOutput, ...]


@dataclass(frozen=True)
class LoadedBundle:
    artifact_root: Path
    output_root: Path
    experiments: tuple[LoadedExperiment, ...]
    build_environment_hash: str
    generator_source_closure_hash: str


def experiment_artifact_ids(experiment_id: str) -> tuple[str, ...]:
    plan = ARTIFACT_PLAN[experiment_id]
    return tuple(plan["tables"]) + tuple(plan["figures"])


def _path_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _generator_source_closure_hash() -> str:
    root = Path(__file__).resolve().parents[3]
    relative_paths = (
        Path("src/poi_mpp/reporting/__init__.py"),
        Path("src/poi_mpp/reporting/load.py"),
        Path("src/poi_mpp/reporting/statistics.py"),
        Path("src/poi_mpp/reporting/tables.py"),
        Path("src/poi_mpp/reporting/figures.py"),
        Path("src/poi_mpp/reporting/manifest.py"),
        Path("scripts/build_artifact_manifest.py"),
        Path("scripts/generate_figures.py"),
        Path("scripts/report_all.py"),
        Path("pyproject.toml"),
        Path("requirements.lock"),
    )
    payload = {
        str(relative_path): _path_hash(root / relative_path)
        for relative_path in relative_paths
    }
    return digest("REPORT_GENERATOR_CLOSURE", payload)


def _reject_synthetic_origin(origin: str | None, *, experiment_id: str) -> None:
    if origin == EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value:
        raise PublicationEligibilityError((f"{experiment_id} synthetic non-evidence inputs cannot build publication artifacts",))


def _reject_nonfinite(value: Any, *, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise PublicationEligibilityError((f"non-finite numeric value at {path}",))
    if isinstance(value, dict):
        for key in sorted(value):
            _reject_nonfinite(value[key], path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_nonfinite(item, path=f"{path}[{index}]")


def _resolved_anchored_path(root: Path, candidate: str | Path) -> Path:
    path = Path(candidate)
    if not path.is_absolute():
        path = root / path
    try:
        resolved_root = root.resolve(strict=True)
    except FileNotFoundError as error:
        raise PublicationEligibilityError((f"artifact_root does not exist: {root}",)) from error
    current = path
    while True:
        try:
            candidate_stat = os.lstat(current)
        except OSError as error:
            raise PublicationEligibilityError((f"unable to stat input path: {current}",)) from error
        if os.path.islink(current):
            raise PublicationEligibilityError((f"symlinked input path is forbidden: {path}",))
        if current == resolved_root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise PublicationEligibilityError((f"configured input path is missing: {path}",)) from error
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise PublicationEligibilityError((f"path escapes artifact_root: {path}",)) from error
    if not resolved.is_file():
        raise PublicationEligibilityError((f"input path must be a regular file: {path}",))
    return resolved


def _load_json(root: Path, candidate: str | Path, *, label: str) -> tuple[Path, Any, str]:
    path = _resolved_anchored_path(root, candidate)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PublicationEligibilityError((f"{label} is not valid JSON: {path}",)) from error
    _reject_nonfinite(payload, path=label)
    return path, payload, _path_hash(path)


def _load_yaml_text(root: Path, candidate: str | Path, *, label: str) -> tuple[Path, str, str]:
    path = _resolved_anchored_path(root, candidate)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PublicationEligibilityError((f"unable to read {label}: {path}",)) from error
    return path, text, _path_hash(path)


def _load_parquet_rows(root: Path, candidate: str | Path, *, label: str) -> tuple[Path, tuple[dict[str, Any], ...], str]:
    path = _resolved_anchored_path(root, candidate)
    try:
        table = pq.read_table(path)
    except Exception as error:
        raise PublicationEligibilityError((f"{label} is not valid parquet: {path}",)) from error
    rows = table.to_pylist()
    if not rows:
        raise PublicationEligibilityError((f"{label} must contain at least one row",))
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PublicationEligibilityError((f"{label} row {index} must be an object",))
        _reject_nonfinite(row, path=f"{label}[{index}]")
        normalized.append(dict(row))
    return path, tuple(normalized), _path_hash(path)


def _rows_payload(root: Path, candidate: str | Path, *, label: str) -> tuple[tuple[dict[str, Any], ...], str]:
    _, payload, payload_hash = _load_json(root, candidate, label=label)
    rows: Any = payload
    if isinstance(payload, dict) and "rows" in payload:
        rows = payload["rows"]
    if not isinstance(rows, list) or not rows:
        raise PublicationEligibilityError((f"{label} must contain a non-empty rows list",))
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PublicationEligibilityError((f"{label} row {index} must be an object",))
        _reject_nonfinite(row, path=f"{label}.rows[{index}]")
        normalized.append(dict(row))
    return tuple(normalized), payload_hash


def _limits_from_summary(summary: dict[str, Any]) -> tuple[str, ...]:
    limits: list[str] = []
    for key in ("assumption_ledger", "residual_surface_ledger"):
        value = summary.get(key)
        if isinstance(value, list):
            limits.extend(str(item) for item in value if str(item).strip())
        elif isinstance(value, tuple):
            limits.extend(str(item) for item in value if str(item).strip())
    return tuple(dict.fromkeys(limits))


def _mapping_payload(payload: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PublicationEligibilityError((f"{label} must be a JSON object",))
    return dict(payload)


def _require_summary_alignment(
    *,
    summary_payload: dict[str, Any],
    canonical_summary: dict[str, Any],
    label: str,
    excluded_fields: frozenset[str] = frozenset(),
) -> None:
    mismatches: list[str] = []
    for key, canonical_value in canonical_summary.items():
        if key in excluded_fields:
            continue
        if key not in summary_payload:
            mismatches.append(f"{label}.{key} is missing")
            continue
        if summary_payload[key] != canonical_value:
            mismatches.append(f"{label}.{key} does not match canonical aggregation")
    if mismatches:
        raise PublicationEligibilityError(tuple(mismatches))


def _require_string_field(payload: dict[str, Any], key: str, *, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PublicationEligibilityError((f"{label}.{key} must be a non-blank string",))
    return value


def _require_hex_hash_field(payload: dict[str, Any], key: str, *, label: str) -> str:
    value = _require_string_field(payload, key, label=label)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise PublicationEligibilityError((f"{label}.{key} must be a lowercase 64-hex digest",))
    return value


def _resolved_anchored_directory(root: Path, candidate: str | Path, *, label: str) -> Path:
    path = Path(candidate)
    if not path.is_absolute():
        path = root / path
    try:
        resolved_root = root.resolve(strict=True)
    except FileNotFoundError as error:
        raise PublicationEligibilityError((f"artifact_root does not exist: {root}",)) from error
    current = path
    while True:
        try:
            os.lstat(current)
        except OSError as error:
            raise PublicationEligibilityError((f"unable to stat {label}: {current}",)) from error
        if os.path.islink(current):
            raise PublicationEligibilityError((f"symlinked {label} is forbidden: {path}",))
        if current == resolved_root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise PublicationEligibilityError((f"{label} is missing: {path}",)) from error
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise PublicationEligibilityError((f"{label} escapes artifact_root: {path}",)) from error
    if not resolved.is_dir():
        raise PublicationEligibilityError((f"{label} must be a directory: {path}",))
    return resolved


def _reject_non_evidence_markers(payload: bytes, *, label: str) -> None:
    for marker in E3_FORBIDDEN_MARKERS:
        if marker in payload:
            raise PublicationEligibilityError((f"{label} contains a placeholder or non-evidence marker",))


def _validated_e3_output_relative_path(*, artifact_id: str, receipt_path: str, run_id: str) -> str:
    expected = (
        f"results/publication/{run_id}/raw_e3_execution.zip"
        if artifact_id == "RAW_E3_EXECUTION"
        else E3_EXPECTED_ARTIFACT_PATHS[artifact_id]
    )
    if receipt_path != expected:
        raise PublicationEligibilityError((f"E3 {artifact_id} path must equal {expected}",))
    return receipt_path.removeprefix("publication/")


def _write_generated_output(output_root: Path, relative_path: str, payload: bytes) -> None:
    target = output_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def _validated_e3_metric_rows(
    *,
    payload: bytes,
    run_id: str,
    bindings: dict[str, str],
) -> list[dict[str, Any]]:
    required_fields = {
        "schema_version",
        "artifact_role",
        "experiment_id",
        "claim_id",
        "run_id",
        "evidence_origin",
        "metric",
        "value",
        "sample_count",
        *bindings.keys(),
    }
    try:
        text = payload.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames is None or set(reader.fieldnames) != required_fields:
            raise ValueError("CSV columns do not match the typed T8 contract")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error, ValueError) as error:
        raise PublicationEligibilityError((f"E3 T8 CSV is invalid: {error}",)) from error
    if not rows:
        raise PublicationEligibilityError(("E3 T8 must contain at least one metric row",))
    observed_metrics: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if row["schema_version"] != "POI_MPP_E3_T8_V1":
            raise PublicationEligibilityError(("E3 T8 schema_version must equal POI_MPP_E3_T8_V1",))
        if row["artifact_role"] != "SEMANTIC_METRICS":
            raise PublicationEligibilityError(("E3 T8 artifact_role must equal SEMANTIC_METRICS",))
        if row["experiment_id"] != "E3" or row["claim_id"] != "C3":
            raise PublicationEligibilityError(("E3 T8 must close over experiment E3 and claim C3",))
        if row["run_id"] != run_id:
            raise PublicationEligibilityError(("E3 T8 run_id must match the verified receipt run_id",))
        if row["evidence_origin"] != EvidenceOrigin.REAL_MODEL_EXECUTION.value:
            raise PublicationEligibilityError(("E3 T8 evidence_origin must equal REAL_MODEL_EXECUTION",))
        if any(row[key] != expected for key, expected in bindings.items()):
            raise PublicationEligibilityError(("E3 T8 execution bindings must match T4 execution bindings",))
        metric = row["metric"]
        if metric not in E3_EXPECTED_METRICS:
            raise PublicationEligibilityError((f"E3 T8 contains unsupported metric {metric}",))
        try:
            value = Decimal(row["value"])
            sample_count = int(row["sample_count"])
        except (InvalidOperation, ValueError) as error:
            raise PublicationEligibilityError((f"E3 T8 metric {metric} has an invalid value or sample_count",)) from error
        expected_value, expected_count = E3_EXPECTED_METRICS[metric]
        if value != expected_value or sample_count != expected_count:
            raise PublicationEligibilityError(("E3 metric values must match the attested publication contract",))
        observed_metrics.add(metric)
        normalized.append(
            {
                "metric": metric,
                "value": float(value),
                "sample_count": sample_count,
            }
        )
    if observed_metrics != set(E3_EXPECTED_METRICS):
        raise PublicationEligibilityError(("E3 T8 metric scope must exactly match the attested publication contract",))
    return sorted(normalized, key=lambda row: row["metric"])


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unwrap_verified_e3_import_receipt(
    receipt: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    if receipt.get("schema_version") == "POI_MPP_E3_RESULT_ATTESTATION_VERIFICATION_V1":
        return receipt, {}
    if receipt.get("schema_version") != "POI_MPP_E3_VERIFIED_IMPORT_RECEIPT_V1":
        raise PublicationEligibilityError(("E3 verification receipt has an unsupported schema_version",))
    if receipt.get("status") != "VERIFIED_E3_IMPORTED" or receipt.get("run_id") != "e3-confirmatory-real-20260824":
        raise PublicationEligibilityError(("E3 verified import receipt status or run_id is invalid",))
    authority = receipt.get("authority_verification")
    attestation = receipt.get("attestation_verification")
    if not isinstance(authority, dict) or not isinstance(attestation, dict):
        raise PublicationEligibilityError(("E3 verified import receipt must embed both canonical verifier outputs",))
    if authority.get("status") != "VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY" or authority.get("decision") != "APPROVED":
        raise PublicationEligibilityError(("E3 verified import receipt must preserve APPROVED authority verification",))
    if receipt.get("authority_verification_sha256") != _canonical_json_sha256(authority):
        raise PublicationEligibilityError(("E3 authority verifier output hash is invalid",))
    if receipt.get("attestation_verification_sha256") != _canonical_json_sha256(attestation):
        raise PublicationEligibilityError(("E3 attestation verifier output hash is invalid",))
    if receipt.get("metrics") != {
        "ABSTAIN": "0.125",
        "FAR": "0.500",
        "FRR": "0.167",
        "calibration": "0.178",
        "coverage": "0.875",
    }:
        raise PublicationEligibilityError(("E3 verified import receipt metrics drifted",))
    if receipt.get("metric_sample_counts") != {
        "ABSTAIN": 8,
        "FAR": 2,
        "FRR": 6,
        "calibration": 7,
        "coverage": 8,
    }:
        raise PublicationEligibilityError(("E3 verified import receipt metric denominators drifted",))
    if receipt.get("dataset_composition") != {
        "record_count": 8,
        "class_counts": {"invalid": 2, "valid": 6},
    }:
        raise PublicationEligibilityError(("E3 verified import receipt dataset composition drifted",))
    if receipt.get("decision") != {
        "alpha_sem": "0.25",
        "c3_disposition": "NOT_SUPPORTED",
        "reason": "FAR exceeds the frozen alpha_sem threshold",
    }:
        raise PublicationEligibilityError(("E3 verified import receipt C3 adjudication drifted",))
    caveats = receipt.get("caveats")
    caveat_text = " ".join(str(item).lower() for item in caveats) if isinstance(caveats, list) else ""
    if not all(term in caveat_text for term in ("identity", "independence", "private-key custody")):
        raise PublicationEligibilityError(("E3 verified import receipt omits the cryptographic trust boundary",))
    imported = receipt.get("imported_artifacts")
    if not isinstance(imported, list) or len(imported) != 4:
        raise PublicationEligibilityError(("E3 verified import receipt must bind exactly four imported artifacts",))
    imported_paths: dict[str, str] = {}
    attested_by_id = {
        item.get("artifact_id"): item
        for item in attestation.get("verified_artifacts", [])
        if isinstance(item, dict)
    }
    expected_filenames = {
        "F7": "F7_semantic_verification_quality.svg",
        "RAW_E3_EXECUTION": "raw_e3_execution.zip",
        "T4": "T4_dataset_composition.json",
        "T8": "T8_semantic_verification.csv",
    }
    for item in imported:
        if not isinstance(item, dict) or item.get("artifact_id") not in expected_filenames:
            raise PublicationEligibilityError(("E3 verified import receipt contains an invalid imported artifact",))
        artifact_id = str(item["artifact_id"])
        attested = attested_by_id.get(artifact_id)
        if not isinstance(attested, dict):
            raise PublicationEligibilityError(("E3 imported artifact lacks a matching attested artifact",))
        expected_target = f"results/publication/{receipt['run_id']}/source/{expected_filenames[artifact_id]}"
        if item.get("target_path") != expected_target or item.get("source_path") != attested.get("path"):
            raise PublicationEligibilityError(("E3 imported artifact lineage path drifted",))
        if item.get("sha256") != attested.get("sha256") or item.get("size_bytes") != attested.get("size_bytes"):
            raise PublicationEligibilityError(("E3 imported artifact lineage hash or size drifted",))
        imported_paths[artifact_id] = expected_filenames[artifact_id]
    if set(imported_paths) != set(expected_filenames):
        raise PublicationEligibilityError(("E3 verified import receipt imported artifact scope drifted",))
    return attestation, imported_paths


def _validate_e3_raw_bundle(*, path: Path, payload: bytes, run_id: str, bindings: dict[str, str]) -> None:
    if not zipfile.is_zipfile(path):
        raise PublicationEligibilityError(("E3 RAW_E3_EXECUTION must be a valid ZIP bundle",))
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        member_names = [info.filename for info in infos if not info.is_dir()]
        expected_members = {"run_manifest.json", *E3_EXPECTED_RAW_MEMBER_PATHS.values()}
        if set(member_names) != expected_members or len(member_names) != len(expected_members):
            raise PublicationEligibilityError(("E3 RAW_E3_EXECUTION member set must exactly match the typed raw contract",))
        for info in infos:
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts or member.as_posix() != info.filename or "\\" in info.filename:
                raise PublicationEligibilityError(("E3 RAW_E3_EXECUTION contains an unsafe archive path",))
            if stat.S_ISLNK(info.external_attr >> 16):
                raise PublicationEligibilityError(("E3 RAW_E3_EXECUTION may not contain symlinks",))
        try:
            manifest = json.loads(archive.read("run_manifest.json"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise PublicationEligibilityError(("E3 RAW run_manifest.json is invalid",)) from error
        if not isinstance(manifest, dict):
            raise PublicationEligibilityError(("E3 RAW run_manifest.json must be a JSON object",))
        if manifest.get("schema_version") != "POI_MPP_E3_RAW_EXECUTION_V1":
            raise PublicationEligibilityError(("E3 RAW schema_version must equal POI_MPP_E3_RAW_EXECUTION_V1",))
        if manifest.get("artifact_role") != "RAW_EXECUTION_BUNDLE":
            raise PublicationEligibilityError(("E3 RAW artifact_role must equal RAW_EXECUTION_BUNDLE",))
        if manifest.get("experiment_id") != "E3" or manifest.get("claim_id") != "C3":
            raise PublicationEligibilityError(("E3 RAW must close over experiment E3 and claim C3",))
        if manifest.get("run_id") != run_id:
            raise PublicationEligibilityError(("E3 RAW run_id must match the verified receipt run_id",))
        if manifest.get("evidence_origin") != EvidenceOrigin.REAL_MODEL_EXECUTION.value:
            raise PublicationEligibilityError(("E3 RAW evidence_origin must equal REAL_MODEL_EXECUTION",))
        if tuple(manifest.get("metric_scope", ())) != tuple(E3_EXPECTED_METRICS):
            raise PublicationEligibilityError(("E3 RAW metric_scope must equal the attested metric scope",))
        manifest_bindings = manifest.get("execution_bindings")
        if not isinstance(manifest_bindings, dict) or manifest_bindings != bindings:
            raise PublicationEligibilityError(("E3 RAW execution bindings must match T4 execution bindings",))
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != set(E3_EXPECTED_RAW_MEMBER_PATHS):
            raise PublicationEligibilityError(("E3 RAW files map must bind all six execution members",))
        for logical_name, member_path in E3_EXPECTED_RAW_MEMBER_PATHS.items():
            reference = files.get(logical_name)
            if not isinstance(reference, dict):
                raise PublicationEligibilityError((f"E3 RAW {logical_name} file binding must be a JSON object",))
            if reference.get("path") != member_path:
                raise PublicationEligibilityError((f"E3 RAW {logical_name} path must equal {member_path}",))
            actual = archive.read(member_path)
            actual_hash = hashlib.sha256(actual).hexdigest()
            if reference.get("sha256") != actual_hash or bindings[logical_name] != actual_hash:
                raise PublicationEligibilityError((f"E3 RAW {logical_name} must match the archive member bytes",))
            if int(reference.get("size_bytes", 0)) != len(actual):
                raise PublicationEligibilityError((f"E3 RAW {logical_name} size must match the archive member bytes",))


def _e3_loaded(root: Path, output_root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.verified_receipt_path is None or source.artifact_root_path is None:
        return _missing_experiment("E3", E3_WAITING_EXTERNAL_REASON)
    receipt_path, receipt_payload_raw, receipt_hash = _load_json(root, source.verified_receipt_path, label="E3 verification receipt")
    import_receipt = _mapping_payload(receipt_payload_raw, label="E3 verification receipt")
    receipt, imported_paths = _unwrap_verified_e3_import_receipt(import_receipt)
    source_root = _resolved_anchored_directory(root, source.artifact_root_path, label="E3 artifact root")
    if receipt.get("schema_version") != "POI_MPP_E3_RESULT_ATTESTATION_VERIFICATION_V1":
        raise PublicationEligibilityError(("E3 verification receipt schema_version must equal POI_MPP_E3_RESULT_ATTESTATION_VERIFICATION_V1",))
    if receipt.get("status") != "VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION":
        raise PublicationEligibilityError(("E3 requires a complete publication-scope E3 receipt",))
    if receipt.get("publication_eligibility_status") != "COMPLETE_INPUT_SET_REQUIRES_SEPARATE_C3_ADJUDICATION":
        raise PublicationEligibilityError(("E3 requires a complete publication-scope E3 receipt",))
    if receipt.get("authority_decision") != "APPROVED":
        raise PublicationEligibilityError(("E3 requires an APPROVED publication-scope receipt",))
    if receipt.get("publication_support_decision_status") != "NOT_EVALUATED_BY_THIS_ATTESTATION":
        raise PublicationEligibilityError(("E3 receipt must preserve post-execution-only publication support status",))
    if receipt.get("results_disposition") != "ATTESTED_AS_REPORTED":
        raise PublicationEligibilityError(("E3 receipt results_disposition must equal ATTESTED_AS_REPORTED",))
    run_id = _require_string_field(receipt, "run_id", label="E3 verification receipt")
    if receipt.get("experiment_id") != "E3" or receipt.get("claim_id") != "C3":
        raise PublicationEligibilityError(("E3 receipt must close over experiment E3 and claim C3",))
    if receipt.get("evidence_origin") != EvidenceOrigin.REAL_MODEL_EXECUTION.value:
        raise PublicationEligibilityError(("E3 receipt evidence_origin must equal REAL_MODEL_EXECUTION",))
    receipt_artifacts = receipt.get("verified_artifacts")
    if not isinstance(receipt_artifacts, list) or len(receipt_artifacts) != 4:
        raise PublicationEligibilityError(("E3 receipt must contain exactly four verified artifacts",))
    artifacts_by_id: dict[str, tuple[dict[str, Any], Path, bytes, str, str]] = {}
    for artifact in receipt_artifacts:
        if not isinstance(artifact, dict):
            raise PublicationEligibilityError(("E3 verified_artifact entries must be JSON objects",))
        artifact_id = _require_string_field(artifact, "artifact_id", label="E3 verified_artifact")
        if artifact_id not in {"T4", "T8", "F7", "RAW_E3_EXECUTION"}:
            raise PublicationEligibilityError((f"E3 receipt contains unsupported artifact_id {artifact_id}",))
        relative_path = _require_string_field(artifact, "path", label=f"E3 {artifact_id}")
        normalized = PurePosixPath(relative_path).as_posix()
        if normalized != relative_path or PurePosixPath(relative_path).is_absolute() or ".." in PurePosixPath(relative_path).parts:
            raise PublicationEligibilityError((f"E3 {artifact_id} path must be a normalized safe relative path",))
        resolved = _resolved_anchored_path(source_root, imported_paths.get(artifact_id, relative_path))
        payload = resolved.read_bytes()
        _reject_non_evidence_markers(payload, label=f"E3 {artifact_id}")
        sha256 = _require_hex_hash_field(artifact, "sha256", label=f"E3 {artifact_id}")
        if hashlib.sha256(payload).hexdigest() != sha256:
            raise PublicationEligibilityError((f"E3 {artifact_id} hash does not match the verified receipt",))
        size_bytes = artifact.get("size_bytes")
        if not isinstance(size_bytes, int) or size_bytes <= 0 or len(payload) != size_bytes:
            raise PublicationEligibilityError((f"E3 {artifact_id} size does not match the verified receipt",))
        output_relative_path = _validated_e3_output_relative_path(artifact_id=artifact_id, receipt_path=relative_path, run_id=run_id)
        artifacts_by_id[artifact_id] = (artifact, resolved, payload, sha256, output_relative_path)
    if set(artifacts_by_id) != {"T4", "T8", "F7", "RAW_E3_EXECUTION"}:
        raise PublicationEligibilityError(("E3 receipt must contain T4, T8, F7, and RAW_E3_EXECUTION",))

    try:
        t4_payload = json.loads(artifacts_by_id["T4"][2].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PublicationEligibilityError(("E3 T4 JSON is invalid",)) from error
    if not isinstance(t4_payload, dict):
        raise PublicationEligibilityError(("E3 T4 must be a JSON object",))
    if t4_payload.get("schema_version") != "POI_MPP_E3_T4_V1":
        raise PublicationEligibilityError(("E3 T4 schema_version must equal POI_MPP_E3_T4_V1",))
    if t4_payload.get("artifact_role") != "DATASET_COMPOSITION":
        raise PublicationEligibilityError(("E3 T4 artifact_role must equal DATASET_COMPOSITION",))
    if t4_payload.get("experiment_id") != "E3" or t4_payload.get("claim_id") != "C3":
        raise PublicationEligibilityError(("E3 T4 must close over experiment E3 and claim C3",))
    if t4_payload.get("run_id") != run_id:
        raise PublicationEligibilityError(("E3 T4 run_id must match the verified receipt run_id",))
    if t4_payload.get("evidence_origin") != EvidenceOrigin.REAL_MODEL_EXECUTION.value:
        raise PublicationEligibilityError(("E3 T4 evidence_origin must equal REAL_MODEL_EXECUTION",))
    if t4_payload.get("record_count") != 8:
        raise PublicationEligibilityError(("E3 T4 record_count must equal 8",))
    class_counts = t4_payload.get("class_counts")
    if class_counts != {"invalid": 2, "valid": 6}:
        raise PublicationEligibilityError(("E3 T4 class_counts must equal {'invalid': 2, 'valid': 6}",))
    bindings = t4_payload.get("execution_bindings")
    if not isinstance(bindings, dict):
        raise PublicationEligibilityError(("E3 T4 execution_bindings must be a JSON object",))
    expected_binding_keys = set(E3_EXPECTED_RAW_MEMBER_PATHS) | {"pre_execution_authority_record_sha256"}
    if set(bindings) != expected_binding_keys:
        raise PublicationEligibilityError(("E3 T4 execution_bindings must bind all raw members plus the authority record",))
    if any(not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value) for value in bindings.values()):
        raise PublicationEligibilityError(("E3 T4 execution_bindings values must be lowercase SHA-256 hex digests",))
    if bindings["pre_execution_authority_record_sha256"] != receipt.get("pre_execution_authority_record_sha256"):
        raise PublicationEligibilityError(("E3 T4 authority hash must match the verified receipt",))

    metric_rows = _validated_e3_metric_rows(payload=artifacts_by_id["T8"][2], run_id=run_id, bindings=bindings)

    try:
        f7_root = ElementTree.fromstring(artifacts_by_id["F7"][2])
    except ElementTree.ParseError as error:
        raise PublicationEligibilityError(("E3 F7 SVG is invalid",)) from error
    metadata_nodes = [
        node
        for node in f7_root.iter()
        if node.tag.rsplit("}", 1)[-1] == "metadata" and node.attrib.get("id") == "poi-e3-attestation"
    ]
    if len(metadata_nodes) != 1 or not metadata_nodes[0].text:
        raise PublicationEligibilityError(("E3 F7 must include exactly one poi-e3-attestation metadata block",))
    try:
        f7_metadata = json.loads(metadata_nodes[0].text)
    except json.JSONDecodeError as error:
        raise PublicationEligibilityError(("E3 F7 metadata is not valid JSON",)) from error
    if not isinstance(f7_metadata, dict):
        raise PublicationEligibilityError(("E3 F7 metadata must be a JSON object",))
    if f7_metadata.get("schema_version") != "POI_MPP_E3_F7_METADATA_V1":
        raise PublicationEligibilityError(("E3 F7 schema_version must equal POI_MPP_E3_F7_METADATA_V1",))
    if f7_metadata.get("artifact_role") != "SEMANTIC_QUALITY_FIGURE":
        raise PublicationEligibilityError(("E3 F7 artifact_role must equal SEMANTIC_QUALITY_FIGURE",))
    if f7_metadata.get("experiment_id") != "E3" or f7_metadata.get("claim_id") != "C3":
        raise PublicationEligibilityError(("E3 F7 must close over experiment E3 and claim C3",))
    if f7_metadata.get("run_id") != run_id:
        raise PublicationEligibilityError(("E3 F7 run_id must match the verified receipt run_id",))
    if f7_metadata.get("evidence_origin") != EvidenceOrigin.REAL_MODEL_EXECUTION.value:
        raise PublicationEligibilityError(("E3 F7 evidence_origin must equal REAL_MODEL_EXECUTION",))
    if f7_metadata.get("source_t8_sha256") != artifacts_by_id["T8"][3]:
        raise PublicationEligibilityError(("E3 F7 source_t8_sha256 must match the verified T8 artifact",))
    if f7_metadata.get("metric_scope") != list(E3_EXPECTED_METRICS):
        raise PublicationEligibilityError(("E3 F7 metric_scope must equal the attested metric scope",))
    if f7_metadata.get("execution_bindings") != bindings:
        raise PublicationEligibilityError(("E3 F7 execution_bindings must match T4 execution_bindings",))

    _validate_e3_raw_bundle(
        path=artifacts_by_id["RAW_E3_EXECUTION"][1],
        payload=artifacts_by_id["RAW_E3_EXECUTION"][2],
        run_id=run_id,
        bindings=bindings,
    )

    output_map = {
        artifact_id: output_relative_path
        for artifact_id, (_, _, _, _, output_relative_path) in artifacts_by_id.items()
    }
    for artifact_id, (_, _, payload, _, output_relative_path) in artifacts_by_id.items():
        _write_generated_output(output_root, output_relative_path, payload)

    input_entries = (
        _entry(
            experiment_id="E3",
            input_role="verified_receipt",
            path=receipt_path,
            root=root,
            sha256=receipt_hash,
            schema_version=str(receipt["schema_version"]),
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION.value,
            disposition="NOT_SUPPORTED",
            run_id=run_id,
            config_hash=bindings["config_hash"],
        ),
        _entry(
            experiment_id="E3",
            input_role="source_t4",
            path=artifacts_by_id["T4"][1],
            root=root,
            sha256=artifacts_by_id["T4"][3],
            schema_version=str(t4_payload["schema_version"]),
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION.value,
            disposition="NOT_SUPPORTED",
            run_id=run_id,
            config_hash=bindings["config_hash"],
        ),
        _entry(
            experiment_id="E3",
            input_role="source_t8",
            path=artifacts_by_id["T8"][1],
            root=root,
            sha256=artifacts_by_id["T8"][3],
            schema_version="POI_MPP_E3_T8_V1",
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION.value,
            disposition="NOT_SUPPORTED",
            run_id=run_id,
            config_hash=bindings["config_hash"],
        ),
        _entry(
            experiment_id="E3",
            input_role="source_f7",
            path=artifacts_by_id["F7"][1],
            root=root,
            sha256=artifacts_by_id["F7"][3],
            schema_version="POI_MPP_E3_F7_METADATA_V1",
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION.value,
            disposition="NOT_SUPPORTED",
            run_id=run_id,
            config_hash=bindings["config_hash"],
        ),
        _entry(
            experiment_id="E3",
            input_role="source_raw_execution",
            path=artifacts_by_id["RAW_E3_EXECUTION"][1],
            root=root,
            sha256=artifacts_by_id["RAW_E3_EXECUTION"][3],
            schema_version="POI_MPP_E3_RAW_EXECUTION_V1",
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION.value,
            disposition="NOT_SUPPORTED",
            run_id=run_id,
            config_hash=bindings["config_hash"],
        ),
    )
    generated_source_closure_hash = digest(
        "E3_VERIFIED_RECEIPT_IMPORT",
        {
            "receipt_sha256": receipt_hash,
            "artifacts": {
                artifact_id: artifacts_by_id[artifact_id][3]
                for artifact_id in ("T4", "T8", "F7", "RAW_E3_EXECUTION")
            },
        },
    )
    generated_outputs = tuple(
        GeneratedOutput(
            artifact_id=artifact_id,
            relative_path=output_map[artifact_id],
            kind=("raw" if artifact_id == "RAW_E3_EXECUTION" else output_map[artifact_id].split("/", 1)[0]),
            schema_version=(
                "POI_MPP_E3_RAW_EXECUTION_V1"
                if artifact_id == "RAW_E3_EXECUTION"
                else ("POI_MPP_E3_F7_METADATA_V1" if artifact_id == "F7" else ("POI_MPP_E3_T4_V1" if artifact_id == "T4" else "POI_MPP_E3_T8_V1"))
            ),
            run_id=run_id,
            config_hash=bindings["config_hash"],
            source_closure_hash=generated_source_closure_hash,
            derives_to_artifact_ids=(artifact_id,),
            derived_from_input_paths=tuple(entry.relative_path for entry in input_entries),
        )
        for artifact_id in ("T4", "T8", "F7", "RAW_E3_EXECUTION")
    )
    summary = {
        "claim_id": "C3",
        "run_id": run_id,
        "evidence_origin": EvidenceOrigin.REAL_MODEL_EXECUTION.value,
        "artifact_scope": ["F7", "RAW_E3_EXECUTION", "T4", "T8"],
        "metric_scope": sorted(E3_EXPECTED_METRICS),
        "record_count": 8,
        "invalid_count": 2,
        "far": float(E3_EXPECTED_METRICS["FAR"][0]),
        "frr": float(E3_EXPECTED_METRICS["FRR"][0]),
        "coverage": float(E3_EXPECTED_METRICS["coverage"][0]),
        "calibration": float(E3_EXPECTED_METRICS["calibration"][0]),
        "alpha_sem": 0.25,
        "claim_disposition": "NOT_SUPPORTED",
        "authority_decision": "APPROVED",
        "attestation_status": "VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION",
        "sample_note": E3_RESULT_NOTE,
    }
    return LoadedExperiment(
        experiment_id="E3",
        table_ids=("T4", "T8"),
        figure_ids=("F7",),
        claim_id="C3",
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION.value,
        disposition="NOT_SUPPORTED",
        scope=E3_PUBLICATION_SCOPE,
        maturity="REAL_MODEL_EXECUTION",
        run_id=run_id,
        config_hash=bindings["config_hash"],
        source_hashes=(
            receipt_hash,
            artifacts_by_id["T4"][3],
            artifacts_by_id["T8"][3],
            artifacts_by_id["F7"][3],
            artifacts_by_id["RAW_E3_EXECUTION"][3],
        ),
        table_rows=(),
        figure_points=(),
        summary=summary,
        sample_size=8,
        uncertainty="attested_small_sample_rates",
        limits=(
            "FAR 0.500 (1/2) exceeded frozen alpha_sem 0.25; C3 remains NOT_SUPPORTED.",
            E3_RESULT_NOTE,
            "Cryptographic verification authenticates exact artifacts and signer-key continuity only; identity, independence, expertise, and private-key custody remain out-of-band checks.",
        ),
        omission_reason=None,
        input_entries=input_entries,
        generated_outputs=generated_outputs,
    )


def _require_payload_singleton(
    rows_payload: tuple[dict[str, Any], ...],
    *,
    field_name: str,
    label: str,
) -> str:
    values: set[str] = set()
    for row in rows_payload:
        value = row.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise PublicationEligibilityError((f"{label}.{field_name} must be a non-blank string",))
        values.add(value)
    if len(values) != 1:
        raise PublicationEligibilityError((f"{label}.{field_name} must be singular",))
    return next(iter(values))


def _entry(
    *,
    experiment_id: str,
    input_role: str,
    path: Path,
    root: Path,
    sha256: str,
    schema_version: str | None,
    origin: str | None,
    disposition: str,
    run_id: str | None,
    config_hash: str | None,
) -> InputEntry:
    return InputEntry(
        experiment_id=experiment_id,
        input_role=input_role,
        relative_path=str(path.relative_to(root)),
        sha256=sha256,
        schema_version=schema_version,
        origin=origin,
        disposition=disposition,
        run_id=run_id,
        config_hash=config_hash,
        paper_artifact_ids=experiment_artifact_ids(experiment_id),
    )


def _missing_experiment(experiment_id: str, reason: str) -> LoadedExperiment:
    return LoadedExperiment(
        experiment_id=experiment_id,
        table_ids=tuple(ARTIFACT_PLAN[experiment_id]["tables"]),
        figure_ids=tuple(ARTIFACT_PLAN[experiment_id]["figures"]),
        claim_id=f"{experiment_id}_MISSING",
        origin=None,
        disposition="MISSING" if "missing" in reason.lower() else "WAITING_EXTERNAL",
        scope=None,
        maturity="ABSENT",
        run_id=None,
        config_hash=None,
        source_hashes=(),
        table_rows=(),
        figure_points=(),
        summary=None,
        sample_size=None,
        uncertainty=None,
        limits=(),
        omission_reason=reason,
        input_entries=(),
        generated_outputs=(),
    )


def _e1_loaded(root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.rows_path is None:
        return _missing_experiment("E1", "missing E1 rows_path")
    rows_path, rows_payload, rows_hash = _load_parquet_rows(root, source.rows_path, label="E1 rows")
    if {row.get("experiment_id") for row in rows_payload} != {"E1"}:
        raise PublicationEligibilityError(("E1 rows.experiment_id must equal E1",))
    _require_payload_singleton(rows_payload, field_name="run_id", label="E1 rows")
    task_ids = {row.get("task_id") for row in rows_payload}
    if any(isinstance(task_id, bool) or not isinstance(task_id, int) for task_id in task_ids):
        raise PublicationEligibilityError(("E1 rows.task_id must be singular",))
    if len(task_ids) != 1:
        raise PublicationEligibilityError(("E1 rows.task_id must be singular",))
    if {row.get("measurement_design") for row in rows_payload} != {"FIXED_ORDER_PILOT"}:
        raise PublicationEligibilityError(("E1 rows.measurement_design must equal FIXED_ORDER_PILOT",))
    _require_payload_singleton(rows_payload, field_name="origin", label="E1 rows")
    try:
        rows = tuple(E1MeasurementRow.model_validate(row) for row in rows_payload)
    except Exception as error:
        raise PublicationEligibilityError((f"E1 rows failed canonical validation: {error}",)) from error
    origins = {row.origin.value for row in rows}
    if len(origins) != 1:
        raise PublicationEligibilityError(("E1 rows mix origins",))
    origin = next(iter(origins))
    _reject_synthetic_origin(origin, experiment_id="E1")
    warmup_rows = [row for row in rows if row.is_warmup]
    if not warmup_rows:
        raise PublicationEligibilityError(("E1 rows require at least one warmup pair",))
    warmup_pairs: dict[str, list[E1MeasurementRow]] = {}
    for row in warmup_rows:
        warmup_pairs.setdefault(row.pair_id, []).append(row)
    required_variants = {"NATIVE_SINGLE", "TWO_RUN_BASELINE", "MPP_SINGLE_PASS"}
    for pair_id, pair_rows in sorted(warmup_pairs.items()):
        observed_variants = [row.variant.value for row in pair_rows]
        if len(pair_rows) != 3 or set(observed_variants) != required_variants or len(set(observed_variants)) != 3:
            raise PublicationEligibilityError((f"E1 warmup pair {pair_id} must contain exactly one of each required variant",))
    measured_rows = [row.model_dump(mode="json") for row in rows if not row.is_warmup]
    if not measured_rows:
        raise PublicationEligibilityError(("E1 rows require at least one non-warmup measurement row",))
    summary = summarize_e1_rows(measured_rows).model_dump(mode="json")
    if summary["measurement_design"] != "FIXED_ORDER_PILOT":
        raise PublicationEligibilityError(("E1 summary.measurement_design must remain FIXED_ORDER_PILOT",))
    if summary["claim_disposition"] != "INCONCLUSIVE":
        raise PublicationEligibilityError(("E1 fixed-order pilot must remain mechanically INCONCLUSIVE",))
    return LoadedExperiment(
        experiment_id="E1",
        table_ids=("T6",),
        figure_ids=("F5",),
        claim_id=str(summary["claim_id"]),
        origin=origin,
        disposition=str(summary["claim_disposition"]),
        scope=E1_PUBLICATION_SCOPE,
        maturity="REAL_MODEL_EXECUTION",
        run_id=rows[0].run_id,
        config_hash=None,
        source_hashes=(rows_hash,),
        table_rows=tuple(measured_rows),
        figure_points=tuple(row.model_dump(mode="json") for row in rows),
        summary=summary,
        sample_size=len(measured_rows),
        uncertainty="bootstrap_delta_ci",
        limits=(str(summary["claim_disposition_reason"]),),
        omission_reason=None,
        input_entries=(
            _entry(
                experiment_id="E1",
                input_role="rows",
                path=rows_path,
                root=root,
                sha256=rows_hash,
                schema_version=str(rows[0].schema_version),
                origin=origin,
                disposition=str(summary["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=None,
            ),
        ),
        generated_outputs=(),
    )


def _e2_loaded(root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.rows_path is None or source.summary_path is None:
        return _missing_experiment("E2", "missing E2 rows_path or summary_path")
    rows_path = _resolved_anchored_path(root, source.rows_path)
    rows_payload, rows_hash = _rows_payload(root, rows_path, label="E2 rows")
    summary_path, summary_payload_raw, summary_hash = _load_json(root, source.summary_path, label="E2 summary")
    summary_payload = _mapping_payload(summary_payload_raw, label="E2 summary")
    if {row.get("experiment_id") for row in rows_payload} != {"E2"}:
        raise PublicationEligibilityError(("E2 rows.experiment_id must equal E2",))
    _require_payload_singleton(rows_payload, field_name="run_id", label="E2 rows")
    try:
        rows = tuple(E2ReceiptRow.model_validate(row) for row in rows_payload)
    except Exception as error:
        raise PublicationEligibilityError((f"E2 rows failed canonical validation: {error}",)) from error
    origins = {row.origin.value for row in rows}
    if len(origins) != 1:
        raise PublicationEligibilityError(("E2 rows mix origins",))
    origin = next(iter(origins))
    _reject_synthetic_origin(origin, experiment_id="E2")
    claim_id = _require_string_field(summary_payload, "claim_id", label="E2 summary")
    canonical_summary = summarize_e2_rows(list(rows), claim_id=claim_id).model_dump(mode="json")
    _require_summary_alignment(
        summary_payload=summary_payload,
        canonical_summary=canonical_summary,
        label="E2 summary",
        excluded_fields=frozenset({"claim_disposition"}),
    )
    if summary_payload.get("measurement_design") != E2_MEASUREMENT_DESIGN:
        raise PublicationEligibilityError(("E2 summary.measurement_design must equal NARROW_SCOPE_PILOT",))
    if summary_payload.get("frozen_scope") != E2_FROZEN_SCOPE:
        raise PublicationEligibilityError(("E2 summary.frozen_scope must equal the frozen narrow publication scope",))
    if summary_payload.get("claim_disposition") != "INCONCLUSIVE":
        raise PublicationEligibilityError(("E2 narrow-scope publication summary must remain INCONCLUSIVE",))
    if summary_payload.get("claim_disposition_reason") != E2_CLAIM_DISPOSITION_REASON:
        raise PublicationEligibilityError(("E2 summary.claim_disposition_reason must equal the frozen narrow pilot boundary",))
    return LoadedExperiment(
        experiment_id="E2",
        table_ids=("T7",),
        figure_ids=("F6",),
        claim_id=claim_id,
        origin=origin,
        disposition=str(summary_payload["claim_disposition"]),
        scope=E2_PUBLICATION_SCOPE,
        maturity="REAL_MODEL_EXECUTION",
        run_id=rows[0].run_id,
        config_hash=None,
        source_hashes=(rows_hash, summary_hash),
        table_rows=tuple(row.model_dump(mode="json") for row in rows),
        figure_points=(),
        summary=summary_payload,
        sample_size=len(rows),
        uncertainty="wilson_from_supported_audit_surfaces",
        limits=_limits_from_summary(summary_payload),
        omission_reason=None,
        input_entries=(
            _entry(
                experiment_id="E2",
                input_role="rows",
                path=rows_path,
                root=root,
                sha256=rows_hash,
                schema_version=str(rows[0].schema_version),
                origin=origin,
                disposition=str(summary_payload["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=None,
            ),
            _entry(
                experiment_id="E2",
                input_role="summary",
                path=summary_path,
                root=root,
                sha256=summary_hash,
                schema_version=str(summary_payload.get("schema_version") or ""),
                origin=origin,
                disposition=str(summary_payload["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=None,
            ),
        ),
        generated_outputs=(),
    )


def _e4_loaded(root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.rows_path is None or source.summary_path is None or source.metadata_path is None:
        return _missing_experiment("E4", "missing E4 rows_path, summary_path, or metadata_path")
    rows_path = _resolved_anchored_path(root, source.rows_path)
    rows_payload, rows_hash = _rows_payload(root, rows_path, label="E4 rows")
    summary_path, summary_payload_raw, summary_hash = _load_json(root, source.summary_path, label="E4 summary")
    metadata_path, metadata_payload_raw, metadata_hash = _load_json(root, source.metadata_path, label="E4 metadata")
    summary_payload = _mapping_payload(summary_payload_raw, label="E4 summary")
    metadata_payload = _mapping_payload(metadata_payload_raw, label="E4 metadata")
    if {row.get("experiment_id") for row in rows_payload} != {"E4"}:
        raise PublicationEligibilityError(("E4 rows.experiment_id must equal E4",))
    _require_payload_singleton(rows_payload, field_name="run_id", label="E4 rows")
    try:
        rows = tuple(E4ScenarioRow.model_validate(row) for row in rows_payload)
    except Exception as error:
        raise PublicationEligibilityError((f"E4 rows failed canonical validation: {error}",)) from error
    origins = {row.origin.value for row in rows}
    if len(origins) != 1:
        raise PublicationEligibilityError(("E4 rows mix origins",))
    origin = next(iter(origins))
    _reject_synthetic_origin(origin, experiment_id="E4")
    claim_id = _require_string_field(summary_payload, "claim_id", label="E4 summary")
    canonical_summary = summarize_e4_rows(rows, claim_id=claim_id).model_dump(mode="json")
    _require_summary_alignment(
        summary_payload=summary_payload,
        canonical_summary=canonical_summary,
        label="E4 summary",
        excluded_fields=frozenset({"claim_disposition"}),
    )
    if summary_payload.get("claim_disposition") != "INCONCLUSIVE":
        raise PublicationEligibilityError(("E4 declared-outcome playback summary must remain INCONCLUSIVE",))
    if metadata_payload.get("method_boundary") != E4_METHOD_BOUNDARY:
        raise PublicationEligibilityError(("E4 metadata.method_boundary must equal DECLARED_OUTCOME_PLAYBACK",))
    if metadata_payload.get("claim_disposition_reason") != E4_INCONCLUSIVE_REASON:
        raise PublicationEligibilityError(("E4 metadata.claim_disposition_reason must equal the declared playback boundary",))
    if metadata_payload.get("publication_scope") != E4_PUBLICATION_SCOPE:
        raise PublicationEligibilityError(("E4 metadata.publication_scope must equal E4_CONFIRMATORY_PUBLICATION_V1",))
    metadata_config_hash = _require_hex_hash_field(metadata_payload, "run_config_hash", label="E4 metadata")
    publication_decision = metadata_payload.get("publication_decision")
    if not isinstance(publication_decision, dict):
        raise PublicationEligibilityError(("E4 metadata.publication_decision must be a JSON object",))
    if publication_decision.get("claim_id") != claim_id:
        raise PublicationEligibilityError(("E4 metadata.publication_decision.claim_id must match the summary claim_id",))
    if publication_decision.get("completeness") != "COMPLETE":
        raise PublicationEligibilityError(("E4 metadata.publication_decision.completeness must remain COMPLETE",))
    if publication_decision.get("claim_support") != "INCONCLUSIVE":
        raise PublicationEligibilityError(("E4 metadata.publication_decision.claim_support must remain INCONCLUSIVE",))
    reasons = publication_decision.get("reasons")
    if not isinstance(reasons, list) or E4_INCONCLUSIVE_REASON not in reasons:
        raise PublicationEligibilityError(("E4 metadata.publication_decision.reasons must contain the declared playback reason",))
    return LoadedExperiment(
        experiment_id="E4",
        table_ids=("T9",),
        figure_ids=("F8",),
        claim_id=claim_id,
        origin=origin,
        disposition=str(summary_payload["claim_disposition"]),
        scope=E4_PUBLICATION_SCOPE,
        maturity="REPRODUCIBLE_SIMULATION",
        run_id=rows[0].run_id,
        config_hash=metadata_config_hash,
        source_hashes=(rows_hash, summary_hash, metadata_hash),
        table_rows=tuple(row.model_dump(mode="json") for row in t9_rows(rows)),
        figure_points=tuple(point.model_dump(mode="json") for point in f8_points(rows)),
        summary=summary_payload,
        sample_size=len(rows),
        uncertainty="observed_and_exact_miss_probability",
        limits=_limits_from_summary(summary_payload),
        omission_reason=None,
        input_entries=(
            _entry(
                experiment_id="E4",
                input_role="rows",
                path=rows_path,
                root=root,
                sha256=rows_hash,
                schema_version=str(rows[0].schema_version),
                origin=origin,
                disposition=str(summary_payload["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=metadata_config_hash,
            ),
            _entry(
                experiment_id="E4",
                input_role="summary",
                path=summary_path,
                root=root,
                sha256=summary_hash,
                schema_version=str(summary_payload.get("schema_version") or ""),
                origin=origin,
                disposition=str(summary_payload["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=metadata_config_hash,
            ),
            _entry(
                experiment_id="E4",
                input_role="metadata",
                path=metadata_path,
                root=root,
                sha256=metadata_hash,
                schema_version=str(metadata_payload.get("schema_version") or ""),
                origin=origin,
                disposition=str(summary_payload["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=metadata_config_hash,
            ),
        ),
        generated_outputs=(),
    )


def _e8_loaded(root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.rows_path is None or source.contract_path is None:
        return _missing_experiment("E8", "missing E8 rows_path or contract_path")
    rows_path = _resolved_anchored_path(root, source.rows_path)
    contract_path = _resolved_anchored_path(root, source.contract_path)
    rows_payload, rows_hash = _rows_payload(root, rows_path, label="E8 rows")
    _, contract_text, contract_hash = _load_yaml_text(root, contract_path, label="E8 contract")
    contract = load_e8_confirmatory_contract(contract_path)
    try:
        rows = tuple(E8ScenarioRow.model_validate(row) for row in rows_payload)
    except Exception as error:
        raise PublicationEligibilityError((f"E8 rows failed canonical validation: {error}",)) from error
    origins = {row.origin.value for row in rows}
    if len(origins) != 1:
        raise PublicationEligibilityError(("E8 rows mix origins",))
    origin = next(iter(origins))
    _reject_synthetic_origin(origin, experiment_id="E8")
    summary = summarize_e8_rows(rows, contract=contract).model_dump(mode="json")
    return LoadedExperiment(
        experiment_id="E8",
        table_ids=("T13",),
        figure_ids=("F11",),
        claim_id=str(summary["claim_id"]),
        origin=origin,
        disposition=str(summary["claim_disposition"]),
        scope=rows[0].publication_scope,
        maturity="REPRODUCIBLE_SIMULATION",
        run_id=rows[0].run_id,
        config_hash=rows[0].run_config_hash,
        source_hashes=(rows_hash, contract_hash),
        table_rows=tuple(row.model_dump(mode="json") for row in t13_rows(rows)),
        figure_points=tuple(point.model_dump(mode="json") for point in f11_points(rows)),
        summary=summary,
        sample_size=len(rows),
        uncertainty="wilson_from_replay" if any("interval" in key for key in summary) else None,
        limits=_limits_from_summary(summary) + tuple(str(line) for line in yaml.safe_load(contract_text).get("notes", ())),
        omission_reason=None,
        input_entries=(
            _entry(
                experiment_id="E8",
                input_role="rows",
                path=rows_path,
                root=root,
                sha256=rows_hash,
                schema_version=str(rows[0].schema_version),
                origin=origin,
                disposition=str(summary["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=rows[0].run_config_hash,
            ),
            _entry(
                experiment_id="E8",
                input_role="confirmatory_contract",
                path=contract_path,
                root=root,
                sha256=contract_hash,
                schema_version=str(contract.schema_version),
                origin=origin,
                disposition=str(summary["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=rows[0].run_config_hash,
            ),
        ),
        generated_outputs=(),
    )


def _e7_loaded(root: Path, output_root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.run_config_path is not None:
        run_config_path = _resolved_anchored_path(root, source.run_config_path)
        run_config = load_run_config(run_config_path)
        bundle_output = output_root / "raw" / "E7_live_bundle.json"
        result = collect_and_summarize_e7_publication(
            contracts_root=source.contracts_root or str(Path(__file__).resolve().parents[3] / "contracts"),
            run_config=run_config,
            bundle_output_path=bundle_output,
            contract=default_measurement_contract(),
            timeout=source.timeout_seconds,
        )
        summary = result.summary.model_dump(mode="json")
        run_config_hash = _path_hash(run_config_path)
        input_entries = (
            _entry(
                experiment_id="E7",
                input_role="run_config",
                path=run_config_path,
                root=root,
                sha256=run_config_hash,
                schema_version=str(run_config.schema_version),
                origin=run_config.origin.value,
                disposition=str(summary["claim_disposition"]),
                run_id=run_config.run_id,
                config_hash=result.bundle.run_config_hash,
            ),
        )
        return LoadedExperiment(
            experiment_id="E7",
            table_ids=("T12",),
            figure_ids=("F12",),
            claim_id=str(summary["claim_id"]),
            origin=result.bundle.run_config_snapshot.origin.value,
            disposition=str(summary["claim_disposition"]),
            scope=result.bundle.run_config_snapshot.authorization_scope,
            maturity="LOCAL_FOUNDRY_MEASUREMENT",
            run_id=result.bundle.run_config_snapshot.run_id,
            config_hash=result.bundle.run_config_hash,
            source_hashes=(
                result.bundle.raw_report_hash,
                result.bundle.run_config_hash,
                result.parity_verification.source_closure_hash,
                result.parity_verification.protocol_vectors_hash,
                result.parity_verification.protocol_witness_hash,
            ),
            table_rows=tuple(row.model_dump(mode="json") for row in t12_rows(result.bundle.rows)),
            figure_points=tuple(point.model_dump(mode="json") for point in f12_points(result.bundle.rows)),
            summary=summary,
            sample_size=len(result.bundle.rows),
            uncertainty="N/A_single_measurement",
            limits=(),
            omission_reason=None,
            input_entries=input_entries,
            generated_outputs=(
                GeneratedOutput(
                    artifact_id="RAW_E7_LIVE_BUNDLE",
                    relative_path="raw/E7_live_bundle.json",
                    kind="raw",
                    schema_version=str(result.bundle.schema_version),
                    run_id=result.bundle.run_config_snapshot.run_id,
                    config_hash=result.bundle.run_config_hash,
                    source_closure_hash=result.parity_verification.source_closure_hash,
                    derives_to_artifact_ids=("T12", "F12"),
                    derived_from_input_paths=tuple(entry.relative_path for entry in input_entries),
                ),
            ),
        )
    if source.bundle_path is None:
        return _missing_experiment("E7", "missing E7 run_config_path for live measurement")
    bundle_path, bundle_payload, bundle_hash = _load_json(root, source.bundle_path, label="E7 bundle")
    bundle = E7Bundle.model_validate(bundle_payload)
    parity_attachment: E7ParityAttachment | None = None
    input_entries = [
        _entry(
            experiment_id="E7",
            input_role="bundle",
            path=bundle_path,
            root=root,
            sha256=bundle_hash,
            schema_version=str(bundle.schema_version),
            origin=bundle.run_config_snapshot.origin.value,
            disposition="INCONCLUSIVE",
            run_id=bundle.run_config_snapshot.run_id,
            config_hash=bundle.run_config_hash,
        )
    ]
    if source.parity_attachment_path is not None:
        parity_path, parity_payload, parity_hash = _load_json(root, source.parity_attachment_path, label="E7 parity attachment")
        parity_attachment = E7ParityAttachment.model_validate(parity_payload)
        source_hashes = (bundle_hash, parity_hash)
        input_entries.append(
            _entry(
                experiment_id="E7",
                input_role="parity_attachment",
                path=parity_path,
                root=root,
                sha256=parity_hash,
                schema_version=str(parity_attachment.schema_version),
                origin=bundle.run_config_snapshot.origin.value,
                disposition="INCONCLUSIVE",
                run_id=bundle.run_config_snapshot.run_id,
                config_hash=bundle.run_config_hash,
            )
        )
    else:
        source_hashes = (bundle_hash,)
    summary = summarize_e7_bundle(
        bundle,
        contract=default_measurement_contract(),
        parity_attachment=parity_attachment,
    ).model_dump(mode="json")
    return LoadedExperiment(
        experiment_id="E7",
        table_ids=("T12",),
        figure_ids=("F12",),
        claim_id=str(summary["claim_id"]),
        origin=bundle.run_config_snapshot.origin.value,
        disposition=str(summary["claim_disposition"]),
        scope=bundle.run_config_snapshot.authorization_scope,
        maturity="LOCAL_FOUNDRY_METADATA_ONLY",
        run_id=bundle.run_config_snapshot.run_id,
        config_hash=bundle.run_config_hash,
        source_hashes=source_hashes,
        table_rows=(),
        figure_points=(),
        summary=summary,
        sample_size=len(bundle.rows),
        uncertainty=None,
        limits=(),
        omission_reason="stored E7 bundle metadata is non-authoritative; live collection is required",
        input_entries=tuple(input_entries),
        generated_outputs=(),
    )


def _e6_loaded(root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.rows_path is None or source.contract_path is None:
        return _missing_experiment("E6", "missing E6 rows_path or contract_path")
    rows_path = _resolved_anchored_path(root, source.rows_path)
    contract_path = _resolved_anchored_path(root, source.contract_path)
    rows_payload, rows_hash = _rows_payload(root, rows_path, label="E6 rows")
    contract = load_e6_confirmatory_contract(contract_path)
    rows = tuple(E6ScenarioRow.model_validate(row) for row in rows_payload)
    origins = {row.origin.value for row in rows}
    if len(origins) != 1:
        raise PublicationEligibilityError(("E6 rows mix origins",))
    origin = next(iter(origins))
    _reject_synthetic_origin(origin, experiment_id="E6")
    summary = summarize_e6_rows(rows, contract=contract).model_dump(mode="json")
    return LoadedExperiment(
        experiment_id="E6",
        table_ids=("T11",),
        figure_ids=("F9", "F10"),
        claim_id=str(summary["claim_id"]),
        origin=origin,
        disposition=str(summary["claim_disposition"]),
        scope=rows[0].publication_scope,
        maturity="REPRODUCIBLE_SIMULATION",
        run_id=rows[0].run_id,
        config_hash=rows[0].run_config_hash,
        source_hashes=(rows_hash, _path_hash(contract_path)),
        table_rows=tuple(row.model_dump(mode="json") for row in t11_rows(rows)),
        figure_points=tuple(point.model_dump(mode="json") for point in f9_points(rows))
        + tuple(point.model_dump(mode="json") for point in f10_points(rows)),
        summary=summary,
        sample_size=len(rows),
        uncertainty="confidence_interval_micros",
        limits=_limits_from_summary(summary),
        omission_reason=None,
        input_entries=(
            _entry(
                experiment_id="E6",
                input_role="rows",
                path=rows_path,
                root=root,
                sha256=rows_hash,
                schema_version=str(rows[0].schema_version),
                origin=origin,
                disposition=str(summary["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=rows[0].run_config_hash,
            ),
            _entry(
                experiment_id="E6",
                input_role="confirmatory_contract",
                path=contract_path,
                root=root,
                sha256=_path_hash(contract_path),
                schema_version=str(contract.schema_version),
                origin=origin,
                disposition=str(summary["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=rows[0].run_config_hash,
            ),
        ),
        generated_outputs=(),
    )


def _e5_loaded(root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.rows_path is None or source.contract_path is None:
        return _missing_experiment("E5", "missing E5 rows_path or contract_path")
    rows_path = _resolved_anchored_path(root, source.rows_path)
    contract_path = _resolved_anchored_path(root, source.contract_path)
    rows_payload, rows_hash = _rows_payload(root, rows_path, label="E5 rows")
    contract = load_e5_confirmatory_contract(contract_path)
    rows = tuple(E5ScenarioRow.model_validate(row) for row in rows_payload)
    origins = {row.origin.value for row in rows}
    if len(origins) != 1:
        raise PublicationEligibilityError(("E5 rows mix origins",))
    origin = next(iter(origins))
    _reject_synthetic_origin(origin, experiment_id="E5")
    summary = summarize_e5_rows(rows, contract=contract).model_dump(mode="json")
    return LoadedExperiment(
        experiment_id="E5",
        table_ids=("T10",),
        figure_ids=(),
        claim_id=str(summary["claim_id"]),
        origin=origin,
        disposition=str(summary["claim_disposition"]),
        scope=rows[0].publication_scope,
        maturity="REPRODUCIBLE_SIMULATION",
        run_id=rows[0].run_id,
        config_hash=rows[0].run_config_hash,
        source_hashes=(rows_hash, _path_hash(contract_path)),
        table_rows=tuple(row.model_dump(mode="json") for row in t10_rows(rows)),
        figure_points=(),
        summary=summary,
        sample_size=len(rows),
        uncertainty="invalid_maturity_interval",
        limits=_limits_from_summary(summary),
        omission_reason=None,
        input_entries=(
            _entry(
                experiment_id="E5",
                input_role="rows",
                path=rows_path,
                root=root,
                sha256=rows_hash,
                schema_version=str(rows[0].schema_version),
                origin=origin,
                disposition=str(summary["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=rows[0].run_config_hash,
            ),
            _entry(
                experiment_id="E5",
                input_role="confirmatory_contract",
                path=contract_path,
                root=root,
                sha256=_path_hash(contract_path),
                schema_version=str(contract.schema_version),
                origin=origin,
                disposition=str(summary["claim_disposition"]),
                run_id=rows[0].run_id,
                config_hash=rows[0].run_config_hash,
            ),
        ),
        generated_outputs=(),
    )


def _unimplemented_loaded(experiment_id: str, reason: str) -> LoadedExperiment:
    return _missing_experiment(experiment_id, reason)


def load_publication_inputs(spec: ReportBuildSpec) -> LoadedBundle:
    artifact_root = Path(spec.artifact_root).resolve()
    output_root = Path(spec.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    loaders = {
        "E1": lambda source: _e1_loaded(artifact_root, source),
        "E2": lambda source: _e2_loaded(artifact_root, source),
        "E3": lambda source: _e3_loaded(artifact_root, output_root, source),
        "E4": lambda source: _e4_loaded(artifact_root, source),
        "E5": lambda source: _e5_loaded(artifact_root, source),
        "E6": lambda source: _e6_loaded(artifact_root, source),
        "E7": lambda source: _e7_loaded(artifact_root, output_root, source),
        "E8": lambda source: _e8_loaded(artifact_root, source),
    }
    experiments: list[LoadedExperiment] = []
    for experiment_id in ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"):
        source = spec.sources.get(experiment_id)
        if source is None:
            if experiment_id == "E3":
                experiments.append(_missing_experiment(experiment_id, E3_WAITING_EXTERNAL_REASON))
            else:
                experiments.append(_missing_experiment(experiment_id, f"missing configured source for {experiment_id}"))
            continue
        source = ExperimentSource.model_validate(source)
        if experiment_id in loaders:
            experiments.append(loaders[experiment_id](source))
            continue
        experiments.append(_unimplemented_loaded(experiment_id, f"{experiment_id} authoritative input is not configured in this publication build"))
    environment = collect_environment(repo_root=Path(__file__).resolve().parents[3], lock_path=Path(__file__).resolve().parents[3] / "requirements.lock")
    return LoadedBundle(
        artifact_root=artifact_root,
        output_root=output_root,
        experiments=tuple(experiments),
        build_environment_hash=publication_build_environment_hash(environment),
        generator_source_closure_hash=_generator_source_closure_hash(),
    )


__all__ = [
    "ExperimentSource",
    "LoadedBundle",
    "LoadedExperiment",
    "PublicationEligibilityError",
    "ReportBuildSpec",
    "load_publication_inputs",
]
