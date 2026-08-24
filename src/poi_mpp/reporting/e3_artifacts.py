"""Deterministic, fail-closed export of externally authorized E3 artifacts.

This module serializes an already validated :class:`E3ConfirmatoryResult`.
It does not authenticate evaluator authority, run a model, sign an attestation,
or decide whether claim C3 is supported.
"""

from __future__ import annotations

import csv
import ctypes
from enum import StrEnum
import errno
import hashlib
from html import escape
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Literal
import zipfile

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e3_semantic import (
    E3ConfirmatoryResult,
    E3SemanticRow,
    VerifiedE3AuthorityGrant,
)
from poi_mpp.reporting.e3 import semantic_metrics
from poi_mpp.worker.model_manifest import PinnedModelManifest


METRIC_ORDER = ("FAR", "FRR", "ABSTAIN", "coverage", "calibration")
ARTIFACT_ORDER = ("T4", "T8", "F7", "RAW_E3_EXECUTION")
RAW_MEMBER_PATHS = {
    "model_hash": "model_manifest.json",
    "config_hash": "config.json",
    "input_hash": "inputs.jsonl",
    "output_hash": "outputs.jsonl",
    "trace_hash": "trace.jsonl",
    "provenance_hash": "provenance.json",
}
MAX_RAW_ZIP_MEMBERS = 64
MAX_RAW_MEMBER_BYTES = 32 * 1024 * 1024
MAX_RAW_ZIP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_RUN_ID = re.compile(r"[A-Za-z0-9._-]+\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_FORBIDDEN_MARKERS = (
    b"WAITING_EXTERNAL",
    b"SYNTHETIC_NON_EVIDENCE",
    b'"origin": null',
)


