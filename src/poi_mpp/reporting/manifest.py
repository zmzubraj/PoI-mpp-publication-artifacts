"""Atomic publication report writing and closure validation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from poi_mpp.reporting.figures import figure_artifacts
from poi_mpp.reporting.load import (
    LoadedBundle,
    PublicationEligibilityError,
    ReportBuildSpec,
    load_publication_inputs,
)
from poi_mpp.reporting.tables import omission_rows, table_artifacts


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


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
        observed = _sha256_path(path)
        expected = _sha256_bytes(data)
        if observed != expected:
            raise PublicationEligibilityError((f"atomic write verification failed for {path.name}",))
        return observed
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


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


def _table_id_to_experiment(bundle: LoadedBundle) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for experiment in bundle.experiments:
        if experiment.table_id is not None:
            mapping[experiment.table_id] = experiment.experiment_id
        for figure_id in experiment.figure_ids:
            mapping[figure_id] = experiment.experiment_id
    return mapping


def _manifest_payload(bundle: LoadedBundle, artifact_hashes: dict[str, str]) -> dict[str, Any]:
    omission_index = {
        row["artifact_id"]: row
        for row in omission_rows(bundle)
    }
    outputs: list[dict[str, Any]] = []
    mapping = _table_id_to_experiment(bundle)
    for relative_path in sorted(artifact_hashes):
        artifact_id = Path(relative_path).name.split("_", 1)[0].split(".", 1)[0]
        experiment_id = mapping.get(artifact_id, "REPORT")
        experiment = next((item for item in bundle.experiments if item.experiment_id == experiment_id), None)
        outputs.append(
            {
                "artifact_id": artifact_id,
                "relative_path": relative_path,
                "sha256": artifact_hashes[relative_path],
                "kind": relative_path.split("/", 1)[0],
                "experiment_id": experiment_id,
                "origin": "" if experiment is None or experiment.origin is None else experiment.origin,
                "disposition": "OMITTED"
                if artifact_id in omission_index and relative_path.startswith("figures/")
                else ("" if experiment is None else experiment.disposition),
                "derivation_edge": f"{experiment_id}->{artifact_id}",
                "omission_reason": omission_index.get(artifact_id, {}).get("reason"),
                "source_hashes": [] if experiment is None else list(experiment.source_hashes),
            }
        )
    omissions = list(omission_rows(bundle))
    return {
        "schema_version": "POI_MPP_PUBLICATION_REPORT_MANIFEST_V1",
        "generator_source_closure_hash": bundle.generator_source_closure_hash,
        "environment_hash": bundle.environment_hash,
        "outputs": outputs,
        "omissions": omissions,
    }


def build_publication_report(spec: ReportBuildSpec) -> PublicationManifest:
    bundle = load_publication_inputs(spec)
    outputs = {}
    outputs.update(table_artifacts(bundle))
    outputs.update(figure_artifacts(bundle))
    artifact_hashes: dict[str, str] = {}
    for relative_path, data in sorted(outputs.items()):
        artifact_hashes[relative_path] = _atomic_write_bytes(bundle.output_root / relative_path, data)
    manifest_payload = _manifest_payload(bundle, artifact_hashes)
    manifest_bytes = (json.dumps(manifest_payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    manifest_sha256 = _atomic_write_bytes(bundle.output_root / "artifact_manifest.json", manifest_bytes)
    artifact_hashes["artifact_manifest.json"] = manifest_sha256
    outputs_index = tuple(
        ManifestEntry(
            artifact_id=item["artifact_id"],
            relative_path=item["relative_path"],
            sha256=item["sha256"],
            kind=item["kind"],
            origin=item["origin"],
            disposition=item["disposition"],
            derivation_edge=item["derivation_edge"],
            omission_reason=item["omission_reason"],
        )
        for item in manifest_payload["outputs"]
    )
    omissions_index = tuple(
        ManifestEntry(
            artifact_id=item["artifact_id"],
            relative_path="",
            sha256="",
            kind="omission",
            origin=item["origin"],
            disposition=item["disposition"],
            derivation_edge=f"{item['experiment_id']}->{item['artifact_id']}",
            omission_reason=item["reason"],
        )
        for item in manifest_payload["omissions"]
    )
    return PublicationManifest(
        output_root=bundle.output_root,
        outputs=outputs_index,
        omissions=omissions_index,
        generator_source_closure_hash=bundle.generator_source_closure_hash,
        environment_hash=bundle.environment_hash,
        manifest_sha256=manifest_sha256,
    )


def validate_existing_manifest(output_root: Path) -> PublicationManifest:
    manifest_path = output_root / "artifact_manifest.json"
    if not manifest_path.is_file():
        raise PublicationEligibilityError(("artifact_manifest.json is missing",))
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PublicationEligibilityError(("artifact_manifest.json is not valid JSON",)) from error
    expected_files = {"artifact_manifest.json"}
    for item in payload.get("outputs", []):
        expected_files.add(item["relative_path"])
    actual_files = {
        str(path.relative_to(output_root))
        for path in output_root.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        raise PublicationEligibilityError(("artifact manifest closure mismatch",))
    for item in payload.get("outputs", []):
        path = output_root / item["relative_path"]
        if _sha256_path(path) != item["sha256"]:
            raise PublicationEligibilityError((f"artifact hash mismatch for {item['relative_path']}",))
    outputs = tuple(
        ManifestEntry(
            artifact_id=item["artifact_id"],
            relative_path=item["relative_path"],
            sha256=item["sha256"],
            kind=item["kind"],
            origin=item["origin"],
            disposition=item["disposition"],
            derivation_edge=item["derivation_edge"],
            omission_reason=item.get("omission_reason"),
        )
        for item in payload.get("outputs", [])
    )
    omissions = tuple(
        ManifestEntry(
            artifact_id=item["artifact_id"],
            relative_path="",
            sha256="",
            kind="omission",
            origin=item["origin"],
            disposition=item["disposition"],
            derivation_edge=f"{item['experiment_id']}->{item['artifact_id']}",
            omission_reason=item["reason"],
        )
        for item in payload.get("omissions", [])
    )
    return PublicationManifest(
        output_root=output_root,
        outputs=outputs,
        omissions=omissions,
        generator_source_closure_hash=str(payload["generator_source_closure_hash"]),
        environment_hash=str(payload["environment_hash"]),
        manifest_sha256=_sha256_path(manifest_path),
    )


__all__ = [
    "PublicationManifest",
    "ManifestEntry",
    "build_publication_report",
    "validate_existing_manifest",
]
