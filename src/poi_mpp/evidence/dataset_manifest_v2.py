"""Versioned dataset manifests for publication-bound evidence contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
from pathlib import Path, PurePosixPath
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import EvidenceOrigin


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SAFE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DATASET_MANIFEST_V2_DOMAIN = "DATASET_MANIFEST_V2"


class _FrozenDatasetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetSplitV2(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    CONFIRMATORY = "CONFIRMATORY"
    PLUMBING = "PLUMBING"


class DatasetPrivacyStatus(StrEnum):
    AUTHORIZED_PUBLIC = "AUTHORIZED_PUBLIC"
    AUTHORIZED_RESTRICTED = "AUTHORIZED_RESTRICTED"
    SENSITIVE_REDACTED = "SENSITIVE_REDACTED"


class DatasetExpectedDecision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class DatasetExpectedSemanticOutcome(StrEnum):
    SUPPORTED_GROUNDS = "SUPPORTED_GROUNDS"
    REJECTED_GROUNDS = "REJECTED_GROUNDS"
    ABSTAIN_GROUNDS = "ABSTAIN_GROUNDS"


def _require_nonblank_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _require_pattern(value: Any, *, field_name: str, pattern: re.Pattern[str]) -> str:
    normalized = _require_nonblank_string(value, field_name=field_name)
    if pattern.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} has an invalid format")
    return normalized


def _require_sha256(value: Any, *, field_name: str) -> str:
    normalized = _require_nonblank_string(value, field_name=field_name)
    if _SHA256.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return normalized


def _require_probability(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if normalized < 0.0 or normalized > 1.0:
        raise ValueError(f"{field_name} must lie within [0, 1]")
    return normalized


def _normalize_relative_path(value: Any, *, field_name: str) -> str:
    normalized = _require_nonblank_string(value, field_name=field_name)
    path = PurePosixPath(normalized)
    if path.is_absolute():
        raise ValueError(f"{field_name} must be relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field_name} cannot contain parent traversal")
    return path.as_posix()


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    probe = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise ValueError(f"{label} may not be a symlink")


@dataclass(frozen=True)
class DatasetRootedBinding:
    record_id: str
    item_path: Path
    label_path: Path


class DatasetAnnotationProvenanceV2(_FrozenDatasetModel):
    annotation_scope: str
    annotation_hash: str
    agreement_fraction: float

    @field_validator("annotation_scope", mode="before")
    @classmethod
    def normalize_annotation_scope(cls, value: Any) -> str:
        return _require_pattern(value, field_name="annotation_scope", pattern=_SAFE_TOKEN)

    @field_validator("annotation_hash", mode="before")
    @classmethod
    def normalize_annotation_hash(cls, value: Any) -> str:
        return _require_sha256(value, field_name="annotation_hash")

    @field_validator("agreement_fraction", mode="before")
    @classmethod
    def normalize_agreement_fraction(cls, value: Any) -> float:
        return _require_probability(value, field_name="agreement_fraction")


class DatasetManifestRecordV2(_FrozenDatasetModel):
    record_id: str
    item_path: str
    label_path: str
    item_hash: str
    label_hash: str
    content_hash: str
    split: DatasetSplitV2
    license_id: str
    privacy_status: DatasetPrivacyStatus
    expected_decision: DatasetExpectedDecision
    expected_semantic_outcome: DatasetExpectedSemanticOutcome
    error_family: str
    subgroup: str
    difficulty: str
    deduplication_group: str
    annotation: DatasetAnnotationProvenanceV2
    evidence_origin: EvidenceOrigin

    @field_validator(
        "record_id",
        "license_id",
        "error_family",
        "subgroup",
        "difficulty",
        "deduplication_group",
        mode="before",
    )
    @classmethod
    def normalize_safe_labels(cls, value: Any, info: ValidationInfo) -> str:
        return _require_pattern(value, field_name=info.field_name, pattern=_SAFE_LABEL)

    @field_validator("item_path", "label_path", mode="before")
    @classmethod
    def normalize_relative_paths(cls, value: Any, info: ValidationInfo) -> str:
        return _normalize_relative_path(value, field_name=info.field_name)

    @field_validator("item_hash", "label_hash", "content_hash", mode="before")
    @classmethod
    def normalize_hashes(cls, value: Any, info: ValidationInfo) -> str:
        return _require_sha256(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_origin_boundary(self) -> "DatasetManifestRecordV2":
        if self.split is DatasetSplitV2.PLUMBING:
            if self.evidence_origin is not EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
                raise ValueError("plumbing fixtures must remain SYNTHETIC_NON_EVIDENCE")
            return self
        if self.evidence_origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
            raise ValueError("synthetic non-evidence cannot enter development or confirmatory datasets")
        if (
            self.split is DatasetSplitV2.CONFIRMATORY
            and self.evidence_origin is not EvidenceOrigin.REAL_MODEL_EXECUTION
        ):
            raise ValueError("confirmatory publication evidence must use REAL_MODEL_EXECUTION")
        return self


class DatasetManifestV2(_FrozenDatasetModel):
    schema_version: Literal["POI_MPP_DATASET_MANIFEST_V2"] = "POI_MPP_DATASET_MANIFEST_V2"
    dataset_id: str
    split: DatasetSplitV2
    records: tuple[DatasetManifestRecordV2, ...]

    @field_validator("dataset_id", mode="before")
    @classmethod
    def normalize_dataset_id(cls, value: Any) -> str:
        return _require_pattern(value, field_name="dataset_id", pattern=_SAFE_LABEL)

    @field_validator("records", mode="before")
    @classmethod
    def normalize_records(cls, value: Any) -> tuple[DatasetManifestRecordV2, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("records must be a sequence")
        records = tuple(
            item if isinstance(item, DatasetManifestRecordV2) else DatasetManifestRecordV2.model_validate(item)
            for item in value
        )
        if not records:
            raise ValueError("records must not be empty")
        return tuple(sorted(records, key=lambda item: item.record_id))

    @model_validator(mode="after")
    def validate_manifest_records(self) -> "DatasetManifestV2":
        if any(record.split is not self.split for record in self.records):
            raise ValueError("all records must match the manifest split")
        record_ids = [record.record_id for record in self.records]
        item_hashes = [record.item_hash for record in self.records]
        label_hashes = [record.label_hash for record in self.records]
        content_hashes = [record.content_hash for record in self.records]
        if len(set(record_ids)) != len(record_ids):
            raise ValueError("duplicate record_id in dataset manifest")
        if len(set(item_hashes)) != len(item_hashes):
            raise ValueError("duplicate item_hash in dataset manifest")
        if len(set(label_hashes)) != len(label_hashes):
            raise ValueError("duplicate label_hash in dataset manifest")
        if len(set(content_hashes)) != len(content_hashes):
            raise ValueError("duplicate content_hash in dataset manifest")
        return self

    def canonical_material(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def dataset_manifest_hash(self) -> str:
        return digest(_DATASET_MANIFEST_V2_DOMAIN, self.canonical_material())

    def rooted_file_bindings(self, root: str | Path) -> tuple[DatasetRootedBinding, ...]:
        root_path = Path(root)
        _assert_no_symlink_components(root_path, label="root")
        resolved_root = root_path.resolve(strict=True)
        bindings: list[DatasetRootedBinding] = []
        for record in self.records:
            item_path = self._resolve_rooted_member(
                resolved_root,
                relative_path=record.item_path,
                label="item path",
            )
            label_path = self._resolve_rooted_member(
                resolved_root,
                relative_path=record.label_path,
                label="label path",
            )
            bindings.append(
                DatasetRootedBinding(
                    record_id=record.record_id,
                    item_path=item_path,
                    label_path=label_path,
                )
            )
        return tuple(bindings)

    def verify_rooted_file_hashes(self, root: str | Path) -> tuple[str, ...]:
        """Verify the exact item and label bytes bound by this manifest.

        ``content_hash`` remains the normalized semantic-content binding defined by
        the dataset producer; this method verifies only the raw file hashes whose
        byte-level meaning is unambiguous.
        """

        records_by_id = {record.record_id: record for record in self.records}
        verified: list[str] = []
        for binding in self.rooted_file_bindings(root):
            record = records_by_id[binding.record_id]
            actual_item_hash = hashlib.sha256(binding.item_path.read_bytes()).hexdigest()
            if actual_item_hash != record.item_hash:
                raise ValueError(f"item_hash mismatch for {record.record_id}")
            actual_label_hash = hashlib.sha256(binding.label_path.read_bytes()).hexdigest()
            if actual_label_hash != record.label_hash:
                raise ValueError(f"label_hash mismatch for {record.record_id}")
            verified.append(record.record_id)
        return tuple(verified)

    def decision_counts(self) -> dict[str, int]:
        """Return a complete deterministic decision-class summary."""

        return {
            decision.value: sum(
                record.expected_decision is decision for record in self.records
            )
            for decision in DatasetExpectedDecision
        }

    def error_family_counts(self) -> dict[str, int]:
        """Return deterministic error-family counts for calibration review."""

        families = sorted({record.error_family for record in self.records})
        return {
            family: sum(record.error_family == family for record in self.records)
            for family in families
        }

    @staticmethod
    def _resolve_rooted_member(root: Path, *, relative_path: str, label: str) -> Path:
        candidate = root / PurePosixPath(relative_path)
        _assert_no_symlink_components(candidate, label=label)
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise ValueError(f"{label} escapes root") from error
        if resolved.is_symlink():
            raise ValueError(f"{label} may not be a symlink")
        return resolved


def assert_v2_split_isolation(
    development: DatasetManifestV2,
    confirmatory: DatasetManifestV2,
) -> None:
    """Fail closed when a V2 development/confirmatory pair shares bound identity.

    Near-duplicate and source-family isolation require separately reviewed source
    metadata and are intentionally not inferred from these record fields.
    """

    if development.split is not DatasetSplitV2.DEVELOPMENT:
        raise ValueError("development manifest must use DEVELOPMENT split")
    if confirmatory.split is not DatasetSplitV2.CONFIRMATORY:
        raise ValueError("confirmatory manifest must use CONFIRMATORY split")

    fields = (
        "record_id",
        "item_hash",
        "label_hash",
        "content_hash",
        "deduplication_group",
    )
    for field_name in fields:
        development_values = {
            getattr(record, field_name) for record in development.records
        }
        confirmatory_values = {
            getattr(record, field_name) for record in confirmatory.records
        }
        overlap = sorted(development_values & confirmatory_values)
        if overlap:
            raise ValueError(
                f"{field_name} overlap between development and confirmatory manifests"
            )
