"""Immutable semantic authority registry snapshots and external crypto receipts."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

from poi_mpp.auditor.semantic.authority import SemanticAuthorityRecordV1
from poi_mpp.evidence.canonical import canonical_bytes as _canonical_bytes
from poi_mpp.evidence.canonical import digest


SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1_SCHEMA = "POI_MPP_SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1"
SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1_DOMAIN = "SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1"
SEMANTIC_AUTHORITY_REGISTRY_ENTRY_V1_DOMAIN = "SEMANTIC_AUTHORITY_REGISTRY_ENTRY_V1"
SEMANTIC_AUTHORITY_CRYPTO_VERIFICATION_V1_SCHEMA = (
    "POI_MPP_SEMANTIC_AUTHORITY_CRYPTO_VERIFICATION_V1"
)
SEMANTIC_AUTHORITY_CRYPTO_VERIFICATION_V1_DOMAIN = (
    "SEMANTIC_AUTHORITY_CRYPTO_VERIFICATION_V1"
)
SEMANTIC_AUTHORITY_VERIFICATION_RECEIPT_V1_SCHEMA = (
    "POI_MPP_SEMANTIC_AUTHORITY_VERIFICATION_RECEIPT_V1"
)
SEMANTIC_AUTHORITY_VERIFICATION_RECEIPT_V1_DOMAIN = (
    "SEMANTIC_AUTHORITY_VERIFICATION_RECEIPT_V1"
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}\Z")


class _FrozenRegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _ordered_unique(reasons: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reasons))


def _normalized_hash(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value.strip()) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value.strip()


def _normalized_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an exact integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _normalized_token(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN.fullmatch(value.strip()) is None:
        raise ValueError(f"{field_name} has an invalid format")
    return value.strip()


def _record_entry_material(record: SemanticAuthorityRecordV1) -> dict[str, object]:
    payload = record.model_dump(mode="json")
    payload.pop("registry_snapshot_hash", None)
    scope = dict(payload["scope"])
    # The registry anchors stable authority/key capability. The task-specific
    # policy hash is instead bound by the detached signed authority record and
    # its canonical cryptographic-verification receipt. Excluding it here
    # prevents a circular policy_hash <-> registry_snapshot_hash dependency.
    scope.pop("semantic_policy_hash", None)
    payload["scope"] = scope
    return payload


class SemanticAuthorityRegistryEntryV1(_FrozenRegistryModel):
    authority_id: str
    key_id: str
    registry_revision: int
    registry_entry_digest: str

    @field_validator("authority_id", "key_id", mode="before")
    @classmethod
    def normalize_tokens(cls, value: Any, info: ValidationInfo) -> str:
        return _normalized_token(value, field_name=info.field_name)

    @field_validator("registry_revision", mode="before")
    @classmethod
    def normalize_revision(cls, value: Any) -> int:
        return _normalized_positive_int(value, field_name="registry_revision")

    @field_validator("registry_entry_digest", mode="before")
    @classmethod
    def normalize_digest(cls, value: Any) -> str:
        return _normalized_hash(value, field_name="registry_entry_digest")

    @classmethod
    def from_authority_record(
        cls, record: SemanticAuthorityRecordV1
    ) -> "SemanticAuthorityRegistryEntryV1":
        return cls(
            authority_id=record.authority_id,
            key_id=record.key_id,
            registry_revision=record.registry_revision,
            registry_entry_digest=digest(
                SEMANTIC_AUTHORITY_REGISTRY_ENTRY_V1_DOMAIN,
                _record_entry_material(record),
            ),
        )


class SemanticAuthorityVerificationReceiptV1(_FrozenRegistryModel):
    schema_version: Literal[SEMANTIC_AUTHORITY_VERIFICATION_RECEIPT_V1_SCHEMA] = (
        SEMANTIC_AUTHORITY_VERIFICATION_RECEIPT_V1_SCHEMA
    )
    verifier_id: str
    verification_method: Literal["OPENSSH_DETACHED_SIGNATURE"]
    verified_on: date
    authority_record_digest: str
    key_id: str
    authority_record_sha256: str
    detached_signature_sha256: str
    allowed_signers_sha256: str
    verifier_output_sha256: str

    @field_validator("verifier_id", "key_id", mode="before")
    @classmethod
    def normalize_tokens(cls, value: Any, info: ValidationInfo) -> str:
        return _normalized_token(value, field_name=info.field_name)

    @field_validator(
        "authority_record_digest",
        "authority_record_sha256",
        "detached_signature_sha256",
        "allowed_signers_sha256",
        "verifier_output_sha256",
        mode="before",
    )
    @classmethod
    def normalize_hashes(cls, value: Any, info: ValidationInfo) -> str:
        return _normalized_hash(value, field_name=info.field_name)

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    @property
    def receipt_digest(self) -> str:
        return digest(
            SEMANTIC_AUTHORITY_VERIFICATION_RECEIPT_V1_DOMAIN,
            self.canonical_payload(),
        )


class SemanticAuthorityCryptoVerificationV1(_FrozenRegistryModel):
    schema_version: Literal[SEMANTIC_AUTHORITY_CRYPTO_VERIFICATION_V1_SCHEMA] = (
        SEMANTIC_AUTHORITY_CRYPTO_VERIFICATION_V1_SCHEMA
    )
    authority_id: str
    key_id: str
    record_digest: str
    registry_revision: int
    registry_snapshot_hash: str
    cryptographic_validity_verified: bool
    verification_receipt: SemanticAuthorityVerificationReceiptV1

    @field_validator("authority_id", "key_id", mode="before")
    @classmethod
    def normalize_tokens(cls, value: Any, info: ValidationInfo) -> str:
        return _normalized_token(value, field_name=info.field_name)

    @field_validator("record_digest", "registry_snapshot_hash", mode="before")
    @classmethod
    def normalize_hashes(cls, value: Any, info: ValidationInfo) -> str:
        return _normalized_hash(value, field_name=info.field_name)

    @field_validator("registry_revision", mode="before")
    @classmethod
    def normalize_revision(cls, value: Any) -> int:
        return _normalized_positive_int(value, field_name="registry_revision")

    @field_validator("cryptographic_validity_verified", mode="before")
    @classmethod
    def normalize_verified_flag(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("cryptographic_validity_verified must be a boolean")
        return value

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(
            SEMANTIC_AUTHORITY_CRYPTO_VERIFICATION_V1_DOMAIN,
            self.canonical_payload(),
        )

    @property
    def verification_digest(self) -> str:
        return digest(
            SEMANTIC_AUTHORITY_CRYPTO_VERIFICATION_V1_DOMAIN,
            self.canonical_payload(),
        )


class SemanticAuthorityRegistrySnapshotV1(_FrozenRegistryModel):
    schema_version: Literal[SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1_SCHEMA] = (
        SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1_SCHEMA
    )
    registry_revision: int
    authority_records: tuple[SemanticAuthorityRecordV1, ...]
    entries: tuple[SemanticAuthorityRegistryEntryV1, ...]

    @field_validator("registry_revision", mode="before")
    @classmethod
    def normalize_revision(cls, value: Any) -> int:
        return _normalized_positive_int(value, field_name="registry_revision")

    @model_validator(mode="before")
    @classmethod
    def derive_entries(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("registry snapshot input must be a mapping")
        if "authority_records" not in value:
            raise ValueError("authority_records is required")
        raw_records = value["authority_records"]
        if not isinstance(raw_records, (list, tuple)):
            raise ValueError("authority_records must be a sequence")
        records = tuple(
            item
            if isinstance(item, SemanticAuthorityRecordV1)
            else SemanticAuthorityRecordV1.model_validate(item)
            for item in raw_records
        )
        sorted_records = tuple(sorted(records, key=lambda item: (item.authority_id, item.key_id)))
        revision = _normalized_positive_int(value.get("registry_revision"), field_name="registry_revision")
        entries = tuple(
            SemanticAuthorityRegistryEntryV1.from_authority_record(record)
            for record in sorted_records
        )
        return {
            "schema_version": value.get(
                "schema_version",
                SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1_SCHEMA,
            ),
            "registry_revision": revision,
            "authority_records": sorted_records,
            "entries": entries,
        }

    @model_validator(mode="after")
    def validate_snapshot_contract(self) -> "SemanticAuthorityRegistrySnapshotV1":
        authority_ids = [record.authority_id for record in self.authority_records]
        if len(set(authority_ids)) != len(authority_ids):
            raise ValueError("authority_id must be unique within the registry snapshot")
        key_ids = [record.key_id for record in self.authority_records]
        if len(set(key_ids)) != len(key_ids):
            raise ValueError("key_id must be unique within the registry snapshot")
        if tuple(
            SemanticAuthorityRegistryEntryV1.from_authority_record(record)
            for record in self.authority_records
        ) != self.entries:
            raise ValueError("entries must match the canonical authority record digest entries")
        snapshot_hash = self.preview_snapshot_hash(
            registry_revision=self.registry_revision,
            authority_records=self.authority_records,
        )
        for record in self.authority_records:
            if record.registry_revision != self.registry_revision:
                raise ValueError("authority record registry_revision does not match snapshot")
            if record.registry_snapshot_hash != snapshot_hash:
                raise ValueError("authority record registry_snapshot_hash does not match snapshot")
        return self

    @classmethod
    def preview_entries(
        cls,
        *,
        authority_records: tuple[SemanticAuthorityRecordV1, ...] | list[SemanticAuthorityRecordV1],
    ) -> tuple[SemanticAuthorityRegistryEntryV1, ...]:
        records = tuple(authority_records)
        return tuple(
            SemanticAuthorityRegistryEntryV1.from_authority_record(record)
            for record in sorted(records, key=lambda item: (item.authority_id, item.key_id))
        )

    @classmethod
    def preview_snapshot_hash(
        cls,
        *,
        registry_revision: int,
        authority_records: tuple[SemanticAuthorityRecordV1, ...] | list[SemanticAuthorityRecordV1],
    ) -> str:
        normalized_revision = _normalized_positive_int(
            registry_revision,
            field_name="registry_revision",
        )
        entries = cls.preview_entries(authority_records=authority_records)
        payload = {
            "schema_version": SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1_SCHEMA,
            "registry_revision": normalized_revision,
            "entries": [entry.model_dump(mode="json") for entry in entries],
        }
        return digest(SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1_DOMAIN, payload)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "registry_revision": self.registry_revision,
            "entries": [entry.model_dump(mode="json") for entry in self.entries],
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(
            SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1_DOMAIN,
            self.canonical_payload(),
        )

    @property
    def snapshot_hash(self) -> str:
        return digest(
            SEMANTIC_AUTHORITY_REGISTRY_SNAPSHOT_V1_DOMAIN,
            self.canonical_payload(),
        )

    def get_authority(self, authority_id: str) -> SemanticAuthorityRecordV1 | None:
        normalized_authority_id = _normalized_token(authority_id, field_name="authority_id")
        for record in self.authority_records:
            if record.authority_id == normalized_authority_id:
                return record
        return None

    def get_by_key_id(self, key_id: str) -> SemanticAuthorityRecordV1 | None:
        normalized_key_id = _normalized_token(key_id, field_name="key_id")
        for record in self.authority_records:
            if record.key_id == normalized_key_id:
                return record
        return None

    def binding_reasons(self, record: SemanticAuthorityRecordV1) -> tuple[str, ...]:
        reasons: list[str] = []
        bound_record = self.get_authority(record.authority_id)
        if bound_record is None:
            reasons.append("authority record is not present in this registry snapshot")
            return tuple(reasons)
        if bound_record != record:
            reasons.append("authority record payload does not match the registry snapshot")
        if record.registry_revision != self.registry_revision:
            reasons.append("authority record registry_revision is stale for this snapshot")
        if record.registry_snapshot_hash != self.snapshot_hash:
            reasons.append("authority record registry snapshot hash is stale for this snapshot")
        return _ordered_unique(reasons)

    def cryptographic_binding_reasons(
        self,
        *,
        record: SemanticAuthorityRecordV1,
        cryptographic_verification: SemanticAuthorityCryptoVerificationV1,
    ) -> tuple[str, ...]:
        reasons = list(self.binding_reasons(record))
        if cryptographic_verification.authority_id != record.authority_id:
            reasons.append("cryptographic verification authority_id mismatch")
        if cryptographic_verification.key_id != record.key_id:
            reasons.append("cryptographic verification key_id mismatch")
        if cryptographic_verification.record_digest != record.record_digest:
            reasons.append("cryptographic verification record_digest mismatch")
        if cryptographic_verification.registry_revision != self.registry_revision:
            reasons.append("cryptographic verification registry_revision is stale")
        if cryptographic_verification.registry_snapshot_hash != self.snapshot_hash:
            reasons.append("cryptographic verification registry snapshot hash is stale")
        if cryptographic_verification.cryptographic_validity_verified is not True:
            reasons.append("cryptographic verification remains unverified by the canonical external verifier")
        receipt = cryptographic_verification.verification_receipt
        if receipt.authority_record_digest != record.record_digest:
            reasons.append("receipt authority_record_digest mismatch")
        if receipt.key_id != record.key_id:
            reasons.append("receipt key_id mismatch")
        if receipt.detached_signature_sha256 != record.detached_signature_sha256:
            reasons.append("receipt detached_signature_sha256 mismatch")
        return _ordered_unique(reasons)

    def active_lookup_reasons(
        self,
        *,
        authority_id: str,
        cryptographic_verification: SemanticAuthorityCryptoVerificationV1,
        on_date: date | None = None,
    ) -> tuple[str, ...]:
        record = self.get_authority(authority_id)
        if record is None:
            return ("authority record is absent from the registry snapshot",)
        reasons = list(
            self.cryptographic_binding_reasons(
                record=record,
                cryptographic_verification=cryptographic_verification,
            )
        )
        reasons.extend(record.scope_gate_reasons(on_date=on_date))
        return _ordered_unique(reasons)

    def get_active_authority(
        self,
        *,
        authority_id: str,
        cryptographic_verification: SemanticAuthorityCryptoVerificationV1,
        on_date: date | None = None,
    ) -> SemanticAuthorityRecordV1 | None:
        record = self.get_authority(authority_id)
        if record is None:
            return None
        if self.active_lookup_reasons(
            authority_id=authority_id,
            cryptographic_verification=cryptographic_verification,
            on_date=on_date,
        ):
            return None
        return record

    def claim_scope_reasons(
        self,
        record: SemanticAuthorityRecordV1,
        *,
        claim_id: str,
        claim_spec_hash: str,
    ) -> tuple[str, ...]:
        reasons = list(self.binding_reasons(record))
        if record.scope.claim_id != _normalized_token(claim_id, field_name="claim_id"):
            reasons.append("authority claim_id mismatch")
        if record.scope.claim_spec_hash != _normalized_hash(
            claim_spec_hash,
            field_name="claim_spec_hash",
        ):
            reasons.append("authority claim_spec_hash mismatch")
        return _ordered_unique(reasons)

    def claim_scope_match(
        self,
        record: SemanticAuthorityRecordV1,
        *,
        claim_id: str,
        claim_spec_hash: str,
    ) -> bool:
        return not self.claim_scope_reasons(
            record,
            claim_id=claim_id,
            claim_spec_hash=claim_spec_hash,
        )

    def dataset_scope_reasons(
        self,
        record: SemanticAuthorityRecordV1,
        *,
        dataset_manifest_hash: str,
    ) -> tuple[str, ...]:
        reasons = list(self.binding_reasons(record))
        if record.scope.dataset_manifest_hash != _normalized_hash(
            dataset_manifest_hash,
            field_name="dataset_manifest_hash",
        ):
            reasons.append("authority dataset_manifest_hash mismatch")
        return _ordered_unique(reasons)

    def dataset_scope_match(
        self,
        record: SemanticAuthorityRecordV1,
        *,
        dataset_manifest_hash: str,
    ) -> bool:
        return not self.dataset_scope_reasons(
            record,
            dataset_manifest_hash=dataset_manifest_hash,
        )

    def policy_scope_reasons(
        self,
        record: SemanticAuthorityRecordV1,
        *,
        semantic_policy_hash: str,
    ) -> tuple[str, ...]:
        reasons = list(self.binding_reasons(record))
        if record.scope.semantic_policy_hash != _normalized_hash(
            semantic_policy_hash,
            field_name="semantic_policy_hash",
        ):
            reasons.append("authority semantic_policy_hash mismatch")
        return _ordered_unique(reasons)

    def policy_scope_match(
        self,
        record: SemanticAuthorityRecordV1,
        *,
        semantic_policy_hash: str,
    ) -> bool:
        return not self.policy_scope_reasons(
            record,
            semantic_policy_hash=semantic_policy_hash,
        )

    def environment_scope_reasons(
        self,
        record: SemanticAuthorityRecordV1,
        *,
        runtime_environment_hash: str,
    ) -> tuple[str, ...]:
        reasons = list(self.binding_reasons(record))
        if record.scope.runtime_environment_hash != _normalized_hash(
            runtime_environment_hash,
            field_name="runtime_environment_hash",
        ):
            reasons.append("authority runtime_environment_hash mismatch")
        return _ordered_unique(reasons)

    def environment_scope_match(
        self,
        record: SemanticAuthorityRecordV1,
        *,
        runtime_environment_hash: str,
    ) -> bool:
        return not self.environment_scope_reasons(
            record,
            runtime_environment_hash=runtime_environment_hash,
        )
