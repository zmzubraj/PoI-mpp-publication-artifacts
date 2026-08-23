from __future__ import annotations

from pathlib import Path

from poi_mpp.evidence.publication_paths import publication_path_ref


def test_publication_path_ref_uses_repo_relative_posix_path(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    artifact_path = repo_root / "results" / "e1" / "rows.parquet"

    assert publication_path_ref(artifact_path, repo_root=repo_root) == "results/e1/rows.parquet"


def test_publication_path_ref_reduces_external_path_to_basename(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    external_path = tmp_path / "private-parent" / "capture.json"

    rendered = publication_path_ref(external_path, repo_root=repo_root)

    assert rendered == "capture.json"
    assert str(tmp_path) not in rendered
    assert ".." not in rendered
    assert "file://" not in rendered


def test_publication_path_ref_preserves_none(tmp_path: Path) -> None:
    assert publication_path_ref(None, repo_root=tmp_path / "repo") is None


def test_publication_path_ref_uses_opaque_id_for_unsafe_external_basename(tmp_path: Path) -> None:
    rendered = publication_path_ref(
        tmp_path / "outside" / "capture..json",
        repo_root=tmp_path / "repo",
    )

    assert rendered.startswith("external-artifact-")
    assert ".." not in rendered
    assert "/" not in rendered