class E3ArtifactExportError(ValueError):
    """Raised before publication artifacts are committed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class E3AuthorityDecision(StrEnum):
    APPROVED = "APPROVED"
    LIMITED_SCOPE = "LIMITED_SCOPE"


class E3ExecutionBindings(_FrozenModel):
    model_hash: str
    config_hash: str
    input_hash: str
    output_hash: str
    trace_hash: str
    provenance_hash: str
    pre_execution_authority_record_sha256: str

    @field_validator("*")
    @classmethod
    def _lowercase_sha256(cls, value: str) -> str:
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ValueError("execution bindings must be lowercase SHA-256 hex digests")
        return value


class E3ArtifactScope(_FrozenModel):
    decision: E3AuthorityDecision
    run_id: str
    evidence_origin: EvidenceOrigin
    metric_scope: tuple[Literal["FAR", "FRR", "ABSTAIN", "coverage", "calibration"], ...]
    artifact_scope: tuple[Literal["T4", "T8", "F7", "RAW_E3_EXECUTION"], ...]

    @field_validator("run_id")
    @classmethod
    def _safe_run_id(cls, value: str) -> str:
        if not isinstance(value, str) or not _RUN_ID.fullmatch(value):
            raise ValueError("run_id must contain only A-Z, a-z, 0-9, dot, underscore, or hyphen")
        return value

    @field_validator("metric_scope", "artifact_scope")
    @classmethod
    def _nonempty_unique_scope(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("authorized scope must be non-empty and unique")
        return value

    @model_validator(mode="after")
    def _authority_scope_contract(self) -> "E3ArtifactScope":
        if self.evidence_origin is not EvidenceOrigin.REAL_MODEL_EXECUTION:
            raise ValueError("E3 publication artifacts require REAL_MODEL_EXECUTION")
        metrics = set(self.metric_scope)
        artifacts = set(self.artifact_scope)
        if self.decision is E3AuthorityDecision.APPROVED:
            if metrics != set(METRIC_ORDER) or artifacts != set(ARTIFACT_ORDER):
                raise ValueError("APPROVED scope must contain the complete metric and artifact sets")
        else:
            if not {"T8", "RAW_E3_EXECUTION"}.issubset(artifacts):
                raise ValueError("LIMITED_SCOPE must include T8 and RAW_E3_EXECUTION")
        if "F7" in artifacts and "T8" not in artifacts:
            raise ValueError("F7 requires T8 in the same authorized scope")
        return self


class E3RawExecutionMembers(_FrozenModel):
    model_manifest: Path
    config: Path
    inputs: Path
    outputs: Path
    trace: Path
    provenance: Path


class E3ArtifactExportReceipt(_FrozenModel):
    schema_version: Literal["POI_MPP_E3_ARTIFACT_EXPORT_RECEIPT_V1"] = (
        "POI_MPP_E3_ARTIFACT_EXPORT_RECEIPT_V1"
    )
    run_id: str
    completeness: Literal["COMPLETE_INPUT_SET", "INCOMPLETE_NONPUBLICATION"]
    artifact_paths: tuple[str, ...]


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stat_regular_source(path: Path, *, label: str) -> tuple[Path, int]:
    if path.is_symlink():
        raise E3ArtifactExportError(f"{label} may not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise E3ArtifactExportError(f"{label} is missing or unreadable") from error
    if not resolved.is_file():
        raise E3ArtifactExportError(f"{label} must be a regular file")
    try:
        size = resolved.stat().st_size
    except OSError as error:
        raise E3ArtifactExportError(f"{label} is unreadable") from error
    if size <= 0:
        raise E3ArtifactExportError(f"{label} must not be empty")
    if size > MAX_RAW_MEMBER_BYTES:
        raise E3ArtifactExportError(f"{label} exceeds per-file size ceiling")
    return resolved, size


def _read_regular_source(resolved: Path, *, label: str, expected_size: int) -> bytes:
    try:
        payload = resolved.read_bytes()
    except OSError as error:
        raise E3ArtifactExportError(f"{label} is unreadable") from error
    if len(payload) != expected_size:
        raise E3ArtifactExportError(f"{label} changed after its pre-read stat")
    for marker in _FORBIDDEN_MARKERS:
        if marker in payload:
            raise E3ArtifactExportError(f"{label} contains a placeholder or non-evidence marker")
    return payload


def _load_raw_members(
    raw_members: E3RawExecutionMembers,
) -> tuple[dict[str, bytes], dict[str, Path]]:
    canonical = E3RawExecutionMembers.model_validate(raw_members.model_dump(mode="python"))
    field_to_binding = {
        "model_manifest": "model_hash",
        "config": "config_hash",
        "inputs": "input_hash",
        "outputs": "output_hash",
        "trace": "trace_hash",
        "provenance": "provenance_hash",
    }
    binding_to_field = {binding: field for field, binding in field_to_binding.items()}
    source_stats: dict[str, tuple[Path, int]] = {}
    paths: dict[str, Path] = {}
    for field_name, binding_name in field_to_binding.items():
        resolved, size = _stat_regular_source(
            getattr(canonical, field_name), label=f"raw {field_name}"
        )
        source_stats[binding_name] = (resolved, size)
        paths[binding_name] = resolved
    if len(set(paths.values())) != len(paths):
        raise E3ArtifactExportError("raw execution sources must use distinct file paths")
    if sum(size for _, size in source_stats.values()) > MAX_RAW_ZIP_UNCOMPRESSED_BYTES:
        raise E3ArtifactExportError("raw execution sources exceed total uncompressed ceiling")
    payloads = {
        binding_name: _read_regular_source(
            resolved,
            label=f"raw {binding_to_field[binding_name]}",
            expected_size=size,
        )
        for binding_name, (resolved, size) in source_stats.items()
    }
    return payloads, paths


def _validate_bindings(
    *, bindings: E3ExecutionBindings, raw_payloads: dict[str, bytes]
) -> E3ExecutionBindings:
    canonical = E3ExecutionBindings.model_validate(bindings.model_dump(mode="json"))
    for binding_name, payload in raw_payloads.items():
        if getattr(canonical, binding_name) != _sha256(payload):
            raise E3ArtifactExportError(f"{binding_name} does not match the exact raw member bytes")
    return canonical


def _scope_from_verified_grant(
    grant: object,
    *,
    result: E3ConfirmatoryResult,
) -> E3ArtifactScope:
    if not isinstance(grant, VerifiedE3AuthorityGrant):
        raise E3ArtifactExportError(
            "a canonical verified authority grant is required; caller-constructed scope is not authority"
        )
    summary = grant.verification_summary
    if summary.get("status") != "VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY":
        raise E3ArtifactExportError("verified authority grant has an invalid verification status")
    if grant.experiment_id != "E3" or grant.claim_id != "C3":
        raise E3ArtifactExportError("verified authority grant must close experiment E3 and claim C3")
    if grant.task_class != "GROUNDED_SEMANTIC_ASSURANCE":
        raise E3ArtifactExportError("verified authority grant has the wrong E3 task class")
    if not grant.authority_identity.strip():
        raise E3ArtifactExportError("verified authority grant must identify its external authority")
    if not _SHA256.fullmatch(grant.authority_record_sha256):
        raise E3ArtifactExportError("verified authority grant has an invalid authority_record_sha256")

    run_ids = {row.run_id for row in result.evaluated_rows}
    if len(run_ids) != 1:
        raise E3ArtifactExportError("evaluated rows must close to exactly one run_id")
    try:
        return E3ArtifactScope(
            decision=E3AuthorityDecision(grant.decision),
            run_id=next(iter(run_ids)),
            evidence_origin=EvidenceOrigin(grant.evidence_origin),
            metric_scope=grant.metric_scope,
            artifact_scope=grant.artifact_scope,
        )
    except (TypeError, ValueError) as error:
        raise E3ArtifactExportError(f"verified authority grant scope is invalid: {error}") from error


def _validate_result(result: E3ConfirmatoryResult) -> E3ConfirmatoryResult:
    try:
        canonical = E3ConfirmatoryResult.model_validate(result.model_dump(mode="json"))
    except (AttributeError, ValidationError) as error:
        raise E3ArtifactExportError(f"invalid E3 confirmatory result: {error}") from error
    if not canonical.evaluated_rows:
        raise E3ArtifactExportError("E3 confirmatory result must retain evaluated rows")
    case_ids = [row.case_id for row in canonical.evaluated_rows]
    if len(case_ids) != len(set(case_ids)):
        raise E3ArtifactExportError("evaluated rows contain duplicate case_id values")
    if any(row.experiment_id != "E3" for row in canonical.evaluated_rows):
        raise E3ArtifactExportError("evaluated rows must close to experiment E3")
    if any(row.origin is not EvidenceOrigin.REAL_MODEL_EXECUTION for row in canonical.evaluated_rows):
        raise E3ArtifactExportError("evaluated rows must use REAL_MODEL_EXECUTION")
    if canonical.summary.denominator != len(canonical.evaluated_rows):
        raise E3ArtifactExportError("summary denominator does not equal evaluated row count")
    try:
        recomputed = semantic_metrics(
            canonical.evaluated_rows,
            claim_id=canonical.summary.claim_id,
            policy=canonical.summary.policy,
        )
    except ValueError as error:
        raise E3ArtifactExportError(f"evaluated rows do not form a valid E3 result: {error}") from error
    if recomputed.model_dump(mode="json") != canonical.summary.model_dump(mode="json"):
        raise E3ArtifactExportError("summary is not exactly derived from evaluated rows")
    _validate_result_origin(canonical)
    return canonical


def _json_object(payload: bytes, *, label: str) -> dict[str, object]:
    try:
        decoded = payload.decode("utf-8", errors="strict")
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise E3ArtifactExportError(f"{label} must be strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise E3ArtifactExportError(f"{label} must be a JSON object")
    return value


def _jsonl_objects(payload: bytes, *, label: str) -> tuple[dict[str, object], ...]:
    try:
        decoded = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise E3ArtifactExportError(f"{label} must be strict UTF-8 JSONL") from error
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(decoded.splitlines(), start=1):
        if not line.strip():
            raise E3ArtifactExportError(f"{label} line {line_number} must not be blank")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise E3ArtifactExportError(
                f"{label} line {line_number} must be a JSON object"
            ) from error
        if not isinstance(row, dict):
            raise E3ArtifactExportError(f"{label} line {line_number} must be a JSON object")
        for field in ("case_id", "run_id", "experiment_id"):
            if not isinstance(row.get(field), str) or not str(row[field]).strip():
                raise E3ArtifactExportError(f"{label} line {line_number} requires {field}")
        case_id = str(row["case_id"])
        if case_id in seen:
            raise E3ArtifactExportError(f"{label} contains duplicate case_id {case_id}")
        seen.add(case_id)
        rows.append(row)
    if not rows:
        raise E3ArtifactExportError(f"{label} must contain at least one JSON object")
    return tuple(rows)


def _validate_scope_object(value: dict[str, object], *, label: str, run_id: str) -> None:
    if value.get("run_id") != run_id:
        raise E3ArtifactExportError(f"{label} run_id does not match evaluated rows")
    if value.get("experiment_id") != "E3":
        raise E3ArtifactExportError(f"{label} experiment_id must equal E3")
    origin = value.get("origin", value.get("evidence_origin"))
    if origin != EvidenceOrigin.REAL_MODEL_EXECUTION.value:
        raise E3ArtifactExportError(f"{label} origin must equal REAL_MODEL_EXECUTION")


def _validate_raw_execution(
    *,
    result: E3ConfirmatoryResult,
    scope: E3ArtifactScope,
    raw_payloads: dict[str, bytes],
) -> None:
    model_payload = _json_object(raw_payloads["model_hash"], label="raw model_manifest")
    try:
        PinnedModelManifest.model_validate(model_payload)
    except ValidationError as error:
        raise E3ArtifactExportError(
            f"raw model_manifest failed PinnedModelManifest contract: {error}"
        ) from error
    _validate_scope_object(
        _json_object(raw_payloads["config_hash"], label="raw config"),
        label="raw config",
        run_id=scope.run_id,
    )
    _validate_scope_object(
        _json_object(raw_payloads["provenance_hash"], label="raw provenance"),
        label="raw provenance",
        run_id=scope.run_id,
    )

    expected = {row.case_id: row for row in result.evaluated_rows}
    expected_ids = set(expected)
    streams = {
        "raw inputs": _jsonl_objects(raw_payloads["input_hash"], label="raw inputs"),
        "raw outputs": _jsonl_objects(raw_payloads["output_hash"], label="raw outputs"),
        "raw trace": _jsonl_objects(raw_payloads["trace_hash"], label="raw trace"),
    }
    for label, rows in streams.items():
        if {str(row["case_id"]) for row in rows} != expected_ids:
            raise E3ArtifactExportError(f"{label} case-id set does not equal evaluated rows")
        for row in rows:
            if row["run_id"] != scope.run_id:
                raise E3ArtifactExportError(f"{label} run_id does not match evaluated rows")
            if row["experiment_id"] != "E3":
                raise E3ArtifactExportError(f"{label} experiment_id must equal E3")

    for payload in streams["raw outputs"]:
        try:
            output_row = E3SemanticRow.model_validate(payload)
        except ValidationError as error:
            raise E3ArtifactExportError(f"raw outputs failed E3SemanticRow contract: {error}") from error
        expected_row = expected[output_row.case_id]
        if output_row.model_dump(mode="json") != expected_row.model_dump(mode="json"):
            raise E3ArtifactExportError(
                f"raw outputs evaluated row {output_row.case_id} differs from confirmatory result"
            )


def _metric_values(result: E3ConfirmatoryResult) -> dict[str, tuple[float | None, int]]:
    summary = result.summary
    return {
        "FAR": (summary.far.value, summary.far.denominator),
        "FRR": (summary.frr.value, summary.frr.denominator),
        "ABSTAIN": (summary.abstention.value, summary.abstention.denominator),
        "coverage": (summary.coverage.value, summary.coverage.denominator),
        "calibration": (summary.calibration.brier_score, summary.calibration.denominator),
    }


def _validate_result_origin(result: E3ConfirmatoryResult) -> None:
    provenance = result.annotation_provenance
    origin_sets = (
        provenance.source_origins,
        provenance.annotation_origins,
        provenance.evaluator_origins,
    )
    if any(
        not origins or any(origin is not EvidenceOrigin.REAL_MODEL_EXECUTION for origin in origins)
        for origins in origin_sets
    ):
        raise E3ArtifactExportError(
            "E3 publication artifacts require real source, annotation, and evaluator origins"
        )


def _t4_bytes(
    *, result: E3ConfirmatoryResult, scope: E3ArtifactScope, bindings: E3ExecutionBindings
) -> bytes:
    confusion = result.summary.confusion_matrix
    valid = confusion.valid_accept + confusion.valid_reject + confusion.valid_abstain
    invalid = confusion.invalid_accept + confusion.invalid_reject + confusion.invalid_abstain
    return _canonical_json(
        {
            "schema_version": "POI_MPP_E3_T4_V1",
            "artifact_role": "DATASET_COMPOSITION",
            "experiment_id": "E3",
            "claim_id": "C3",
            "run_id": scope.run_id,
            "evidence_origin": "REAL_MODEL_EXECUTION",
            "record_count": result.summary.denominator,
            "class_counts": {"invalid": invalid, "valid": valid},
            "execution_bindings": bindings.model_dump(mode="json"),
        }
    )


def _format_metric(value: float) -> str:
    return format(value, ".17g")


def _t8_bytes(
    *, result: E3ConfirmatoryResult, scope: E3ArtifactScope, bindings: E3ExecutionBindings
) -> tuple[bytes, tuple[tuple[str, float, int], ...]]:
    metric_values = _metric_values(result)
    selected: list[tuple[str, float, int]] = []
    for metric in METRIC_ORDER:
        if metric not in scope.metric_scope:
            continue
        value, denominator = metric_values[metric]
        if value is None or denominator <= 0:
            raise E3ArtifactExportError(
                f"authorized metric {metric} is undefined and cannot enter typed T8 evidence"
            )
        selected.append((metric, value, denominator))

    binding_fields = tuple(E3ExecutionBindings.model_fields)
    fieldnames = (
        "schema_version",
        "artifact_role",
        "experiment_id",
        "claim_id",
        "run_id",
        "evidence_origin",
        "metric",
        "value",
        "sample_count",
        *binding_fields,
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    binding_payload = bindings.model_dump(mode="json")
    for metric, value, denominator in selected:
        writer.writerow(
            {
                "schema_version": "POI_MPP_E3_T8_V1",
                "artifact_role": "SEMANTIC_METRICS",
                "experiment_id": "E3",
                "claim_id": "C3",
                "run_id": scope.run_id,
                "evidence_origin": "REAL_MODEL_EXECUTION",
                "metric": metric,
                "value": _format_metric(value),
                "sample_count": str(denominator),
                **binding_payload,
            }
        )
    return stream.getvalue().encode("utf-8"), tuple(selected)


def _f7_bytes(
    *,
    selected_metrics: tuple[tuple[str, float, int], ...],
    scope: E3ArtifactScope,
    bindings: E3ExecutionBindings,
    t8_sha256: str,
) -> bytes:
    metadata = _canonical_json(
        {
            "schema_version": "POI_MPP_E3_F7_METADATA_V1",
            "artifact_role": "SEMANTIC_QUALITY_FIGURE",
            "experiment_id": "E3",
            "claim_id": "C3",
            "run_id": scope.run_id,
            "evidence_origin": "REAL_MODEL_EXECUTION",
            "metric_scope": [metric for metric, _, _ in selected_metrics],
            "source_t8_sha256": t8_sha256,
            "execution_bindings": bindings.model_dump(mode="json"),
        }
    ).decode("utf-8").strip()
    bars: list[str] = []
    for index, (metric, value, denominator) in enumerate(selected_metrics):
        x = 150 + index * 105
        height = round(value * 180, 6)
        y = 230 - height
        bars.extend(
            (
                f'<rect x="{x}" y="{y:g}" width="52" height="{height:g}" fill="#315c8c"/>',
                f'<text x="{x + 26}" y="250" text-anchor="middle" font-size="12">{metric}</text>',
                f'<text x="{x + 26}" y="{max(18, y - 7):g}" text-anchor="middle" font-size="11">{_format_metric(value)} (n={denominator})</text>',
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="280" viewBox="0 0 760 280" role="img" aria-labelledby="title desc">\n'
        '<title id="title">E3 semantic verification quality</title>\n'
        '<desc id="desc">Authorized semantic error, abstention, coverage, and calibration metrics.</desc>\n'
        f'<metadata id="poi-e3-attestation">{escape(metadata, quote=False)}</metadata>\n'
        '<rect width="760" height="280" fill="#ffffff"/>\n'
        '<line x1="120" y1="230" x2="700" y2="230" stroke="#25364d"/>\n'
        '<line x1="120" y1="50" x2="120" y2="230" stroke="#25364d"/>\n'
        + "\n".join(bars)
        + '\n</svg>\n'
    ).encode("utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _raw_zip_bytes(
    *,
    raw_payloads: dict[str, bytes],
    selected_metrics: tuple[tuple[str, float, int], ...],
    scope: E3ArtifactScope,
    bindings: E3ExecutionBindings,
) -> bytes:
    files = {
        binding_name: {
            "path": RAW_MEMBER_PATHS[binding_name],
            "sha256": _sha256(raw_payloads[binding_name]),
            "size_bytes": len(raw_payloads[binding_name]),
        }
        for binding_name in RAW_MEMBER_PATHS
    }
    manifest = _canonical_json(
        {
            "schema_version": "POI_MPP_E3_RAW_EXECUTION_V1",
            "artifact_role": "RAW_EXECUTION_BUNDLE",
            "experiment_id": "E3",
            "claim_id": "C3",
            "run_id": scope.run_id,
            "evidence_origin": "REAL_MODEL_EXECUTION",
            "metric_scope": [metric for metric, _, _ in selected_metrics],
            "execution_bindings": bindings.model_dump(mode="json"),
            "files": files,
        }
    )
    ordered_members = [
        (RAW_MEMBER_PATHS[binding_name], raw_payloads[binding_name])
        for binding_name in RAW_MEMBER_PATHS
    ] + [("run_manifest.json", manifest)]
    if len(ordered_members) > MAX_RAW_ZIP_MEMBERS:
        raise E3ArtifactExportError("RAW_E3_EXECUTION exceeds member-count ceiling")
    if sum(len(payload) for _, payload in ordered_members) > MAX_RAW_ZIP_UNCOMPRESSED_BYTES:
        raise E3ArtifactExportError("RAW_E3_EXECUTION exceeds uncompressed ceiling")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for member_name, payload in ordered_members:
            archive.writestr(_zip_info(member_name), payload)
    return stream.getvalue()


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish ``source`` only when ``destination`` is absent."""

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if hasattr(libc, "renamex_np"):
        renamex_np = libc.renamex_np
        renamex_np.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        renamex_np.restype = ctypes.c_int
        result = renamex_np(source_bytes, destination_bytes, 0x00000004)  # RENAME_EXCL
    elif hasattr(libc, "renameat2"):
        renameat2 = libc.renameat2
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, source_bytes, -100, destination_bytes, 1)  # RENAME_NOREPLACE
    else:
        raise E3ArtifactExportError(
            "atomic no-replace publication is unsupported on this platform"
        )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise E3ArtifactExportError(
            "artifact_root already exists; atomic no-replace publication refused"
        )
    raise OSError(error_number, os.strerror(error_number), str(destination))


