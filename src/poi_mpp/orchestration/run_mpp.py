"""Local Task 21 orchestration for real-path blockers and synthetic mechanics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
import yaml

from poi_mpp.auditor.availability import ReconstructionStatus, verify_reconstruction
from poi_mpp.auditor.semantic import (
    EvidenceAnnotation,
    EvidenceAnnotationKind,
    EvidenceRecord,
    GroundedClaim,
    SemanticCalibrationArtifact,
    VerificationDecision,
    VerificationMode,
    verify_grounded,
)
from poi_mpp.auditor.semantic.models import semantic_evidence_content_hash
from poi_mpp.evidence.canonical import canonical_bytes, digest
from poi_mpp.evidence.config import RunConfig, approved_schema_hash, config_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments import WAITING_EXTERNAL_EVALUATOR_AUTHORITY, load_e3_confirmatory_schema
from poi_mpp.experiments.e7_evm import verify_current_e7_parity
from poi_mpp.protocol.audit_compiler import AuditPolicy, compile_audit
from poi_mpp.protocol.availability import ErasureParameters, LocalShardStore, SamplingMode, issue_sample_certificate
from poi_mpp.protocol.committee import sample_committee
from poi_mpp.protocol.commitment import commit_response
from poi_mpp.protocol.credit import allocate_credit, derive_active_weight
from poi_mpp.protocol.receipt import ActivateReceipt, OpenChallenge, RecordAudit, RecordDataAvailability, SlashReceipt
from poi_mpp.protocol.reference_machine import transition
from poi_mpp.protocol.types import AuditDecision, Receipt, ReceiptState, TaskClass, TaskSpec, TransitionContext
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
from poi_mpp.worker.inference import ExecutionBundle, FixtureInferenceAdapter, execute_once
from poi_mpp.worker.model_manifest import PinnedModelManifest, bytes32_word


WAITING_LOCAL_MODEL_ARTIFACT = "WAITING_LOCAL_MODEL_ARTIFACT"
NON_PUBLICATION_MECHANICS = "NON_PUBLICATION_MECHANICS"
REPLAY_REJECTED = "REPLAY_REJECTED"
_ROOT = Path(__file__).resolve().parents[3]
_CONTRACTS = _ROOT / "contracts"
_ANVIL_PRIVATE_KEY = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
_ANVIL_OWNER = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
_CHAIN_GENESIS_BLOCK = 1
_CHAIN_BLOCKS_PER_EPOCH = 50
_COMMITMENT_FINALITY_DEPTH = 2
_CHALLENGE_WINDOW_BLOCKS = 5
_BETA = 10
_CONCENTRATION_CAP = 1000
_CREDIT_BUDGET = 90
_TASK_DEADLINE = 500
_AUDIT_DOMAIN_SIZE = 16
_ANVIL_LOG_LIMIT = 4096
_CANONICAL_PREFIX = "POI_MPP_V1"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "PIP_NO_INDEX": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "NO_PROXY": "127.0.0.1,localhost",
    "no_proxy": "127.0.0.1,localhost",
}
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "FTP_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "ftp_proxy",
)
_CONTRACT_ARTIFACTS = (
    ("PolicyRegistry", "src/PolicyRegistry.sol", "out/PolicyRegistry.sol/PolicyRegistry.json"),
    ("ModelRegistry", "src/ModelRegistry.sol", "out/ModelRegistry.sol/ModelRegistry.json"),
    ("TaskManager", "src/TaskManager.sol", "out/TaskManager.sol/TaskManager.json"),
    ("CommitmentHub", "src/CommitmentHub.sol", "out/CommitmentHub.sol/CommitmentHub.json"),
    ("AuditManager", "src/AuditManager.sol", "out/AuditManager.sol/AuditManager.json"),
    ("ReceiptManager", "src/ReceiptManager.sol", "out/ReceiptManager.sol/ReceiptManager.json"),
    ("CreditEngine", "src/CreditEngine.sol", "out/CreditEngine.sol/CreditEngine.json"),
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False):  # type: ignore[override]
        if not update:
            return super().model_copy(deep=deep)
        payload = self.model_dump(mode="python")
        payload.update(dict(update))
        return type(self).model_validate(payload)

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any):  # type: ignore[override]
        raise TypeError(f"{cls.__name__}.model_construct is disabled; use model_validate")


class RealPathBlocker(StrEnum):
    WAITING_LOCAL_MODEL_ARTIFACT = WAITING_LOCAL_MODEL_ARTIFACT
    WAITING_EXTERNAL_EVALUATOR_AUTHORITY = WAITING_EXTERNAL_EVALUATOR_AUTHORITY


class SyntheticDisposition(StrEnum):
    NON_PUBLICATION_MECHANICS = NON_PUBLICATION_MECHANICS


class LocalModelSpec(_StrictFrozenModel):
    model_root: Path
    tokenizer_root: Path
    manifest: PinnedModelManifest
    decode_policy: DeterministicDecodePolicy

    @field_validator("model_root", "tokenizer_root", mode="before")
    @classmethod
    def _require_path(cls, value: object) -> Path:
        if not isinstance(value, str | Path):
            raise ValueError("model/tokenizer roots must be paths")
        candidate = str(value)
        if "://" in candidate:
            raise ValueError("model/tokenizer roots must be local filesystem paths, not model URIs")
        return Path(candidate)


class ChainConfig(_StrictFrozenModel):
    host: str
    port: int = Field(gt=0, le=65535)
    chain_id: int = Field(gt=0)
    startup_timeout_seconds: int = Field(gt=0, le=300)
    command_timeout_seconds: int = Field(gt=0, le=600)

    @field_validator("host")
    @classmethod
    def _require_host(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("host must not be blank")
        candidate = value.strip()
        if candidate == "localhost":
            return candidate
        try:
            parsed = ipaddress.ip_address(candidate)
        except ValueError as error:
            raise ValueError("host must be a loopback address or localhost") from error
        if not parsed.is_loopback:
            raise ValueError("host must be a loopback address or localhost")
        return candidate


class SemanticConfig(_StrictFrozenModel):
    confirmatory_schema_path: Path
    evaluator_registry_reference: str

    @field_validator("confirmatory_schema_path", mode="before")
    @classmethod
    def _require_schema_path(cls, value: object) -> Path:
        if not isinstance(value, str | Path):
            raise ValueError("confirmatory_schema_path must be a path")
        return Path(value)

    @field_validator("evaluator_registry_reference")
    @classmethod
    def _require_registry_ref(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("evaluator_registry_reference must not be blank")
        return value


class LocalMPPConfig(_StrictFrozenModel):
    schema_version: str
    run_config: RunConfig
    model: LocalModelSpec
    chain: ChainConfig
    semantic: SemanticConfig
    output_root: Path
    committee_size: int = Field(gt=0, le=16)

    @field_validator("schema_version")
    @classmethod
    def _require_schema_version(cls, value: str) -> str:
        if value != "POI_MPP_LOCAL_MPP_CONFIG_V1":
            raise ValueError("schema_version must equal POI_MPP_LOCAL_MPP_CONFIG_V1")
        return value

    @field_validator("output_root", mode="before")
    @classmethod
    def _require_output_root(cls, value: object) -> Path:
        if not isinstance(value, str | Path):
            raise ValueError("output_root must be a path")
        return Path(value)

    @field_validator("run_config", mode="before")
    @classmethod
    def _normalize_run_config(cls, value: object) -> object:
        if isinstance(value, Mapping) and "schema_hash" not in value:
            return {**value, "schema_hash": approved_schema_hash()}
        return value

    @model_validator(mode="after")
    def _validate_contract(self) -> "LocalMPPConfig":
        if self.run_config.origin is not EvidenceOrigin.REAL_MODEL_EXECUTION:
            raise ValueError("run_config.origin must equal REAL_MODEL_EXECUTION")
        if self.run_config.authorization_scope != "PUBLICATION_EVIDENCE_AUTHORIZED":
            raise ValueError("run_config.authorization_scope must equal PUBLICATION_EVIDENCE_AUTHORIZED")
        if self.run_config.experiment_id != "E3":
            raise ValueError("run_config.experiment_id must equal E3")
        return self


class ContractHashRecord(_StrictFrozenModel):
    contract_name: str
    source_path: str
    compiler_version: str
    source_sha256: str
    creation_bytecode_sha256: str
    artifact_runtime_sha256: str
    deployed_address: str
    deployed_runtime_sha256: str


class ParitySummary(_StrictFrozenModel):
    source_closure_hash: str
    protocol_vectors_hash: str
    protocol_witness_hash: str


class DeploymentSummary(_StrictFrozenModel):
    chain_id: int
    deployer_address: str
    worker_address: str
    policy_address: str
    model_registry_address: str
    task_manager_address: str
    commitment_hub_address: str
    audit_manager_address: str
    receipt_manager_address: str
    credit_engine_address: str
    anvil_version: str
    anvil_log: "AnvilLogSummary | None" = None
    contract_hashes: tuple[ContractHashRecord, ...]


class AnvilLogSummary(_StrictFrozenModel):
    relative_path: str
    captured_bytes: int = Field(ge=0, le=_ANVIL_LOG_LIMIT)
    truncated: bool
    captured_sha256: str
    full_sha256: str

    @field_validator("relative_path")
    @classmethod
    def _require_relative_path(cls, value: str) -> str:
        return _validated_relative_posix_path(value)

    @field_validator("captured_sha256", "full_sha256")
    @classmethod
    def _require_hash(cls, value: str) -> str:
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("anvil log hashes must be lowercase sha256 hex")
        return value


class MechanicsArtifact(_StrictFrozenModel):
    schema_version: str = "POI_MPP_TASK21_MECHANICS_ARTIFACT_V1"
    artifact_id: str
    relative_path: str
    content_hash: str
    parent_hashes: tuple[str, ...] = ()
    origin: EvidenceOrigin
    summary_disposition: SyntheticDisposition

    @field_validator("artifact_id", "relative_path", "content_hash")
    @classmethod
    def _require_nonblank(cls, value: str, info) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        if info.field_name == "relative_path":
            return _validated_relative_posix_path(value)
        return value

    @model_validator(mode="after")
    def _validate_synthetic_boundary(self) -> "MechanicsArtifact":
        if self.origin is not EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
            raise ValueError("Task 21 mechanics artifacts must remain SYNTHETIC_NON_EVIDENCE")
        if self.summary_disposition is not SyntheticDisposition.NON_PUBLICATION_MECHANICS:
            raise ValueError("synthetic mechanics must remain NON_PUBLICATION_MECHANICS")
        return self

    @property
    def path(self) -> PurePosixPath:
        return PurePosixPath(self.relative_path)


class HappyPathSummary(_StrictFrozenModel):
    task_epoch: int
    receipt_state: str
    credit_epoch: int
    committee_members: tuple[str, ...]
    execution_bundle_path: PurePosixPath
    committee_artifact_path: PurePosixPath

    @field_validator("execution_bundle_path", "committee_artifact_path", mode="before")
    @classmethod
    def _require_paths(cls, value: object) -> PurePosixPath:
        if not isinstance(value, str | Path | PurePosixPath):
            raise ValueError("artifact paths must be paths")
        return _validate_relative_path(_path_text(value))


class FailurePathSummary(_StrictFrozenModel):
    execution_rejection_state: str
    semantic_abstention_state: str
    da_failure_state: str
    successful_challenge_state: str
    service_task_credit_total: int = Field(ge=0)
    replay_rejection_error_code: str


class SyntheticJourneySummary(_StrictFrozenModel):
    summary_disposition: SyntheticDisposition
    artifacts: tuple[MechanicsArtifact, ...]
    happy_path: HappyPathSummary
    failure_paths: FailurePathSummary


class RealPathSummary(_StrictFrozenModel):
    blocker: RealPathBlocker
    reasons: tuple[str, ...]


class LocalMPPResult(_StrictFrozenModel):
    schema_version: str = "POI_MPP_TASK21_RESULT_V1"
    config_hash: str
    parity: ParitySummary
    contracts: DeploymentSummary
    real_path: RealPathSummary
    synthetic: SyntheticJourneySummary


@dataclass(frozen=True)
class _CommandResult:
    stdout: str
    stderr: str


@dataclass
class _BoundedLogCapture:
    path: Path
    limit: int
    captured: bytearray
    full_hasher: "hashlib._Hash"
    truncated: bool = False

    def consume(self, stream) -> None:
        try:
            while True:
                chunk = stream.read(1024)
                if not chunk:
                    break
                self.full_hasher.update(chunk)
                remaining = self.limit - len(self.captured)
                if remaining > 0:
                    self.captured.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.truncated = True
        finally:
            stream.close()
            self.path.write_bytes(bytes(self.captured))

    def summary(self, *, output_root: Path) -> AnvilLogSummary:
        return AnvilLogSummary(
            relative_path=_relative_output_path(output_root, self.path),
            captured_bytes=len(self.captured),
            truncated=self.truncated,
            captured_sha256=_hash_bytes(bytes(self.captured)),
            full_sha256=self.full_hasher.hexdigest(),
        )


@dataclass
class _AnvilProcess:
    process: subprocess.Popen[bytes]
    rpc_url: str
    host: str
    port: int
    log_path: Path
    version: str
    log_capture: _BoundedLogCapture
    log_thread: threading.Thread

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                os.killpg(os.getpgid(self.process.pid), 15)
            except ProcessLookupError:
                pass
            deadline = time.time() + 10.0
            while time.time() < deadline:
                if self.process.poll() is not None:
                    break
                time.sleep(0.1)
            if self.process.poll() is None:
                os.killpg(os.getpgid(self.process.pid), 9)
        self.process.wait(timeout=5)
        self.log_thread.join(timeout=5)
        if self.log_thread.is_alive():
            raise RuntimeError("Anvil log drain did not finish before cleanup timeout")


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    return _hash_bytes(path.read_bytes())


def _safe_env() -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "USER"):
        value = os.environ.get(key)
        if value is not None:
            result[key] = value
    result.update(_OFFLINE_ENV)
    return result


def _path_text(value: str | Path | PurePosixPath) -> str:
    if isinstance(value, PurePosixPath):
        return value.as_posix()
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _canonicalize_managed_macos_alias(path: Path) -> Path:
    absolute = Path(os.path.abspath(str(path)))
    if sys.platform != "darwin":
        return absolute
    absolute_text = absolute.as_posix()
    for alias_prefix, canonical_prefix in (("/var", "/private/var"), ("/tmp", "/private/tmp")):
        if absolute_text != alias_prefix and not absolute_text.startswith(f"{alias_prefix}/"):
            continue
        try:
            alias_status = os.lstat(alias_prefix)
        except OSError:
            continue
        if not stat.S_ISLNK(alias_status.st_mode):
            continue
        if os.path.realpath(alias_prefix) != canonical_prefix:
            continue
        suffix = absolute_text[len(alias_prefix) :].lstrip("/")
        canonical = Path(canonical_prefix)
        return canonical / suffix if suffix else canonical
    return absolute


def _absolute_lexical_path(base: Path, candidate: str | Path) -> Path:
    path = Path(candidate)
    if not path.is_absolute():
        path = base / path
    return _canonicalize_managed_macos_alias(path)


def _open_directory_no_symlinks(path: Path, *, create: bool, label: str) -> tuple[int, Path]:
    absolute = _absolute_lexical_path(Path.cwd(), path)
    components = [part for part in absolute.parts if part not in {absolute.anchor, "."}]
    if not components:
        raise ValueError(f"{label} is invalid")
    flags = os.O_RDONLY | _DIRECTORY | _NOFOLLOW
    descriptor = os.open(absolute.anchor, flags)
    current = Path(absolute.anchor)
    try:
        for component in components:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError as error:
                if not create:
                    raise ValueError(f"{label} is missing or not a trusted local directory") from error
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                try:
                    child = os.open(component, flags, dir_fd=descriptor)
                except OSError as open_error:
                    raise ValueError(f"{label} could not be opened without following symlinks") from open_error
            except OSError as error:
                raise ValueError(f"{label} could not be opened without following symlinks") from error
            os.close(descriptor)
            descriptor = child
            current = current / component
            details = os.fstat(descriptor)
            if not stat.S_ISDIR(details.st_mode):
                raise ValueError(f"{label} is not a directory")
        return descriptor, current
    except BaseException:
        os.close(descriptor)
        raise


def _prepare_output_root(path: Path) -> Path:
    descriptor, absolute = _open_directory_no_symlinks(path, create=True, label="output root")
    os.close(descriptor)
    return absolute


def _existing_output_root(path: Path) -> Path:
    descriptor, absolute = _open_directory_no_symlinks(path, create=False, label="output root")
    os.close(descriptor)
    return absolute


def _run(
    args: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    env: Mapping[str, str] | None = None,
) -> _CommandResult:
    completed = subprocess.run(
        list(args),
        cwd=cwd,
        env=dict(env or _safe_env()),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return _CommandResult(stdout=completed.stdout.strip(), stderr=completed.stderr.strip())


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _json_command(
    args: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    result = _run(args, cwd=cwd, timeout=timeout, env=env)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"command did not return JSON: {' '.join(args)}") from error


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) != 0


def _block_number(rpc_url: str, timeout: int) -> int:
    result = _run(("cast", "block-number", "--rpc-url", rpc_url), cwd=_ROOT, timeout=timeout)
    return int(result.stdout)


def _mine_to_block(rpc_url: str, current: int, target: int, timeout: int) -> None:
    if target <= current:
        return
    count = target - current
    _run(("cast", "rpc", "--rpc-url", rpc_url, "anvil_mine", hex(count)), cwd=_ROOT, timeout=timeout)


def _call(rpc_url: str, contract: str, signature: str, *args: object, timeout: int) -> str:
    command = ["cast", "call", "--rpc-url", rpc_url, contract, signature]
    command.extend(str(arg) for arg in args)
    return _run(tuple(command), cwd=_ROOT, timeout=timeout).stdout


def _call_uint(rpc_url: str, contract: str, signature: str, *args: object, timeout: int) -> int:
    return int(_call(rpc_url, contract, signature, *args, timeout=timeout))


def _call_word(rpc_url: str, contract: str, signature: str, *args: object, timeout: int) -> str:
    return _call(rpc_url, contract, signature, *args, timeout=timeout)


def _send(
    rpc_url: str,
    contract: str,
    signature: str,
    *args: object,
    timeout: int,
) -> dict[str, Any]:
    command = [
        "cast",
        "send",
        "--json",
        "--rpc-url",
        rpc_url,
        "--private-key",
        _ANVIL_PRIVATE_KEY,
        contract,
        signature,
    ]
    command.extend(_format_cast_arg(arg) for arg in args)
    return _json_command(tuple(command), cwd=_ROOT, timeout=timeout)


def _format_cast_arg(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _deploy(
    rpc_url: str,
    contract_ref: str,
    *,
    timeout: int,
    constructor_args: Sequence[object],
) -> str:
    payload = _json_command(
        (
            "forge",
            "create",
            "--broadcast",
            "--json",
            "--rpc-url",
            rpc_url,
            "--private-key",
            _ANVIL_PRIVATE_KEY,
            contract_ref,
            "--constructor-args",
            *(str(arg) for arg in constructor_args),
        ),
        cwd=_CONTRACTS,
        timeout=timeout,
    )
    deployed_to = payload.get("deployedTo")
    if not isinstance(deployed_to, str) or not deployed_to:
        raise RuntimeError(f"forge create did not return a deployed address for {contract_ref}")
    return deployed_to


def _contract_metadata(name: str, source_path: str, artifact_path: str) -> dict[str, Any]:
    source = (_CONTRACTS / source_path).read_bytes()
    artifact = json.loads((_CONTRACTS / artifact_path).read_text(encoding="utf-8"))
    deployed_bytecode = bytes.fromhex(artifact["deployedBytecode"]["object"][2:])
    creation_bytecode = bytes.fromhex(artifact["bytecode"]["object"][2:])
    compiler_version = artifact["metadata"]["compiler"]["version"]
    immutable_spans: list[tuple[int, int]] = []
    for entries in artifact["deployedBytecode"].get("immutableReferences", {}).values():
        for entry in entries:
            immutable_spans.append((int(entry["start"]), int(entry["length"])))
    normalized_runtime = _normalize_runtime_bytecode(deployed_bytecode, immutable_spans)
    return {
        "contract_name": name,
        "source_path": source_path,
        "compiler_version": compiler_version,
        "source_sha256": _hash_bytes(source),
        "creation_bytecode_sha256": _hash_bytes(creation_bytecode),
        "artifact_runtime_sha256": _hash_bytes(normalized_runtime),
        "immutable_spans": tuple(immutable_spans),
    }


def _normalize_runtime_bytecode(bytecode: bytes, spans: Sequence[tuple[int, int]]) -> bytes:
    mutable = bytearray(bytecode)
    for start, length in spans:
        end = start + length
        if start < 0 or end > len(mutable):
            raise RuntimeError("immutable reference span exceeds deployed bytecode length")
        mutable[start:end] = b"\x00" * length
    return bytes(mutable)


def _collect_contract_hashes(
    rpc_url: str,
    addresses: Mapping[str, str],
    *,
    timeout: int,
) -> tuple[ContractHashRecord, ...]:
    rows: list[ContractHashRecord] = []
    for name, source_path, artifact_path in _CONTRACT_ARTIFACTS:
        meta = _contract_metadata(name, source_path, artifact_path)
        address = addresses[name]
        onchain_code = _run(("cast", "code", "--rpc-url", rpc_url, address), cwd=_ROOT, timeout=timeout).stdout
        if not isinstance(onchain_code, str) or not onchain_code.startswith("0x"):
            raise RuntimeError(f"unable to read on-chain runtime bytecode for {name}")
        normalized_onchain_runtime = _normalize_runtime_bytecode(
            bytes.fromhex(onchain_code[2:]),
            meta["immutable_spans"],
        )
        deployed_runtime_sha256 = _hash_bytes(normalized_onchain_runtime)
        if deployed_runtime_sha256 != meta["artifact_runtime_sha256"]:
            raise RuntimeError(f"runtime bytecode hash mismatch for {name}")
        rows.append(
            ContractHashRecord(
                contract_name=name,
                source_path=meta["source_path"],
                compiler_version=meta["compiler_version"],
                source_sha256=meta["source_sha256"],
                creation_bytecode_sha256=meta["creation_bytecode_sha256"],
                artifact_runtime_sha256=meta["artifact_runtime_sha256"],
                deployed_address=address,
                deployed_runtime_sha256=deployed_runtime_sha256,
            )
        )
    return tuple(rows)


def _start_anvil(config: ChainConfig, output_root: Path) -> _AnvilProcess:
    if not _port_available(config.host, config.port):
        raise RuntimeError(f"Anvil port already in use: {config.host}:{config.port}")
    log_dir = output_root / "logs"
    _ensure_directory(output_root, PurePosixPath("logs"))
    log_path = log_dir / "anvil.log"
    version = _run(("anvil", "--version"), cwd=_ROOT, timeout=config.command_timeout_seconds).stdout
    process = subprocess.Popen(
        (
            "anvil",
            "--host",
            config.host,
            "--port",
            str(config.port),
            "--chain-id",
            str(config.chain_id),
            "--silent",
        ),
        cwd=_ROOT,
        env=_safe_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    if process.stdout is None:  # pragma: no cover - subprocess invariant
        raise RuntimeError("Anvil stdout pipe was not created")
    log_capture = _BoundedLogCapture(
        path=log_path,
        limit=_ANVIL_LOG_LIMIT,
        captured=bytearray(),
        full_hasher=hashlib.sha256(),
    )
    log_thread = threading.Thread(
        target=log_capture.consume,
        args=(process.stdout,),
        name="task21-anvil-log-drain",
        daemon=True,
    )
    log_thread.start()
    rpc_url = f"http://{config.host}:{config.port}"
    deadline = time.time() + config.startup_timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            observed = _run(("cast", "chain-id", "--rpc-url", rpc_url), cwd=_ROOT, timeout=2).stdout
            if int(observed) == config.chain_id:
                return _AnvilProcess(
                    process=process,
                    rpc_url=rpc_url,
                    host=config.host,
                    port=config.port,
                    log_path=log_path,
                    version=version,
                    log_capture=log_capture,
                    log_thread=log_thread,
                )
        except Exception as error:  # pragma: no cover - exercised only on startup races
            last_error = error
            time.sleep(0.2)
    if process.poll() is None:
        try:
            os.killpg(os.getpgid(process.pid), 15)
        except ProcessLookupError:
            pass
    if last_error is not None:
        raise RuntimeError(f"Anvil did not become ready: {last_error}") from last_error
    raise RuntimeError("Anvil did not become ready before timeout")


def _ensure_directory(root: Path, relative: PurePosixPath) -> Path:
    current = root
    parts = [part for part in relative.parts if part not in ("", ".")]
    for part in parts:
        candidate = current / part
        if candidate.exists():
            status = os.lstat(candidate)
            if stat.S_ISLNK(status.st_mode):
                raise ValueError(f"symlinked output directory is forbidden: {candidate}")
            if not candidate.is_dir():
                raise ValueError(f"output directory component is not a directory: {candidate}")
        else:
            candidate.mkdir(mode=0o700)
        current = candidate
    return current


def _validate_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("artifact path must not be blank")
    if "\\" in value or value.startswith("/") or value.startswith("./") or value.endswith("/.") or "/./" in value:
        raise ValueError(f"artifact path escapes output root: {value}")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(f"artifact path contains invalid components: {value}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"artifact path escapes output root: {value}")
    return relative


def _validated_relative_posix_path(value: str | Path | PurePosixPath) -> str:
    return _validate_relative_path(_path_text(value)).as_posix()


def _resolve_output_relative_path(root: Path, value: str | Path | PurePosixPath) -> Path:
    relative = _validate_relative_path(_path_text(value))
    current = _existing_output_root(root)
    for part in relative.parts:
        candidate = current / part
        if candidate.exists():
            status = os.lstat(candidate)
            if stat.S_ISLNK(status.st_mode):
                raise ValueError(f"symlinked output path is forbidden: {candidate}")
        current = candidate
    return current


def _relative_output_path(root: Path, target: Path) -> str:
    relative = target.relative_to(root)
    return _validated_relative_posix_path(PurePosixPath(relative.as_posix()))


def _decode_canonical_json(raw: bytes, domain: str) -> dict[str, Any]:
    prefix = f"{_CANONICAL_PREFIX}|{domain}|".encode("ascii")
    if not raw.startswith(prefix):
        raise ValueError(f"canonical payload missing expected {domain} prefix")
    payload = json.loads(raw[len(prefix) :].decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("canonical payload must decode to an object")
    return payload


def _artifact_relative_parts(filename: str) -> tuple[str, ...]:
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("configured artifact filename is invalid")
    if "\x00" in filename or "\\" in filename or filename.startswith("/") or (len(filename) >= 2 and filename[1] == ":"):
        raise ValueError("configured artifact filename is invalid")
    relative = PurePosixPath(filename)
    if relative.as_posix() != filename or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("configured artifact filename is invalid")
    return relative.parts


def _hash_local_artifact_file(root: Path, filename: str, *, label: str) -> str:
    descriptor, _ = _open_directory_no_symlinks(root, create=False, label=f"configured {label} root")
    opened_parents: list[int] = []
    try:
        current_fd = descriptor
        parts = _artifact_relative_parts(filename)
        for parent in parts[:-1]:
            try:
                next_fd = os.open(parent, os.O_RDONLY | _DIRECTORY | _NOFOLLOW, dir_fd=current_fd)
            except FileNotFoundError as error:
                raise FileNotFoundError(filename) from error
            except OSError as error:
                raise ValueError(f"configured {label} artifact file is not a trusted local file: {filename}") from error
            parent_stat = os.fstat(next_fd)
            if not stat.S_ISDIR(parent_stat.st_mode):
                os.close(next_fd)
                raise ValueError(f"configured {label} artifact file is not a trusted local file: {filename}")
            opened_parents.append(next_fd)
            current_fd = next_fd
        leaf = parts[-1]
        try:
            pre_stat = os.stat(leaf, dir_fd=current_fd, follow_symlinks=False)
        except FileNotFoundError as error:
            raise FileNotFoundError(filename) from error
        if not stat.S_ISREG(pre_stat.st_mode) or pre_stat.st_nlink != 1:
            raise ValueError(f"configured {label} artifact file is not a trusted local file: {filename}")
        try:
            file_fd = os.open(leaf, os.O_RDONLY | _NOFOLLOW, dir_fd=current_fd)
        except OSError as error:
            raise ValueError(f"configured {label} artifact file is not a trusted local file: {filename}") from error
        try:
            fd_stat = os.fstat(file_fd)
            post_stat = os.stat(leaf, dir_fd=current_fd, follow_symlinks=False)
            identities = {
                (pre_stat.st_dev, pre_stat.st_ino),
                (fd_stat.st_dev, fd_stat.st_ino),
                (post_stat.st_dev, post_stat.st_ino),
            }
            if len(identities) != 1:
                raise ValueError(f"configured {label} artifact file changed identity during access: {filename}")
            if not stat.S_ISREG(fd_stat.st_mode) or fd_stat.st_nlink != 1:
                raise ValueError(f"configured {label} artifact file is not a trusted local file: {filename}")
            hasher = hashlib.sha256()
            while True:
                chunk = os.read(file_fd, 65536)
                if not chunk:
                    return hasher.hexdigest()
                hasher.update(chunk)
        finally:
            os.close(file_fd)
    finally:
        for parent_fd in reversed(opened_parents):
            os.close(parent_fd)
        os.close(descriptor)


def _write_json_atomic(root: Path, relative_path: str, payload: Mapping[str, Any]) -> tuple[Path, str]:
    safe_root = _prepare_output_root(root)
    relative = _validate_relative_path(relative_path)
    directory = _ensure_directory(safe_root, relative.parent)
    target = directory / relative.name
    if target.exists():
        status = os.lstat(target)
        if stat.S_ISLNK(status.st_mode):
            raise ValueError(f"symlinked output target is forbidden: {target}")
    content = canonical_bytes("TASK21_JSON", payload)
    temp_name = directory / f".{relative.name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
    try:
        offset = 0
        while offset < len(content):
            offset += os.write(fd, content[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp_name, target)
    with target.open("rb") as handle:
        stored = handle.read()
    if stored != content:
        raise RuntimeError(f"atomic write verification failed for {target}")
    return target, _hash_bytes(content)


def _mechanics_payload(
    *,
    artifact_id: str,
    origin: EvidenceOrigin,
    parent_hashes: Sequence[str],
    payload: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "POI_MPP_TASK21_MECHANICS_PAYLOAD_V1",
        "artifact_id": artifact_id,
        "origin": origin.value,
        "summary_disposition": NON_PUBLICATION_MECHANICS,
        "parent_hashes": list(parent_hashes),
        "provenance": dict(provenance),
        "payload": dict(payload),
    }


def _write_mechanics_artifact(
    *,
    output_root: Path,
    artifact_id: str,
    relative_path: str,
    parent_hashes: Sequence[str],
    payload: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> MechanicsArtifact:
    canonical_relative_path = _validated_relative_posix_path(relative_path)
    envelope = _mechanics_payload(
        artifact_id=artifact_id,
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        parent_hashes=parent_hashes,
        payload=payload,
        provenance=provenance,
    )
    target, content_hash = _write_json_atomic(output_root, canonical_relative_path, envelope)
    return MechanicsArtifact(
        artifact_id=artifact_id,
        relative_path=canonical_relative_path,
        content_hash=content_hash,
        parent_hashes=tuple(parent_hashes),
        origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
        summary_disposition=SyntheticDisposition.NON_PUBLICATION_MECHANICS,
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"unable to load local MPP config: {path}") from error
    if not isinstance(raw, dict):
        raise ValueError("local MPP config must be a mapping")
    return raw


def _validation_error_message(error: ValidationError) -> str:
    extras: list[str] = []
    for issue in error.errors():
        if issue.get("type") == "extra_forbidden":
            path = ".".join(str(item) for item in issue.get("loc", ()))
            extras.append(path)
    if extras:
        return f"unknown configuration fields: {', '.join(extras)}"
    return str(error)


def load_local_mpp_config(path: str | Path) -> LocalMPPConfig:
    config_path = Path(path).resolve()
    raw = _load_yaml(config_path)
    if isinstance(raw.get("model"), dict):
        model = dict(raw["model"])
        for key in ("model_root", "tokenizer_root"):
            candidate = model.get(key)
            if isinstance(candidate, str | Path):
                model[key] = str(_absolute_lexical_path(config_path.parent, candidate))
        raw["model"] = model
    if isinstance(raw.get("semantic"), dict):
        semantic = dict(raw["semantic"])
        schema_path = semantic.get("confirmatory_schema_path")
        if isinstance(schema_path, str) and not Path(schema_path).is_absolute():
            semantic["confirmatory_schema_path"] = str((config_path.parent / schema_path).resolve())
        raw["semantic"] = semantic
    output_root = raw.get("output_root")
    if isinstance(output_root, str | Path):
        raw["output_root"] = str(_absolute_lexical_path(config_path.parent, output_root))
    try:
        return LocalMPPConfig.model_validate(raw)
    except ValidationError as error:
        raise ValueError(_validation_error_message(error)) from error


def _verify_local_model_artifact(config: LocalMPPConfig) -> tuple[RealPathBlocker, tuple[str, ...]]:
    reasons: list[str] = []
    for label, root, file_hashes in (
        ("model", config.model.model_root, config.model.manifest.model_file_hashes),
        ("tokenizer", config.model.tokenizer_root, config.model.manifest.tokenizer_file_hashes),
    ):
        try:
            descriptor, _ = _open_directory_no_symlinks(root, create=False, label=f"configured {label} root")
            os.close(descriptor)
        except ValueError:
            reasons.append(f"configured {label} root is not a trusted local directory")
            continue
        for filename, expected_hash in file_hashes.items():
            try:
                observed_hash = _hash_local_artifact_file(root, filename, label=label)
            except FileNotFoundError:
                reasons.append(f"missing local artifact file under configured {label} root: {filename}")
                continue
            except ValueError as error:
                detail = str(error)
                if "changed identity during access" in detail:
                    reasons.append(f"configured {label} artifact file changed identity during access: {filename}")
                else:
                    reasons.append(f"configured {label} artifact file is not a trusted local file: {filename}")
                continue
            if observed_hash != expected_hash:
                reasons.append(f"hash mismatch for local artifact file under configured {label} root: {filename}")
    if reasons:
        return (RealPathBlocker.WAITING_LOCAL_MODEL_ARTIFACT, tuple(reasons))
    load_e3_confirmatory_schema(config.semantic.confirmatory_schema_path)
    return (
        RealPathBlocker.WAITING_EXTERNAL_EVALUATOR_AUTHORITY,
        (
            f"{WAITING_EXTERNAL_EVALUATOR_AUTHORITY}: external evaluator registry capability is still absent",
            f"declared reference: {config.semantic.evaluator_registry_reference}",
        ),
    )


def _register_owner_roles(policy_address: str, rpc_url: str, *, timeout: int) -> None:
    for role_name in (
        "MODEL_ADMIN_ROLE()(bytes32)",
        "TASK_ADMIN_ROLE()(bytes32)",
        "AUDITOR_ROLE()(bytes32)",
        "RECEIPT_OPERATOR_ROLE()(bytes32)",
        "CREDIT_OPERATOR_ROLE()(bytes32)",
    ):
        role = _call_word(rpc_url, policy_address, role_name, timeout=timeout)
        _send(rpc_url, policy_address, "grantRole(bytes32,address)", role, _ANVIL_OWNER, timeout=timeout)


def _deploy_stack(config: LocalMPPConfig, anvil: _AnvilProcess) -> DeploymentSummary:
    timeout = config.chain.command_timeout_seconds
    policy_address = _deploy(
        anvil.rpc_url,
        "src/PolicyRegistry.sol:PolicyRegistry",
        timeout=timeout,
        constructor_args=(
            _COMMITMENT_FINALITY_DEPTH,
            _CHALLENGE_WINDOW_BLOCKS,
            _BETA,
            _CONCENTRATION_CAP,
            _CHAIN_GENESIS_BLOCK,
            _CHAIN_BLOCKS_PER_EPOCH,
        ),
    )
    _register_owner_roles(policy_address, anvil.rpc_url, timeout=timeout)
    model_registry_address = _deploy(
        anvil.rpc_url,
        "src/ModelRegistry.sol:ModelRegistry",
        timeout=timeout,
        constructor_args=(policy_address,),
    )
    task_manager_address = _deploy(
        anvil.rpc_url,
        "src/TaskManager.sol:TaskManager",
        timeout=timeout,
        constructor_args=(policy_address, model_registry_address),
    )
    commitment_hub_address = _deploy(
        anvil.rpc_url,
        "src/CommitmentHub.sol:CommitmentHub",
        timeout=timeout,
        constructor_args=(policy_address, task_manager_address),
    )
    audit_manager_address = _deploy(
        anvil.rpc_url,
        "src/AuditManager.sol:AuditManager",
        timeout=timeout,
        constructor_args=(policy_address, commitment_hub_address, task_manager_address),
    )
    receipt_manager_address = _deploy(
        anvil.rpc_url,
        "src/ReceiptManager.sol:ReceiptManager",
        timeout=timeout,
        constructor_args=(policy_address, task_manager_address, commitment_hub_address, audit_manager_address),
    )
    credit_engine_address = _deploy(
        anvil.rpc_url,
        "src/CreditEngine.sol:CreditEngine",
        timeout=timeout,
        constructor_args=(policy_address, task_manager_address, receipt_manager_address),
    )
    _send(anvil.rpc_url, policy_address, "setModelRegistry(address)", model_registry_address, timeout=timeout)
    _send(anvil.rpc_url, policy_address, "setTaskManager(address)", task_manager_address, timeout=timeout)
    _send(anvil.rpc_url, policy_address, "setCommitmentHub(address)", commitment_hub_address, timeout=timeout)
    _send(anvil.rpc_url, policy_address, "setAuditManager(address)", audit_manager_address, timeout=timeout)
    _send(anvil.rpc_url, policy_address, "setReceiptManager(address)", receipt_manager_address, timeout=timeout)
    _send(anvil.rpc_url, policy_address, "setCreditEngine(address)", credit_engine_address, timeout=timeout)
    addresses = {
        "PolicyRegistry": policy_address,
        "ModelRegistry": model_registry_address,
        "TaskManager": task_manager_address,
        "CommitmentHub": commitment_hub_address,
        "AuditManager": audit_manager_address,
        "ReceiptManager": receipt_manager_address,
        "CreditEngine": credit_engine_address,
    }
    contract_hashes = _collect_contract_hashes(anvil.rpc_url, addresses, timeout=timeout)
    return DeploymentSummary(
        chain_id=config.chain.chain_id,
        deployer_address=_ANVIL_OWNER,
        worker_address=_ANVIL_OWNER,
        policy_address=policy_address,
        model_registry_address=model_registry_address,
        task_manager_address=task_manager_address,
        commitment_hub_address=commitment_hub_address,
        audit_manager_address=audit_manager_address,
        receipt_manager_address=receipt_manager_address,
        credit_engine_address=credit_engine_address,
        anvil_version=anvil.version,
        contract_hashes=contract_hashes,
    )


def _current_epoch(policy_address: str, rpc_url: str, *, timeout: int) -> int:
    return _call_uint(rpc_url, policy_address, "currentEpoch()(uint64)", timeout=timeout)


def _task_id_before_create(task_manager_address: str, rpc_url: str, *, timeout: int) -> int:
    return _call_uint(rpc_url, task_manager_address, "nextTaskId()(uint256)", timeout=timeout)


def _receipt_id_before_mint(receipt_manager_address: str, rpc_url: str, *, timeout: int) -> int:
    return _call_uint(rpc_url, receipt_manager_address, "nextReceiptId()(uint256)", timeout=timeout)


def _expected_happy_credit_epoch(task_epoch: int) -> int:
    return task_epoch + 1


def _read_authoritative_audit_round(
    rpc_url: str,
    audit_manager_address: str,
    task_id: int,
    *,
    timeout: int,
) -> dict[str, Any]:
    payload = _json_command(
        (
            "cast",
            "call",
            "--json",
            "--rpc-url",
            rpc_url,
            audit_manager_address,
            "getAudit(uint256)((bytes32,bytes32,bytes32,bytes32,uint32,uint64,uint64,uint8,bool,bool,bool,bool,bool))",
            str(task_id),
        ),
        cwd=_ROOT,
        timeout=timeout,
    )
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], list) or len(payload[0]) != 13:
        raise RuntimeError("unexpected AuditManager.getAudit payload shape")
    row = payload[0]
    return {
        "audit_id": row[0],
        "commitment_hash": row[1],
        "seed_hash": row[2],
        "policy_hash": row[3],
        "round_index": int(row[4]),
        "opened_block": int(row[5]),
        "challenge_deadline": int(row[6]),
        "decision": int(row[7]),
        "da_passed": bool(row[8]),
        "da_recorded": bool(row[9]),
        "challenged": bool(row[10]),
        "slashed": bool(row[11]),
        "exists": bool(row[12]),
    }


def _read_authoritative_receipt(
    rpc_url: str,
    receipt_manager_address: str,
    receipt_id: int,
    *,
    timeout: int,
) -> Receipt:
    payload = _json_command(
        (
            "cast",
            "call",
            "--json",
            "--rpc-url",
            rpc_url,
            receipt_manager_address,
            "getReceipt(uint256)((uint256,address,bytes32,bytes32,bytes32,uint8,uint64,uint64,uint64))",
            str(receipt_id),
        ),
        cwd=_ROOT,
        timeout=timeout,
    )
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], list) or len(payload[0]) != 9:
        raise RuntimeError("unexpected ReceiptManager.getReceipt payload shape")
    row = payload[0]
    try:
        state = tuple(ReceiptState)[int(row[5])]
    except (IndexError, TypeError, ValueError) as error:
        raise RuntimeError(f"unexpected receipt state ordinal from chain: {row[5]}") from error
    return Receipt.model_validate(
        {
            "receipt_id": receipt_id,
            "task_id": int(row[0]),
            "worker_id": row[1],
            "commitment_hash": row[2],
            "audit_id": row[3],
            "nullifier": row[4],
            "state": state,
            "epoch_issued": int(row[6]),
            "challenge_deadline": int(row[7]),
            "activated_epoch": None if int(row[8]) == 0 else int(row[8]),
            "audit_decision": None,
            "audit_accepted": False,
            "da_decision": None,
            "data_availability_passed": False,
            "challenge_reason": None,
            "slash_reason": None,
        }
    )


def _validated_happy_authoritative_receipt(
    *,
    rpc_url: str,
    deployment: DeploymentSummary,
    receipt_id: int,
    task: TaskSpec,
    expected_worker: str,
    expected_commitment_hash: str,
    expected_audit_id: str,
    expected_nullifier: str,
    timeout: int,
) -> Receipt:
    receipt = _read_authoritative_receipt(
        rpc_url,
        deployment.receipt_manager_address,
        receipt_id,
        timeout=timeout,
    )
    audit_round = _read_authoritative_audit_round(
        rpc_url,
        deployment.audit_manager_address,
        task.task_id,
        timeout=timeout,
    )
    expected_epoch = _expected_happy_credit_epoch(task.epoch)
    mismatches: list[str] = []
    expected_fields = {
        "task_id": task.task_id,
        "worker_id": expected_worker,
        "commitment_hash": expected_commitment_hash,
        "audit_id": expected_audit_id,
        "nullifier": expected_nullifier,
        "state": ReceiptState.ACTIVE,
        "epoch_issued": task.epoch,
        "activated_epoch": expected_epoch,
    }
    for key, expected in expected_fields.items():
        observed = getattr(receipt, key)
        if observed != expected:
            mismatches.append(f"{key}: expected {expected!r}, observed {observed!r}")
    if audit_round["audit_id"] != expected_audit_id:
        mismatches.append(f"audit_round.audit_id: expected {expected_audit_id!r}, observed {audit_round['audit_id']!r}")
    if audit_round["commitment_hash"] != expected_commitment_hash:
        mismatches.append(
            f"audit_round.commitment_hash: expected {expected_commitment_hash!r}, observed {audit_round['commitment_hash']!r}"
        )
    if receipt.challenge_deadline != audit_round["challenge_deadline"]:
        mismatches.append(
            f"challenge_deadline: expected {audit_round['challenge_deadline']!r}, observed {receipt.challenge_deadline!r}"
        )
    if audit_round["decision"] != int(AuditDecision.ACCEPT):
        mismatches.append(f"audit_round.decision: expected {int(AuditDecision.ACCEPT)!r}, observed {audit_round['decision']!r}")
    if not audit_round["da_passed"] or not audit_round["da_recorded"] or not audit_round["exists"]:
        mismatches.append(
            "audit_round flags: expected da_passed=True, da_recorded=True, exists=True"
        )
    if mismatches:
        raise RuntimeError("authoritative receipt readback mismatch: " + "; ".join(mismatches))
    return receipt.model_copy(
        update={
            "audit_decision": AuditDecision.ACCEPT,
            "audit_accepted": True,
            "da_decision": True,
            "data_availability_passed": True,
        }
    )


def _register_model_and_worker(
    config: LocalMPPConfig,
    deployment: DeploymentSummary,
    *,
    timeout: int,
    rpc_url: str,
) -> tuple[str, str]:
    manifest = config.model.manifest
    policy = config.model.decode_policy
    model_root = manifest.model_root()
    runtime_root = manifest.runtime_root(policy)
    manifest_hash = manifest.manifest_hash(policy)
    _send(
        rpc_url,
        deployment.model_registry_address,
        "registerModel(bytes32,bytes32,bytes32,uint8)",
        model_root,
        runtime_root,
        manifest_hash,
        manifest.assurance_class,
        timeout=timeout,
    )
    _send(
        rpc_url,
        deployment.task_manager_address,
        "registerWorker(address)",
        deployment.worker_address,
        timeout=timeout,
    )
    return (model_root, runtime_root)


def _create_task(
    task_root: str,
    *,
    task_class: TaskClass,
    deployment: DeploymentSummary,
    rpc_url: str,
    model_root: str,
    timeout: int,
) -> int:
    task_id = _task_id_before_create(deployment.task_manager_address, rpc_url, timeout=timeout)
    epoch = _current_epoch(deployment.policy_address, rpc_url, timeout=timeout)
    _send(
        rpc_url,
        deployment.task_manager_address,
        "createTask(bytes32,bytes32,address,uint8,uint256,uint64,uint64)",
        task_root,
        model_root,
        deployment.worker_address,
        int(task_class),
        _CREDIT_BUDGET,
        epoch,
        _TASK_DEADLINE,
        timeout=timeout,
    )
    return task_id


def _make_task_spec(
    *,
    task_id: int,
    task_root: str,
    task_class: TaskClass,
    worker: str,
    epoch: int,
    commitment_height: int,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        task_root=task_root,
        worker_id=worker,
        task_class=task_class,
        active=True,
        registered=True,
        credit_budget=_CREDIT_BUDGET,
        epoch=epoch,
        deadline=_TASK_DEADLINE,
        commitment_height=commitment_height,
        commitment_finality_depth=_COMMITMENT_FINALITY_DEPTH,
        challenge_window_blocks=_CHALLENGE_WINDOW_BLOCKS,
        audit_domain_size=_AUDIT_DOMAIN_SIZE,
    )


def _make_pending_receipt(task: TaskSpec, commitment_hash: str, audit_id: str, receipt_id: int, nullifier: str) -> Receipt:
    return Receipt(
        receipt_id=receipt_id,
        task_id=task.task_id,
        worker_id=task.worker_id,
        commitment_hash=commitment_hash,
        audit_id=audit_id,
        state=ReceiptState.PENDING,
        epoch_issued=task.epoch,
        challenge_deadline=task.commitment_height + task.challenge_window_blocks,
        nullifier=nullifier,
        audit_decision=None,
        audit_accepted=False,
        da_decision=None,
        data_availability_passed=False,
        activated_epoch=None,
        challenge_reason=None,
        slash_reason=None,
    )


def _run_reference_machine_failures(
    task: TaskSpec,
    commitment_hash: str,
    audit_id: str,
    *,
    fixture_root: Path,
) -> FailurePathSummary:
    receipt = _make_pending_receipt(
        task,
        commitment_hash,
        audit_id,
        77,
        bytes32_word("TASK21_FAILURE_NULLIFIER", {"task_id": task.task_id}),
    )
    mature = TransitionContext(
        current_height=task.commitment_height + task.challenge_window_blocks,
        current_epoch=task.epoch + 1,
        used_nullifiers=frozenset(),
    )
    execution_rejection = transition(receipt, RecordAudit(decision=AuditDecision.REJECT), mature)
    abstain_result = verify_grounded(
        response="claim::abstain",
        claims=(GroundedClaim(claim_id="claim-1", text="claim::abstain", cited_citation_ids=("cite-1",)),),
        evidence=(
            EvidenceRecord.model_validate(
                {
                    "evidence_id": "evidence-cite-1",
                    "citation_id": "cite-1",
                    "source_family": "task21",
                    "origin": EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
                    "content": "evidence::cite-1",
                    "content_hash": semantic_evidence_content_hash(
                        citation_id="cite-1",
                        content="evidence::cite-1",
                        source_family="task21",
                    ),
                    "annotations": (
                        EvidenceAnnotation(
                            claim_id="claim-1",
                            kind=EvidenceAnnotationKind.SUPPORTS,
                            reason="synthetic plumbing only",
                        ),
                    ),
                }
            ),
        ),
        calibration=SemanticCalibrationArtifact.create(
            dataset_label="task21-synthetic",
            minimum_support_fraction=1.0,
            example_count=1,
        ),
        mode=VerificationMode.CONFIRMATORY,
    )
    if abstain_result.decision is not VerificationDecision.ABSTAIN:
        raise RuntimeError("Task 21 semantic abstention path failed to abstain")
    semantic_abstention = transition(receipt, RecordAudit(decision=AuditDecision.ABSTAIN), mature)

    store = LocalShardStore(fixture_root)
    layout = store.initialize(
        finalized_commitment_hash=commitment_hash,
        erasure=ErasureParameters(total_shards=4, reconstruction_threshold=3),
        shard_payloads=(b"a", b"b", b"c", b"d"),
    )
    certificate = issue_sample_certificate(
        layout=layout,
        store=store,
        beacon=b"task21-da-failure",
        round_index=0,
        sample_count=2,
        replacement=False,
    )
    store.shard_path(certificate.sample_indices[0]).unlink()
    reconstruction = verify_reconstruction(
        layout=layout,
        store=store,
        certificate=certificate,
        mode=SamplingMode.STATIC_WITHOUT_REPLACEMENT,
    )
    if reconstruction.status is not ReconstructionStatus.WITHHELD:
        raise RuntimeError("Task 21 DA failure path did not withhold")
    da_failed = transition(
        transition(receipt, RecordAudit(decision=AuditDecision.ACCEPT), mature),
        RecordDataAvailability(available=False),
        mature,
    )
    challenged = transition(
        transition(
            transition(receipt, RecordAudit(decision=AuditDecision.ACCEPT), mature),
            RecordDataAvailability(available=True),
            mature,
        ),
        OpenChallenge(reason="semantic mismatch"),
        mature,
    )
    slashed = transition(challenged, SlashReceipt(reason="semantic mismatch"), mature)
    return FailurePathSummary(
        execution_rejection_state=execution_rejection.state.name,
        semantic_abstention_state=semantic_abstention.state.name,
        da_failure_state=da_failed.state.name,
        successful_challenge_state=slashed.state.name,
        service_task_credit_total=0,
        replay_rejection_error_code=REPLAY_REJECTED,
    )


def _run_synthetic_mechanics(
    config: LocalMPPConfig,
    deployment: DeploymentSummary,
    *,
    rpc_url: str,
    timeout: int,
    config_hash_value: str,
    parity: ParitySummary,
) -> SyntheticJourneySummary:
    model_root, _ = _register_model_and_worker(config, deployment, timeout=timeout, rpc_url=rpc_url)
    consensus_task_root = bytes32_word("TASK21_CONSENSUS_TASK_ROOT", {"task": "consensus"})
    service_task_root = bytes32_word("TASK21_SERVICE_TASK_ROOT", {"task": "service"})
    consensus_task_id = _create_task(
        consensus_task_root,
        task_class=TaskClass.CONSENSUS,
        deployment=deployment,
        rpc_url=rpc_url,
        model_root=model_root,
        timeout=timeout,
    )
    service_task_id = _create_task(
        service_task_root,
        task_class=TaskClass.SERVICE,
        deployment=deployment,
        rpc_url=rpc_url,
        model_root=model_root,
        timeout=timeout,
    )
    current_block = _block_number(rpc_url, timeout)
    current_epoch = _current_epoch(deployment.policy_address, rpc_url, timeout=timeout)
    consensus_task = _make_task_spec(
        task_id=consensus_task_id,
        task_root=consensus_task_root,
        task_class=TaskClass.CONSENSUS,
        worker=deployment.worker_address,
        epoch=current_epoch,
        commitment_height=current_block + 1,
    )
    service_task = _make_task_spec(
        task_id=service_task_id,
        task_root=service_task_root,
        task_class=TaskClass.SERVICE,
        worker=deployment.worker_address,
        epoch=current_epoch,
        commitment_height=current_block + 2,
    )
    adapter = FixtureInferenceAdapter.synthetic(
        response="Grounded answer. Evidence sentence.",
        trace_token_ids=(11, 12),
        evidence_texts=("Evidence sentence.",),
    )
    execution_bundle = execute_once(
        consensus_task,
        config.model.manifest,
        config.model.decode_policy,
        adapter=adapter,
    )
    provenance = {
        "config_hash": config_hash_value,
        "parity_source_closure_hash": parity.source_closure_hash,
        "worker_address": deployment.worker_address,
    }
    artifacts: list[MechanicsArtifact] = []
    execution_artifact = _write_mechanics_artifact(
        output_root=config.output_root,
        artifact_id="task21-synthetic-execution-bundle",
        relative_path="synthetic/happy/execution_bundle.json",
        parent_hashes=(),
        payload=execution_bundle.model_dump(mode="json"),
        provenance=provenance,
    )
    artifacts.append(execution_artifact)

    consensus_commitment = commit_response(
        consensus_task,
        config.model.manifest.to_protocol_manifest(config.model.decode_policy),
        execution_bundle.response_hash,
        execution_bundle.trace_root,
        execution_bundle.evidence_root,
        execution_bundle.artifact_root,
        nonce=bytes.fromhex("55" * 32),
    )
    service_commitment = commit_response(
        service_task,
        config.model.manifest.to_protocol_manifest(config.model.decode_policy),
        bytes32_word("TASK21_SERVICE_RESPONSE", {"task_id": service_task_id}),
        bytes32_word("TASK21_SERVICE_TRACE", {"task_id": service_task_id}),
        bytes32_word("TASK21_SERVICE_EVIDENCE", {"task_id": service_task_id}),
        bytes32_word("TASK21_SERVICE_ARTIFACT", {"task_id": service_task_id}),
        nonce=bytes.fromhex("66" * 32),
    )
    _send(
        rpc_url,
        deployment.commitment_hub_address,
        "commitResponse(uint256,bytes32,bytes32,bytes32,bytes32,bytes32)",
        consensus_task_id,
        execution_bundle.response_hash,
        execution_bundle.trace_root,
        execution_bundle.evidence_root,
        execution_bundle.artifact_root,
        consensus_commitment.nonce,
        timeout=timeout,
    )
    _send(
        rpc_url,
        deployment.commitment_hub_address,
        "commitResponse(uint256,bytes32,bytes32,bytes32,bytes32,bytes32)",
        service_task_id,
        service_commitment.response_hash,
        service_commitment.trace_root,
        service_commitment.evidence_root,
        service_commitment.artifact_root,
        service_commitment.nonce,
        timeout=timeout,
    )

    finalize_target = max(consensus_commitment.finalized_height or 0, service_commitment.finalized_height or 0)
    _mine_to_block(rpc_url, _block_number(rpc_url, timeout), finalize_target, timeout)

    audit_policy = AuditPolicy(sample_count=4)
    consensus_audit = compile_audit(audit_policy, consensus_task, consensus_commitment, b"task21-beacon", 0)
    service_audit = compile_audit(audit_policy, service_task, service_commitment, b"task21-service-beacon", 0)
    for task_id, audit in ((consensus_task_id, consensus_audit), (service_task_id, service_audit)):
        _send(
            rpc_url,
            deployment.audit_manager_address,
            "openAudit(uint256,bytes32,bytes32,bytes32,uint32)",
            task_id,
            audit.audit_id,
            audit.seed_hash,
            audit.policy_hash,
            audit.round_index,
            timeout=timeout,
        )
        _send(
            rpc_url,
            deployment.audit_manager_address,
            "recordAuditResult(uint256,uint8)",
            task_id,
            int(AuditDecision.ACCEPT),
            timeout=timeout,
        )
        _send(
            rpc_url,
            deployment.audit_manager_address,
            "recordDataAvailability(uint256,bool)",
            task_id,
            True,
            timeout=timeout,
        )

    consensus_receipt_id = _receipt_id_before_mint(deployment.receipt_manager_address, rpc_url, timeout=timeout)
    _send(
        rpc_url,
        deployment.receipt_manager_address,
        "mintPending(uint256,bytes32)",
        consensus_task_id,
        bytes32_word("TASK21_NULLIFIER", {"task_id": consensus_task_id}),
        timeout=timeout,
    )
    service_receipt_id = _receipt_id_before_mint(deployment.receipt_manager_address, rpc_url, timeout=timeout)
    _send(
        rpc_url,
        deployment.receipt_manager_address,
        "mintPending(uint256,bytes32)",
        service_task_id,
        bytes32_word("TASK21_SERVICE_NULLIFIER", {"task_id": service_task_id}),
        timeout=timeout,
    )

    target_epoch_start_block = (_CHAIN_BLOCKS_PER_EPOCH * current_epoch) + 1
    _mine_to_block(rpc_url, _block_number(rpc_url, timeout), target_epoch_start_block, timeout)
    _send(rpc_url, deployment.receipt_manager_address, "activate(uint256)", consensus_receipt_id, timeout=timeout)
    _send(rpc_url, deployment.receipt_manager_address, "activate(uint256)", service_receipt_id, timeout=timeout)
    _send(rpc_url, deployment.credit_engine_address, "setCollateral(address,uint256)", deployment.worker_address, 900, timeout=timeout)
    _send(
        rpc_url,
        deployment.credit_engine_address,
        "allocateCredit(uint256,uint256[])",
        consensus_task_id,
        f"[{consensus_receipt_id}]",
        timeout=timeout,
    )
    service_receipt_credit_before = _call_uint(
        rpc_url,
        deployment.credit_engine_address,
        "receiptCredit(uint256)(uint256)",
        service_receipt_id,
        timeout=timeout,
    )
    _send(
        rpc_url,
        deployment.credit_engine_address,
        "allocateCredit(uint256,uint256[])",
        service_task_id,
        f"[{service_receipt_id}]",
        timeout=timeout,
    )
    service_receipt_credit_after = _call_uint(
        rpc_url,
        deployment.credit_engine_address,
        "receiptCredit(uint256)(uint256)",
        service_receipt_id,
        timeout=timeout,
    )
    if service_receipt_credit_before != service_receipt_credit_after:
        raise RuntimeError("service task unexpectedly received credit")
    try:
        _send(
            rpc_url,
            deployment.credit_engine_address,
            "allocateCredit(uint256,uint256[])",
            consensus_task_id,
            f"[{consensus_receipt_id}]",
            timeout=timeout,
        )
    except subprocess.CalledProcessError:
        replay_error = REPLAY_REJECTED
    else:  # pragma: no cover - defensive failure path
        raise RuntimeError("replay credit allocation unexpectedly succeeded")

    consensus_nullifier = bytes32_word("TASK21_NULLIFIER", {"task_id": consensus_task_id})
    authoritative_receipt = _validated_happy_authoritative_receipt(
        rpc_url=rpc_url,
        deployment=deployment,
        receipt_id=consensus_receipt_id,
        task=consensus_task,
        expected_worker=deployment.worker_address,
        expected_commitment_hash=consensus_commitment.commitment_hash,
        expected_audit_id=consensus_audit.audit_id,
        expected_nullifier=consensus_nullifier,
        timeout=timeout,
    )
    if authoritative_receipt.activated_epoch is None:
        raise RuntimeError("authoritative receipt readback did not return an activated epoch")
    credit_epoch = authoritative_receipt.activated_epoch
    happy_credit = allocate_credit(
        consensus_task,
        (authoritative_receipt,),
    )
    weight = derive_active_weight(happy_credit.total_credit, 900, _BETA, _CONCENTRATION_CAP)
    committee = sample_committee(
        {deployment.worker_address: weight},
        committee_size=config.committee_size,
        seed=f"epoch-{credit_epoch}".encode("utf-8"),
    )
    committee_artifact = _write_mechanics_artifact(
        output_root=config.output_root,
        artifact_id="task21-synthetic-committee",
        relative_path="synthetic/happy/committee.json",
        parent_hashes=(execution_artifact.content_hash,),
        payload={
            "credit_epoch": credit_epoch,
            "members": committee,
            "weight": weight,
        },
        provenance=provenance,
    )
    artifacts.append(committee_artifact)

    challenge_task_root = bytes32_word("TASK21_CHALLENGE_TASK_ROOT", {"task": "challenge"})
    challenge_task_id = _create_task(
        challenge_task_root,
        task_class=TaskClass.CONSENSUS,
        deployment=deployment,
        rpc_url=rpc_url,
        model_root=model_root,
        timeout=timeout,
    )
    challenge_task_epoch = _current_epoch(deployment.policy_address, rpc_url, timeout=timeout)
    challenge_task = _make_task_spec(
        task_id=challenge_task_id,
        task_root=challenge_task_root,
        task_class=TaskClass.CONSENSUS,
        worker=deployment.worker_address,
        epoch=challenge_task_epoch,
        commitment_height=_block_number(rpc_url, timeout) + 1,
    )
    challenge_bundle = execute_once(challenge_task, config.model.manifest, config.model.decode_policy, adapter=adapter)
    challenge_commitment = commit_response(
        challenge_task,
        config.model.manifest.to_protocol_manifest(config.model.decode_policy),
        challenge_bundle.response_hash,
        challenge_bundle.trace_root,
        challenge_bundle.evidence_root,
        challenge_bundle.artifact_root,
        nonce=bytes.fromhex("77" * 32),
    )
    _send(
        rpc_url,
        deployment.commitment_hub_address,
        "commitResponse(uint256,bytes32,bytes32,bytes32,bytes32,bytes32)",
        challenge_task_id,
        challenge_bundle.response_hash,
        challenge_bundle.trace_root,
        challenge_bundle.evidence_root,
        challenge_bundle.artifact_root,
        challenge_commitment.nonce,
        timeout=timeout,
    )
    _mine_to_block(rpc_url, _block_number(rpc_url, timeout), challenge_commitment.finalized_height or 0, timeout)
    challenge_audit = compile_audit(audit_policy, challenge_task, challenge_commitment, b"task21-challenge", 0)
    _send(
        rpc_url,
        deployment.audit_manager_address,
        "openAudit(uint256,bytes32,bytes32,bytes32,uint32)",
        challenge_task_id,
        challenge_audit.audit_id,
        challenge_audit.seed_hash,
        challenge_audit.policy_hash,
        challenge_audit.round_index,
        timeout=timeout,
    )
    _send(
        rpc_url,
        deployment.audit_manager_address,
        "recordAuditResult(uint256,uint8)",
        challenge_task_id,
        int(AuditDecision.ACCEPT),
        timeout=timeout,
    )
    _send(
        rpc_url,
        deployment.audit_manager_address,
        "recordDataAvailability(uint256,bool)",
        challenge_task_id,
        True,
        timeout=timeout,
    )
    challenge_receipt_id = _receipt_id_before_mint(deployment.receipt_manager_address, rpc_url, timeout=timeout)
    _send(
        rpc_url,
        deployment.receipt_manager_address,
        "mintPending(uint256,bytes32)",
        challenge_task_id,
        bytes32_word("TASK21_CHALLENGE_NULLIFIER", {"task_id": challenge_task_id}),
        timeout=timeout,
    )
    _send(
        rpc_url,
        deployment.audit_manager_address,
        "openChallenge(uint256,bytes32)",
        challenge_task_id,
        bytes32_word("TASK21_DISPUTE_ROOT", {"task_id": challenge_task_id}),
        timeout=timeout,
    )
    _send(rpc_url, deployment.receipt_manager_address, "markChallenged(uint256)", challenge_receipt_id, timeout=timeout)
    _send(rpc_url, deployment.audit_manager_address, "slash(uint256)", challenge_task_id, timeout=timeout)
    _send(rpc_url, deployment.receipt_manager_address, "slash(uint256)", challenge_receipt_id, timeout=timeout)

    failure_paths = _run_reference_machine_failures(
        consensus_task,
        consensus_commitment.commitment_hash,
        consensus_audit.audit_id,
        fixture_root=config.output_root / "synthetic" / "failure-da-store",
    ).model_copy(
        update={
            "service_task_credit_total": service_receipt_credit_after,
            "replay_rejection_error_code": replay_error,
        }
    )
    return SyntheticJourneySummary(
        summary_disposition=SyntheticDisposition.NON_PUBLICATION_MECHANICS,
        artifacts=tuple(artifacts),
        happy_path=HappyPathSummary(
            task_epoch=consensus_task.epoch,
            receipt_state=authoritative_receipt.state.name,
            credit_epoch=authoritative_receipt.activated_epoch,
            committee_members=committee,
            execution_bundle_path=execution_artifact.path,
            committee_artifact_path=committee_artifact.path,
        ),
        failure_paths=failure_paths,
    )


def run_local_mpp(config: LocalMPPConfig) -> LocalMPPResult:
    output_root = _prepare_output_root(config.output_root)
    parity_result = verify_current_e7_parity(
        repo_root=_ROOT,
        contracts_root=_CONTRACTS,
        timeout=config.chain.command_timeout_seconds,
    )
    parity = ParitySummary(
        source_closure_hash=parity_result.source_closure_hash,
        protocol_vectors_hash=parity_result.protocol_vectors_hash,
        protocol_witness_hash=parity_result.protocol_witness_hash,
    )
    anvil = _start_anvil(config.chain, output_root)
    deployment: DeploymentSummary | None = None
    blocker: RealPathBlocker | None = None
    reasons: tuple[str, ...] | None = None
    synthetic: SyntheticJourneySummary | None = None
    try:
        deployment = _deploy_stack(config, anvil)
        blocker, reasons = _verify_local_model_artifact(config)
        synthetic = _run_synthetic_mechanics(
            config,
            deployment,
            rpc_url=anvil.rpc_url,
            timeout=config.chain.command_timeout_seconds,
            config_hash_value=config_hash(config.run_config),
            parity=parity,
        )
    finally:
        anvil.close()
    if deployment is None or blocker is None or reasons is None or synthetic is None:  # pragma: no cover - defensive
        raise RuntimeError("local MPP run did not produce a complete result")
    result = LocalMPPResult(
        config_hash=config_hash(config.run_config),
        parity=parity,
        contracts=deployment.model_copy(update={"anvil_log": anvil.log_capture.summary(output_root=output_root)}),
        real_path=RealPathSummary(blocker=blocker, reasons=reasons),
        synthetic=synthetic,
    )
    _write_json_atomic(
        output_root,
        "run_mpp_result.json",
        result.model_dump(mode="json"),
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run local Task 21 MPP orchestration")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-root", required=False)
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = load_local_mpp_config(args.config)
    if args.output_root is not None:
        config = config.model_copy(update={"output_root": _absolute_lexical_path(Path.cwd(), args.output_root)})
    result = run_local_mpp(config)
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
