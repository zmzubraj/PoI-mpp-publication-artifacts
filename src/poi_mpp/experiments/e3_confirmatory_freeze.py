"""Fail-closed E3-v2 Phase-4 confirmatory dataset freeze preflight.

This module validates material integrity only.  It deliberately cannot promote a
bundle to authorized execution: an external authority binding and accountable
freeze approval remain separate inputs owned by later orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from poi_mpp.evidence.dataset_manifest_v2 import (
    DatasetManifestV2,
    DatasetSplitV2,
    assert_v2_split_isolation,
)
from poi_mpp.evidence.models import EvidenceOrigin


REPO_ROOT = Path(__file__).resolve().parents[3]
_SHA256_CHARS = frozenset("0123456789abcdef")
_DECISIONS = frozenset({"ACCEPT", "REJECT", "ABSTAIN"})
_REQUIRED_FILES = frozenset(
    {
        "dataset_manifest_v2.json",
        "annotation_ledger.json",
        "annotation_agreement.json",
        "adjudication_ledger.json",
        "license_privacy_ledger.json",
    }
)


class E3ConfirmatoryFreezeError(ValueError):
    """Raised when confirmatory freeze materials fail closed validation."""


class E3ConfirmatoryFreezeStatus(StrEnum):
    WAITING_EXTERNAL = "WAITING_EXTERNAL"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ManifestEntry(_FrozenModel):
    path: str
    sha256: str

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _safe_relative_path(value, label="manifest path")

    @field_validator("sha256")
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        return _require_sha256(value, label="manifest sha256")


class _FreezeManifest(_FrozenModel):
    schema_version: Literal["POI_MPP_E3_V2_CONFIRMATORY_FREEZE_MANIFEST_V1"] = (
        "POI_MPP_E3_V2_CONFIRMATORY_FREEZE_MANIFEST_V1"
    )
    files: tuple[_ManifestEntry, ...]

    @field_validator("files", mode="before")
    @classmethod
    def _normalize_files(cls, value: Any) -> tuple[_ManifestEntry, ...]:
        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError("manifest files must be a non-empty sequence")
        entries = tuple(
            entry if isinstance(entry, _ManifestEntry) else _ManifestEntry.model_validate(entry)
            for entry in value
        )
        paths = [entry.path for entry in entries]
        if len(paths) != len(set(paths)):
            raise ValueError("manifest files must not contain duplicate paths")
        return entries


@dataclass(frozen=True)
class E3ConfirmatoryFreezeWaitingExternal:
    status: E3ConfirmatoryFreezeStatus
    missing_inputs: tuple[str, ...]
    reason: str
    material_lineage_hash: str | None = None


@dataclass(frozen=True)
class E3ConfirmatoryFreezeMaterialBundle:
    bundle_root: Path
    dataset_manifest: DatasetManifestV2
    development_manifest: DatasetManifestV2
    decision_counts: dict[str, int]
    agreement_summary: dict[str, int | float]
    bundle_manifest_sha256: str
    dataset_manifest_hash: str
    development_manifest_hash: str
    annotation_ledger_sha256: str
    annotation_agreement_sha256: str
    adjudication_ledger_sha256: str
    license_privacy_ledger_sha256: str
    material_lineage_hash: str


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _require_nonblank(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise E3ConfirmatoryFreezeError(f"{label} must not be blank")
    return value.strip()


def _require_sha256(value: Any, *, label: str) -> str:
    normalized = _require_nonblank(value, label=label)
    if len(normalized) != 64 or any(char not in _SHA256_CHARS for char in normalized):
        raise E3ConfirmatoryFreezeError(f"{label} must be a lowercase SHA-256 digest")
    return normalized


def _safe_relative_path(value: Any, *, label: str) -> str:
    normalized = _require_nonblank(value, label=label)
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise E3ConfirmatoryFreezeError(f"{label} must be a safe relative path")
    return pure.as_posix()


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    probe = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise E3ConfirmatoryFreezeError(f"{label} may not be a symlink")


def _require_external_directory(path: Path, *, label: str) -> Path:
    _assert_no_symlink_components(path, label=label)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        raise
    if not resolved.is_dir():
        raise E3ConfirmatoryFreezeError(f"{label} must be a directory")
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise E3ConfirmatoryFreezeError(f"{label} must live outside the repository")


def _require_external_file(path: Path, *, label: str) -> Path:
    _assert_no_symlink_components(path, label=label)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        raise
    if not resolved.is_file():
        raise E3ConfirmatoryFreezeError(f"{label} must be a file")
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise E3ConfirmatoryFreezeError(f"{label} must live outside the repository")


def _resolve_member(root: Path, relative_path: str, *, label: str) -> Path:
    normalized = _safe_relative_path(relative_path, label=label)
    candidate = root / PurePosixPath(normalized)
    _assert_no_symlink_components(candidate, label=label)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise E3ConfirmatoryFreezeError(f"{label} is missing") from error
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise E3ConfirmatoryFreezeError(f"{label} escapes bundle root") from error
    if not resolved.is_file():
        raise E3ConfirmatoryFreezeError(f"{label} must be a file")
    return resolved


def _read_canonical_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    _assert_no_symlink_components(path, label=label)
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise E3ConfirmatoryFreezeError(f"{label} must be valid JSON") from error
    if not isinstance(payload, dict):
        raise E3ConfirmatoryFreezeError(f"{label} must be a JSON object")
    if raw != _canonical_json_bytes(payload):
        raise E3ConfirmatoryFreezeError(f"{label} must use canonical JSON serialization")
    return payload, raw


def _require_manifest_closure(bundle_root: Path) -> tuple[dict[str, str], str]:
    manifest_path = _resolve_member(bundle_root, "manifest.json", label="manifest.json")
    payload, raw = _read_canonical_json(manifest_path, label="manifest.json")
    try:
        manifest = _FreezeManifest.model_validate(payload)
    except ValidationError as error:
        raise E3ConfirmatoryFreezeError(f"manifest.json schema validation failed: {error}") from error
    actual: dict[str, str] = {}
    for path in sorted(bundle_root.rglob("*")):
        if path.is_symlink():
            raise E3ConfirmatoryFreezeError(
                f"{path.relative_to(bundle_root).as_posix()} may not be a symlink"
            )
        if path.is_file():
            relative = path.relative_to(bundle_root).as_posix()
            if relative != "manifest.json":
                actual[relative] = _sha256_path(path)
    expected = {entry.path: entry.sha256 for entry in manifest.files}
    if set(actual) != set(expected):
        missing = sorted(set(actual) - set(expected))
        unknown = sorted(set(expected) - set(actual))
        detail = missing[0] if missing else unknown[0]
        raise E3ConfirmatoryFreezeError(f"manifest.json file closure mismatch: {detail}")
    for relative, expected_hash in expected.items():
        if actual[relative] != expected_hash:
            raise E3ConfirmatoryFreezeError(f"manifest.json hash mismatch for {relative}")
    missing_required = sorted(_REQUIRED_FILES - set(expected))
    if missing_required:
        raise E3ConfirmatoryFreezeError(
            f"required confirmatory freeze member is missing: {missing_required[0]}"
        )
    return expected, _sha256_bytes(raw)


def validate_confirmatory_decision_counts(decisions: Iterable[str]) -> dict[str, int]:
    """Validate the frozen 200/200/100 confirmatory class allocation."""

    normalized = list(decisions)
    unknown = sorted(set(normalized) - _DECISIONS)
    if unknown:
        raise E3ConfirmatoryFreezeError(f"unknown confirmatory decision: {unknown[0]}")
    counts = {decision: normalized.count(decision) for decision in sorted(_DECISIONS)}
    if len(normalized) != 500:
        raise E3ConfirmatoryFreezeError("confirmatory dataset requires exactly 500 records")
    if counts["ACCEPT"] != 200:
        raise E3ConfirmatoryFreezeError("confirmatory dataset requires exactly 200 ACCEPT records")
    if counts["REJECT"] != 200:
        raise E3ConfirmatoryFreezeError("confirmatory dataset requires exactly 200 REJECT records")
    if counts["ABSTAIN"] != 100:
        raise E3ConfirmatoryFreezeError("confirmatory dataset requires exactly 100 ABSTAIN records")
    return {"ACCEPT": counts["ACCEPT"], "REJECT": counts["REJECT"], "ABSTAIN": counts["ABSTAIN"]}


def _exact_row_closure(*, record_ids: Sequence[str], rows: Sequence[Mapping[str, Any]], label: str) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        record_id = _require_nonblank(row.get("record_id"), label=f"{label} record_id")
        if record_id in indexed:
            raise E3ConfirmatoryFreezeError(f"{label} contains duplicate record_id")
        indexed[record_id] = row
    if set(indexed) != set(record_ids):
        raise E3ConfirmatoryFreezeError(f"{label} closure mismatch")
    return indexed


def reconcile_annotation_material(
    *,
    record_ids: Sequence[str],
    annotation_rows: Sequence[Mapping[str, Any]],
    agreement: Mapping[str, Any],
    adjudication_rows: Sequence[Mapping[str, Any]],
    record_agreement_fractions: Mapping[str, float],
) -> dict[str, int | float]:
    """Mechanically reconcile dual annotations, disagreements, and agreement."""

    indexed = _exact_row_closure(
        record_ids=record_ids,
        rows=annotation_rows,
        label="annotation ledger",
    )
    disagreements: set[str] = set()
    annotators_by_record: dict[str, set[str]] = {}
    agreements = 0
    for record_id in record_ids:
        row = indexed[record_id]
        annotations = row.get("annotations")
        if not isinstance(annotations, list) or len(annotations) != 2:
            raise E3ConfirmatoryFreezeError(
                f"{record_id} requires exactly two distinct nonblank annotator IDs"
            )
        annotator_ids = [
            _require_nonblank(annotation.get("annotator_id"), label="annotator_id")
            for annotation in annotations
            if isinstance(annotation, Mapping)
        ]
        if len(annotator_ids) != 2 or len(set(annotator_ids)) != 2:
            raise E3ConfirmatoryFreezeError(
                f"{record_id} requires exactly two distinct nonblank annotator IDs"
            )
        annotators_by_record[record_id] = set(annotator_ids)
        decisions: list[str] = []
        for annotation in annotations:
            decision = _require_nonblank(annotation.get("decision"), label="annotation decision")
            if decision not in _DECISIONS:
                raise E3ConfirmatoryFreezeError("annotation decision is invalid")
            _safe_relative_path(annotation.get("annotation_path"), label="annotation path")
            _require_sha256(annotation.get("annotation_hash"), label="annotation hash")
            decisions.append(decision)
        _require_nonblank(row.get("provenance_reference"), label="annotation provenance_reference")
        if decisions[0] == decisions[1]:
            agreements += 1
            expected_fraction = 1.0
        else:
            disagreements.add(record_id)
            expected_fraction = 0.0
        if record_agreement_fractions.get(record_id) != expected_fraction:
            raise E3ConfirmatoryFreezeError(
                f"record agreement_fraction mismatch for {record_id}"
            )

    adjudications: dict[str, Mapping[str, Any]] = {}
    for row in adjudication_rows:
        record_id = _require_nonblank(row.get("record_id"), label="adjudication record_id")
        if record_id in adjudications:
            raise E3ConfirmatoryFreezeError("adjudication ledger contains duplicate record_id")
        adjudicator_id = _require_nonblank(row.get("adjudicator_id"), label="adjudicator_id")
        if adjudicator_id in annotators_by_record.get(record_id, set()):
            raise E3ConfirmatoryFreezeError(
                f"adjudicator must be distinct from original annotators for {record_id}"
            )
        decision = _require_nonblank(row.get("decision"), label="adjudication decision")
        if decision not in _DECISIONS:
            raise E3ConfirmatoryFreezeError("adjudication decision is invalid")
        _safe_relative_path(row.get("adjudication_path"), label="adjudication path")
        _require_sha256(row.get("adjudication_hash"), label="adjudication hash")
        adjudications[record_id] = row
    if set(adjudications) != disagreements:
        raise E3ConfirmatoryFreezeError("adjudication closure mismatch for annotation disagreements")

    numerator = agreement.get("numerator")
    denominator = agreement.get("denominator")
    rate = agreement.get("rate")
    if isinstance(numerator, bool) or not isinstance(numerator, int) or numerator != agreements:
        raise E3ConfirmatoryFreezeError("agreement numerator does not reconcile")
    if isinstance(denominator, bool) or not isinstance(denominator, int) or denominator != len(record_ids):
        raise E3ConfirmatoryFreezeError("agreement denominator does not reconcile")
    try:
        exact_rate = Decimal(str(rate))
    except (InvalidOperation, ValueError) as error:
        raise E3ConfirmatoryFreezeError("agreement rate must be a finite decimal") from error
    if denominator == 0 or exact_rate != Decimal(numerator) / Decimal(denominator):
        raise E3ConfirmatoryFreezeError("agreement rate does not reconcile exactly")
    return {"numerator": numerator, "denominator": denominator, "rate": float(exact_rate)}


def reconcile_license_privacy_material(
    *,
    records: Sequence[Mapping[str, Any]],
    ledger_rows: Sequence[Mapping[str, Any]],
) -> int:
    """Require one license/privacy authorization row bound to every record."""

    record_ids = [
        _require_nonblank(record.get("record_id"), label="dataset record_id") for record in records
    ]
    indexed = _exact_row_closure(
        record_ids=record_ids,
        rows=ledger_rows,
        label="license/privacy ledger",
    )
    for record in records:
        record_id = str(record["record_id"])
        row = indexed[record_id]
        if row.get("license_id") != record.get("license_id"):
            raise E3ConfirmatoryFreezeError(f"license binding mismatch for {record_id}")
        privacy = record.get("privacy_status")
        privacy_value = getattr(privacy, "value", privacy)
        if row.get("privacy_status") != privacy_value:
            raise E3ConfirmatoryFreezeError(f"privacy binding mismatch for {record_id}")
        _require_nonblank(row.get("source_reference"), label="source_reference")
        _require_nonblank(row.get("authorization_reference"), label="authorization_reference")
    return len(record_ids)


def assert_confirmatory_split_isolation(
    development: DatasetManifestV2,
    confirmatory: DatasetManifestV2,
) -> None:
    """Invoke the canonical V2 isolation rule and normalize its fail-closed error."""

    try:
        assert_v2_split_isolation(development, confirmatory)
    except ValueError as error:
        raise E3ConfirmatoryFreezeError(str(error)) from error
    groups = [record.deduplication_group for record in confirmatory.records]
    if len(groups) != len(set(groups)):
        raise E3ConfirmatoryFreezeError(
            "duplicate or near-duplicate deduplication_group within confirmatory dataset"
        )


def assert_phase3_development_manifest_contract(
    development: DatasetManifestV2,
) -> None:
    """Require the exact Phase-3 development dataset contract before lineage use."""

    if development.split is not DatasetSplitV2.DEVELOPMENT:
        raise E3ConfirmatoryFreezeError("development manifest must use DEVELOPMENT split")
    if any(
        record.evidence_origin is not EvidenceOrigin.REAL_MODEL_EXECUTION
        for record in development.records
    ):
        raise E3ConfirmatoryFreezeError(
            "development manifest requires REAL_MODEL_EXECUTION evidence origin"
        )
    counts = development.decision_counts()
    if len(development.records) < 120 or len(development.records) > 150:
        raise E3ConfirmatoryFreezeError("development manifest requires 120-150 records")
    if counts["ACCEPT"] != 50:
        raise E3ConfirmatoryFreezeError("development manifest requires exactly 50 ACCEPT records")
    if counts["REJECT"] != 50:
        raise E3ConfirmatoryFreezeError("development manifest requires exactly 50 REJECT records")
    if counts["ABSTAIN"] < 20 or counts["ABSTAIN"] > 50:
        raise E3ConfirmatoryFreezeError("development manifest requires 20-50 ABSTAIN records")


def _verify_bound_annotation_files(
    *,
    bundle_root: Path,
    dataset_manifest: DatasetManifestV2,
    annotation_rows: Sequence[Mapping[str, Any]],
    adjudication_rows: Sequence[Mapping[str, Any]],
) -> None:
    records = {record.record_id: record for record in dataset_manifest.records}
    for row in annotation_rows:
        record_id = str(row["record_id"])
        for annotation in row["annotations"]:
            path = _resolve_member(bundle_root, annotation["annotation_path"], label="annotation path")
            if _sha256_path(path) != annotation["annotation_hash"]:
                raise E3ConfirmatoryFreezeError(f"annotation hash mismatch for {record_id}")
        row_hash = _sha256_bytes(_canonical_json_bytes(dict(row)))
        if records[record_id].annotation.annotation_hash != row_hash:
            raise E3ConfirmatoryFreezeError(f"annotation provenance binding mismatch for {record_id}")
    for row in adjudication_rows:
        path = _resolve_member(bundle_root, row["adjudication_path"], label="adjudication path")
        if _sha256_path(path) != row["adjudication_hash"]:
            raise E3ConfirmatoryFreezeError(f"adjudication hash mismatch for {row['record_id']}")


def validate_e3_phase4_confirmatory_freeze_materials(
    *,
    bundle_root: Path | str,
    development_manifest_path: Path | str,
) -> E3ConfirmatoryFreezeMaterialBundle:
    """Validate external confirmatory material without granting execution authority."""

    resolved_root = _require_external_directory(Path(bundle_root), label="bundle root")
    development_path = _require_external_file(
        Path(development_manifest_path),
        label="development manifest",
    )
    _, bundle_manifest_sha256 = _require_manifest_closure(resolved_root)

    dataset_path = _resolve_member(resolved_root, "dataset_manifest_v2.json", label="dataset_manifest_v2.json")
    dataset_payload, _ = _read_canonical_json(dataset_path, label="dataset_manifest_v2.json")
    try:
        dataset_manifest = DatasetManifestV2.model_validate(dataset_payload)
    except ValidationError as error:
        raise E3ConfirmatoryFreezeError(f"confirmatory dataset validation failed: {error}") from error
    if dataset_manifest.split is not DatasetSplitV2.CONFIRMATORY:
        raise E3ConfirmatoryFreezeError("confirmatory dataset must use CONFIRMATORY split")
    if any(record.evidence_origin is not EvidenceOrigin.REAL_MODEL_EXECUTION for record in dataset_manifest.records):
        raise E3ConfirmatoryFreezeError("confirmatory dataset requires REAL_MODEL_EXECUTION evidence origin")
    decision_counts = validate_confirmatory_decision_counts(
        record.expected_decision.value for record in dataset_manifest.records
    )
    groups = [record.deduplication_group for record in dataset_manifest.records]
    if len(groups) != len(set(groups)):
        raise E3ConfirmatoryFreezeError(
            "duplicate or near-duplicate deduplication_group within confirmatory dataset"
        )
    try:
        dataset_manifest.verify_rooted_file_hashes(resolved_root)
    except (OSError, ValueError) as error:
        raise E3ConfirmatoryFreezeError(str(error)) from error

    development_payload, development_raw = _read_canonical_json(
        development_path,
        label="development manifest",
    )
    try:
        development_manifest = DatasetManifestV2.model_validate(development_payload)
    except ValidationError as error:
        raise E3ConfirmatoryFreezeError(f"development dataset validation failed: {error}") from error
    assert_phase3_development_manifest_contract(development_manifest)
    assert_confirmatory_split_isolation(development_manifest, dataset_manifest)

    ledger_payload, annotation_raw = _read_canonical_json(
        _resolve_member(resolved_root, "annotation_ledger.json", label="annotation_ledger.json"),
        label="annotation_ledger.json",
    )
    agreement_payload, agreement_raw = _read_canonical_json(
        _resolve_member(resolved_root, "annotation_agreement.json", label="annotation_agreement.json"),
        label="annotation_agreement.json",
    )
    adjudication_payload, adjudication_raw = _read_canonical_json(
        _resolve_member(resolved_root, "adjudication_ledger.json", label="adjudication_ledger.json"),
        label="adjudication_ledger.json",
    )
    license_payload, license_raw = _read_canonical_json(
        _resolve_member(resolved_root, "license_privacy_ledger.json", label="license_privacy_ledger.json"),
        label="license_privacy_ledger.json",
    )
    annotation_rows = ledger_payload.get("rows")
    adjudication_rows = adjudication_payload.get("rows")
    license_rows = license_payload.get("rows")
    if not isinstance(annotation_rows, list) or not isinstance(adjudication_rows, list) or not isinstance(license_rows, list):
        raise E3ConfirmatoryFreezeError("confirmatory ledgers must contain rows arrays")
    record_ids = tuple(record.record_id for record in dataset_manifest.records)
    agreement_summary = reconcile_annotation_material(
        record_ids=record_ids,
        annotation_rows=annotation_rows,
        agreement=agreement_payload,
        adjudication_rows=adjudication_rows,
        record_agreement_fractions={
            record.record_id: record.annotation.agreement_fraction
            for record in dataset_manifest.records
        },
    )
    _verify_bound_annotation_files(
        bundle_root=resolved_root,
        dataset_manifest=dataset_manifest,
        annotation_rows=annotation_rows,
        adjudication_rows=adjudication_rows,
    )
    reconcile_license_privacy_material(
        records=[record.model_dump(mode="json") for record in dataset_manifest.records],
        ledger_rows=license_rows,
    )

    lineage = {
        "bundle_manifest_sha256": bundle_manifest_sha256,
        "dataset_manifest_hash": dataset_manifest.dataset_manifest_hash(),
        "development_manifest_hash": development_manifest.dataset_manifest_hash(),
        "annotation_ledger_sha256": _sha256_bytes(annotation_raw),
        "annotation_agreement_sha256": _sha256_bytes(agreement_raw),
        "adjudication_ledger_sha256": _sha256_bytes(adjudication_raw),
        "license_privacy_ledger_sha256": _sha256_bytes(license_raw),
    }
    return E3ConfirmatoryFreezeMaterialBundle(
        bundle_root=resolved_root,
        dataset_manifest=dataset_manifest,
        development_manifest=development_manifest,
        decision_counts=decision_counts,
        agreement_summary=agreement_summary,
        bundle_manifest_sha256=bundle_manifest_sha256,
        dataset_manifest_hash=lineage["dataset_manifest_hash"],
        development_manifest_hash=lineage["development_manifest_hash"],
        annotation_ledger_sha256=lineage["annotation_ledger_sha256"],
        annotation_agreement_sha256=lineage["annotation_agreement_sha256"],
        adjudication_ledger_sha256=lineage["adjudication_ledger_sha256"],
        license_privacy_ledger_sha256=lineage["license_privacy_ledger_sha256"],
        material_lineage_hash=_sha256_bytes(_canonical_json_bytes(lineage)),
    )


def prepare_e3_phase4_confirmatory_freeze(
    *,
    bundle_root: Path | str,
    development_manifest_path: Path | str,
) -> E3ConfirmatoryFreezeWaitingExternal:
    """Return WAITING_EXTERNAL until material, authority, and human approval exist."""

    bundle_path = Path(bundle_root)
    development_path = Path(development_manifest_path)
    missing: list[str] = []
    if not bundle_path.exists():
        missing.append("bundle_root")
    if not development_path.exists():
        missing.append("development_manifest")
    if missing:
        return E3ConfirmatoryFreezeWaitingExternal(
            status=E3ConfirmatoryFreezeStatus.WAITING_EXTERNAL,
            missing_inputs=tuple(missing),
            reason="missing_accountable_inputs",
        )
    materials = validate_e3_phase4_confirmatory_freeze_materials(
        bundle_root=bundle_path,
        development_manifest_path=development_path,
    )
    return E3ConfirmatoryFreezeWaitingExternal(
        status=E3ConfirmatoryFreezeStatus.WAITING_EXTERNAL,
        missing_inputs=("verified_external_authority_binding", "accountable_freeze_approval"),
        reason="materials_validated_authority_and_approval_required",
        material_lineage_hash=materials.material_lineage_hash,
    )
