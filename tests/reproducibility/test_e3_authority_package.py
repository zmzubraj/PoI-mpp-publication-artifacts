from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from scripts import build_e3_authority_package as package_builder


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_e3_authority_package.py"
MANIFEST = (
    REPO_ROOT
    / "docs"
    / "paper_artifacts"
    / "final"
    / "external_review"
    / "E3_AUTHORITY_REQUEST_MANIFEST.json"
)
MANIFEST_MEMBER = MANIFEST.relative_to(REPO_ROOT).as_posix()
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
FIXED_FILE_MODE = 0o100644


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )


def _build(output: Path) -> None:
    completed = _run("--output", str(output))
    assert completed.returncode == 0, completed.stderr


def _write_test_manifest(manifest_path: Path, entry: dict[str, object]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "schema_version": "POI_MPP_E3_AUTHORITY_REQUEST_V1",
        "request_input_count": 1,
        "request_inputs": [entry],
    }
    canonical = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    manifest["self_digest"] = hashlib.sha256(canonical).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_package_contains_exact_hash_closed_request_material_with_fixed_metadata(
    tmp_path: Path,
) -> None:
    output = tmp_path / "request.zip"
    _build(output)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected_members = sorted(
        [MANIFEST_MEMBER, *(entry["path"] for entry in manifest["request_inputs"])]
    )
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == expected_members
        assert archive.read(MANIFEST_MEMBER) == MANIFEST.read_bytes()
        for info in archive.infolist():
            assert info.date_time == FIXED_TIMESTAMP
            assert info.create_system == 3
            assert info.external_attr >> 16 == FIXED_FILE_MODE
            assert not info.is_dir()
            assert not Path(info.filename).is_absolute()
            assert ".." not in Path(info.filename).parts

        by_path = {entry["path"]: entry for entry in manifest["request_inputs"]}
        for relative_path, entry in by_path.items():
            payload = archive.read(relative_path)
            assert len(payload) == entry["size_bytes"]
            assert hashlib.sha256(payload).hexdigest() == entry["sha256"]


def test_package_is_byte_for_byte_reproducible_and_checkable(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    _build(first)
    _build(second)

    assert first.read_bytes() == second.read_bytes()
    checked = _run("--output", str(first), "--check")
    assert checked.returncode == 0, checked.stderr

    first.write_bytes(first.read_bytes() + b"tamper")
    rejected = _run("--output", str(first), "--check")
    assert rejected.returncode != 0
    assert "stale or non-canonical" in rejected.stderr


def test_package_rejects_hash_or_size_mismatch_before_writing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    payload = repo_root / "scope.md"
    payload.write_text("approved scope\n", encoding="utf-8")
    manifest_path = repo_root / "request.json"
    _write_test_manifest(
        manifest_path,
        {"path": "scope.md", "sha256": "0" * 64, "size_bytes": payload.stat().st_size},
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="hash mismatch"):
        package_builder._validated_request_inputs(repo_root, manifest)


def test_package_rejects_self_consistent_but_noncanonical_request_manifest(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    payload = repo_root / "scope.md"
    payload.write_text("approved scope\n", encoding="utf-8")
    manifest_path = (
        repo_root
        / "docs"
        / "paper_artifacts"
        / "final"
        / "external_review"
        / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    )
    _write_test_manifest(
        manifest_path,
        {
            "path": "scope.md",
            "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
            "size_bytes": payload.stat().st_size,
        },
    )
    output = tmp_path / "noncanonical.zip"

    completed = _run(
        "--repo-root",
        str(repo_root),
        "--manifest",
        str(manifest_path),
        "--output",
        str(output),
    )

    assert completed.returncode != 0
    assert "does not exactly match canonical E3 request builder output" in completed.stderr
    assert not output.exists()


def test_package_rejects_path_traversal_and_symlink_inputs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    for relative_path in ("../outside.txt", "link.txt"):
        if relative_path == "link.txt":
            (repo_root / "link.txt").symlink_to(outside)
        manifest_path = repo_root / "request.json"
        _write_test_manifest(
            manifest_path,
            {
                "path": relative_path,
                "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
                "size_bytes": outside.stat().st_size,
            },
        )

        expected = "unsafe request input path" if relative_path.startswith("..") else "may not be a symlink"
        with pytest.raises(ValueError, match=expected):
            package_builder._validated_file(repo_root, relative_path)


def test_package_rejects_manifest_reached_through_symlinked_directory(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    real_directory = repo_root / "real"
    real_directory.mkdir(parents=True)
    payload = repo_root / "scope.md"
    payload.write_text("approved scope\n", encoding="utf-8")
    manifest_path = real_directory / "request.json"
    _write_test_manifest(
        manifest_path,
        {
            "path": "scope.md",
            "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
            "size_bytes": payload.stat().st_size,
        },
    )
    linked_directory = repo_root / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)
    output = tmp_path / "unsafe-manifest.zip"

    completed = _run(
        "--repo-root",
        str(repo_root),
        "--manifest",
        str(linked_directory / "request.json"),
        "--output",
        str(output),
    )

    assert completed.returncode != 0
    assert "manifest path may not contain symlinks" in completed.stderr
    assert not output.exists()


def test_package_has_no_external_authority_or_result_extras(tmp_path: Path) -> None:
    output = tmp_path / "request.zip"
    _build(output)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = {MANIFEST_MEMBER, *(entry["path"] for entry in manifest["request_inputs"])}
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == expected
        forbidden_suffixes = (".sig", ".pub", ".pem", ".key")
        assert not any(name.endswith(forbidden_suffixes) for name in archive.namelist())
        forbidden_files = {
            "allowed_signers",
            "authority_record.json",
            "e3_result.json",
            "result_attestation.json",
        }
        assert not any(Path(name).name.lower() in forbidden_files for name in archive.namelist())


def test_package_enforces_member_count_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(package_builder, "MAX_ARCHIVE_MEMBERS", 1, raising=False)

    with pytest.raises(ValueError, match="member count ceiling"):
        package_builder._enforce_archive_limits([("one", b"1"), ("two", b"2")])


def test_package_enforces_total_uncompressed_size_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(package_builder, "MAX_TOTAL_UNCOMPRESSED_BYTES", 1, raising=False)

    with pytest.raises(ValueError, match="uncompressed size ceiling"):
        package_builder._enforce_archive_limits([("one", b"12")])
