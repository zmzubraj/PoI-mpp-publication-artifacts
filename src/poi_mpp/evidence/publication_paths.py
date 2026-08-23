"""Non-sensitive path references for publication-facing JSON artifacts."""

from __future__ import annotations

from hashlib import sha256
from os import PathLike
from pathlib import Path


def publication_path_ref(
    path: str | PathLike[str] | None,
    *,
    repo_root: str | PathLike[str],
) -> str | None:
    """Render a path without exposing machine-local parent directories.

    Files inside ``repo_root`` use a stable repository-relative POSIX path.
    Files outside it use only their basename.  An opaque stable identifier is
    used for the unusual case where an external path has no safe basename.
    """

    if path is None:
        return None

    raw_path = str(path)
    if raw_path.startswith("file://"):
        basename = raw_path.rstrip("/").rsplit("/", maxsplit=1)[-1]
        return basename if _is_safe_public_ref(basename) else _opaque_external_ref(raw_path)

    root = Path(repo_root).expanduser().resolve(strict=False)
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)

    try:
        relative = resolved.relative_to(root)
    except ValueError:
        basename = resolved.name
        if _is_safe_public_ref(basename):
            return basename
        return _opaque_external_ref(resolved.as_posix())

    rendered = relative.as_posix()
    if rendered in {"", "."}:
        return "."
    if not _is_safe_public_ref(rendered):
        return _opaque_external_ref(resolved.as_posix())
    return rendered


def _opaque_external_ref(material: str) -> str:
    identifier = sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"external-artifact-{identifier}"


def _is_safe_public_ref(value: str) -> bool:
    return bool(value) and value not in {".", ".."} and ".." not in value and "://" not in value
