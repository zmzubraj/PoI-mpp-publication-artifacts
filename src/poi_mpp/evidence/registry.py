"""Atomic, no-overwrite persistence for semantically complete artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.validation import ArtifactValidationError, validate_artifact


_FROZEN_SCHEMA = "POI_MPP_FROZEN_ARTIFACT_V1"
_SAFE_ARTIFACT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


class ArtifactRegistry:
    """A local immutable registry whose on-disk entries are canonical JSON."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ArtifactValidationError(("artifact registry root is not a directory",))

    @staticmethod
    def _safe_filename(artifact_id: object) -> str:
        if not isinstance(artifact_id, str) or not _SAFE_ARTIFACT_ID.fullmatch(artifact_id):
            raise ArtifactValidationError(("artifact_id cannot derive a safe filename",))
        return f"{artifact_id}.frozen.json"

    @staticmethod
    def _serialize(payload: dict[str, Any]) -> bytes:
        try:
            return json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ArtifactValidationError(("frozen artifact is not canonical JSON",)) from error

    def _load_frozen_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.frozen.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ArtifactValidationError((f"invalid frozen artifact: {path.name}",)) from error
            if not isinstance(payload, dict) or payload.get("schema_version") != _FROZEN_SCHEMA:
                raise ArtifactValidationError((f"invalid frozen artifact schema: {path.name}",))
            record = payload.get("record")
            frozen_hash = payload.get("frozen_hash")
            if not isinstance(record, dict) or not isinstance(frozen_hash, str):
                raise ArtifactValidationError((f"invalid frozen artifact payload: {path.name}",))
            if frozen_hash != digest("FROZEN_ARTIFACT", record):
                raise ArtifactValidationError((f"frozen artifact hash mismatch: {path.name}",))
            records.append(record)
        return records

    def _registered_hashes(self) -> set[str]:
        records = self._load_frozen_records()
        hashes = {record.get("content_hash") for record in records}
        if any(not isinstance(value, str) for value in hashes):
            raise ArtifactValidationError(("registered artifact is missing content_hash",))
        known = {value for value in hashes if isinstance(value, str)}
        for record in records:
            own_hash = record["content_hash"]
            validate_artifact(
                record,
                known_parent_hashes=known - {own_hash},
            )
        return known

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        """Best-effort directory durability; unsupported platforms remain atomic."""

        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)

    def write_atomic(self, record: object, *, manifest: object | None = None) -> Path:
        """Validate and atomically publish a new frozen artifact exactly once.

        A same-directory temporary file is flushed before publication.  ``link``
        provides an atomic no-overwrite publish operation on the target
        filesystem; unlike ``replace`` it cannot silently replace a prior frozen
        artifact if another writer wins the race.
        """

        known_parents = self._registered_hashes()
        report = validate_artifact(
            record,
            known_parent_hashes=known_parents,
            manifest=manifest,
        )
        if report.record.get("stage") != "FROZEN":
            raise ArtifactValidationError(("atomic registry writes require FROZEN stage",))
        filename = self._safe_filename(report.record.get("artifact_id"))
        target = self.root / filename
        if target.exists():
            raise ArtifactValidationError((f"artifact is already frozen: {filename}",))

        payload = {
            "schema_version": _FROZEN_SCHEMA,
            "record": report.record,
            "frozen_hash": digest("FROZEN_ARTIFACT", report.record),
        }
        serialized = self._serialize(payload)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.root, prefix=f".{report.record['artifact_id']}.", suffix=".tmp", delete=False
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            # The target name is created atomically and fails if it appeared
            # after the precheck.  Only after successful publication is the
            # temporary name removed.
            os.link(temp_path, target)
            temp_path.unlink()
            temp_path = None
            self._fsync_directory(self.root)
            return target
        except Exception:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
