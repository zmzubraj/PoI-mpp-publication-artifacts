"""Fail-closed semantic validation for publication evidence artifacts.

This module intentionally separates *artifact completeness* from the later
scientific claim decision.  A valid negative or inconclusive result can be
complete; no claim result can repair a missing provenance, parent, or numeric
binding.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel

from poi_mpp.evidence.models import ArtifactStage, EvidenceOrigin
from poi_mpp.evidence.provenance import UNVERSIONED_BLOCKED


CompletenessDisposition = Literal["COMPLETE", "INCOMPLETE"]
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_MISSING = object()
_TERMINAL_STAGES = frozenset(
    {ArtifactStage.FROZEN.value, ArtifactStage.PUBLICATION_ELIGIBLE.value}
)


class ArtifactValidationError(ValueError):
    """A structured, deterministic rejection of an incomplete artifact."""

    def __init__(self, reasons: Iterable[str]):
        ordered = tuple(dict.fromkeys(str(reason) for reason in reasons))
        self.reasons = ordered
        super().__init__("; ".join(ordered) if ordered else "artifact validation failed")


@dataclass(frozen=True)
class ValidationReport:
    """The semantic completeness result and canonical normalized record."""

    completeness: CompletenessDisposition
    reasons: tuple[str, ...]
    record: dict[str, Any]

    @property
    def is_complete(self) -> bool:
        return self.completeness == "COMPLETE"


def _as_json_mapping(value: object, *, label: str) -> dict[str, Any]:
    """Return a detached finite JSON mapping without coercing input values."""

    if isinstance(value, BaseModel):
        raw: object = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise ArtifactValidationError((f"{label} must be a typed record or mapping",))
    try:
        serialized = json.dumps(raw, allow_nan=False, ensure_ascii=False, sort_keys=True)
        parsed = json.loads(serialized)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ArtifactValidationError((f"{label} contains non-finite or non-JSON data",)) from error
    if not isinstance(parsed, dict):
        raise ArtifactValidationError((f"{label} must serialize to an object",))
    return parsed


def _value(mapping: Mapping[str, Any], key: str) -> Any:
    return mapping.get(key, _MISSING)


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _finite_reasons(value: Any, *, path: str = "record") -> list[str]:
    reasons: list[str] = []
    if isinstance(value, float) and not math.isfinite(value):
        return [f"non-finite numeric value at {path}"]
    if isinstance(value, Mapping):
        for key in sorted(value, key=lambda item: str(item)):
            reasons.extend(_finite_reasons(value[key], path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reasons.extend(_finite_reasons(item, path=f"{path}[{index}]"))
    return reasons


def _state_reasons(value: Any, *, path: str = "record") -> list[str]:
    """Reject explicit interruption/partial/omission evidence anywhere in input."""

    reasons: list[str] = []
    if not isinstance(value, Mapping):
        return reasons
    for key in sorted(value, key=lambda item: str(item)):
        item = value[key]
        normalized_key = str(key).lower().replace("-", "_")
        item_path = f"{path}.{key}"
        if normalized_key in {
            "interrupted",
            "partial",
            "silently_omitted_inputs",
            "omitted_inputs",
            "has_invalid_rows",
        } and item is True:
            reasons.append(f"incomplete input state at {item_path}")
        if normalized_key in {"valid", "is_valid"} and item is False:
            reasons.append(f"invalid input state at {item_path}")
        if normalized_key in {"status", "input_status", "run_status", "row_status"} and isinstance(item, str):
            if item.upper() in {"FAILED", "INTERRUPTED", "PARTIAL", "OMITTED", "INVALID"}:
                reasons.append(f"incomplete input state at {item_path}")
        if normalized_key in {"invalid_rows", "omitted_rows", "missing_rows"}:
            if isinstance(item, bool) or not isinstance(item, int) or item != 0:
                reasons.append(f"invalid or omitted rows at {item_path}")
        if normalized_key in {"omitted_input_ids", "missing_input_ids"}:
            if not isinstance(item, list) or item:
                reasons.append(f"invalid or omitted inputs at {item_path}")
        reasons.extend(_state_reasons(item, path=item_path))
    return reasons


def _denominator_reasons(record: Mapping[str, Any]) -> list[str]:
    denominators: list[tuple[str, Any]] = []

    def collect(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key in sorted(value, key=lambda item: str(item)):
                item_path = f"{path}.{key}"
                if "denominator" in str(key).lower():
                    denominators.append((item_path, value[key]))
                collect(value[key], item_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                collect(item, f"{path}[{index}]")

    collect(record, "record")
    if not denominators:
        return ("missing denominator",)
    reasons: list[str] = []
    for name, value in denominators:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            reasons.append(f"invalid denominator at {name}")
    return reasons


def _confidence_interval_reasons(record: Mapping[str, Any]) -> list[str]:
    required = _value(record, "ci_required")
    if required is _MISSING:
        required = _value(record, "confidence_interval_required")
    if required is _MISSING:
        required = _value(record, "ci_applicable")
    interval = _value(record, "confidence_interval")
    reasons: list[str] = []
    if required is not _MISSING and not isinstance(required, bool):
        reasons.append("confidence interval applicability must be a boolean")
    if required is True and interval is _MISSING:
        reasons.append("missing required confidence interval")
    if interval is not _MISSING:
        if not isinstance(interval, list) or len(interval) != 2:
            reasons.append("confidence interval must contain exactly two finite bounds")
        elif any(
            isinstance(bound, bool)
            or not isinstance(bound, (int, float))
            or not math.isfinite(bound)
            for bound in interval
        ):
            reasons.append("confidence interval must contain exactly two finite bounds")
        elif interval[0] > interval[1]:
            reasons.append("confidence interval lower bound exceeds upper bound")
    return reasons


def _provenance_reasons(record: Mapping[str, Any], provenance: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in ("run_id", "experiment_id", "origin", "authorization_scope", "parent_hashes"):
        if _value(provenance, field) is _MISSING:
            reasons.append(f"missing provenance.{field}")
    for field in ("config_hash", "environment_hash", "model_hash", "dataset_hash"):
        value = _value(provenance, field)
        if value is _MISSING:
            reasons.append(f"missing provenance.{field}")
        elif not _is_hash(value):
            reasons.append(f"invalid provenance.{field}")
    code_revision = _value(provenance, "code_revision")
    if code_revision is _MISSING:
        reasons.append("missing provenance.code_revision")
    elif code_revision == UNVERSIONED_BLOCKED:
        reasons.append("provenance.code_revision is UNVERSIONED_BLOCKED")
    elif not isinstance(code_revision, str) or _GIT_REVISION.fullmatch(code_revision) is None:
        reasons.append("invalid provenance.code_revision")

    if _value(provenance, "authorization_scope") is not _MISSING:
        authorization = provenance["authorization_scope"]
        if not isinstance(authorization, str) or not authorization.strip():
            reasons.append("invalid provenance.authorization_scope")
    for field in ("run_id", "experiment_id", "origin"):
        if _value(provenance, field) is not _MISSING and provenance[field] != record.get(field):
            reasons.append(f"provenance.{field} does not bind record.{field}")

    record_parents = record.get("parent_hashes")
    provenance_parents = _value(provenance, "parent_hashes")
    if provenance_parents is not _MISSING and provenance_parents != record_parents:
        reasons.append("provenance.parent_hashes does not bind record.parent_hashes")
    return reasons


def _parent_reasons(record: Mapping[str, Any], known_parent_hashes: Iterable[str] | None) -> list[str]:
    parents = record.get("parent_hashes")
    if not isinstance(parents, list):
        return ["parent_hashes must be a list"]
    if any(not _is_hash(parent) for parent in parents):
        return ["parent_hashes must contain lowercase SHA-256 hashes"]
    if len(set(parents)) != len(parents):
        return ["parent_hashes must not contain duplicates"]
    own_hash = record.get("content_hash")
    if own_hash in parents:
        return ["artifact cannot list its own content_hash as a parent"]
    if not parents:
        return []
    if known_parent_hashes is None:
        return ["parent closure unavailable for declared parents"]
    known = set(known_parent_hashes)
    invalid_known = sorted(parent for parent in known if not _is_hash(parent))
    if invalid_known:
        return ["registered parent hash set contains an invalid hash"]
    missing = sorted(parent for parent in parents if parent not in known)
    return [f"unregistered parent hash: {parent}" for parent in missing]


def validate_artifact(
    record: object,
    *,
    known_parent_hashes: Iterable[str] | None = None,
    manifest: object | None = None,
    raise_on_error: bool = True,
) -> ValidationReport:
    """Validate one artifact without filling, correcting, or inferring data.

    ``manifest`` is accepted only as an explicit, serialized provenance binding.
    The returned canonical ``record`` contains that binding so a registry can
    preserve it in the frozen artifact.  With ``raise_on_error=False`` callers
    receive an ``INCOMPLETE`` report suitable for aggregate gate evaluation.
    """

    normalized = _as_json_mapping(record, label="artifact record")
    explicit_manifest = _as_json_mapping(manifest, label="run manifest") if manifest is not None else None
    embedded_provenance = normalized.get("provenance")
    reasons: list[str] = []

    # Synthetic provenance is the first reason by design: it must never look
    # like ordinary missing metadata that a caller might attempt to repair.
    origin = normalized.get("origin")
    if origin == EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value:
        reasons.append("synthetic non-evidence origin is not publication evidence")

    for field in ("artifact_id", "run_id", "experiment_id"):
        value = _value(normalized, field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"missing or invalid {field}")
    if origin not in {candidate.value for candidate in EvidenceOrigin}:
        reasons.append("missing or invalid origin")
    stage = normalized.get("stage")
    if stage not in _TERMINAL_STAGES:
        reasons.append("artifact is nonterminal; FROZEN provenance is required")
    if not _is_hash(normalized.get("content_hash")):
        reasons.append("missing or invalid content_hash")

    if explicit_manifest is not None:
        if embedded_provenance is not None and embedded_provenance != explicit_manifest:
            reasons.append("embedded provenance does not match supplied run manifest")
        normalized["provenance"] = explicit_manifest
        provenance: object = explicit_manifest
    else:
        provenance = embedded_provenance
    if not isinstance(provenance, Mapping):
        reasons.append("missing provenance binding")
    else:
        if provenance.get("origin") == EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value:
            reasons.append("synthetic non-evidence provenance is not publication evidence")
        reasons.extend(_provenance_reasons(normalized, provenance))

    reasons.extend(_finite_reasons(normalized))
    reasons.extend(_state_reasons(normalized))
    reasons.extend(_denominator_reasons(normalized))
    reasons.extend(_confidence_interval_reasons(normalized))
    reasons.extend(_parent_reasons(normalized, known_parent_hashes))
    reasons = list(dict.fromkeys(reasons))
    report = ValidationReport(
        completeness="COMPLETE" if not reasons else "INCOMPLETE",
        reasons=tuple(reasons),
        record=normalized,
    )
    if reasons and raise_on_error:
        raise ArtifactValidationError(report.reasons)
    return report
