"""Domain-separated canonical JSON serialization and SHA-256 hashing."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel


_PREFIX = "POI_MPP_V1"
_DOMAIN_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*\Z")


def _validated_domain(domain: str) -> str:
    if not isinstance(domain, str) or not _DOMAIN_PATTERN.fullmatch(domain):
        raise ValueError("domain must match [A-Z][A-Z0-9_]*")
    return domain


def _json_compatible(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def canonical_bytes(domain: str, value: Any) -> bytes:
    """Serialize ``value`` as versioned, domain-separated canonical UTF-8 JSON.

    Compact separators and sorted mapping keys make semantically equivalent
    mappings produce identical bytes. ``allow_nan=False`` rejects non-finite
    floats rather than silently encoding non-standard JSON tokens.
    """

    normalized_domain = _validated_domain(domain)
    try:
        payload = json.dumps(
            _json_compatible(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("value is not finite JSON-serializable data") from error
    return f"{_PREFIX}|{normalized_domain}|".encode("ascii") + payload


def digest(domain: str, value: Any) -> str:
    """Return the lowercase hexadecimal SHA-256 digest of canonical bytes."""

    return hashlib.sha256(canonical_bytes(domain, value)).hexdigest()