def _write_staged_tree(artifact_root: Path, outputs: dict[str, bytes]) -> None:
    if artifact_root.exists() or artifact_root.is_symlink():
        raise E3ArtifactExportError("artifact_root must not already exist")
    parent = artifact_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{artifact_root.name}.staging-", dir=parent))
    try:
        for relative_path, payload in outputs.items():
            target = staging / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        _rename_noreplace(staging, artifact_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def export_e3_artifacts(
    *,
    result: E3ConfirmatoryResult,
    authority_grant: VerifiedE3AuthorityGrant,
    bindings: E3ExecutionBindings,
    raw_members: E3RawExecutionMembers,
    artifact_root: str | Path,
) -> E3ArtifactExportReceipt:
    """Export an exact authority-scoped E3 artifact tree with one atomic rename."""

    canonical_result = _validate_result(result)
    canonical_scope = _scope_from_verified_grant(authority_grant, result=canonical_result)
    raw_payloads, _ = _load_raw_members(raw_members)
    canonical_bindings = _validate_bindings(bindings=bindings, raw_payloads=raw_payloads)
    if (
        canonical_bindings.pre_execution_authority_record_sha256
        != authority_grant.authority_record_sha256
    ):
        raise E3ArtifactExportError(
            "pre_execution_authority_record_sha256 does not match verified authority grant"
        )
    _validate_raw_execution(
        result=canonical_result,
        scope=canonical_scope,
        raw_payloads=raw_payloads,
    )
    t8, selected_metrics = _t8_bytes(
        result=canonical_result, scope=canonical_scope, bindings=canonical_bindings
    )

    outputs: dict[str, bytes] = {}
    artifacts = set(canonical_scope.artifact_scope)
    if "T4" in artifacts:
        outputs["publication/tables/T4_dataset_composition.json"] = _t4_bytes(
            result=canonical_result, scope=canonical_scope, bindings=canonical_bindings
        )
    outputs["publication/tables/T8_semantic_verification.csv"] = t8
    if "F7" in artifacts:
        outputs["publication/figures/F7_semantic_verification_quality.svg"] = _f7_bytes(
            selected_metrics=selected_metrics,
            scope=canonical_scope,
            bindings=canonical_bindings,
            t8_sha256=_sha256(t8),
        )
    outputs[
        f"results/publication/{canonical_scope.run_id}/raw_e3_execution.zip"
    ] = _raw_zip_bytes(
        raw_payloads=raw_payloads,
        selected_metrics=selected_metrics,
        scope=canonical_scope,
        bindings=canonical_bindings,
    )

    root = Path(artifact_root)
    try:
        _write_staged_tree(root, outputs)
    except E3ArtifactExportError:
        raise
    except OSError as error:
        raise E3ArtifactExportError(f"unable to atomically publish E3 artifacts: {error}") from error
    return E3ArtifactExportReceipt(
        run_id=canonical_scope.run_id,
        completeness=(
            "COMPLETE_INPUT_SET"
            if canonical_scope.decision is E3AuthorityDecision.APPROVED
            else "INCOMPLETE_NONPUBLICATION"
        ),
        artifact_paths=tuple(outputs),
    )


__all__ = [
    "E3ArtifactExportError",
    "E3ArtifactExportReceipt",
    "E3ArtifactScope",
    "E3AuthorityDecision",
    "E3ExecutionBindings",
    "E3RawExecutionMembers",
    "export_e3_artifacts",
]
