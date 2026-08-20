"""FD-anchored immutable registry for canonical frozen artifact envelopes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any

from poi_mpp.evidence.canonical import canonical_bytes, digest
from poi_mpp.evidence.validation import (
    ArtifactValidationError,
    ProvenanceBundle,
    provenance_bundle_from_json,
    validate_artifact,
    validate_artifact_graph,
)


_FROZEN_SCHEMA = "POI_MPP_FROZEN_ARTIFACT_V1"
_SAFE_ARTIFACT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_TEMP_NAME = re.compile(r"\.[A-Za-z0-9][A-Za-z0-9_-]{0,127}\.[0-9a-f]{32}\.tmp\Z")


class ArtifactRegistry:
    """One canonical envelope format, anchored to a verified directory FD."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        if self.root.exists():
            if self.root.is_symlink():
                raise ArtifactValidationError(("artifact registry root must not be a symlink",))
        else:
            self.root.mkdir(parents=True, exist_ok=False)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            self._dir_fd = os.open(self.root, flags)
        except OSError as error:
            raise ArtifactValidationError(("artifact registry root could not be opened without following symlinks",)) from error
        if not stat.S_ISDIR(os.fstat(self._dir_fd).st_mode):
            self.close()
            raise ArtifactValidationError(("artifact registry root is not a directory",))
        self._recover_temps()
        self._entries = self._load_entries()

    def close(self) -> None:
        descriptor = getattr(self, "_dir_fd", None)
        if descriptor is not None:
            os.close(descriptor)
            self._dir_fd = None

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            pass

    @staticmethod
    def _safe_filename(artifact_id: object) -> str:
        if not isinstance(artifact_id, str) or not _SAFE_ARTIFACT_ID.fullmatch(artifact_id):
            raise ArtifactValidationError(("artifact_id cannot derive a safe filename",))
        return f"{artifact_id}.frozen.json"

    @staticmethod
    def _prefix() -> bytes:
        return canonical_bytes("FROZEN_ARTIFACT", {})[:-2]

    def _names(self) -> list[str]:
        return sorted(os.listdir(self._dir_fd))

    def _lstat_regular(self, name: str) -> None:
        details = os.lstat(name, dir_fd=self._dir_fd)
        if stat.S_ISLNK(details.st_mode):
            raise ArtifactValidationError((f"symlink registry entry is forbidden: {name}",))
        if not stat.S_ISREG(details.st_mode):
            raise ArtifactValidationError((f"registry entry is not a regular file: {name}",))

    def _read_name(self, name: str) -> bytes:
        self._lstat_regular(name)
        descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self._dir_fd)
        try:
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
        finally:
            os.close(descriptor)

    def _recover_temps(self) -> None:
        recovered = False
        for name in self._names():
            if not name.endswith(".tmp"):
                continue
            self._lstat_regular(name)
            if not _TEMP_NAME.fullmatch(name):
                raise ArtifactValidationError((f"unrecognized registry temporary file: {name}",))
            os.unlink(name, dir_fd=self._dir_fd)
            recovered = True
        if recovered:
            self._fsync_directory()

    def _decode_envelope(self, name: str) -> dict[str, Any]:
        raw = self._read_name(name)
        prefix = self._prefix()
        if not raw.startswith(prefix):
            raise ArtifactValidationError((f"frozen artifact lacks canonical bytes: {name}",))
        try:
            envelope = json.loads(raw[len(prefix):].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ArtifactValidationError((f"invalid frozen artifact JSON: {name}",)) from error
        if not isinstance(envelope, dict) or canonical_bytes("FROZEN_ARTIFACT", envelope) != raw:
            raise ArtifactValidationError((f"frozen artifact canonical bytes mismatch: {name}",))
        if set(envelope) != {"schema_version", "record", "provenance_bundle", "frozen_hash"} or envelope.get("schema_version") != _FROZEN_SCHEMA:
            raise ArtifactValidationError((f"invalid frozen artifact schema: {name}",))
        if not isinstance(envelope.get("record"), dict) or not isinstance(envelope.get("provenance_bundle"), dict):
            raise ArtifactValidationError((f"invalid frozen artifact envelope: {name}",))
        expected_hash = digest("FROZEN_ARTIFACT", {"record": envelope["record"], "provenance_bundle": envelope["provenance_bundle"]})
        if envelope.get("frozen_hash") != expected_hash:
            raise ArtifactValidationError((f"frozen artifact hash mismatch: {name}",))
        return envelope

    def _load_entries(self) -> dict[str, dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        records: list[dict[str, Any]] = []
        bundles: list[ProvenanceBundle] = []
        for name in self._names():
            if not name.endswith(".frozen.json"):
                continue
            envelope = self._decode_envelope(name)
            record = envelope["record"]
            if name != self._safe_filename(record.get("artifact_id")):
                raise ArtifactValidationError((f"frozen artifact filename does not bind artifact_id: {name}",))
            if name in entries:
                raise ArtifactValidationError((f"duplicate registry filename: {name}",))
            entries[name] = envelope
            records.append(record)
            bundles.append(provenance_bundle_from_json(envelope["provenance_bundle"]))
        hashes = [record.get("content_hash") for record in records]
        known = {value for value in hashes if isinstance(value, str)}
        for record, bundle in zip(records, bundles, strict=True):
            own_hash = record.get("content_hash")
            validate_artifact(record, provenance_bundle=bundle, known_parent_hashes=known - ({own_hash} if isinstance(own_hash, str) else set()))
        graph_reasons = validate_artifact_graph(records)
        if graph_reasons:
            raise ArtifactValidationError(graph_reasons)
        return entries

    def read_frozen(self, filename: str) -> dict[str, Any]:
        if filename not in self._entries:
            raise ArtifactValidationError((f"unknown frozen artifact: {filename}",))
        return self._decode_envelope(filename)

    def _fsync_directory(self) -> None:
        os.fsync(self._dir_fd)

    def _write_temp(self, name: str, content: bytes) -> None:
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=self._dir_fd)
        try:
            offset = 0
            while offset < len(content):
                offset += os.write(descriptor, content[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def write_atomic(self, record: object, *, provenance_bundle: ProvenanceBundle | None = None) -> Path:
        """Publish a fully valid artifact, never overwriting an existing target.

        Once the same-directory hard link succeeds, this method returns success
        even if cleanup or directory fsync subsequently fails.  Such a temp is a
        deterministic recoverable residue and is removed on the next open.
        """

        records = [entry["record"] for entry in self._entries.values()]
        known = {item.get("content_hash") for item in records if isinstance(item.get("content_hash"), str)}
        preliminary = validate_artifact(record, provenance_bundle=provenance_bundle, known_parent_hashes=known, raise_on_error=False)
        graph_reasons = validate_artifact_graph([*records, preliminary.record])
        if graph_reasons:
            raise ArtifactValidationError(graph_reasons)
        if preliminary.reasons:
            raise ArtifactValidationError(preliminary.reasons)
        report = preliminary
        if report.record.get("stage") != "FROZEN":
            raise ArtifactValidationError(("atomic registry writes require FROZEN stage",))
        filename = self._safe_filename(report.record.get("artifact_id"))
        if filename in self._entries:
            raise ArtifactValidationError((f"artifact is already frozen: {filename}",))
        assert report.provenance_bundle is not None
        envelope = {
            "schema_version": _FROZEN_SCHEMA,
            "record": report.record,
            "provenance_bundle": report.provenance_bundle,
            "frozen_hash": digest("FROZEN_ARTIFACT", {"record": report.record, "provenance_bundle": report.provenance_bundle}),
        }
        content = canonical_bytes("FROZEN_ARTIFACT", envelope)
        temp_name = f".{report.record['artifact_id']}.{secrets.token_hex(16)}.tmp"
        published = False
        try:
            self._write_temp(temp_name, content)
            os.link(temp_name, filename, src_dir_fd=self._dir_fd, dst_dir_fd=self._dir_fd, follow_symlinks=False)
            published = True
        except FileExistsError as error:
            raise ArtifactValidationError((f"artifact is already frozen: {filename}",)) from error
        finally:
            if not published:
                try:
                    os.unlink(temp_name, dir_fd=self._dir_fd)
                except FileNotFoundError:
                    pass
        if published:
            try:
                os.unlink(temp_name, dir_fd=self._dir_fd)
            except OSError:
                pass
            try:
                self._fsync_directory()
            except OSError:
                pass
            self._entries[filename] = envelope
            return self.root / filename
        raise ArtifactValidationError(("atomic publication did not complete",))
