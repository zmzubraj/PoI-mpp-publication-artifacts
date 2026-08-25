"""Fail-closed preflight for external E3-v2 development bundles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from poi_mpp.evidence.dataset_manifest_v2 import DatasetManifestV2
from poi_mpp.evidence.environment_manifest import ExecutionEnvironmentManifestV1
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
from poi_mpp.worker.model_manifest import PinnedModelManifest


REPO_ROOT = Path(__file__).resolve().parents[3]
_AUTHORITY_VERIFIER = REPO_ROOT / "scripts" / "verify_e3_authority.py"
_SHA256 = set("0123456789abcdef")
_PREEXEC_STATIC_FILES = frozenset(
    {
        "owner_declaration.json",
        "model/pinned_model_manifest.json",
        "model/file_hashes.sha256",
        "dataset/dataset_manifest_v2.json",
        "dataset/annotation_agreement.json",
        "dataset/adjudication_ledger.json",
        "dataset/license_privacy_ledger.json",
        "policy/claim_spec.json",
        "policy/prompt_template.txt",
        "policy/output_schema.json",
        "policy/contradiction_policy.json",
        "policy/error_recovery_policy.json",
        "policy/error_taxonomy_review.json",
        "execution/environment_manifest.json",
        "execution/deterministic_decode_policy.json",
        "manifest.json",
    }
)
_PRIMARY_MODEL_SCALES = frozenset({"1B", "1.5B", "2B", "3B"})
_FORBIDDEN_WEIGHT_SUFFIXES = (".bin", ".pt", ".pth", ".ckpt")


class E3DevelopmentBundleError(ValueError):
    """Raised when an external E3-v2 development bundle fails preflight."""


class E3DevelopmentBundleStatus(StrEnum):
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    READY_FOR_EXECUTION = "READY_FOR_EXECUTION"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ManifestEntry(_FrozenModel):
    path: str
    sha256: str

    @field_validator("path")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("manifest path must not be blank")
        pure = PurePosixPath(value)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise ValueError("manifest path must be a safe relative path")
        return pure.as_posix()

    @field_validator("sha256")
    @classmethod
    def _sha256_hex(cls, value: str) -> str:
        if not isinstance(value, str) or len(value) != 64 or any(ch not in _SHA256 for ch in value):
            raise ValueError("manifest sha256 must be a lowercase SHA-256 hex digest")
        return value


class _BundleManifest(_FrozenModel):
    schema_version: str = "POI_MPP_E3_V2_DEVELOPMENT_BUNDLE_MANIFEST_V1"
    files: tuple[_ManifestEntry, ...]

    @field_validator("files", mode="before")
    @classmethod
    def _normalize_files(cls, value: Any) -> tuple[_ManifestEntry, ...]:
        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError("manifest files must be a non-empty sequence")
        files = tuple(
            item if isinstance(item, _ManifestEntry) else _ManifestEntry.model_validate(item)
            for item in value
        )
        paths = [item.path for item in files]
        if len(paths) != len(set(paths)):
            raise ValueError("manifest files must not contain duplicate paths")
        return files


class _OwnerDeclaration(_FrozenModel):
    schema_version: str = "POI_MPP_E3_V2_OWNER_DECLARATION_V1"
    owner_id: str
    accountable_reviewer_id: str
    offline_execution_declared: bool
    local_only_execution_declared: bool
    license_review_reference: str
    runtime_wheel_ledger_review_reference: str
    deterministic_decode_review_reference: str
    dataset_review_reference: str
    annotation_review_reference: str
    policy_review_reference: str

    @field_validator(
        "owner_id",
        "accountable_reviewer_id",
        "license_review_reference",
        "runtime_wheel_ledger_review_reference",
        "deterministic_decode_review_reference",
        "dataset_review_reference",
        "annotation_review_reference",
        "policy_review_reference",
    )
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("owner declaration fields must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def _require_local_offline(self) -> "_OwnerDeclaration":
        if not self.offline_execution_declared:
            raise ValueError("owner declaration must affirm offline execution")
        if not self.local_only_execution_declared:
            raise ValueError("owner declaration must affirm local-only execution")
        if self.owner_id == self.accountable_reviewer_id:
            raise ValueError("owner declaration must separate owner_id and accountable_reviewer_id")
        return self


@dataclass(frozen=True)
class E3DevelopmentWaitingExternal:
    status: E3DevelopmentBundleStatus
    missing_inputs: tuple[str, ...]
    reason: str | None = None


@dataclass(frozen=True)
class E3DevelopmentPreparedBundle:
    status: E3DevelopmentBundleStatus
    bundle_root: Path
    authority_grant: Any
    owner_declaration: _OwnerDeclaration
    dataset_manifest: DatasetManifestV2
    model_manifest: PinnedModelManifest
    decode_policy: DeterministicDecodePolicy
    environment_manifest: ExecutionEnvironmentManifestV1
    policy_input_file_hashes: dict[str, str]
    bundle_manifest_hashes: dict[str, str]


@dataclass(frozen=True)
class E3DevelopmentMaterialBundle:
    bundle_root: Path
    owner_declaration: _OwnerDeclaration
    dataset_manifest: DatasetManifestV2
    model_manifest: PinnedModelManifest
    decode_policy: DeterministicDecodePolicy
    environment_manifest: ExecutionEnvironmentManifestV1
    policy_input_file_hashes: dict[str, str]
    bundle_manifest_hashes: dict[str, str]
    bundle_manifest_sha256: str


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else (Path.cwd() / path)
    probe = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise E3DevelopmentBundleError(f"{label} may not be a symlink")


def _require_external_directory(path: Path, *, label: str) -> Path:
    _assert_no_symlink_components(path, label=label)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise error
    if not resolved.is_dir():
        raise E3DevelopmentBundleError(f"{label} must be a directory")
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise E3DevelopmentBundleError(f"{label} must live outside the repository")


def _require_external_file(path: Path, *, label: str) -> Path:
    _assert_no_symlink_components(path, label=label)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise error
    if not resolved.is_file():
        raise E3DevelopmentBundleError(f"{label} must be a file")
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise E3DevelopmentBundleError(f"{label} must live outside the repository")


def _safe_relative_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise E3DevelopmentBundleError(f"{label} must not be blank")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise E3DevelopmentBundleError(f"{label} must be a safe relative path")
    return pure.as_posix()


def _resolve_bundle_member(bundle_root: Path, relative_path: str, *, label: str) -> Path:
    normalized = _safe_relative_path(relative_path, label=label)
    candidate = bundle_root / PurePosixPath(normalized)
    _assert_no_symlink_components(candidate, label=label)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise E3DevelopmentBundleError(f"{label} is missing: {normalized}") from error
    try:
        resolved.relative_to(bundle_root)
    except ValueError as error:
        raise E3DevelopmentBundleError(f"{label} escapes bundle root") from error
    if resolved.is_symlink():
        raise E3DevelopmentBundleError(f"{label} may not be a symlink")
    return resolved


def _read_canonical_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    _assert_no_symlink_components(path, label=label)
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise E3DevelopmentBundleError(f"{label} must be valid JSON") from error
    if not isinstance(payload, dict):
        raise E3DevelopmentBundleError(f"{label} must be a JSON object")
    if raw != _canonical_json_bytes(payload):
        raise E3DevelopmentBundleError(f"{label} must use canonical JSON serialization")
    return payload, raw


def _read_bundle_json(bundle_root: Path, relative_path: str, *, label: str) -> tuple[dict[str, Any], Path, bytes]:
    path = _resolve_bundle_member(bundle_root, relative_path, label=label)
    payload, raw = _read_canonical_json(path, label=label)
    return payload, path, raw


def _load_verify_authority():
    module_name = "_poi_mpp_verify_e3_authority_runtime"
    module = sys.modules.get(module_name)
    if module is None:
        spec = importlib.util.spec_from_file_location(module_name, _AUTHORITY_VERIFIER)
        if spec is None or spec.loader is None:
            raise E3DevelopmentBundleError("canonical authority verifier is unavailable")
        module = importlib.util.module_from_spec(spec)
        scripts_root = str(_AUTHORITY_VERIFIER.parent)
        inserted = False
        if scripts_root not in sys.path:
            sys.path.insert(0, scripts_root)
            inserted = True
        try:
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        finally:
            if inserted:
                sys.path.pop(0)
    verify = getattr(module, "verify_authority", None)
    if verify is None:
        raise E3DevelopmentBundleError("canonical authority verifier is unavailable")
    return verify


def _parse_file_hash_listing(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise E3DevelopmentBundleError("model/file_hashes.sha256 is unreadable") from error
    if not lines:
        raise E3DevelopmentBundleError("model/file_hashes.sha256 must not be empty")
    for line in lines:
        if not line.strip():
            continue
        try:
            digest_value, relative_path = line.split(None, 1)
        except ValueError as error:
            raise E3DevelopmentBundleError("model/file_hashes.sha256 contains an invalid row") from error
        normalized_path = _safe_relative_path(relative_path.strip(), label="model file hash path")
        if len(digest_value) != 64 or any(ch not in _SHA256 for ch in digest_value):
            raise E3DevelopmentBundleError("model/file_hashes.sha256 contains an invalid digest")
        if normalized_path in entries:
            raise E3DevelopmentBundleError("model/file_hashes.sha256 must not contain duplicate paths")
        entries[normalized_path] = digest_value
    return entries


def _require_manifest_hash_closure(bundle_root: Path) -> dict[str, str]:
    payload, _, _ = _read_bundle_json(bundle_root, "manifest.json", label="manifest.json")
    try:
        manifest = _BundleManifest.model_validate(payload)
    except ValidationError as error:
        raise E3DevelopmentBundleError(f"manifest.json schema validation failed: {error}") from error
    actual_files: dict[str, str] = {}
    for path in sorted(bundle_root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(bundle_root).as_posix()
        if path.is_symlink():
            raise E3DevelopmentBundleError(f"{relative_path} may not be a symlink")
        _assert_no_symlink_components(path, label=relative_path)
        actual_files[relative_path] = _sha256_path(path)
    actual_files.pop("manifest.json", None)
    manifest_files = {entry.path: entry.sha256 for entry in manifest.files}
    unknown = sorted(set(manifest_files) - set(actual_files))
    if unknown:
        raise E3DevelopmentBundleError(f"manifest.json contains unknown path: {unknown[0]}")
    missing = sorted(set(actual_files) - set(manifest_files))
    if missing:
        raise E3DevelopmentBundleError(f"manifest.json is missing path: {missing[0]}")
    for relative_path, expected_hash in manifest_files.items():
        actual_hash = actual_files[relative_path]
        if actual_hash != expected_hash:
            raise E3DevelopmentBundleError(f"manifest.json hash mismatch for {relative_path}")
    return manifest_files


def _bundle_manifest_sha256(bundle_root: Path) -> str:
    return _sha256_path(_resolve_bundle_member(bundle_root, "manifest.json", label="manifest.json"))


def _require_required_bundle_members(bundle_root: Path, manifest_paths: set[str]) -> None:
    effective_paths = set(manifest_paths)
    effective_paths.add("manifest.json")
    missing = sorted(_PREEXEC_STATIC_FILES - effective_paths)
    if missing:
        raise E3DevelopmentBundleError(f"required pre-execution bundle member is missing: {missing[0]}")
    annotations_dir = _resolve_bundle_member(bundle_root, "dataset/annotations", label="dataset/annotations")
    if not annotations_dir.is_dir():
        raise E3DevelopmentBundleError("dataset/annotations must be a directory")
    annotation_files = [path for path in annotations_dir.rglob("*") if path.is_file()]
    if not annotation_files:
        raise E3DevelopmentBundleError("dataset/annotations must contain at least one file")


def _require_authority(
    *,
    request_manifest_path: Path,
    authority_record_path: Path,
    allowed_signers_path: Path,
    signature_path: Path,
) -> Any:
    _require_external_file(authority_record_path, label="authority record")
    allowed_signers = _require_external_file(allowed_signers_path, label="allowed-signers file")
    signature = _require_external_file(signature_path, label="detached signature")
    verify_authority = _load_verify_authority()
    try:
        grant = verify_authority(
            request_manifest_path,
            authority_record_path,
            allowed_signers_path=allowed_signers,
            signature_path=signature,
        )
    except Exception as error:  # pragma: no cover - canonical verifier owns exact error types
        raise E3DevelopmentBundleError(str(error)) from error
    if grant.experiment_id != "E3" or grant.claim_id != "C3":
        raise E3DevelopmentBundleError("authority grant does not match E3/C3 scope")
    if grant.evidence_origin != "REAL_MODEL_EXECUTION":
        raise E3DevelopmentBundleError("authority grant must require REAL_MODEL_EXECUTION")
    return grant


def _require_dataset_contract(bundle_root: Path) -> DatasetManifestV2:
    payload, _, _ = _read_bundle_json(
        bundle_root,
        "dataset/dataset_manifest_v2.json",
        label="dataset/dataset_manifest_v2.json",
    )
    try:
        manifest = DatasetManifestV2.model_validate(payload)
    except ValidationError as error:
        raise E3DevelopmentBundleError(f"dataset manifest validation failed: {error}") from error
    if manifest.split.value != "DEVELOPMENT":
        raise E3DevelopmentBundleError("dataset manifest must use DEVELOPMENT split")
    counts = manifest.decision_counts()
    if counts["ACCEPT"] != 50:
        raise E3DevelopmentBundleError("development dataset requires exactly 50 ACCEPT records")
    if counts["REJECT"] != 50:
        raise E3DevelopmentBundleError("development dataset requires exactly 50 REJECT records")
    if counts["ABSTAIN"] < 20 or counts["ABSTAIN"] > 50:
        raise E3DevelopmentBundleError("development dataset requires 20-50 ABSTAIN records")
    if len(manifest.records) < 120 or len(manifest.records) > 150:
        raise E3DevelopmentBundleError("development dataset requires 120-150 total records")
    if any(record.evidence_origin.value != "REAL_MODEL_EXECUTION" for record in manifest.records):
        raise E3DevelopmentBundleError(
            "development dataset observations must remain REAL_MODEL_EXECUTION; synthetic non-evidence cannot enter development"
        )
    dataset_root = _resolve_bundle_member(bundle_root, "dataset", label="dataset")
    manifest.verify_rooted_file_hashes(dataset_root)
    return manifest


def _require_model_contract(bundle_root: Path) -> tuple[PinnedModelManifest, DeterministicDecodePolicy, dict[str, str]]:
    policy_payload, policy_path, policy_raw = _read_bundle_json(
        bundle_root,
        "execution/deterministic_decode_policy.json",
        label="execution/deterministic_decode_policy.json",
    )
    manifest_payload, manifest_path, manifest_raw = _read_bundle_json(
        bundle_root,
        "model/pinned_model_manifest.json",
        label="model/pinned_model_manifest.json",
    )
    try:
        decode_policy = DeterministicDecodePolicy.model_validate(policy_payload)
    except ValidationError as error:
        raise E3DevelopmentBundleError(f"decode policy validation failed: {error}") from error
    try:
        model_manifest = PinnedModelManifest.model_validate(manifest_payload)
    except ValidationError as error:
        raise E3DevelopmentBundleError(f"model manifest validation failed: {error}") from error
    if model_manifest.parameter_scale not in _PRIMARY_MODEL_SCALES:
        raise E3DevelopmentBundleError("primary E3-v2 development model must stay within 1B-3B")
    if model_manifest.quantization != "none":
        raise E3DevelopmentBundleError("primary E3-v2 development model must remain unquantized")
    if not any(name.endswith(".safetensors") for name in model_manifest.model_file_hashes):
        raise E3DevelopmentBundleError("pinned model manifest must include safetensors weights")
    forbidden = [
        name
        for name in model_manifest.model_file_hashes
        if name.lower().endswith(_FORBIDDEN_WEIGHT_SUFFIXES)
    ]
    if forbidden:
        raise E3DevelopmentBundleError("alternate model weight formats are forbidden")
    hash_listing = _parse_file_hash_listing(
        _resolve_bundle_member(bundle_root, "model/file_hashes.sha256", label="model/file_hashes.sha256")
    )
    expected_listing = dict(model_manifest.model_file_hashes)
    for filename, digest_value in model_manifest.tokenizer_file_hashes.items():
        existing = expected_listing.get(filename)
        if existing is not None and existing != digest_value:
            raise E3DevelopmentBundleError("model and tokenizer file hash listings disagree")
        expected_listing[filename] = digest_value
    if hash_listing != expected_listing:
        raise E3DevelopmentBundleError("model/file_hashes.sha256 does not close the pinned model manifest")
    return model_manifest, decode_policy, {
        "model_manifest_file_hash": _sha256_path(manifest_path),
        "deterministic_decode_policy_file_hash": _sha256_path(policy_path),
        "model_manifest_hash": model_manifest.manifest_hash(decode_policy).removeprefix("0x"),
        "deterministic_decode_policy_hash": hashlib.sha256(policy_raw).hexdigest(),
        "model_manifest_raw_hash": hashlib.sha256(manifest_raw).hexdigest(),
    }


def _require_environment_contract(
    bundle_root: Path,
    *,
    model_manifest: PinnedModelManifest,
    decode_policy: DeterministicDecodePolicy,
) -> tuple[ExecutionEnvironmentManifestV1, dict[str, str]]:
    payload, path, raw = _read_bundle_json(
        bundle_root,
        "execution/environment_manifest.json",
        label="execution/environment_manifest.json",
    )
    try:
        environment_manifest = ExecutionEnvironmentManifestV1.model_validate(payload)
    except ValidationError as error:
        raise E3DevelopmentBundleError(f"environment manifest validation failed: {error}") from error
    if environment_manifest.model.parameter_count_billions > 3.0:
        raise E3DevelopmentBundleError("primary E3-v2 development model must stay within 1B-3B")
    if environment_manifest.model.model_revision != model_manifest.revision:
        raise E3DevelopmentBundleError("environment manifest model revision does not match pinned model manifest")
    if environment_manifest.model.tokenizer_revision != model_manifest.tokenizer_revision:
        raise E3DevelopmentBundleError("environment manifest tokenizer revision does not match pinned model manifest")
    if environment_manifest.model.model_id != model_manifest.model_id:
        raise E3DevelopmentBundleError("environment manifest model_id does not match pinned model manifest")
    if environment_manifest.model.tokenizer_id != model_manifest.tokenizer_id:
        raise E3DevelopmentBundleError("environment manifest tokenizer_id does not match pinned model manifest")
    if environment_manifest.deterministic.global_seed != decode_policy.seed:
        raise E3DevelopmentBundleError("environment manifest global_seed must match the deterministic decode seed")
    if environment_manifest.deterministic.inference_seed != decode_policy.seed:
        raise E3DevelopmentBundleError("environment manifest inference_seed must match the deterministic decode seed")
    if environment_manifest.generation.max_new_tokens != decode_policy.max_new_tokens:
        raise E3DevelopmentBundleError("environment manifest max_new_tokens must match the deterministic decode policy")
    return environment_manifest, {
        "runtime_environment_hash": environment_manifest.environment_manifest_hash(),
        "environment_manifest_file_hash": hashlib.sha256(raw).hexdigest(),
        "environment_manifest_hash": _sha256_path(path),
    }


def _require_owner_declaration(bundle_root: Path) -> tuple[_OwnerDeclaration, str]:
    payload, path, raw = _read_bundle_json(
        bundle_root,
        "owner_declaration.json",
        label="owner_declaration.json",
    )
    try:
        declaration = _OwnerDeclaration.model_validate(payload)
    except ValidationError as error:
        raise E3DevelopmentBundleError(f"owner declaration validation failed: {error}") from error
    return declaration, hashlib.sha256(raw).hexdigest()


def _collect_policy_file_hashes(bundle_root: Path) -> dict[str, str]:
    labels = {
        "claim_spec_hash": "policy/claim_spec.json",
        "prompt_template_hash": "policy/prompt_template.txt",
        "output_schema_hash": "policy/output_schema.json",
        "contradiction_policy_hash": "policy/contradiction_policy.json",
        "error_recovery_policy_hash": "policy/error_recovery_policy.json",
        "error_taxonomy_review_hash": "policy/error_taxonomy_review.json",
    }
    return {
        key: _sha256_path(_resolve_bundle_member(bundle_root, relative_path, label=relative_path))
        for key, relative_path in labels.items()
    }


def validate_e3_phase3_development_bundle_materials(
    *,
    bundle_root: Path | str,
) -> E3DevelopmentMaterialBundle:
    """Validate pre-authority bundle materials without attempting external trust checks."""

    resolved_bundle_root = _require_external_directory(Path(bundle_root), label="bundle root")
    manifest_hashes = _require_manifest_hash_closure(resolved_bundle_root)
    _require_required_bundle_members(resolved_bundle_root, set(manifest_hashes))
    owner_declaration, owner_hash = _require_owner_declaration(resolved_bundle_root)
    model_manifest, decode_policy, model_hashes = _require_model_contract(resolved_bundle_root)
    environment_manifest, environment_hashes = _require_environment_contract(
        resolved_bundle_root,
        model_manifest=model_manifest,
        decode_policy=decode_policy,
    )
    dataset_manifest = _require_dataset_contract(resolved_bundle_root)
    policy_hashes = _collect_policy_file_hashes(resolved_bundle_root)
    policy_hashes.update(model_hashes)
    policy_hashes.update(environment_hashes)
    policy_hashes["owner_declaration_hash"] = owner_hash
    return E3DevelopmentMaterialBundle(
        bundle_root=resolved_bundle_root,
        owner_declaration=owner_declaration,
        dataset_manifest=dataset_manifest,
        model_manifest=model_manifest,
        decode_policy=decode_policy,
        environment_manifest=environment_manifest,
        policy_input_file_hashes=policy_hashes,
        bundle_manifest_hashes=manifest_hashes,
        bundle_manifest_sha256=_bundle_manifest_sha256(resolved_bundle_root),
    )


def _authority_binds_development_bundle(
    *,
    authority_grant: Any,
    material_bundle: E3DevelopmentMaterialBundle,
) -> bool:
    policy_binding_keys = (
        "claim_spec_hash",
        "prompt_template_hash",
        "output_schema_hash",
        "contradiction_policy_hash",
        "error_recovery_policy_hash",
        "error_taxonomy_review_hash",
    )
    policy_bindings = {
        key: material_bundle.policy_input_file_hashes[key]
        for key in policy_binding_keys
    }
    expected_bindings = {
        "development_bundle_manifest_sha256": material_bundle.bundle_manifest_sha256,
        "development_dataset_manifest_hash": material_bundle.dataset_manifest.dataset_manifest_hash(),
        "development_model_manifest_hash": material_bundle.policy_input_file_hashes["model_manifest_hash"],
        "development_decode_policy_hash": material_bundle.policy_input_file_hashes[
            "deterministic_decode_policy_hash"
        ],
        "development_environment_manifest_hash": material_bundle.policy_input_file_hashes[
            "runtime_environment_hash"
        ],
        "development_policy_inputs_digest": hashlib.sha256(
            _canonical_json_bytes(policy_bindings)
        ).hexdigest(),
    }
    for field_name, expected_value in expected_bindings.items():
        if getattr(authority_grant, field_name, None) != expected_value:
            return False
    return True


def prepare_e3_phase3_development_bundle(
    *,
    bundle_root: Path | str,
    request_manifest_path: Path | str,
    authority_record_path: Path | str | None,
    allowed_signers_path: Path | str | None,
    signature_path: Path | str | None,
) -> E3DevelopmentWaitingExternal | E3DevelopmentPreparedBundle:
    """Validate the external Phase-3 bundle and return a READY/WAITING disposition."""

    missing: list[str] = []
    bundle_root_path = Path(bundle_root)
    request_manifest = Path(request_manifest_path)
    authority_record = None if authority_record_path is None else Path(authority_record_path)
    allowed_signers = None if allowed_signers_path is None else Path(allowed_signers_path)
    signature = None if signature_path is None else Path(signature_path)

    if not bundle_root_path.exists():
        missing.append("bundle_root")
    if authority_record is None or not authority_record.exists():
        missing.append("authority_record")
    if allowed_signers is None or not allowed_signers.exists():
        missing.append("allowed_signers")
    if signature is None or not signature.exists():
        missing.append("signature")
    if missing:
        return E3DevelopmentWaitingExternal(
            status=E3DevelopmentBundleStatus.WAITING_EXTERNAL,
            missing_inputs=tuple(missing),
            reason="missing_external_inputs",
        )

    try:
        material_bundle = validate_e3_phase3_development_bundle_materials(bundle_root=bundle_root_path)
    except FileNotFoundError:
        return E3DevelopmentWaitingExternal(
            status=E3DevelopmentBundleStatus.WAITING_EXTERNAL,
            missing_inputs=("bundle_root",),
            reason="missing_external_inputs",
        )

    grant = _require_authority(
        request_manifest_path=request_manifest,
        authority_record_path=authority_record,
        allowed_signers_path=allowed_signers,
        signature_path=signature,
    )
    if getattr(grant, "decision", None) == "LIMITED_SCOPE":
        return E3DevelopmentWaitingExternal(
            status=E3DevelopmentBundleStatus.WAITING_EXTERNAL,
            missing_inputs=(),
            reason="limited_scope_runner_not_implemented",
        )
    if getattr(grant, "decision", None) != "APPROVED":
        raise E3DevelopmentBundleError("authority decision must be APPROVED or LIMITED_SCOPE")
    if not _authority_binds_development_bundle(
        authority_grant=grant,
        material_bundle=material_bundle,
    ):
        return E3DevelopmentWaitingExternal(
            status=E3DevelopmentBundleStatus.WAITING_EXTERNAL,
            missing_inputs=(),
            reason="authority_request_does_not_bind_development_bundle",
        )

    return E3DevelopmentPreparedBundle(
        status=E3DevelopmentBundleStatus.READY_FOR_EXECUTION,
        bundle_root=material_bundle.bundle_root,
        authority_grant=grant,
        owner_declaration=material_bundle.owner_declaration,
        dataset_manifest=material_bundle.dataset_manifest,
        model_manifest=material_bundle.model_manifest,
        decode_policy=material_bundle.decode_policy,
        environment_manifest=material_bundle.environment_manifest,
        policy_input_file_hashes=material_bundle.policy_input_file_hashes,
        bundle_manifest_hashes=material_bundle.bundle_manifest_hashes,
    )
