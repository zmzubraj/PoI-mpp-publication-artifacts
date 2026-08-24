#!/usr/bin/env python3
"""Verify an externally signed, post-execution E3 result attestation.

This verifier authenticates a completed evaluator attestation and its exact
hash-bound artifacts. It never assigns publication support to claim C3.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
from typing import Any, Literal
import zipfile
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from build_e3_authority_request import REPO_ROOT
from verify_e3_authority import AuthorityRecord, AuthorityVerificationError, verify_authority


REQUIRED_ARTIFACT_IDS = frozenset({"T4", "T8", "F7", "RAW_E3_EXECUTION"})
REQUIRED_METRICS = frozenset({"FAR", "FRR", "ABSTAIN", "coverage", "calibration"})
ARTIFACT_CONTRACTS = {
    "T4": ("DATASET_COMPOSITION", "publication/tables/T4_dataset_composition.json"),
    "T8": ("SEMANTIC_METRICS", "publication/tables/T8_semantic_verification.csv"),
    "F7": ("SEMANTIC_QUALITY_FIGURE", "publication/figures/F7_semantic_verification_quality.svg"),
}
RAW_MEMBER_PATHS = {
    "model_hash": "model_manifest.json",
    "config_hash": "config.json",
    "input_hash": "inputs.jsonl",
    "output_hash": "outputs.jsonl",
    "trace_hash": "trace.jsonl",
    "provenance_hash": "provenance.json",
}
MAX_RAW_ZIP_MEMBERS = 64
MAX_RAW_ZIP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
FORBIDDEN_EVIDENCE_MARKERS = (
    b"WAITING_EXTERNAL",
    b"SYNTHETIC_NON_EVIDENCE",
    b'"origin": null',
)


class ResultAttestationVerificationError(ValueError):
    pass


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _safe_relative_path(value: str) -> str:
    if "\\" in value:
        raise ValueError("path must use safe POSIX separators")
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
        raise ValueError("path must be a normalized safe relative path")
    return value


def _strict_iso_date(value: str) -> str:
    if len(value) != 10:
        raise ValueError("date must use strict ISO YYYY-MM-DD format")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("date must use strict ISO YYYY-MM-DD format") from error
    if parsed.isoformat() != value:
        raise ValueError("date must use strict ISO YYYY-MM-DD format")
    return value


class FileReference(_FrozenModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("path")
    @classmethod
    def _path_is_safe(cls, value: str) -> str:
        return _safe_relative_path(value)


class RequestManifestReference(FileReference):
    self_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ExecutionBindings(_FrozenModel):
    model_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    trace_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    provenance_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    pre_execution_authority_record_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ResultScope(_FrozenModel):
    experiment_id: Literal["E3"]
    claim_id: Literal["C3"]
    task_class: Literal["GROUNDED_SEMANTIC_ASSURANCE"]
    run_id: str = Field(min_length=1)
    evidence_origin: Literal["REAL_MODEL_EXECUTION"]
    metric_scope: tuple[Literal["FAR", "FRR", "ABSTAIN", "coverage", "calibration"], ...]
    artifact_scope: tuple[Literal["T4", "T8", "F7", "RAW_E3_EXECUTION"], ...]
    execution_bindings: ExecutionBindings

    @field_validator("run_id")
    @classmethod
    def _run_id_is_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run_id must not be blank")
        return value

    @field_validator("metric_scope", "artifact_scope")
    @classmethod
    def _scope_is_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("scope must be non-empty and contain unique values")
        return value


class ResultArtifact(_FrozenModel):
    artifact_id: Literal["T4", "T8", "F7", "RAW_E3_EXECUTION"]
    artifact_role: Literal[
        "DATASET_COMPOSITION",
        "SEMANTIC_METRICS",
        "SEMANTIC_QUALITY_FIGURE",
        "RAW_EXECUTION_BUNDLE",
    ]
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)
    experiment_id: Literal["E3"]
    claim_id: Literal["C3"]
    run_id: str = Field(min_length=1)
    evidence_origin: Literal["REAL_MODEL_EXECUTION"]

    @field_validator("path")
    @classmethod
    def _path_is_safe(cls, value: str) -> str:
        return _safe_relative_path(value)

    @field_validator("run_id")
    @classmethod
    def _run_id_is_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run_id must not be blank")
        return value


class ResultAttestationRecord(_FrozenModel):
    schema_version: Literal["POI_MPP_E3_RESULT_ATTESTATION_V1"]
    record_type: Literal["POST_EXECUTION_RESULT_ATTESTATION"]
    authority_identity: str = Field(min_length=1)
    authority_basis: str = Field(min_length=1)
    expertise_scope: str = Field(min_length=1)
    pre_execution_authority_record: FileReference
    reviewed_request_manifest: RequestManifestReference
    result_scope: ResultScope
    artifacts: tuple[ResultArtifact, ...] = Field(min_length=1, max_length=4)
    results_disposition: Literal["ATTESTED_AS_REPORTED", "QUALIFIED", "REJECTED"]
    attestation_notes: str = Field(min_length=1)
    attestation_date: str
    publication_support_decision_status: Literal["NOT_EVALUATED_BY_THIS_ATTESTATION"]
    external_signature_required: Literal[True]
    signature_namespace: Literal["file"]
    signature_reference: str = Field(min_length=1)
    allowed_signers_reference: str = Field(min_length=1)

    @field_validator(
        "authority_identity",
        "authority_basis",
        "expertise_scope",
        "attestation_notes",
        "signature_reference",
        "allowed_signers_reference",
    )
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value

    @field_validator("attestation_date")
    @classmethod
    def _date_is_strict_iso(cls, value: str) -> str:
        return _strict_iso_date(value)


class _TypedArtifactBase(_FrozenModel):
    artifact_role: str
    experiment_id: Literal["E3"]
    claim_id: Literal["C3"]
    run_id: str = Field(min_length=1)
    evidence_origin: Literal["REAL_MODEL_EXECUTION"]
    execution_bindings: ExecutionBindings


class T4Artifact(_TypedArtifactBase):
    schema_version: Literal["POI_MPP_E3_T4_V1"]
    artifact_role: Literal["DATASET_COMPOSITION"]
    record_count: int = Field(gt=0)
    class_counts: dict[str, int]

    @model_validator(mode="after")
    def _counts_close(self) -> "T4Artifact":
        if not self.class_counts or any(value < 0 for value in self.class_counts.values()):
            raise ValueError("class_counts must be non-empty and non-negative")
        if sum(self.class_counts.values()) != self.record_count:
            raise ValueError("class_counts must sum to record_count")
        return self


class F7Metadata(_TypedArtifactBase):
    schema_version: Literal["POI_MPP_E3_F7_METADATA_V1"]
    artifact_role: Literal["SEMANTIC_QUALITY_FIGURE"]
    metric_scope: tuple[Literal["FAR", "FRR", "ABSTAIN", "coverage", "calibration"], ...]
    source_t8_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class RawFileReference(_FrozenModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)

    @field_validator("path")
    @classmethod
    def _path_is_safe(cls, value: str) -> str:
        return _safe_relative_path(value)


class RawRunManifest(_TypedArtifactBase):
    schema_version: Literal["POI_MPP_E3_RAW_EXECUTION_V1"]
    artifact_role: Literal["RAW_EXECUTION_BUNDLE"]
    metric_scope: tuple[Literal["FAR", "FRR", "ABSTAIN", "coverage", "calibration"], ...]
    files: dict[str, RawFileReference]


def _read_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise ResultAttestationVerificationError(f"{label} may not be a symlink")
    try:
        raw = path.resolve(strict=True).read_bytes()
    except (FileNotFoundError, OSError) as error:
        raise ResultAttestationVerificationError(f"{label} is missing or unreadable: {path}") from error
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ResultAttestationVerificationError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ResultAttestationVerificationError(f"{label} must be a JSON object")
    return payload, raw


def _external_file(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ResultAttestationVerificationError(f"{label} may not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise ResultAttestationVerificationError(f"{label} is missing: {path}") from error
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise ResultAttestationVerificationError(f"{label} must live outside the repository")
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise ResultAttestationVerificationError(f"{label} must be a non-empty file")
    return resolved


def _accepted_reference_paths(path: Path) -> set[str]:
    accepted = {path.name}
    try:
        accepted.add(path.resolve(strict=True).relative_to(REPO_ROOT.resolve(strict=True)).as_posix())
    except ValueError:
        pass
    return accepted


def _artifact_file(root: Path, artifact: ResultArtifact) -> tuple[Path, bytes]:
    relative = PurePosixPath(artifact.path)
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ResultAttestationVerificationError(f"artifact {artifact.artifact_id} may not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as error:
        raise ResultAttestationVerificationError(
            f"artifact {artifact.artifact_id} is missing or escapes artifact root"
        ) from error
    if not resolved.is_file():
        raise ResultAttestationVerificationError(f"artifact {artifact.artifact_id} must be a regular file")
    payload = resolved.read_bytes()
    if len(payload) != artifact.size_bytes:
        raise ResultAttestationVerificationError(f"artifact {artifact.artifact_id} size mismatch")
    if hashlib.sha256(payload).hexdigest() != artifact.sha256:
        raise ResultAttestationVerificationError(f"artifact {artifact.artifact_id} sha256 mismatch")
    return resolved, payload


def _reject_non_evidence_markers(artifact_id: str, payload: bytes) -> None:
    for marker in FORBIDDEN_EVIDENCE_MARKERS:
        if marker in payload:
            raise ResultAttestationVerificationError(
                f"artifact {artifact_id} contains a placeholder or non-evidence marker"
            )


def _bindings_dict(bindings: ExecutionBindings) -> dict[str, str]:
    return {key: str(value) for key, value in bindings.model_dump().items()}


def _validate_typed_base(
    artifact: _TypedArtifactBase,
    *,
    scope: ResultScope,
    label: str,
) -> None:
    if artifact.run_id != scope.run_id:
        raise ResultAttestationVerificationError(f"{label} run_id does not match result scope")
    if artifact.experiment_id != "E3" or artifact.claim_id != "C3":
        raise ResultAttestationVerificationError(f"{label} typed contract does not close over E3/C3")
    if artifact.evidence_origin != "REAL_MODEL_EXECUTION":
        raise ResultAttestationVerificationError(
            f"{label} typed contract evidence_origin must be REAL_MODEL_EXECUTION"
        )
    if artifact.execution_bindings != scope.execution_bindings:
        raise ResultAttestationVerificationError(f"{label} execution bindings do not match result scope")


def _validate_t4(payload: bytes, *, scope: ResultScope) -> None:
    try:
        value = json.loads(payload)
        artifact = T4Artifact.model_validate(value)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError) as error:
        raise ResultAttestationVerificationError(f"T4 typed JSON contract validation failed: {error}") from error
    _validate_typed_base(artifact, scope=scope, label="T4")


def _validate_t8(payload: bytes, *, scope: ResultScope) -> None:
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
        *_bindings_dict(scope.execution_bindings).keys(),
    }
    try:
        text = payload.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames is None or set(reader.fieldnames) != required_fields:
            raise ValueError("CSV columns do not match the typed T8 contract")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error, ValueError) as error:
        raise ResultAttestationVerificationError(f"T8 typed CSV contract validation failed: {error}") from error
    if not rows:
        raise ResultAttestationVerificationError("T8 typed CSV contract requires at least one metric row")
    expected_bindings = _bindings_dict(scope.execution_bindings)
    metrics: list[str] = []
    for row in rows:
        fixed = {
            "schema_version": "POI_MPP_E3_T8_V1",
            "artifact_role": "SEMANTIC_METRICS",
            "experiment_id": "E3",
            "claim_id": "C3",
            "run_id": scope.run_id,
            "evidence_origin": "REAL_MODEL_EXECUTION",
        }
        if any(row[key] != expected for key, expected in fixed.items()):
            raise ResultAttestationVerificationError("T8 typed CSV scope fields do not match E3/C3/run")
        if any(row[key] != expected for key, expected in expected_bindings.items()):
            raise ResultAttestationVerificationError("T8 execution bindings do not match result scope")
        metric = row["metric"]
        if metric not in REQUIRED_METRICS:
            raise ResultAttestationVerificationError(f"T8 contains unsupported metric: {metric}")
        try:
            value = Decimal(row["value"])
            sample_count = int(row["sample_count"])
        except (InvalidOperation, ValueError) as error:
            raise ResultAttestationVerificationError("T8 metric value/sample_count is invalid") from error
        if not value.is_finite() or value < 0 or value > 1 or sample_count <= 0:
            raise ResultAttestationVerificationError("T8 metric value/sample_count is outside contract bounds")
        metrics.append(metric)
    if len(metrics) != len(set(metrics)) or set(metrics) != set(scope.metric_scope):
        raise ResultAttestationVerificationError("T8 metric rows must exactly match result metric scope")


def _validate_f7(
    payload: bytes,
    *,
    scope: ResultScope,
    t8_sha256: str | None,
) -> None:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise ResultAttestationVerificationError(f"F7 typed SVG contract validation failed: {error}") from error
    metadata_nodes = [
        node
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "metadata" and node.attrib.get("id") == "poi-e3-attestation"
    ]
    if len(metadata_nodes) != 1 or not metadata_nodes[0].text:
        raise ResultAttestationVerificationError(
            "F7 typed SVG contract requires exactly one poi-e3-attestation metadata element"
        )
    try:
        metadata = F7Metadata.model_validate(json.loads(metadata_nodes[0].text))
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise ResultAttestationVerificationError(f"F7 typed SVG metadata validation failed: {error}") from error
    _validate_typed_base(metadata, scope=scope, label="F7")
    if len(metadata.metric_scope) != len(set(metadata.metric_scope)) or set(metadata.metric_scope) != set(
        scope.metric_scope
    ):
        raise ResultAttestationVerificationError("F7 metric scope does not match result scope")
    if t8_sha256 is None or metadata.source_t8_sha256 != t8_sha256:
        raise ResultAttestationVerificationError("F7 source_t8_sha256 must bind the attested T8 artifact")


def _validate_zip_bundle(path: Path, *, scope: ResultScope) -> None:
    if not zipfile.is_zipfile(path):
        raise ResultAttestationVerificationError("RAW_E3_EXECUTION must be a valid ZIP bundle")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_RAW_ZIP_MEMBERS:
            raise ResultAttestationVerificationError(
                f"RAW_E3_EXECUTION exceeds {MAX_RAW_ZIP_MEMBERS}-member ceiling"
            )
        uncompressed_bytes = sum(info.file_size for info in infos)
        if uncompressed_bytes > MAX_RAW_ZIP_UNCOMPRESSED_BYTES:
            raise ResultAttestationVerificationError(
                "RAW_E3_EXECUTION exceeds "
                f"{MAX_RAW_ZIP_UNCOMPRESSED_BYTES}-byte uncompressed ceiling"
            )
        member_names: list[str] = []
        for info in infos:
            member = PurePosixPath(info.filename)
            if (
                member.is_absolute()
                or ".." in member.parts
                or member.as_posix() != info.filename
                or "\\" in info.filename
            ):
                raise ResultAttestationVerificationError("RAW_E3_EXECUTION contains an unsafe archive path")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ResultAttestationVerificationError("RAW_E3_EXECUTION may not contain symlinks")
            if info.is_dir():
                continue
            member_names.append(info.filename)
        if len(member_names) != len(set(member_names)):
            raise ResultAttestationVerificationError("RAW_E3_EXECUTION contains duplicate member paths")
        required_members = {"run_manifest.json", *RAW_MEMBER_PATHS.values()}
        if set(member_names) != required_members:
            raise ResultAttestationVerificationError(
                "RAW_E3_EXECUTION member set must exactly match the typed raw contract"
            )
        for member_name in member_names:
            _reject_non_evidence_markers("RAW_E3_EXECUTION", archive.read(member_name))
        try:
            manifest = RawRunManifest.model_validate(json.loads(archive.read("run_manifest.json")))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError) as error:
            raise ResultAttestationVerificationError(
                f"RAW typed run_manifest contract validation failed: {error}"
            ) from error
        _validate_typed_base(manifest, scope=scope, label="RAW")
        if len(manifest.metric_scope) != len(set(manifest.metric_scope)) or set(manifest.metric_scope) != set(
            scope.metric_scope
        ):
            raise ResultAttestationVerificationError("RAW metric scope does not match result scope")
        if set(manifest.files) != set(RAW_MEMBER_PATHS):
            raise ResultAttestationVerificationError("RAW files map must bind all six execution inputs/outputs")
        bindings = _bindings_dict(scope.execution_bindings)
        for logical_name, expected_path in RAW_MEMBER_PATHS.items():
            reference = manifest.files[logical_name]
            if reference.path != expected_path:
                raise ResultAttestationVerificationError(
                    f"RAW {logical_name} path does not match typed contract"
                )
            actual = archive.read(expected_path)
            if reference.size_bytes != len(actual):
                raise ResultAttestationVerificationError(
                    f"RAW {logical_name} size does not match actual archive member"
                )
            actual_hash = hashlib.sha256(actual).hexdigest()
            if reference.sha256 != actual_hash or bindings[logical_name] != actual_hash:
                raise ResultAttestationVerificationError(
                    f"RAW {logical_name} does not match actual archive member"
                )


def _validate_artifacts(record: ResultAttestationRecord, artifact_root: Path) -> list[dict[str, Any]]:
    ids = [artifact.artifact_id for artifact in record.artifacts]
    if len(ids) != len(set(ids)) or set(ids) != set(record.result_scope.artifact_scope):
        raise ResultAttestationVerificationError(
            "artifact set must be exactly the signed result_scope artifact scope"
        )
    scope = record.result_scope
    paths = [PurePosixPath(artifact.path).as_posix() for artifact in record.artifacts]
    if len(paths) != len(set(paths)):
        raise ResultAttestationVerificationError("artifact paths must be unique after normalization")
    artifacts_by_id = {artifact.artifact_id: artifact for artifact in record.artifacts}
    for artifact in record.artifacts:
        if artifact.artifact_id == "RAW_E3_EXECUTION":
            expected_role = "RAW_EXECUTION_BUNDLE"
            expected_path = f"results/publication/{scope.run_id}/raw_e3_execution.zip"
        else:
            expected_role, expected_path = ARTIFACT_CONTRACTS[artifact.artifact_id]
        if artifact.artifact_role != expected_role or artifact.path != expected_path:
            raise ResultAttestationVerificationError(
                f"artifact {artifact.artifact_id} role/path contract mismatch"
            )
    resolved: dict[str, tuple[Path, bytes]] = {}
    for artifact in record.artifacts:
        resolved[artifact.artifact_id] = _artifact_file(artifact_root, artifact)
        _reject_non_evidence_markers(artifact.artifact_id, resolved[artifact.artifact_id][1])

    if "RAW_E3_EXECUTION" not in resolved or "T8" not in resolved:
        raise ResultAttestationVerificationError(
            "authenticated result scope must include RAW_E3_EXECUTION and T8"
        )
    if "T4" in resolved:
        _validate_t4(resolved["T4"][1], scope=scope)
    _validate_t8(resolved["T8"][1], scope=scope)
    if "F7" in resolved:
        _validate_f7(
            resolved["F7"][1],
            scope=scope,
            t8_sha256=artifacts_by_id["T8"].sha256,
        )
    _validate_zip_bundle(resolved["RAW_E3_EXECUTION"][0], scope=scope)

    verified: list[dict[str, Any]] = []
    for artifact in record.artifacts:
        if artifact.run_id != scope.run_id:
            raise ResultAttestationVerificationError(
                f"artifact {artifact.artifact_id} run_id does not match result scope"
            )
        if artifact.experiment_id != scope.experiment_id or artifact.claim_id != scope.claim_id:
            raise ResultAttestationVerificationError(
                f"artifact {artifact.artifact_id} does not close over E3/C3"
            )
        if artifact.evidence_origin != scope.evidence_origin:
            raise ResultAttestationVerificationError(
                f"artifact {artifact.artifact_id} evidence_origin does not match result scope"
            )
        verified.append(
            {
                "artifact_id": artifact.artifact_id,
                "artifact_role": artifact.artifact_role,
                "path": artifact.path,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
            }
        )
    return sorted(verified, key=lambda item: str(item["artifact_id"]))


def _verify_detached_signature(
    *, record_bytes: bytes, identity: str, signature_path: Path, allowed_signers_path: Path
) -> None:
    signature = _external_file(signature_path, label="result attestation detached signature")
    allowed_signers = _external_file(allowed_signers_path, label="allowed-signers file")
    completed = subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "verify",
            "-f",
            str(allowed_signers),
            "-I",
            identity,
            "-n",
            "file",
            "-s",
            str(signature),
        ],
        input=record_bytes,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).decode("utf-8", errors="replace").strip()
        raise ResultAttestationVerificationError(
            f"external E3 result attestation signature verification failed: {detail or 'unknown failure'}"
        )


def verify_result_attestation(
    *,
    request_path: Path,
    authority_record_path: Path,
    authority_signature_path: Path,
    attestation_record_path: Path,
    attestation_signature_path: Path,
    allowed_signers_path: Path,
    artifact_root_path: Path,
) -> dict[str, Any]:
    try:
        authority_verification = verify_authority(
            request_path,
            authority_record_path,
            allowed_signers_path=allowed_signers_path,
            signature_path=authority_signature_path,
        )
    except AuthorityVerificationError as error:
        raise ResultAttestationVerificationError(f"pre-execution authority verification failed: {error}") from error

    request, request_bytes = _read_json(request_path, label="E3 request manifest")
    authority_payload, authority_bytes = _read_json(authority_record_path, label="E3 authority record")
    try:
        authority = AuthorityRecord.model_validate(authority_payload)
    except ValidationError as error:
        raise ResultAttestationVerificationError(f"E3 authority record schema validation failed: {error}") from error
    attestation_payload, attestation_bytes = _read_json(
        attestation_record_path, label="E3 result attestation record"
    )
    try:
        attestation = ResultAttestationRecord.model_validate(attestation_payload)
    except ValidationError as error:
        locations = {tuple(item["loc"]) for item in error.errors()}
        if ("result_scope", "claim_id") in locations or ("result_scope", "experiment_id") in locations:
            raise ResultAttestationVerificationError("result scope must close exactly over E3/C3") from error
        if any(location and location[-1] == "path" for location in locations):
            raise ResultAttestationVerificationError(
                "artifact path must be a normalized safe relative path"
            ) from error
        if ("artifacts",) in locations:
            raise ResultAttestationVerificationError(
                "artifact set must be exactly F7, RAW_E3_EXECUTION, T4, and T8"
            ) from error
        raise ResultAttestationVerificationError(
            f"E3 result attestation record schema validation failed: {error}"
        ) from error

    if (
        attestation.authority_identity != authority.authority_identity
        or attestation.authority_basis != authority.authority_basis
        or attestation.expertise_scope != authority.expertise_scope
    ):
        raise ResultAttestationVerificationError(
            "result attestation authority identity/basis/expertise does not match verified pre-execution authority"
        )

    authority_reference = attestation.pre_execution_authority_record
    if authority_reference.path not in _accepted_reference_paths(authority_record_path):
        raise ResultAttestationVerificationError("pre-execution authority record path mismatch")
    if authority_reference.sha256 != hashlib.sha256(authority_bytes).hexdigest():
        raise ResultAttestationVerificationError("pre-execution authority record sha256 mismatch")

    request_reference = attestation.reviewed_request_manifest
    if request_reference.path not in _accepted_reference_paths(request_path):
        raise ResultAttestationVerificationError("reviewed request manifest path mismatch")
    if request_reference.sha256 != hashlib.sha256(request_bytes).hexdigest():
        raise ResultAttestationVerificationError("request manifest sha256 mismatch")
    if request_reference.self_digest != request["self_digest"]:
        raise ResultAttestationVerificationError("request manifest self_digest mismatch")

    scope = attestation.result_scope
    if scope.experiment_id != "E3" or scope.claim_id != "C3":
        raise ResultAttestationVerificationError("result scope must close exactly over E3/C3")
    if scope.task_class != request["requested_scope"]["task_class"]:
        raise ResultAttestationVerificationError("result task_class does not match the canonical E3 request")
    if scope.evidence_origin != "REAL_MODEL_EXECUTION":
        raise ResultAttestationVerificationError("result evidence_origin must be REAL_MODEL_EXECUTION")
    canonical_metrics = set(request["requested_scope"]["metric_scope"])
    canonical_artifacts = set(request["requested_scope"]["artifact_scope"])
    if not set(scope.metric_scope).issubset(canonical_metrics) or not set(scope.artifact_scope).issubset(
        canonical_artifacts
    ):
        raise ResultAttestationVerificationError("result scope exceeds the canonical E3 request")
    if set(scope.metric_scope) != set(authority.authorized_scope.metric_scope) or set(
        scope.artifact_scope
    ) != set(authority.authorized_scope.artifact_scope):
        raise ResultAttestationVerificationError(
            "result scope must exactly match signed pre-execution authority subsets"
        )
    authority_sha256 = hashlib.sha256(authority_bytes).hexdigest()
    if scope.execution_bindings.pre_execution_authority_record_sha256 != authority_sha256:
        raise ResultAttestationVerificationError(
            "execution bindings pre_execution_authority_record_sha256 mismatch"
        )

    if artifact_root_path.is_symlink():
        raise ResultAttestationVerificationError("artifact root may not be a symlink")
    try:
        artifact_root = artifact_root_path.resolve(strict=True)
    except FileNotFoundError as error:
        raise ResultAttestationVerificationError("artifact root is missing") from error
    if not artifact_root.is_dir():
        raise ResultAttestationVerificationError("artifact root must be a directory")
    verified_artifacts = _validate_artifacts(attestation, artifact_root)
    _verify_detached_signature(
        record_bytes=attestation_bytes,
        identity=attestation.authority_identity,
        signature_path=attestation_signature_path,
        allowed_signers_path=allowed_signers_path,
    )

    complete_required_set = (
        authority.decision == "APPROVED"
        and set(scope.metric_scope) == REQUIRED_METRICS
        and set(scope.artifact_scope) == REQUIRED_ARTIFACT_IDS
    )
    status = (
        "VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION"
        if complete_required_set
        else "VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION_INCOMPLETE"
    )
    publication_eligibility_status = (
        "COMPLETE_INPUT_SET_REQUIRES_SEPARATE_C3_ADJUDICATION"
        if complete_required_set
        else "INCOMPLETE_NONPUBLICATION"
    )

    return {
        "schema_version": "POI_MPP_E3_RESULT_ATTESTATION_VERIFICATION_V1",
        "status": status,
        "experiment_id": "E3",
        "claim_id": "C3",
        "run_id": scope.run_id,
        "evidence_origin": scope.evidence_origin,
        "authority_identity": attestation.authority_identity,
        "authority_decision": authority_verification["decision"],
        "request_manifest_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "request_manifest_self_digest": request["self_digest"],
        "pre_execution_authority_record_sha256": hashlib.sha256(authority_bytes).hexdigest(),
        "result_attestation_record_sha256": hashlib.sha256(attestation_bytes).hexdigest(),
        "results_disposition": attestation.results_disposition,
        "verified_artifacts": verified_artifacts,
        "publication_eligibility_status": publication_eligibility_status,
        "publication_support_decision_status": "NOT_EVALUATED_BY_THIS_ATTESTATION",
        "attestation_boundary": (
            "Signature verification authenticates the exact post-execution E3 artifacts and declared evaluator "
            "disposition only; it does not determine whether C3 is publication-supported."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--authority-record", type=Path, required=True)
    parser.add_argument("--authority-signature", type=Path, required=True)
    parser.add_argument("--attestation-record", type=Path, required=True)
    parser.add_argument("--attestation-signature", type=Path, required=True)
    parser.add_argument("--allowed-signers", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_result_attestation(
            request_path=args.request_manifest,
            authority_record_path=args.authority_record,
            authority_signature_path=args.authority_signature,
            attestation_record_path=args.attestation_record,
            attestation_signature_path=args.attestation_signature,
            allowed_signers_path=args.allowed_signers,
            artifact_root_path=args.artifact_root,
        )
    except (ResultAttestationVerificationError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
