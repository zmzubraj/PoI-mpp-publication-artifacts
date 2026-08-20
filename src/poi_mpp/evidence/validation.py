"""Fail-closed validation for content-addressed publication artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig
from poi_mpp.evidence.models import ArtifactStage, EvidenceOrigin, RunManifest
from poi_mpp.evidence.provenance import UNVERSIONED_BLOCKED, EnvironmentManifest, freeze_run


ARTIFACT_RECORD_SCHEMA_VERSION = "POI_MPP_ARTIFACT_RECORD_V1"
CompletenessDisposition = Literal["COMPLETE", "INCOMPLETE"]
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MISSING = object()
_TERMINAL_STAGES = frozenset({ArtifactStage.FROZEN.value, ArtifactStage.PUBLICATION_ELIGIBLE.value})
_STATE_FLAGS = frozenset({"interrupted", "partial", "silently_omitted_inputs", "omitted_inputs", "has_invalid_rows"})
_CI_FLAGS = frozenset({"ci_required", "confidence_interval_required", "ci_applicable"})
_ROOT_REQUIRED = frozenset({"schema_version", "artifact_id", "run_id", "experiment_id", "origin", "stage", "content_hash", "parent_hashes", "payload", "denominator", "ci_required", "provenance"})
_ROOT_ALLOWED = _ROOT_REQUIRED | frozenset({"confidence_interval", "claim_id", "claim_disposition", "claim_dispositions"})
_MATERIAL_FIELDS = ("schema_version", "artifact_id", "run_id", "experiment_id", "origin", "parent_hashes", "payload", "denominator", "ci_required", "confidence_interval", "claim_id", "claim_disposition", "claim_dispositions")


class ArtifactValidationError(ValueError):
    """A deterministic semantic rejection with machine-readable reasons."""

    def __init__(self, reasons: Iterable[str]):
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__("; ".join(self.reasons) if self.reasons else "artifact validation failed")


@dataclass(frozen=True)
class ProvenanceBundle:
    """The only authority accepted to bind a record to Task 2/3 provenance."""

    config: RunConfig
    environment: EnvironmentManifest
    manifest: RunManifest


@dataclass(frozen=True)
class ValidationReport:
    completeness: CompletenessDisposition
    reasons: tuple[str, ...]
    record: dict[str, Any]
    provenance_bundle: dict[str, Any] | None

    @property
    def is_complete(self) -> bool:
        return self.completeness == "COMPLETE"


def _json_mapping(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise ArtifactValidationError((f"{label} must be a mapping",))
    try:
        parsed = json.loads(json.dumps(dict(value), allow_nan=False, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ArtifactValidationError((f"{label} contains non-finite or non-JSON data",)) from error
    if not isinstance(parsed, dict):
        raise ArtifactValidationError((f"{label} must be an object",))
    return parsed


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def artifact_content_material(record: object) -> dict[str, Any]:
    """Return the exact material committed by ``content_hash``.

    Lifecycle status, ``content_hash`` itself, and the independently verified
    provenance bundle are deliberately excluded.  Every result-bearing payload,
    denominator, CI declaration, parent, and claim disposition is included.
    """

    normalized = _json_mapping(record, label="artifact record")
    return {field: normalized.get(field) for field in _MATERIAL_FIELDS}


def _bundle_json(bundle: ProvenanceBundle) -> dict[str, Any]:
    return {
        "config": bundle.config.model_dump(mode="json"),
        "environment": bundle.environment.model_dump(mode="json"),
        "manifest": bundle.manifest.model_dump(mode="json"),
    }


def provenance_bundle_from_json(value: object) -> ProvenanceBundle:
    raw = _json_mapping(value, label="provenance bundle")
    if set(raw) != {"config", "environment", "manifest"}:
        raise ArtifactValidationError(("provenance bundle has an invalid schema",))
    try:
        bundle = ProvenanceBundle(
            config=RunConfig.model_validate(raw["config"]),
            environment=EnvironmentManifest.model_validate(raw["environment"]),
            manifest=RunManifest.model_validate(raw["manifest"]),
        )
    except (ValidationError, TypeError, ValueError) as error:
        raise ArtifactValidationError(("provenance bundle is not typed and valid",)) from error
    _verified_bundle_json(bundle)
    return bundle


def _verified_bundle_json(bundle: object) -> dict[str, Any]:
    if not isinstance(bundle, ProvenanceBundle):
        raise ArtifactValidationError(("typed provenance bundle is required",))
    if not isinstance(bundle.config, RunConfig) or not isinstance(bundle.environment, EnvironmentManifest) or not isinstance(bundle.manifest, RunManifest):
        raise ArtifactValidationError(("typed provenance bundle is required",))
    try:
        config = RunConfig.model_validate(bundle.config.model_dump(mode="json"))
        environment = EnvironmentManifest.model_validate(bundle.environment.model_dump(mode="json"))
        expected = freeze_run(config, environment)
    except (ValidationError, TypeError, ValueError) as error:
        raise ArtifactValidationError(("provenance bundle fails approved run configuration schema",)) from error
    if expected.code_revision == UNVERSIONED_BLOCKED:
        raise ArtifactValidationError(("provenance.code_revision is UNVERSIONED_BLOCKED",))
    supplied = bundle.manifest.model_dump(mode="json")
    if supplied != expected.model_dump(mode="json"):
        raise ArtifactValidationError(("provenance manifest does not equal recomputed freeze_run",))
    return _bundle_json(ProvenanceBundle(config=config, environment=environment, manifest=expected))


def _finite_reasons(value: Any, path: str = "record") -> list[str]:
    if isinstance(value, float) and not math.isfinite(value):
        return [f"non-finite numeric value at {path}"]
    if isinstance(value, Mapping):
        return [reason for key in sorted(value, key=str) for reason in _finite_reasons(value[key], f"{path}.{key}")]
    if isinstance(value, list):
        return [reason for index, item in enumerate(value) for reason in _finite_reasons(item, f"{path}[{index}]")]
    return []


def _nested_semantic_reasons(value: Any, path: str = "record") -> list[str]:
    reasons: list[str] = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            reasons.extend(_nested_semantic_reasons(item, f"{path}[{index}]"))
        return reasons
    if not isinstance(value, Mapping):
        return reasons
    for key in sorted(value, key=str):
        item = value[key]
        key_name = str(key).lower().replace("-", "_")
        item_path = f"{path}.{key}"
        if key_name in _STATE_FLAGS:
            if not isinstance(item, bool):
                reasons.append(f"state flag must be boolean at {item_path}")
            elif item:
                reasons.append(f"incomplete state flag at {item_path}")
        if key_name in _CI_FLAGS:
            if not isinstance(item, bool):
                reasons.append(f"confidence interval applicability must be boolean at {item_path}")
            elif item and "confidence_interval" not in value:
                reasons.append(f"missing required confidence interval at {path}")
        if key_name == "confidence_interval":
            if not isinstance(item, list) or len(item) != 2 or any(isinstance(bound, bool) or not isinstance(bound, (int, float)) or not math.isfinite(bound) for bound in item):
                reasons.append(f"confidence interval must contain two finite bounds at {item_path}")
            elif item[0] > item[1]:
                reasons.append(f"confidence interval lower bound exceeds upper bound at {item_path}")
        if key_name == "denominator" and (isinstance(item, bool) or not isinstance(item, int) or item <= 0):
            reasons.append(f"invalid denominator at {item_path}")
        reasons.extend(_nested_semantic_reasons(item, item_path))
    return reasons


def _record_shape_reasons(record: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    missing = sorted(_ROOT_REQUIRED - set(record))
    if missing:
        reasons.extend(f"missing required field: {field}" for field in missing)
    unknown = sorted(set(record) - _ROOT_ALLOWED)
    if unknown:
        reasons.extend(f"unknown artifact field: {field}" for field in unknown)
    if record.get("schema_version") != ARTIFACT_RECORD_SCHEMA_VERSION:
        reasons.append("invalid artifact schema_version")
    for field in ("artifact_id", "run_id", "experiment_id"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            reasons.append(f"missing or invalid {field}")
    if record.get("origin") not in {item.value for item in EvidenceOrigin}:
        reasons.append("missing or invalid origin")
    if record.get("origin") == EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value:
        reasons.append("synthetic non-evidence origin is not publication evidence")
    if record.get("stage") not in _TERMINAL_STAGES:
        reasons.append("artifact is nonterminal")
    if not _is_hash(record.get("content_hash")):
        reasons.append("missing or invalid content_hash")
    parents = record.get("parent_hashes")
    if not isinstance(parents, list) or any(not _is_hash(parent) for parent in parents):
        reasons.append("parent_hashes must contain lowercase SHA-256 hashes")
    elif len(set(parents)) != len(parents):
        reasons.append("parent_hashes must not contain duplicates")
    if not isinstance(record.get("payload"), Mapping) or not record.get("payload"):
        reasons.append("payload must be a non-empty mapping")
    denominator = record.get("denominator")
    if isinstance(denominator, bool) or not isinstance(denominator, int) or denominator <= 0:
        reasons.append("missing top-level denominator or invalid denominator")
    if not isinstance(record.get("ci_required"), bool):
        reasons.append("confidence interval applicability must be boolean at record.ci_required")
    direct_claim = "claim_id" in record or "claim_disposition" in record
    matrix_claim = "claim_dispositions" in record
    if direct_claim and matrix_claim:
        reasons.append("claim disposition must use either direct or matrix form")
    elif direct_claim:
        if not isinstance(record.get("claim_id"), str) or not record["claim_id"].strip() or record.get("claim_disposition") not in {"SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"}:
            reasons.append("invalid direct claim disposition")
    elif matrix_claim:
        matrix = record.get("claim_dispositions")
        if not isinstance(matrix, Mapping) or not matrix or any(not isinstance(key, str) or not key.strip() or disposition not in {"SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE"} for key, disposition in matrix.items()):
            reasons.append("invalid claim disposition matrix")
    else:
        reasons.append("missing claim disposition")
    return reasons


def _provenance_reasons(record: Mapping[str, Any], bundle_json: dict[str, Any]) -> list[str]:
    manifest = bundle_json["manifest"]
    if record.get("provenance") != manifest:
        return ["embedded provenance does not exactly match verified manifest"]
    reasons: list[str] = []
    for field in ("run_id", "experiment_id", "origin", "parent_hashes"):
        if record.get(field) != manifest.get(field):
            reasons.append(f"verified manifest does not bind record.{field}")
    return reasons


def _parent_reasons(record: Mapping[str, Any], known_parent_hashes: Iterable[str] | None) -> list[str]:
    parents = record.get("parent_hashes")
    if not isinstance(parents, list) or any(not _is_hash(parent) for parent in parents):
        return []
    if record.get("content_hash") in parents:
        return ["artifact cannot list its own content_hash as a parent"]
    if not parents:
        return []
    if known_parent_hashes is None:
        return ["parent closure unavailable for declared parents"]
    known = set(known_parent_hashes)
    return [f"unregistered parent hash: {parent}" for parent in sorted(parents) if parent not in known]


def validate_artifact(record: object, *, provenance_bundle: ProvenanceBundle | None = None, known_parent_hashes: Iterable[str] | None = None, raise_on_error: bool = True) -> ValidationReport:
    """Validate one artifact without trusting supplied hashes or provenance."""

    normalized = _json_mapping(record, label="artifact record")
    reasons = _record_shape_reasons(normalized)
    bundle_json: dict[str, Any] | None = None
    try:
        bundle_json = _verified_bundle_json(provenance_bundle)
    except ArtifactValidationError as error:
        reasons.extend(error.reasons)
    if bundle_json is not None:
        reasons.extend(_provenance_reasons(normalized, bundle_json))
    if _is_hash(normalized.get("content_hash")):
        expected_hash = digest("ARTIFACT_CONTENT", artifact_content_material(normalized))
        if normalized["content_hash"] != expected_hash:
            reasons.append("content_hash mismatch for artifact content material")
    reasons.extend(_finite_reasons(normalized))
    reasons.extend(_nested_semantic_reasons(normalized))
    reasons.extend(_parent_reasons(normalized, known_parent_hashes))
    report = ValidationReport("COMPLETE" if not reasons else "INCOMPLETE", tuple(dict.fromkeys(reasons)), normalized, bundle_json)
    if report.reasons and raise_on_error:
        raise ArtifactValidationError(report.reasons)
    return report


def validate_artifact_graph(records: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """Validate unique IDs/hashes, closure, and acyclicity in deterministic order."""

    items = list(records)
    reasons: list[str] = []
    for field in ("artifact_id", "content_hash"):
        values = [item.get(field) for item in items if isinstance(item.get(field), str)]
        for value in sorted({value for value in values if values.count(value) > 1}, key=str):
            reasons.append(f"duplicate {field}: {value}")
    hashes = {item.get("content_hash") for item in items if _is_hash(item.get("content_hash"))}
    graph: dict[str, list[str]] = {}
    for item in items:
        node = item.get("content_hash")
        parents = item.get("parent_hashes")
        if not _is_hash(node) or not isinstance(parents, list):
            continue
        graph[node] = sorted(parent for parent in parents if _is_hash(parent))
        for parent in graph[node]:
            if parent not in hashes:
                reasons.append(f"unregistered parent hash: {parent}")
    visiting: list[str] = []
    visited: set[str] = set()
    def visit(node: str) -> None:
        if node in visiting:
            cycle = visiting[visiting.index(node):] + [node]
            reasons.append("parent cycle: " + " -> ".join(cycle))
            return
        if node in visited:
            return
        visiting.append(node)
        for parent in graph.get(node, []):
            if parent in graph:
                visit(parent)
        visiting.pop()
        visited.add(node)
    for node in sorted(graph):
        visit(node)
    return tuple(dict.fromkeys(reasons))
