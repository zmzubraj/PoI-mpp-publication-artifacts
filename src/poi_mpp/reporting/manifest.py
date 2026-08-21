"""Atomic publication report writing and closure validation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic import ValidationError

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence import collect_environment, environment_hash
from poi_mpp.reporting.figures import figure_artifacts
from poi_mpp.reporting.load import (
    ARTIFACT_FILENAMES,
    GeneratedOutput,
    InputEntry,
    LoadedBundle,
    PublicationEligibilityError,
    ReportBuildSpec,
    experiment_artifact_ids,
    load_publication_inputs,
)
from poi_mpp.reporting.tables import omission_rows, table_artifacts


_MANIFEST_SCHEMA_VERSION = "POI_MPP_PUBLICATION_REPORT_MANIFEST_V3"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_relative_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty POSIX relative path")
    if "\x00" in value:
        raise ValueError(f"{label} must not contain NUL bytes")
    if "\\" in value:
        raise ValueError(f"{label} must use POSIX separators")
    if value.startswith("/") or (len(value) >= 2 and value[1] == ":"):
        raise ValueError(f"{label} must be relative")
    normalized = str(PurePosixPath(value))
    if normalized != value:
        raise ValueError(f"{label} must already be in canonical normalized form")
    parts = PurePosixPath(value).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{label} must not contain empty, '.' or '..' components")
    return value


def _assert_no_symlink_components(path: Path, *, stop_at: Path | None = None, require_directory: bool = False) -> None:
    current = path
    while True:
        try:
            metadata = os.lstat(current)
        except OSError as error:
            raise PublicationEligibilityError((f"unable to stat path component: {current}",)) from error
        if stat.S_ISLNK(metadata.st_mode):
            raise PublicationEligibilityError((f"symlinked path component is forbidden: {current}",))
        if require_directory and current == path and not stat.S_ISDIR(metadata.st_mode):
            raise PublicationEligibilityError((f"expected directory path: {current}",))
        if stop_at is not None and current == stop_at:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent


def _safe_read_file(path: Path, *, root: Path | None = None) -> bytes:
    if root is not None:
        _assert_no_symlink_components(path.parent, stop_at=root, require_directory=True)
    else:
        _assert_no_symlink_components(path.parent, require_directory=True)
    flags = os.O_RDONLY | _NOFOLLOW
    try:
        file_descriptor = os.open(str(path), flags)
    except OSError as error:
        raise PublicationEligibilityError((f"unable to open file without following symlinks: {path}",)) from error
    try:
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PublicationEligibilityError((f"path is not a regular file: {path}",))
        if metadata.st_nlink != 1:
            raise PublicationEligibilityError((f"hardlinked output/input file is forbidden: {path}",))
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(file_descriptor)


def _sha256_path(path: Path, *, root: Path | None = None) -> str:
    return _sha256_bytes(_safe_read_file(path, root=root))


def _manifest_join(root: Path, relative_path: str) -> Path:
    canonical = _canonical_relative_path(relative_path, label="manifest relative path")
    candidate = root.joinpath(*PurePosixPath(canonical).parts)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise PublicationEligibilityError((f"manifest path escapes root: {relative_path}",)) from error
    return candidate


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_write_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
        observed = _sha256_path(path, root=path.parent)
        expected = _sha256_bytes(data)
        if observed != expected:
            raise PublicationEligibilityError((f"atomic write verification failed for {path.name}",))
        return observed
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManifestInputRecord(_FrozenModel):
    experiment_id: str
    input_role: str
    relative_path: str
    sha256: str
    schema_version: str | None = None
    origin: str | None = None
    disposition: str
    run_id: str | None = None
    config_hash: str | None = None
    paper_artifact_ids: tuple[str, ...]

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return _canonical_relative_path(value, label="input relative_path")


class ManifestOutputRecord(_FrozenModel):
    output_id: str
    artifact_id: str
    relative_path: str
    sha256: str
    kind: str
    experiment_id: str
    origin: str
    disposition: str
    derivation_edge: str
    omission_reason: str | None = None
    schema_version: str | None = None
    run_id: str | None = None
    config_hash: str | None = None
    source_closure_hash: str | None = None
    source_hashes: tuple[str, ...] = ()
    derived_from_input_paths: tuple[str, ...] = ()
    derives_to_artifact_ids: tuple[str, ...] = ()

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return _canonical_relative_path(value, label="output relative_path")

    @field_validator("derived_from_input_paths")
    @classmethod
    def validate_derived_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_canonical_relative_path(item, label="derived_from_input_paths item") for item in value)


class ManifestOmissionRecord(_FrozenModel):
    artifact_id: str
    experiment_id: str
    disposition: str
    origin: str
    reason: str


class PublicationReportManifestModel(_FrozenModel):
    schema_version: str = _MANIFEST_SCHEMA_VERSION
    artifact_root_relative_path: str
    generator_source_closure_hash: str
    environment_hash: str
    inputs: tuple[ManifestInputRecord, ...]
    outputs: tuple[ManifestOutputRecord, ...]
    omissions: tuple[ManifestOmissionRecord, ...]
    self_digest: str

    @model_validator(mode="after")
    def validate_uniqueness(self) -> "PublicationReportManifestModel":
        input_paths = tuple(item.relative_path for item in self.inputs)
        if len(input_paths) != len(set(input_paths)):
            raise ValueError("duplicate input relative paths are forbidden")
        output_paths = tuple(item.relative_path for item in self.outputs)
        if len(output_paths) != len(set(output_paths)):
            raise ValueError("duplicate output relative paths are forbidden")
        output_ids = tuple(item.output_id for item in self.outputs)
        if len(output_ids) != len(set(output_ids)):
            raise ValueError("duplicate output ids are forbidden")
        derivation_edges = tuple(item.derivation_edge for item in self.outputs)
        if len(derivation_edges) != len(set(derivation_edges)):
            raise ValueError("duplicate derivation edges are forbidden")
        omission_ids = tuple(item.artifact_id for item in self.omissions)
        if len(omission_ids) != len(set(omission_ids)):
            raise ValueError("duplicate omission artifact ids are forbidden")
        known_input_paths = set(input_paths)
        for output in self.outputs:
            if len(output.derived_from_input_paths) != len(set(output.derived_from_input_paths)):
                raise ValueError(f"duplicate derived input paths are forbidden for {output.output_id}")
            missing = sorted(set(output.derived_from_input_paths) - known_input_paths)
            if missing:
                raise ValueError(f"unknown derived input paths for {output.output_id}: {', '.join(missing)}")
        return self


@dataclass(frozen=True)
class ManifestEntry:
    artifact_id: str
    relative_path: str
    sha256: str
    kind: str
    origin: str
    disposition: str
    derivation_edge: str
    omission_reason: str | None


@dataclass(frozen=True)
class PublicationManifest:
    output_root: Path
    outputs: tuple[ManifestEntry, ...]
    omissions: tuple[ManifestEntry, ...]
    generator_source_closure_hash: str
    environment_hash: str
    manifest_sha256: str


def _current_generator_source_closure_hash() -> str:
    from poi_mpp.reporting.load import _generator_source_closure_hash

    return _generator_source_closure_hash()


def _current_environment_hash() -> str:
    repo_root = Path(__file__).resolve().parents[3]
    environment = collect_environment(repo_root=repo_root, lock_path=repo_root / "requirements.lock")
    return environment_hash(environment)


def _output_id(relative_path: str) -> str:
    kind, filename = relative_path.split("/", 1)
    stem, extension = filename.rsplit(".", 1)
    return f"{kind}:{stem}:{extension}"


def _artifact_id_from_relative_path(relative_path: str) -> str:
    kind, filename = relative_path.split("/", 1)
    if kind == "raw" and filename == "E7_live_bundle.json":
        return "RAW_E7_LIVE_BUNDLE"
    if kind == "tables":
        if filename.startswith("claim_matrix"):
            return "CLAIM_MATRIX"
        if filename.startswith("omissions"):
            return "OMISSION_LEDGER"
    return filename.split("_", 1)[0].split(".", 1)[0]


def _manifest_material(payload: dict[str, Any]) -> dict[str, Any]:
    material = dict(payload)
    material["self_digest"] = ""
    return material


def _manifest_self_digest(payload: dict[str, Any]) -> str:
    return digest("PUBLICATION_REPORT_MANIFEST", _manifest_material(payload))


def _manifest_inputs(bundle: LoadedBundle) -> tuple[ManifestInputRecord, ...]:
    records = [
        ManifestInputRecord.model_validate(
            {
                "experiment_id": entry.experiment_id,
                "input_role": entry.input_role,
                "relative_path": entry.relative_path,
                "sha256": entry.sha256,
                "schema_version": entry.schema_version,
                "origin": entry.origin,
                "disposition": entry.disposition,
                "run_id": entry.run_id,
                "config_hash": entry.config_hash,
                "paper_artifact_ids": entry.paper_artifact_ids,
            }
        )
        for experiment in bundle.experiments
        for entry in experiment.input_entries
    ]
    return tuple(sorted(records, key=lambda item: (item.experiment_id, item.input_role, item.relative_path)))


def _generated_output_by_artifact(bundle: LoadedBundle) -> dict[str, tuple[str, GeneratedOutput]]:
    generated: dict[str, tuple[str, GeneratedOutput]] = {}
    for experiment in bundle.experiments:
        for output in experiment.generated_outputs:
            generated[output.artifact_id] = (experiment.experiment_id, output)
    return generated


def _manifest_outputs(bundle: LoadedBundle, artifact_hashes: dict[str, str]) -> tuple[ManifestOutputRecord, ...]:
    experiment_by_artifact = {
        artifact_id: experiment
        for experiment in bundle.experiments
        for artifact_id in (*experiment.table_ids, *experiment.figure_ids)
    }
    generated_by_artifact = _generated_output_by_artifact(bundle)
    outputs: list[ManifestOutputRecord] = []
    for relative_path, sha256 in sorted(artifact_hashes.items()):
        artifact_id = _artifact_id_from_relative_path(relative_path)
        experiment = experiment_by_artifact.get(artifact_id)
        generated_meta = generated_by_artifact.get(artifact_id)
        experiment_id = "REPORT"
        origin = ""
        disposition = ""
        omission_reason = None
        schema_version = None
        run_id = None
        config_hash = None
        source_closure_hash = None
        source_hashes: tuple[str, ...] = ()
        derived_from_input_paths: tuple[str, ...] = ()
        derives_to_artifact_ids: tuple[str, ...] = ()
        derivation_edge = f"REPORT->{artifact_id}:{Path(relative_path).suffix.lstrip('.')}"
        if generated_meta is not None:
            experiment_id, generated_output = generated_meta
            generated_experiment = next(item for item in bundle.experiments if item.experiment_id == experiment_id)
            origin = "" if generated_experiment.origin is None else generated_experiment.origin
            disposition = generated_experiment.disposition
            omission_reason = generated_experiment.omission_reason
            schema_version = generated_output.schema_version
            run_id = generated_output.run_id
            config_hash = generated_output.config_hash
            source_closure_hash = generated_output.source_closure_hash
            source_hashes = generated_experiment.source_hashes
            derived_from_input_paths = generated_output.derived_from_input_paths
            derives_to_artifact_ids = generated_output.derives_to_artifact_ids
            derivation_edge = f"{experiment_id}->{artifact_id}:{Path(relative_path).suffix.lstrip('.')}"
        elif experiment is not None:
            experiment_id = experiment.experiment_id
            origin = "" if experiment.origin is None else experiment.origin
            disposition = experiment.disposition
            omission_reason = experiment.omission_reason
            run_id = experiment.run_id
            config_hash = experiment.config_hash
            source_hashes = experiment.source_hashes
            derived_from_input_paths = tuple(entry.relative_path for entry in experiment.input_entries)
            derivation_edge = f"{experiment.experiment_id}->{artifact_id}:{Path(relative_path).suffix.lstrip('.')}"
        outputs.append(
            ManifestOutputRecord.model_validate(
                {
                    "output_id": _output_id(relative_path),
                    "artifact_id": artifact_id,
                    "relative_path": relative_path,
                    "sha256": sha256,
                    "kind": relative_path.split("/", 1)[0],
                    "experiment_id": experiment_id,
                    "origin": origin,
                    "disposition": disposition,
                    "derivation_edge": derivation_edge,
                    "omission_reason": omission_reason,
                    "schema_version": schema_version,
                    "run_id": run_id,
                    "config_hash": config_hash,
                    "source_closure_hash": source_closure_hash,
                    "source_hashes": source_hashes,
                    "derived_from_input_paths": derived_from_input_paths,
                    "derives_to_artifact_ids": derives_to_artifact_ids,
                }
            )
        )
    return tuple(outputs)


def _manifest_omissions(bundle: LoadedBundle) -> tuple[ManifestOmissionRecord, ...]:
    rows = omission_rows(bundle)
    return tuple(
        ManifestOmissionRecord.model_validate(
            {
                "artifact_id": row["artifact_id"],
                "experiment_id": row["experiment_id"],
                "disposition": row["disposition"],
                "origin": row["origin"],
                "reason": row["reason"],
            }
        )
        for row in rows
    )


def _manifest_payload(bundle: LoadedBundle, artifact_hashes: dict[str, str]) -> PublicationReportManifestModel:
    artifact_root_relative_path = os.path.relpath(bundle.artifact_root, bundle.output_root)
    payload = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "artifact_root_relative_path": artifact_root_relative_path,
        "generator_source_closure_hash": bundle.generator_source_closure_hash,
        "environment_hash": bundle.environment_hash,
        "inputs": [item.model_dump(mode="json") for item in _manifest_inputs(bundle)],
        "outputs": [item.model_dump(mode="json") for item in _manifest_outputs(bundle, artifact_hashes)],
        "omissions": [item.model_dump(mode="json") for item in _manifest_omissions(bundle)],
        "self_digest": "",
    }
    payload["self_digest"] = _manifest_self_digest(payload)
    return PublicationReportManifestModel.model_validate(payload)


def _generated_output_hashes(bundle: LoadedBundle) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for experiment in bundle.experiments:
        for output in experiment.generated_outputs:
            path = _manifest_join(bundle.output_root, output.relative_path)
            hashes[output.relative_path] = _sha256_path(path, root=bundle.output_root)
    return hashes


def _enumerate_output_files(output_root: Path) -> set[str]:
    _assert_no_symlink_components(output_root, require_directory=True)
    files: set[str] = set()
    for current_root, directory_names, file_names in os.walk(output_root, topdown=True, followlinks=False):
        current_path = Path(current_root)
        for directory_name in list(directory_names):
            directory_path = current_path / directory_name
            metadata = os.lstat(directory_path)
            if stat.S_ISLNK(metadata.st_mode):
                raise PublicationEligibilityError((f"symlinked output directory is forbidden: {directory_path}",))
        for file_name in file_names:
            file_path = current_path / file_name
            files.add(str(file_path.relative_to(output_root)))
            _safe_read_file(file_path, root=output_root)
    return files


def build_publication_report(spec: ReportBuildSpec) -> PublicationManifest:
    bundle = load_publication_inputs(spec)
    outputs = {}
    outputs.update(table_artifacts(bundle))
    outputs.update(figure_artifacts(bundle))
    if len(outputs) != len(set(outputs)):
        raise PublicationEligibilityError(("duplicate output paths are forbidden",))
    artifact_hashes: dict[str, str] = {}
    for relative_path, data in sorted(outputs.items()):
        artifact_hashes[relative_path] = _atomic_write_bytes(_manifest_join(bundle.output_root, relative_path), data)
    generated_output_hashes = _generated_output_hashes(bundle)
    duplicate_generated_paths = sorted(set(artifact_hashes).intersection(generated_output_hashes))
    if duplicate_generated_paths:
        raise PublicationEligibilityError((f"generated output path overlaps with report artifact output: {', '.join(duplicate_generated_paths)}",))
    artifact_hashes.update(generated_output_hashes)
    manifest_model = _manifest_payload(bundle, artifact_hashes)
    manifest_bytes = (json.dumps(manifest_model.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    manifest_sha256 = _atomic_write_bytes(bundle.output_root / "artifact_manifest.json", manifest_bytes)
    outputs_index = tuple(
        ManifestEntry(
            artifact_id=item.artifact_id,
            relative_path=item.relative_path,
            sha256=item.sha256,
            kind=item.kind,
            origin=item.origin,
            disposition=item.disposition,
            derivation_edge=item.derivation_edge,
            omission_reason=item.omission_reason,
        )
        for item in manifest_model.outputs
    )
    omissions_index = tuple(
        ManifestEntry(
            artifact_id=item.artifact_id,
            relative_path="",
            sha256="",
            kind="omission",
            origin=item.origin,
            disposition=item.disposition,
            derivation_edge=f"{item.experiment_id}->{item.artifact_id}",
            omission_reason=item.reason,
        )
        for item in manifest_model.omissions
    )
    return PublicationManifest(
        output_root=bundle.output_root,
        outputs=outputs_index,
        omissions=omissions_index,
        generator_source_closure_hash=manifest_model.generator_source_closure_hash,
        environment_hash=manifest_model.environment_hash,
        manifest_sha256=manifest_sha256,
    )


def validate_existing_manifest(output_root: Path) -> PublicationManifest:
    _assert_no_symlink_components(output_root, require_directory=True)
    manifest_path = _manifest_join(output_root, "artifact_manifest.json")
    manifest_bytes = _safe_read_file(manifest_path, root=output_root)
    try:
        manifest_payload = json.loads(manifest_bytes.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise PublicationEligibilityError(("artifact_manifest.json is not valid JSON",)) from error
    try:
        manifest_model = PublicationReportManifestModel.model_validate(manifest_payload)
    except ValidationError as error:
        raise PublicationEligibilityError((str(error),)) from error
    if manifest_model.self_digest != _manifest_self_digest(manifest_model.model_dump(mode="json")):
        raise PublicationEligibilityError(("manifest self-digest mismatch",))
    if manifest_model.generator_source_closure_hash != _current_generator_source_closure_hash():
        raise PublicationEligibilityError(("generator source closure drift detected",))
    if manifest_model.environment_hash != _current_environment_hash():
        raise PublicationEligibilityError(("environment hash drift detected",))
    artifact_root = (output_root / manifest_model.artifact_root_relative_path).resolve()
    _assert_no_symlink_components(artifact_root, require_directory=True)
    seen_input_paths: set[str] = set()
    for entry in manifest_model.inputs:
        if entry.relative_path in seen_input_paths:
            raise PublicationEligibilityError(("duplicate input relative paths are forbidden",))
        seen_input_paths.add(entry.relative_path)
        input_path = _manifest_join(artifact_root, entry.relative_path)
        if _sha256_path(input_path, root=artifact_root) != entry.sha256:
            raise PublicationEligibilityError((f"input hash mismatch for {entry.relative_path}",))
    expected_files = {"artifact_manifest.json"} | {item.relative_path for item in manifest_model.outputs}
    actual_files = _enumerate_output_files(output_root)
    if actual_files != expected_files:
        raise PublicationEligibilityError(("artifact manifest closure mismatch",))
    for item in manifest_model.outputs:
        output_path = _manifest_join(output_root, item.relative_path)
        if _sha256_path(output_path, root=output_root) != item.sha256:
            raise PublicationEligibilityError((f"artifact hash mismatch for {item.relative_path}",))
    outputs = tuple(
        ManifestEntry(
            artifact_id=item.artifact_id,
            relative_path=item.relative_path,
            sha256=item.sha256,
            kind=item.kind,
            origin=item.origin,
            disposition=item.disposition,
            derivation_edge=item.derivation_edge,
            omission_reason=item.omission_reason,
        )
        for item in manifest_model.outputs
    )
    omissions = tuple(
        ManifestEntry(
            artifact_id=item.artifact_id,
            relative_path="",
            sha256="",
            kind="omission",
            origin=item.origin,
            disposition=item.disposition,
            derivation_edge=f"{item.experiment_id}->{item.artifact_id}",
            omission_reason=item.reason,
        )
        for item in manifest_model.omissions
    )
    return PublicationManifest(
        output_root=output_root,
        outputs=outputs,
        omissions=omissions,
        generator_source_closure_hash=manifest_model.generator_source_closure_hash,
        environment_hash=manifest_model.environment_hash,
        manifest_sha256=_sha256_bytes(manifest_bytes),
    )


__all__ = ["ManifestEntry", "PublicationManifest", "build_publication_report", "validate_existing_manifest"]
