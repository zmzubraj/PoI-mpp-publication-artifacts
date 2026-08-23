"""Strict local Foundry gas/state measurement collection for E7."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
import json
from pathlib import Path
import hashlib
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig, config_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.evidence.validation import ArtifactValidationError


PUBLICATION_EVIDENCE_AUTHORIZED = "PUBLICATION_EVIDENCE_AUTHORIZED"
E7_PUBLICATION_SCOPE = "E7_FOUNDRY_PUBLICATION_V1"
E7_REPORT_SCHEMA_VERSION = "POI_MPP_E7_FOUNDRY_REPORT_V1"
E7_BUNDLE_SCHEMA_VERSION = "POI_MPP_E7_BUNDLE_V1"
E7_PARITY_SCHEMA_VERSION = "POI_MPP_E7_PARITY_ATTACHMENT_V1"
E7_COLLECTOR_CAPABILITY_SCHEMA_VERSION = "POI_MPP_E7_COLLECTOR_CAPABILITY_V1"
E7_COMMAND_TRANSCRIPT_SCHEMA_VERSION = "POI_MPP_E7_COMMAND_TRANSCRIPT_V1"
E7_PARITY_VERIFICATION_SCHEMA_VERSION = "POI_MPP_E7_PARITY_VERIFICATION_V1"
_ROOT = Path(__file__).resolve().parents[3]
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_OUTPUT_LIMIT = 20_000
_CANONICAL_REPORT_RELATIVE_PATH = Path("out") / "e7_foundry_measurements.json"
_E7_ARTIFACTS = (
    ("ModelRegistry", "src/ModelRegistry.sol", "out/ModelRegistry.sol/ModelRegistry.json"),
    ("TaskManager", "src/TaskManager.sol", "out/TaskManager.sol/TaskManager.json"),
    ("CommitmentHub", "src/CommitmentHub.sol", "out/CommitmentHub.sol/CommitmentHub.json"),
    ("AuditManager", "src/AuditManager.sol", "out/AuditManager.sol/AuditManager.json"),
    ("ReceiptManager", "src/ReceiptManager.sol", "out/ReceiptManager.sol/ReceiptManager.json"),
    ("CreditEngine", "src/CreditEngine.sol", "out/CreditEngine.sol/CreditEngine.json"),
    ("GasSnapshots", "test/GasSnapshots.t.sol", "out/GasSnapshots.t.sol/GasSnapshots.json"),
)
_E7_PARITY_SOURCES = (
    Path("src/poi_mpp/evidence/canonical.py"),
    Path("src/poi_mpp/protocol/commitment.py"),
    Path("src/poi_mpp/protocol/credit.py"),
    Path("src/poi_mpp/protocol/receipt.py"),
    Path("src/poi_mpp/protocol/reference_machine.py"),
    Path("src/poi_mpp/protocol/types.py"),
    Path("contracts/src/PolicyRegistry.sol"),
    Path("contracts/src/ModelRegistry.sol"),
    Path("contracts/src/TaskManager.sol"),
    Path("contracts/src/CommitmentHub.sol"),
    Path("contracts/src/AuditManager.sol"),
    Path("contracts/src/ReceiptManager.sol"),
    Path("contracts/src/CreditEngine.sol"),
    Path("contracts/test/ProtocolRoles.t.sol"),
    Path("contracts/test/HashVectors.t.sol"),
    Path("contracts/script/ProtocolVectorWitness.s.sol"),
    Path("scripts/export_solidity_vectors.py"),
    Path("tests/integration/test_python_solidity_parity.py"),
    Path("tests/fixtures/protocol_vectors.json"),
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorityBoundaryError(ValueError):
    """Raised when the E7 CLI would overstate authority."""


class E7Operation(StrEnum):
    MODEL_REGISTER = "MODEL_REGISTER"
    TASK_CREATE = "TASK_CREATE"
    COMMIT_RESPONSE = "COMMIT_RESPONSE"
    AUDIT_OPEN = "AUDIT_OPEN"
    AUDIT_RECORD_RESULT = "AUDIT_RECORD_RESULT"
    AUDIT_RECORD_DA = "AUDIT_RECORD_DA"
    OPEN_CHALLENGE = "OPEN_CHALLENGE"
    RECEIPT_MINT_PENDING = "RECEIPT_MINT_PENDING"
    RECEIPT_ACTIVATE = "RECEIPT_ACTIVATE"
    RECEIPT_MARK_CHALLENGED = "RECEIPT_MARK_CHALLENGED"
    RECEIPT_SLASH = "RECEIPT_SLASH"
    CREDIT_ALLOCATE = "CREDIT_ALLOCATE"


class E7ReportAuthority(StrEnum):
    CANONICAL_COLLECTOR_REPORT = "CANONICAL_COLLECTOR_REPORT"
    PLUMBING_FIXTURE = "PLUMBING_FIXTURE"


class E7ExpectedMeasurement(_FrozenModel):
    operation: E7Operation
    batch_size: int = Field(gt=0, le=1024)

    @property
    def key(self) -> str:
        return f"{self.operation.value}:{self.batch_size}"


class E7MeasurementContract(_FrozenModel):
    schema_version: str = "POI_MPP_E7_MEASUREMENT_CONTRACT_V1"
    publication_scope: str = E7_PUBLICATION_SCOPE
    required_run_origin: EvidenceOrigin = EvidenceOrigin.FOUNDRY_MEASUREMENT
    required_run_authorization_scope: str = PUBLICATION_EVIDENCE_AUTHORIZED
    required_test_contract: str = "GasSnapshots"
    required_witness_contract: str = "GasSnapshotWitness"
    expected_measurements: tuple[E7ExpectedMeasurement, ...]

    @model_validator(mode="after")
    def validate_contract(self) -> "E7MeasurementContract":
        if self.publication_scope != E7_PUBLICATION_SCOPE:
            raise ValueError(f"publication_scope must equal {E7_PUBLICATION_SCOPE}")
        if self.required_run_origin is not EvidenceOrigin.FOUNDRY_MEASUREMENT:
            raise ValueError("required_run_origin must equal FOUNDRY_MEASUREMENT")
        if self.required_run_authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
            raise ValueError(
                f"required_run_authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
            )
        if not self.expected_measurements:
            raise ValueError("expected_measurements must not be empty")
        keys = tuple(item.key for item in self.expected_measurements)
        if len(keys) != len(set(keys)):
            raise ValueError("expected_measurements must be unique by operation/batch_size")
        return self


class _RawMeasurement(_FrozenModel):
    operation: E7Operation
    batch_size: int = Field(gt=0, le=1024)
    gas_used: int = Field(ge=0)
    changed_storage_slot_count: int = Field(ge=0)
    storage_change_upper_bound_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_storage_upper_bound(self) -> "_RawMeasurement":
        if self.storage_change_upper_bound_bytes != self.changed_storage_slot_count * 32:
            raise ValueError("storage_change_upper_bound_bytes must equal changed_storage_slot_count * 32")
        return self

    @property
    def key(self) -> str:
        return f"{self.operation.value}:{self.batch_size}"


class _RawFoundryReport(_FrozenModel):
    schema_version: str
    test_contract: str
    witness_contract: str
    chain_id: int = Field(gt=0)
    block_gas_limit: int = Field(gt=0)
    measurements: tuple[_RawMeasurement, ...]

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != E7_REPORT_SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {E7_REPORT_SCHEMA_VERSION}")
        return value

    @field_validator("test_contract", "witness_contract")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @model_validator(mode="after")
    def validate_unique_keys(self) -> "_RawFoundryReport":
        keys = tuple(measurement.key for measurement in self.measurements)
        if not keys:
            raise ValueError("measurements must not be empty")
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate operation/batch_size measurement keys are forbidden")
        return self


class E7ContractArtifact(_FrozenModel):
    contract_name: str
    source_path: str
    source_hash: str
    creation_bytecode_hash: str
    deployed_bytecode_hash: str

    @field_validator("contract_name", "source_path")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("source_hash", "creation_bytecode_hash", "deployed_bytecode_hash")
    @classmethod
    def require_sha256(cls, value: str, info: ValidationInfo) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 hex digest")
        return value


class E7Manifest(_FrozenModel):
    schema_version: str = "POI_MPP_E7_MANIFEST_V1"
    contracts_root: str
    foundry_version: str
    compiler_version: str
    optimizer_enabled: bool
    optimizer_runs: int = Field(ge=0)
    git_revision: str
    git_dirty: bool
    chain_id: int = Field(gt=0)
    block_gas_limit: int = Field(gt=0)
    raw_report_hash: str
    canonical_report_path: str
    test_contract: str
    witness_contract: str
    gas_measurement_surface: str
    storage_measurement_surface: str
    command: tuple[str, ...]
    artifacts: tuple[E7ContractArtifact, ...]

    @field_validator(
        "contracts_root",
        "foundry_version",
        "compiler_version",
        "canonical_report_path",
        "test_contract",
        "witness_contract",
        "gas_measurement_surface",
        "storage_measurement_surface",
    )
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("raw_report_hash")
    @classmethod
    def validate_raw_report_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("raw_report_hash must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("git_revision")
    @classmethod
    def validate_git_revision(cls, value: str) -> str:
        if value != "UNVERSIONED_BLOCKED" and not _GIT_SHA.fullmatch(value):
            raise ValueError("git_revision must be a git SHA-1 or UNVERSIONED_BLOCKED")
        return value

    @model_validator(mode="after")
    def validate_artifacts(self) -> "E7Manifest":
        if not self.artifacts:
            raise ValueError("artifacts must not be empty")
        names = tuple(item.contract_name for item in self.artifacts)
        if len(names) != len(set(names)):
            raise ValueError("artifacts must be unique by contract_name")
        if not self.command:
            raise ValueError("command must not be empty")
        return self


class E7CollectorCapability(_FrozenModel):
    schema_version: str = E7_COLLECTOR_CAPABILITY_SCHEMA_VERSION
    report_authority: E7ReportAuthority
    observed_report_path: str
    canonical_report_path: str
    anchored_no_follow: bool
    symlink_free: bool

    @field_validator("observed_report_path", "canonical_report_path")
    @classmethod
    def require_nonblank_path(cls, value: str, info: ValidationInfo) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @model_validator(mode="after")
    def validate_authority(self) -> "E7CollectorCapability":
        if self.report_authority is E7ReportAuthority.CANONICAL_COLLECTOR_REPORT:
            if not self.anchored_no_follow or not self.symlink_free:
                raise ValueError("canonical collector reports require anchored no-follow and symlink-free provenance")
        return self


class E7MeasurementRow(_FrozenModel):
    schema_version: str = "POI_MPP_E7_MEASUREMENT_ROW_V1"
    run_id: str
    experiment_id: str
    measurement_key: str
    operation: E7Operation
    batch_size: int = Field(gt=0, le=1024)
    origin: EvidenceOrigin
    publication_scope: str
    gas_used: int = Field(ge=0)
    gas_unit: str = "gas"
    changed_storage_slot_count: int = Field(ge=0)
    storage_change_upper_bound_bytes: int = Field(ge=0)
    storage_unit: str = "bytes_upper_bound"
    test_contract: str
    witness_contract: str
    chain_id: int = Field(gt=0)
    block_gas_limit: int = Field(gt=0)
    compiler_version: str
    optimizer_enabled: bool
    optimizer_runs: int = Field(ge=0)
    foundry_version: str
    git_revision: str
    raw_report_hash: str
    run_config_snapshot: RunConfig
    run_config_hash: str
    row_hash: str

    @field_validator(
        "run_id",
        "experiment_id",
        "measurement_key",
        "publication_scope",
        "gas_unit",
        "storage_unit",
        "test_contract",
        "witness_contract",
        "compiler_version",
        "foundry_version",
        "git_revision",
    )
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("run_config_hash", "raw_report_hash", "row_hash")
    @classmethod
    def require_sha256(cls, value: str, info: ValidationInfo) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def validate_row(self) -> "E7MeasurementRow":
        if self.origin is not EvidenceOrigin.FOUNDRY_MEASUREMENT:
            raise ValueError("origin must equal FOUNDRY_MEASUREMENT")
        if self.publication_scope != E7_PUBLICATION_SCOPE:
            raise ValueError(f"publication_scope must equal {E7_PUBLICATION_SCOPE}")
        if self.gas_unit != "gas" or self.storage_unit != "bytes_upper_bound":
            raise ValueError("gas/storage units must be explicit gas and bytes_upper_bound")
        if self.storage_change_upper_bound_bytes != self.changed_storage_slot_count * 32:
            raise ValueError("storage_change_upper_bound_bytes must equal changed_storage_slot_count * 32")
        if self.measurement_key != f"{self.operation.value}:{self.batch_size}":
            raise ValueError("measurement_key must exactly bind operation and batch_size")
        if self.run_id != self.run_config_snapshot.run_id:
            raise ValueError("run_id must exactly bind run_config_snapshot.run_id")
        if self.experiment_id != self.run_config_snapshot.experiment_id:
            raise ValueError("experiment_id must exactly bind run_config_snapshot.experiment_id")
        if self.run_config_snapshot.origin is not EvidenceOrigin.FOUNDRY_MEASUREMENT:
            raise ValueError("run_config_snapshot.origin must equal FOUNDRY_MEASUREMENT")
        if self.run_config_hash != config_hash(self.run_config_snapshot):
            raise ValueError("run_config_hash must exactly bind run_config_snapshot")
        if self.row_hash != row_hash(self):
            raise ValueError("row_hash must exactly bind canonical E7 row material")
        return self


class E7Bundle(_FrozenModel):
    schema_version: str = E7_BUNDLE_SCHEMA_VERSION
    raw_report_path: str
    raw_report_hash: str
    collector_capability: E7CollectorCapability
    run_config_snapshot: RunConfig
    run_config_hash: str
    rows: tuple[E7MeasurementRow, ...]
    manifest: E7Manifest

    @field_validator("raw_report_path")
    @classmethod
    def require_nonblank_path(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("raw_report_path must not be blank")
        return value

    @field_validator("raw_report_hash", "run_config_hash")
    @classmethod
    def require_sha256(cls, value: str, info: ValidationInfo) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def validate_bundle(self) -> "E7Bundle":
        if self.schema_version != E7_BUNDLE_SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {E7_BUNDLE_SCHEMA_VERSION}")
        if self.collector_capability.canonical_report_path != self.manifest.canonical_report_path:
            raise ValueError("collector_capability.canonical_report_path must exactly match manifest.canonical_report_path")
        if self.run_config_hash != config_hash(self.run_config_snapshot):
            raise ValueError("run_config_hash must exactly bind run_config_snapshot")
        if not self.rows:
            raise ValueError("rows must not be empty")
        if self.raw_report_hash != self.manifest.raw_report_hash:
            raise ValueError("bundle.raw_report_hash must exactly match manifest.raw_report_hash")
        if len({row.measurement_key for row in self.rows}) != len(self.rows):
            raise ValueError("rows must be unique by measurement_key")
        if any(row.raw_report_hash != self.raw_report_hash for row in self.rows):
            raise ValueError("rows.raw_report_hash must exactly match bundle.raw_report_hash")
        if any(row.run_config_hash != self.run_config_hash for row in self.rows):
            raise ValueError("rows.run_config_hash must exactly match bundle.run_config_hash")
        if any(row.run_config_snapshot != self.run_config_snapshot for row in self.rows):
            raise ValueError("rows.run_config_snapshot must exactly match bundle.run_config_snapshot")
        if any(row.chain_id != self.manifest.chain_id for row in self.rows):
            raise ValueError("rows.chain_id must exactly match manifest.chain_id")
        if any(row.block_gas_limit != self.manifest.block_gas_limit for row in self.rows):
            raise ValueError("rows.block_gas_limit must exactly match manifest.block_gas_limit")
        if any(row.foundry_version != self.manifest.foundry_version for row in self.rows):
            raise ValueError("rows.foundry_version must exactly match manifest.foundry_version")
        return self


class E7ParityAttachment(_FrozenModel):
    schema_version: str = E7_PARITY_SCHEMA_VERSION
    protocol_vectors_path: str
    protocol_vectors_hash: str
    task8_report_path: str
    task8_report_hash: str
    expected_witness_contract: str = "HashVectors"

    @field_validator("protocol_vectors_path", "task8_report_path", "expected_witness_contract")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("protocol_vectors_hash", "task8_report_hash")
    @classmethod
    def require_sha256(cls, value: str, info: ValidationInfo) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 hex digest")
        return value


class E7CommandTranscript(_FrozenModel):
    schema_version: str = E7_COMMAND_TRANSCRIPT_SCHEMA_VERSION
    command: tuple[str, ...]
    cwd: str
    stdout_hash: str
    stderr_hash: str
    stdout_size: int = Field(ge=0)
    stderr_size: int = Field(ge=0)
    returncode: int = 0

    @field_validator("cwd")
    @classmethod
    def require_nonblank_cwd(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("cwd must not be blank")
        return value

    @field_validator("stdout_hash", "stderr_hash")
    @classmethod
    def require_digest(cls, value: str, info: ValidationInfo) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def validate_command(self) -> "E7CommandTranscript":
        if not self.command:
            raise ValueError("command must not be empty")
        if self.returncode != 0:
            raise ValueError("returncode must equal 0")
        return self


class E7ParityVerification(_FrozenModel):
    schema_version: str = E7_PARITY_VERIFICATION_SCHEMA_VERSION
    source_closure_hash: str
    source_paths: tuple[str, ...]
    protocol_vectors_path: str
    protocol_vectors_hash: str
    protocol_witness_path: str
    protocol_witness_hash: str
    export_vectors_transcript: E7CommandTranscript
    hashvectors_test_transcript: E7CommandTranscript
    python_parity_transcript: E7CommandTranscript

    @field_validator("source_closure_hash", "protocol_vectors_hash", "protocol_witness_hash")
    @classmethod
    def require_hash(cls, value: str, info: ValidationInfo) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("protocol_vectors_path", "protocol_witness_path")
    @classmethod
    def require_nonblank_path(cls, value: str, info: ValidationInfo) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @model_validator(mode="after")
    def validate_parity(self) -> "E7ParityVerification":
        if not self.source_paths:
            raise ValueError("source_paths must not be empty")
        return self


def _path_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ArtifactValidationError((f"unable to read file for hash: {path}",)) from error


def _bytes_hash(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _canonical_report_path(contracts_root: Path) -> Path:
    return _absolute_path(contracts_root / _CANONICAL_REPORT_RELATIVE_PATH)


def _read_json_bytes(path: Path) -> bytes:
    try:
        status = os.lstat(path)
    except OSError as error:
        raise ArtifactValidationError((f"unable to stat foundry report: {path}",)) from error
    if stat.S_ISLNK(status.st_mode):
        raise ArtifactValidationError((f"symlinked foundry report is forbidden: {path}",))
    if not stat.S_ISREG(status.st_mode):
        raise ArtifactValidationError((f"foundry report must be a regular file: {path}",))
    try:
        return path.read_bytes()
    except OSError as error:
        raise ArtifactValidationError((f"unable to read foundry report: {path}",)) from error


def _read_canonical_report_bytes(contracts_root: Path) -> bytes:
    root = contracts_root.resolve(strict=True)
    candidate = root
    for part in _CANONICAL_REPORT_RELATIVE_PATH.parts:
        candidate = candidate / part
        try:
            status = os.lstat(candidate)
        except OSError as error:
            raise ArtifactValidationError((f"canonical E7 report component is missing: {candidate}",)) from error
        if stat.S_ISLNK(status.st_mode):
            raise ArtifactValidationError((f"symlinked canonical E7 report component is forbidden: {candidate}",))
    flags = os.O_RDONLY
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if no_follow:
        flags |= no_follow
    try:
        descriptor = os.open(candidate, flags)
    except OSError as error:
        raise ArtifactValidationError((f"unable to open canonical E7 report with no-follow: {candidate}",)) from error
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise ArtifactValidationError((f"canonical E7 report must be a regular file: {candidate}",))
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            contents = handle.read()
    except OSError as error:
        raise ArtifactValidationError((f"unable to read canonical E7 report: {candidate}",)) from error
    finally:
        os.close(descriptor)
    return contents


def _python_executable(repo_root: Path) -> str:
    candidate = repo_root / ".venv" / "bin" / "python"
    if candidate.is_file():
        return str(candidate)
    return sys.executable


def _completed_transcript(completed: subprocess.CompletedProcess[str], *, cwd: Path) -> E7CommandTranscript:
    stdout = completed.stdout if isinstance(completed.stdout, str) else ""
    stderr = completed.stderr if isinstance(completed.stderr, str) else ""
    return E7CommandTranscript(
        command=tuple(str(part) for part in completed.args),
        cwd=str(cwd.resolve()),
        stdout_hash=_bytes_hash(stdout.encode("utf-8")),
        stderr_hash=_bytes_hash(stderr.encode("utf-8")),
        stdout_size=len(stdout.encode("utf-8")),
        stderr_size=len(stderr.encode("utf-8")),
        returncode=completed.returncode,
    )


def e7_parity_source_relative_paths() -> tuple[Path, ...]:
    return _E7_PARITY_SOURCES


def current_e7_parity_source_closure_hash(repo_root: str | Path | None = None) -> str:
    root = Path(repo_root) if repo_root is not None else _ROOT
    entries: list[dict[str, str]] = []
    for relative_path in _E7_PARITY_SOURCES:
        absolute_path = root / relative_path
        if not absolute_path.is_file():
            raise ArtifactValidationError((f"E7 parity source is missing: {relative_path}",))
        entries.append(
            {
                "path": relative_path.as_posix(),
                "sha256": _path_hash(absolute_path),
            }
        )
    return digest("E7_PARITY_SOURCE_CLOSURE", {"files": entries})


def _artifact_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactValidationError((f"invalid contract artifact JSON: {path}",)) from error
    if not isinstance(payload, dict):
        raise ArtifactValidationError((f"contract artifact must be a mapping: {path}",))
    return payload


def _normalize_report(raw: object) -> _RawFoundryReport:
    try:
        return _RawFoundryReport.model_validate(raw)
    except Exception as error:
        raise ArtifactValidationError(("foundry report is invalid", str(error))) from error


def _parse_report_contents(contents: bytes) -> _RawFoundryReport:
    if not contents.strip():
        raise ArtifactValidationError(("foundry report is empty",))
    try:
        parsed = json.loads(contents.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise ArtifactValidationError(("foundry report is not valid JSON",)) from error
    return _normalize_report(parsed)


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = json.dumps(payload, indent=2).encode("utf-8")
    tmp_descriptor, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        read_back = _read_json_bytes(path)
        if read_back != contents:
            raise ArtifactValidationError((f"atomic write verification failed for {path}",))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return _bytes_hash(contents)


def _git_revision(repo_root: Path) -> tuple[str, bool]:
    try:
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        revision = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ("UNVERSIONED_BLOCKED", True)
    candidate = revision.stdout.strip()
    if not _GIT_SHA.fullmatch(candidate):
        return ("UNVERSIONED_BLOCKED", True)
    return (candidate, bool(status.stdout.strip()))


def _foundry_version(contracts_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["forge", "--version"],
            cwd=contracts_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ArtifactValidationError(("unable to read forge version",)) from error
    version = completed.stdout.strip()
    if not version:
        raise ArtifactValidationError(("forge --version returned empty output",))
    return version


def _artifact_manifest(contracts_root: Path) -> tuple[str, bool, int, tuple[E7ContractArtifact, ...]]:
    artifacts: list[E7ContractArtifact] = []
    compiler_version: str | None = None
    optimizer_enabled: bool | None = None
    optimizer_runs: int | None = None
    for contract_name, source_rel, artifact_rel in _E7_ARTIFACTS:
        source_path = contracts_root / source_rel
        artifact_path = contracts_root / artifact_rel
        if not source_path.is_file():
            raise ArtifactValidationError((f"missing E7 source file: {source_rel}",))
        payload = _artifact_json(artifact_path)
        metadata = payload.get("metadata")
        bytecode = payload.get("bytecode")
        deployed = payload.get("deployedBytecode")
        if not isinstance(metadata, Mapping) or not isinstance(bytecode, Mapping) or not isinstance(deployed, Mapping):
            raise ArtifactValidationError((f"artifact metadata is incomplete: {artifact_rel}",))
        compiler = metadata.get("compiler")
        settings = metadata.get("settings")
        if not isinstance(compiler, Mapping) or not isinstance(settings, Mapping):
            raise ArtifactValidationError((f"artifact metadata settings missing: {artifact_rel}",))
        version = compiler.get("version")
        optimizer = settings.get("optimizer")
        if not isinstance(version, str) or not version.strip():
            raise ArtifactValidationError((f"artifact compiler version missing: {artifact_rel}",))
        if not isinstance(optimizer, Mapping):
            raise ArtifactValidationError((f"artifact optimizer settings missing: {artifact_rel}",))
        enabled = optimizer.get("enabled")
        runs = optimizer.get("runs")
        if not isinstance(enabled, bool) or isinstance(runs, bool) or not isinstance(runs, int) or runs < 0:
            raise ArtifactValidationError((f"artifact optimizer settings invalid: {artifact_rel}",))
        if compiler_version is None:
            compiler_version = version
            optimizer_enabled = enabled
            optimizer_runs = runs
        elif compiler_version != version or optimizer_enabled != enabled or optimizer_runs != runs:
            raise ArtifactValidationError(("mixed compiler or optimizer identities across E7 artifacts",))
        creation = bytecode.get("object")
        runtime = deployed.get("object")
        if not isinstance(creation, str) or not creation.startswith("0x"):
            raise ArtifactValidationError((f"artifact creation bytecode missing: {artifact_rel}",))
        if not isinstance(runtime, str) or not runtime.startswith("0x"):
            raise ArtifactValidationError((f"artifact deployed bytecode missing: {artifact_rel}",))
        artifacts.append(
            E7ContractArtifact(
                contract_name=contract_name,
                source_path=str(source_path.resolve()),
                source_hash=_path_hash(source_path),
                creation_bytecode_hash=digest("E7_CREATION_BYTECODE", {"contract": contract_name, "object": creation}),
                deployed_bytecode_hash=digest("E7_DEPLOYED_BYTECODE", {"contract": contract_name, "object": runtime}),
            )
        )
    if compiler_version is None or optimizer_enabled is None or optimizer_runs is None:
        raise ArtifactValidationError(("E7 artifact manifest is empty",))
    return compiler_version, optimizer_enabled, optimizer_runs, tuple(artifacts)


def row_hash(row: E7MeasurementRow | Mapping[str, object]) -> str:
    if isinstance(row, E7MeasurementRow):
        payload = row.model_dump(mode="json")
    else:
        payload = dict(row)
    material = {
        "schema_version": payload.get("schema_version", "POI_MPP_E7_MEASUREMENT_ROW_V1"),
        "run_id": payload["run_id"],
        "experiment_id": payload["experiment_id"],
        "measurement_key": payload["measurement_key"],
        "operation": payload["operation"],
        "batch_size": payload["batch_size"],
        "origin": payload["origin"],
        "publication_scope": payload["publication_scope"],
        "gas_used": payload["gas_used"],
        "gas_unit": payload["gas_unit"],
        "changed_storage_slot_count": payload["changed_storage_slot_count"],
        "storage_change_upper_bound_bytes": payload["storage_change_upper_bound_bytes"],
        "storage_unit": payload["storage_unit"],
        "test_contract": payload["test_contract"],
        "witness_contract": payload["witness_contract"],
        "chain_id": payload["chain_id"],
        "block_gas_limit": payload["block_gas_limit"],
        "compiler_version": payload["compiler_version"],
        "optimizer_enabled": payload["optimizer_enabled"],
        "optimizer_runs": payload["optimizer_runs"],
        "foundry_version": payload["foundry_version"],
        "git_revision": payload["git_revision"],
        "raw_report_hash": payload["raw_report_hash"],
        "run_config_snapshot": payload["run_config_snapshot"],
        "run_config_hash": payload["run_config_hash"],
    }
    return digest("E7_MEASUREMENT_ROW", material)


def default_measurement_contract() -> E7MeasurementContract:
    return E7MeasurementContract(
        expected_measurements=(
            E7ExpectedMeasurement(operation=E7Operation.MODEL_REGISTER, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.TASK_CREATE, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.COMMIT_RESPONSE, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.AUDIT_OPEN, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.AUDIT_RECORD_RESULT, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.AUDIT_RECORD_DA, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.OPEN_CHALLENGE, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.RECEIPT_MINT_PENDING, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.RECEIPT_ACTIVATE, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.RECEIPT_MARK_CHALLENGED, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.RECEIPT_SLASH, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.CREDIT_ALLOCATE, batch_size=1),
            E7ExpectedMeasurement(operation=E7Operation.CREDIT_ALLOCATE, batch_size=2),
            E7ExpectedMeasurement(operation=E7Operation.CREDIT_ALLOCATE, batch_size=4),
            E7ExpectedMeasurement(operation=E7Operation.CREDIT_ALLOCATE, batch_size=8),
        )
    )


def e7_publication_model_hash(
    contract: E7MeasurementContract | None = None,
) -> str:
    """Bind the exact E7 measurement contract used by the local collector."""

    resolved_contract = default_measurement_contract() if contract is None else contract
    return digest(
        "E7_PUBLICATION_MODEL_HASH",
        resolved_contract.model_dump(mode="json"),
    )


def load_default_parity_attachment(repo_root: str | Path | None = None) -> E7ParityAttachment:
    root = Path(repo_root) if repo_root is not None else _ROOT
    vectors = root / "tests" / "fixtures" / "protocol_vectors.json"
    report = (
        root
        / ".superpowers"
        / "sdd"
        / "2026-08-20-poi-mpp-publication-artifact-implementation"
        / "task-8-report.md"
    )
    if not vectors.is_file() or not report.is_file():
        raise ArtifactValidationError(("Task 8 parity artifacts are missing",))
    payload = _load_protocol_vectors_fixture(vectors)
    report_text = report.read_text(encoding="utf-8")
    required_fragments = (
        "tests/integration/test_python_solidity_parity.py",
        "Result: `5` tests passed.",
        "cd contracts && forge test -vv",
        "Result: `38` tests passed across `5` suites.",
    )
    missing = [fragment for fragment in required_fragments if fragment not in report_text]
    if missing:
        raise ArtifactValidationError(("Task 8 parity report is missing required verification markers", *missing))
    return E7ParityAttachment(
        protocol_vectors_path=str(vectors.resolve()),
        protocol_vectors_hash=_path_hash(vectors),
        task8_report_path=str(report.resolve()),
        task8_report_hash=_path_hash(report),
    )


def e7_publication_dataset_hash(
    *,
    contract: E7MeasurementContract | None = None,
    repo_root: str | Path | None = None,
) -> str:
    """Bind expected measurements and the current Python/Solidity parity closure.

    Only stable semantic identities and content hashes enter this digest.  Local
    absolute paths in the parity attachment are deliberately excluded so the
    publication configuration remains replayable in another checkout.
    """

    resolved_contract = default_measurement_contract() if contract is None else contract
    attachment = load_default_parity_attachment(repo_root)
    return digest(
        "E7_PUBLICATION_DATASET_HASH",
        {
            "schema_version": "POI_MPP_E7_PUBLICATION_DATASET_BINDING_V1",
            "measurement_contract_hash": e7_publication_model_hash(resolved_contract),
            "expected_measurements": [
                item.model_dump(mode="json")
                for item in resolved_contract.expected_measurements
            ],
            "parity_attachment": {
                "schema_version": attachment.schema_version,
                "protocol_vectors_hash": attachment.protocol_vectors_hash,
                "task8_report_hash": attachment.task8_report_hash,
                "expected_witness_contract": attachment.expected_witness_contract,
            },
            "parity_source_closure_hash": current_e7_parity_source_closure_hash(repo_root),
        },
    )


def _load_protocol_vectors_fixture(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactValidationError(("Task 8 protocol vectors are invalid JSON",)) from error
    if not isinstance(payload, dict):
        raise ArtifactValidationError(("Task 8 protocol vectors must be a JSON object",))
    if payload.get("artifact_origin") != "TEST_VECTOR_NON_EVIDENCE":
        raise ArtifactValidationError(("Task 8 protocol vectors must remain TEST_VECTOR_NON_EVIDENCE",))
    if payload.get("evidence_origin") != "SYNTHETIC_NON_EVIDENCE":
        raise ArtifactValidationError(("Task 8 protocol vectors must remain SYNTHETIC_NON_EVIDENCE",))
    witness = payload.get("solidity_witness_source")
    if not isinstance(witness, Mapping) or witness.get("contract") != "HashVectors":
        raise ArtifactValidationError(("Task 8 protocol vectors must bind Solidity witness contract HashVectors",))
    return payload


def verify_current_e7_parity(
    *,
    repo_root: str | Path | None = None,
    contracts_root: str | Path | None = None,
    timeout: int = 120,
) -> E7ParityVerification:
    root = Path(repo_root) if repo_root is not None else _ROOT
    contracts_dir = Path(contracts_root) if contracts_root is not None else root / "contracts"
    export_completed = _run_command(
        (_python_executable(root), "scripts/export_solidity_vectors.py"),
        cwd=root,
        timeout=timeout,
    )
    hashvectors_completed = _run_command(
        ("forge", "test", "--match-contract", "HashVectors", "-q"),
        cwd=contracts_dir,
        timeout=timeout,
    )
    parity_completed = _run_command(
        (_python_executable(root), "-m", "pytest", "tests/integration/test_python_solidity_parity.py", "-q"),
        cwd=root,
        timeout=timeout,
    )
    vectors_path = root / "tests" / "fixtures" / "protocol_vectors.json"
    witness_path = contracts_dir / "out" / "protocol_witnesses.json"
    _load_protocol_vectors_fixture(vectors_path)
    if not witness_path.is_file():
        raise ArtifactValidationError(("Task 8 protocol witness file is missing after exporter run",))
    return E7ParityVerification(
        source_closure_hash=current_e7_parity_source_closure_hash(root),
        source_paths=tuple(relative_path.as_posix() for relative_path in _E7_PARITY_SOURCES),
        protocol_vectors_path=str(vectors_path.resolve()),
        protocol_vectors_hash=_path_hash(vectors_path),
        protocol_witness_path=str(witness_path.resolve()),
        protocol_witness_hash=_path_hash(witness_path),
        export_vectors_transcript=_completed_transcript(export_completed, cwd=root),
        hashvectors_test_transcript=_completed_transcript(hashvectors_completed, cwd=contracts_dir),
        python_parity_transcript=_completed_transcript(parity_completed, cwd=root),
    )


def parse_foundry_measurement_report(
    *,
    report_path: str | Path,
    contracts_root: str | Path,
    run_config: RunConfig,
) -> E7Bundle:
    if run_config.experiment_id != "E7":
        raise ArtifactValidationError(("E7 parsing requires experiment_id E7",))
    if run_config.origin is not EvidenceOrigin.FOUNDRY_MEASUREMENT:
        raise ArtifactValidationError(("E7 parsing requires origin FOUNDRY_MEASUREMENT",))
    report_file = Path(report_path)
    contracts_dir = Path(contracts_root)
    canonical_report = _canonical_report_path(contracts_dir)
    observed_report = _absolute_path(report_file)
    if observed_report == canonical_report:
        report_bytes = _read_canonical_report_bytes(contracts_dir)
        collector_capability = E7CollectorCapability(
            report_authority=E7ReportAuthority.CANONICAL_COLLECTOR_REPORT,
            observed_report_path=str(observed_report),
            canonical_report_path=str(canonical_report),
            anchored_no_follow=True,
            symlink_free=True,
        )
    else:
        report_bytes = _read_json_bytes(report_file)
        collector_capability = E7CollectorCapability(
            report_authority=E7ReportAuthority.PLUMBING_FIXTURE,
            observed_report_path=str(observed_report),
            canonical_report_path=str(canonical_report),
            anchored_no_follow=False,
            symlink_free=False,
        )
    parsed = _parse_report_contents(report_bytes)
    compiler_version, optimizer_enabled, optimizer_runs, artifacts = _artifact_manifest(contracts_dir)
    foundry_version = _foundry_version(contracts_dir)
    git_revision, git_dirty = _git_revision(_ROOT)
    raw_hash = _bytes_hash(report_bytes)
    manifest = E7Manifest(
        contracts_root=str(contracts_dir.resolve()),
        foundry_version=foundry_version,
        compiler_version=compiler_version,
        optimizer_enabled=optimizer_enabled,
        optimizer_runs=optimizer_runs,
        git_revision=git_revision,
        git_dirty=git_dirty,
        chain_id=parsed.chain_id,
        block_gas_limit=parsed.block_gas_limit,
        raw_report_hash=raw_hash,
        canonical_report_path=str(canonical_report),
        test_contract=parsed.test_contract,
        witness_contract=parsed.witness_contract,
        gas_measurement_surface="CALL_BODY_GASLEFT_DELTA_EXCLUDES_TEST_HARNESS",
        storage_measurement_surface="POST_CALL_SLOT_DIFF_VS_FRESH_BASELINE_BYTES_UPPER_BOUND",
        command=("forge", "script", "test/GasSnapshots.t.sol:GasSnapshotWitness", "--via-ir", "-q"),
        artifacts=artifacts,
    )
    rows: list[E7MeasurementRow] = []
    run_hash = config_hash(run_config)
    for measurement in parsed.measurements:
        base = {
            "run_id": run_config.run_id,
            "experiment_id": run_config.experiment_id,
            "measurement_key": measurement.key,
            "operation": measurement.operation.value,
            "batch_size": measurement.batch_size,
            "origin": run_config.origin.value,
            "publication_scope": E7_PUBLICATION_SCOPE,
            "gas_used": measurement.gas_used,
            "gas_unit": "gas",
            "changed_storage_slot_count": measurement.changed_storage_slot_count,
            "storage_change_upper_bound_bytes": measurement.storage_change_upper_bound_bytes,
            "storage_unit": "bytes_upper_bound",
            "test_contract": parsed.test_contract,
            "witness_contract": parsed.witness_contract,
            "chain_id": parsed.chain_id,
            "block_gas_limit": parsed.block_gas_limit,
            "compiler_version": compiler_version,
            "optimizer_enabled": optimizer_enabled,
            "optimizer_runs": optimizer_runs,
            "foundry_version": foundry_version,
            "git_revision": git_revision,
            "raw_report_hash": raw_hash,
            "run_config_snapshot": run_config.model_dump(mode="json"),
            "run_config_hash": run_hash,
        }
        rows.append(E7MeasurementRow.model_validate({**base, "row_hash": row_hash(base)}))
    try:
        return E7Bundle.model_validate(
            {
                "raw_report_path": str(report_file.resolve()),
                "raw_report_hash": raw_hash,
                "collector_capability": collector_capability.model_dump(mode="json"),
                "run_config_snapshot": run_config.model_dump(mode="json"),
                "run_config_hash": run_hash,
                "rows": [row.model_dump(mode="json") for row in rows],
                "manifest": manifest.model_dump(mode="json"),
            }
        )
    except Exception as error:
        raise ArtifactValidationError(("E7 bundle validation failed", str(error))) from error


def _controlled_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": "C",
        "LC_ALL": "C",
        "FOUNDRY_PROFILE": "default",
    }


def _run_command(argv: Sequence[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_controlled_env(),
        )
    except subprocess.TimeoutExpired as error:
        raise ArtifactValidationError((f"command timed out: {' '.join(argv)}",)) from error
    except (OSError, subprocess.CalledProcessError) as error:
        stderr = ""
        stdout = ""
        if isinstance(error, subprocess.CalledProcessError):
            stdout = error.stdout[:_OUTPUT_LIMIT] if isinstance(error.stdout, str) else ""
            stderr = error.stderr[:_OUTPUT_LIMIT] if isinstance(error.stderr, str) else ""
        raise ArtifactValidationError(
            (
                f"command failed: {' '.join(argv)}",
                stdout.strip() or "stdout: <empty>",
                stderr.strip() or "stderr: <empty>",
            )
        ) from error
    if len(completed.stdout) > _OUTPUT_LIMIT or len(completed.stderr) > _OUTPUT_LIMIT:
        completed = subprocess.CompletedProcess(
            completed.args,
            completed.returncode,
            completed.stdout[:_OUTPUT_LIMIT],
            completed.stderr[:_OUTPUT_LIMIT],
        )
    return completed


def collect_foundry_measurements(
    *,
    contracts_root: str | Path,
    run_config: RunConfig,
    output_path: str | Path,
    measurement_contract: E7MeasurementContract | None = None,
    timeout: int = 120,
) -> E7Bundle:
    contract = default_measurement_contract() if measurement_contract is None else measurement_contract
    contracts_dir = Path(contracts_root)
    report_path = contracts_dir / _CANONICAL_REPORT_RELATIVE_PATH
    if report_path.exists():
        report_path.unlink()
    _run_command(
        ("forge", "test", "--match-contract", contract.required_test_contract, "--gas-report", "-vv"),
        cwd=contracts_dir,
        timeout=timeout,
    )
    _run_command(
        ("forge", "script", f"test/GasSnapshots.t.sol:{contract.required_witness_contract}", "--via-ir", "-q"),
        cwd=contracts_dir,
        timeout=timeout,
    )
    if not report_path.is_file():
        raise ArtifactValidationError(("GasSnapshotWitness did not produce the raw E7 report",))
    bundle = parse_foundry_measurement_report(
        report_path=report_path,
        contracts_root=contracts_dir,
        run_config=run_config,
    )
    output_file = Path(output_path)
    _atomic_write_json(output_file, bundle.model_dump(mode="json"))
    return bundle


def assert_cli_authority_boundary(run_config: RunConfig) -> None:
    if run_config.experiment_id != "E7":
        raise AuthorityBoundaryError("E7 wrapper requires experiment_id E7")
    if run_config.origin is not EvidenceOrigin.FOUNDRY_MEASUREMENT:
        raise AuthorityBoundaryError("E7 wrapper requires origin FOUNDRY_MEASUREMENT")
    if run_config.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        raise AuthorityBoundaryError(
            f"E7 collection wrapper requires {PUBLICATION_EVIDENCE_AUTHORIZED} authorization_scope"
        )
    expected_model_hash = e7_publication_model_hash()
    if run_config.model_hash != expected_model_hash:
        raise AuthorityBoundaryError(
            "run_config.model_hash must bind the default E7 measurement contract"
        )
    expected_dataset_hash = e7_publication_dataset_hash(repo_root=_ROOT)
    if run_config.dataset_hash != expected_dataset_hash:
        raise AuthorityBoundaryError(
            "run_config.dataset_hash must bind the expected measurements and current parity closure"
        )


def repo_root() -> Path:
    return _ROOT
