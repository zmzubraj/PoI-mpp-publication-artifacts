"""Dataset manifests and split-isolation checks for semantic evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
import re

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from poi_mpp.evidence.models import EvidenceOrigin


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class DatasetSplit(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    CONFIRMATORY = "CONFIRMATORY"
    PLUMBING = "PLUMBING"


class DatasetLeakageError(ValueError):
    """Raised when confirmatory data overlap breaks the publication boundary."""

    def __init__(self, reasons: Iterable[str]):
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__("; ".join(self.reasons) if self.reasons else "dataset leakage detected")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetRecord(_FrozenModel):
    record_id: str
    split: DatasetSplit
    origin: EvidenceOrigin
    source_family: str
    source_hash: str
    content_hash: str

    @field_validator("record_id", "source_family")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dataset fields must not be blank")
        return value.strip().lower()

    @field_validator("source_hash", "content_hash")
    @classmethod
    def validate_hash(cls, value: str, info) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def validate_origin_boundary(self) -> "DatasetRecord":
        if self.split is DatasetSplit.PLUMBING and self.origin is not EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
            raise ValueError("plumbing fixtures must remain SYNTHETIC_NON_EVIDENCE")
        if self.split is not DatasetSplit.PLUMBING and self.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
            raise ValueError("synthetic non-evidence cannot enter development or confirmatory datasets")
        return self


class DatasetManifest(_FrozenModel):
    dataset_id: str
    split: DatasetSplit
    records: tuple[DatasetRecord, ...]

    @field_validator("dataset_id")
    @classmethod
    def reject_blank_dataset_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dataset_id must not be blank")
        return value

    @model_validator(mode="after")
    def validate_records(self) -> "DatasetManifest":
        if not self.records:
            raise ValueError("dataset manifests require at least one record")
        record_ids = [record.record_id for record in self.records]
        content_hashes = [record.content_hash for record in self.records]
        source_hashes = [record.source_hash for record in self.records]
        if len(set(record_ids)) != len(record_ids):
            raise ValueError("duplicate record_id in dataset manifest")
        if len(set(content_hashes)) != len(content_hashes):
            raise ValueError("duplicate content_hash in dataset manifest")
        if len(set(source_hashes)) != len(source_hashes):
            raise ValueError("duplicate source_hash in dataset manifest")
        if any(record.split is not self.split for record in self.records):
            raise ValueError("all records must match the manifest split")
        return self


def _coerce_id_set(value: object) -> set[str] | None:
    if isinstance(value, set) and all(isinstance(item, str) for item in value):
        return set(value)
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return set(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(value)
    return None


def assert_confirmatory_isolation(
    development: DatasetManifest | Iterable[str],
    confirmatory: DatasetManifest | Iterable[str],
) -> None:
    """Reject any development/confirmatory overlap before publication evaluation."""

    development_ids = _coerce_id_set(development)
    confirmatory_ids = _coerce_id_set(confirmatory)
    if development_ids is not None and confirmatory_ids is not None:
        overlap = sorted(development_ids & confirmatory_ids)
        if overlap:
            raise DatasetLeakageError(f"record id overlap: {record_id}" for record_id in overlap)
        return

    if not isinstance(development, DatasetManifest) or not isinstance(confirmatory, DatasetManifest):
        raise TypeError("assert_confirmatory_isolation requires DatasetManifest values or ID iterables")
    if development.split is not DatasetSplit.DEVELOPMENT:
        raise ValueError("development manifest must use the DEVELOPMENT split")
    if confirmatory.split is not DatasetSplit.CONFIRMATORY:
        raise ValueError("confirmatory manifest must use the CONFIRMATORY split")

    development_ids = {record.record_id for record in development.records}
    confirmatory_ids = {record.record_id for record in confirmatory.records}
    development_content_hashes = {record.content_hash for record in development.records}
    confirmatory_content_hashes = {record.content_hash for record in confirmatory.records}
    development_source_hashes = {record.source_hash for record in development.records}
    confirmatory_source_hashes = {record.source_hash for record in confirmatory.records}
    development_source_families = {record.source_family for record in development.records}
    confirmatory_source_families = {record.source_family for record in confirmatory.records}

    reasons: list[str] = []
    for record_id in sorted(development_ids & confirmatory_ids):
        reasons.append(f"record id overlap: {record_id}")
    for content_hash in sorted(development_content_hashes & confirmatory_content_hashes):
        reasons.append(f"content hash overlap: {content_hash}")
    for source_hash in sorted(development_source_hashes & confirmatory_source_hashes):
        reasons.append(f"source hash overlap: {source_hash}")
    for source_family in sorted(development_source_families & confirmatory_source_families):
        reasons.append(f"source family overlap: {source_family}")
    if reasons:
        raise DatasetLeakageError(reasons)
