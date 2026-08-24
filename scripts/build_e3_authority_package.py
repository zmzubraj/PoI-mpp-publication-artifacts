#!/usr/bin/env python3
"""Build the deterministic unsigned E3 authority-request delivery package.

The ZIP contains only the canonical request manifest and the files hash-bound
by its ``request_inputs`` entries. It does not create evaluator authority,
identity, credentials, signatures, result evidence, or attestations.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from typing import Any
import zipfile

try:
    from scripts import build_e3_authority_request as request_builder
except ModuleNotFoundError:  # Direct execution adds scripts/, not the repository root, to sys.path.
    import build_e3_authority_request as request_builder


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "docs"
    / "paper_artifacts"
    / "final"
    / "external_review"
    / "E3_AUTHORITY_REQUEST_MANIFEST.json"
)
DEFAULT_OUTPUT = DEFAULT_MANIFEST.with_name("E3_AUTHORITY_REQUEST_PACKAGE.zip")
CANONICAL_MANIFEST_PATH = PurePosixPath(
    "docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_MANIFEST.json"
)
SCHEMA_VERSION = "POI_MPP_E3_AUTHORITY_REQUEST_V1"
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FIXED_FILE_MODE = 0o100644
MAX_ARCHIVE_MEMBERS = 128
MAX_TOTAL_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _safe_relative_path(raw_path: object) -> PurePosixPath:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path or "\x00" in raw_path:
        raise ValueError(f"unsafe request input path: {raw_path!r}")
    relative = PurePosixPath(raw_path)
    if (
        relative.is_absolute()
        or relative.as_posix() != raw_path
        or "." in relative.parts
        or ".." in relative.parts
        or not relative.parts
        or ":" in relative.parts[0]
    ):
        raise ValueError(f"unsafe request input path: {raw_path}")
    return relative


def _validated_file(repo_root: Path, raw_path: object) -> tuple[str, Path]:
    relative = _safe_relative_path(raw_path)
    candidate = repo_root.joinpath(*relative.parts)
    current = repo_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"request input may not be a symlink: {relative.as_posix()}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo_root)
    except (FileNotFoundError, ValueError) as error:
        raise ValueError(
            f"request input is missing or escapes repository root: {relative.as_posix()}"
        ) from error
    if not resolved.is_file():
        raise ValueError(f"request input is not a file: {relative.as_posix()}")
    return relative.as_posix(), resolved


def _validated_manifest(repo_root: Path, manifest_path: Path) -> tuple[str, Path, bytes, dict[str, Any]]:
    lexical_manifest = manifest_path.absolute()
    try:
        lexical_relative = lexical_manifest.relative_to(repo_root)
    except ValueError as error:
        raise ValueError("E3 request manifest is missing or outside repository root") from error
    cursor = repo_root
    for part in lexical_relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("E3 request manifest path may not contain symlinks")
    try:
        resolved = lexical_manifest.resolve(strict=True)
        relative = resolved.relative_to(repo_root).as_posix()
    except (FileNotFoundError, ValueError) as error:
        raise ValueError("E3 request manifest is missing or outside repository root") from error
    if not resolved.is_file():
        raise ValueError("E3 request manifest is not a file")
    if relative != CANONICAL_MANIFEST_PATH.as_posix():
        raise ValueError("E3 request manifest does not exactly match canonical E3 request builder output")
    payload = resolved.read_bytes()
    try:
        manifest = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("E3 request manifest is not valid UTF-8 JSON") from error
    if not isinstance(manifest, dict):
        raise ValueError("E3 request manifest must be a JSON object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported E3 request manifest schema_version")
    supplied_digest = manifest.get("self_digest")
    unsigned = dict(manifest)
    unsigned.pop("self_digest", None)
    if not isinstance(supplied_digest, str) or supplied_digest != _sha256(_canonical_bytes(unsigned)):
        raise ValueError("E3 request manifest self_digest mismatch")
    original_repo_root = request_builder.REPO_ROOT
    try:
        request_builder.REPO_ROOT = repo_root
        expected = request_builder.serialized_manifest()
    except (OSError, ValueError) as error:
        raise ValueError(
            "E3 request manifest does not exactly match canonical E3 request builder output"
        ) from error
    finally:
        request_builder.REPO_ROOT = original_repo_root
    if payload != expected:
        raise ValueError("E3 request manifest does not exactly match canonical E3 request builder output")
    return relative, resolved, payload, manifest


def _validated_request_inputs(repo_root: Path, manifest: dict[str, Any]) -> list[tuple[str, bytes]]:
    entries = manifest.get("request_inputs")
    if not isinstance(entries, list):
        raise ValueError("E3 request manifest request_inputs must be an array")
    count = manifest.get("request_input_count")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(entries):
        raise ValueError("E3 request manifest request_input_count mismatch")

    staged: dict[str, bytes] = {}
    casefolded: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("E3 request manifest input entry must be an object")
        relative, source = _validated_file(repo_root, entry.get("path"))
        if relative in staged or relative.casefold() in casefolded:
            raise ValueError(f"duplicate or non-portable request input path: {relative}")
        expected_hash = entry.get("sha256")
        expected_size = entry.get("size_bytes")
        if not isinstance(expected_hash, str) or SHA256_PATTERN.fullmatch(expected_hash) is None:
            raise ValueError(f"invalid request input sha256: {relative}")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
            raise ValueError(f"invalid request input size: {relative}")
        payload = source.read_bytes()
        if len(payload) != expected_size:
            raise ValueError(f"request input size mismatch: {relative}")
        if _sha256(payload) != expected_hash:
            raise ValueError(f"request input hash mismatch: {relative}")
        staged[relative] = payload
        casefolded.add(relative.casefold())
    return sorted(staged.items())


def _staged_members(repo_root: Path, manifest_path: Path) -> list[tuple[str, bytes]]:
    manifest_member, _, manifest_bytes, manifest = _validated_manifest(repo_root, manifest_path)
    inputs = _validated_request_inputs(repo_root, manifest)
    if any(path == manifest_member or path.casefold() == manifest_member.casefold() for path, _ in inputs):
        raise ValueError(f"duplicate or non-portable request input path: {manifest_member}")
    return sorted([(manifest_member, manifest_bytes), *inputs])


def _enforce_archive_limits(members: list[tuple[str, bytes]]) -> None:
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise ValueError(
            f"E3 authority package member count ceiling exceeded: {len(members)} > {MAX_ARCHIVE_MEMBERS}"
        )
    total_size = sum(len(payload) for _, payload in members)
    if total_size > MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise ValueError(
            "E3 authority package total uncompressed size ceiling exceeded: "
            f"{total_size} > {MAX_TOTAL_UNCOMPRESSED_BYTES}"
        )


def build_package(repo_root: Path, manifest_path: Path) -> bytes:
    members = _staged_members(repo_root.resolve(strict=True), manifest_path)
    _enforce_archive_limits(members)
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_STORED,
        allowZip64=False,
        strict_timestamps=True,
    ) as archive:
        for relative_path, payload in members:
            info = zipfile.ZipInfo(relative_path, date_time=FIXED_TIMESTAMP)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = FIXED_FILE_MODE << 16
            archive.writestr(info, payload)
    return output.getvalue()


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail unless output is canonical")
    args = parser.parse_args()
    try:
        expected = build_package(args.repo_root, args.manifest)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    output = args.output.resolve()
    if args.check:
        if not output.is_file() or output.read_bytes() != expected:
            print(f"E3 authority request package is stale or non-canonical: {output}", file=sys.stderr)
            return 1
        print(output)
        return 0
    _write_atomic(output, expected)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
