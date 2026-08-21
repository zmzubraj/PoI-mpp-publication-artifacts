"""Fail-closed loading for deterministic publication reporting."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence import ArtifactValidationError, EvidenceOrigin, collect_environment, environment_hash, load_run_config
from poi_mpp.evidence.canonical import digest
from poi_mpp.experiments.e5_watcher import E5ScenarioRow, load_e5_confirmatory_contract
from poi_mpp.experiments.e6_sybil import E6ScenarioRow, load_e6_confirmatory_contract
from poi_mpp.experiments.e7_evm import (
    E7Bundle,
    E7ParityAttachment,
    E7MeasurementContract,
    default_measurement_contract,
)
from poi_mpp.experiments.e8_consensus import E8ScenarioRow, load_e8_confirmatory_contract
from poi_mpp.reporting.e1 import summarize_e1_rows
from poi_mpp.reporting.e2 import summarize_e2_rows
from poi_mpp.reporting.e3 import semantic_metrics
from poi_mpp.reporting.e4 import f8_points, summarize_e4_rows, t9_rows
from poi_mpp.reporting.e5 import invalid_maturity_sensitivity_points, summarize_e5_rows, t10_rows
from poi_mpp.reporting.e6 import f10_points, f9_points, summarize_e6_rows, t11_rows
from poi_mpp.reporting.e7 import collect_and_summarize_e7_publication, f12_points, summarize_e7_bundle, t12_rows
from poi_mpp.reporting.e8 import f11_points, summarize_e8_rows, t13_rows


_PUBLICATION_DISPOSITIONS = frozenset({"SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE", "MISSING", "WAITING_EXTERNAL"})
_DATA_ARTIFACTS = {
    "E1": ("T6", "F5"),
    "E2": ("T7", "F6"),
    "E3": ("T8", "F7"),
    "E4": ("T9", "F8"),
    "E5": ("T10", None),
    "E6": ("T11", "F9"),
    "E7": ("T12", "F12"),
    "E8": ("T13", "F11"),
}
_STATUS_FIGURES = {
    "E1": "F5",
    "E2": "F6",
    "E3": "F7",
    "E4": "F8",
    "E5": "F10",
    "E6": "F9",
    "E7": "F12",
    "E8": "F11",
}
_SAFE_SOURCE_KEYS = frozenset(
    {
        "rows_path",
        "summary_path",
        "run_config_path",
        "contract_path",
        "bundle_path",
        "parity_attachment_path",
        "replay_context_path",
        "contracts_root",
        "timeout_seconds",
    }
)


class PublicationEligibilityError(ValueError):
    """Deterministic publication-build rejection."""

    def __init__(self, reasons: tuple[str, ...] | list[str] | str):
        if isinstance(reasons, str):
            reasons = (reasons,)
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__("; ".join(self.reasons))


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExperimentSource(_FrozenModel):
    rows_path: str | None = None
    summary_path: str | None = None
    run_config_path: str | None = None
    contract_path: str | None = None
    bundle_path: str | None = None
    parity_attachment_path: str | None = None
    replay_context_path: str | None = None
    contracts_root: str | None = None
    timeout_seconds: int = Field(default=120, ge=1, le=900)

    @model_validator(mode="after")
    def validate_known_shape(self) -> "ExperimentSource":
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("experiment source must declare at least one path or timeout")
        return self


class ReportBuildSpec(_FrozenModel):
    artifact_root: str
    output_root: str
    sources: dict[str, ExperimentSource]
    write_status_figures: bool = True

    @field_validator("artifact_root", "output_root")
    @classmethod
    def require_nonblank_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("paths must not be blank")
        return value

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: dict[str, ExperimentSource]) -> dict[str, ExperimentSource]:
        unknown = sorted(set(value) - set(_DATA_ARTIFACTS))
        if unknown:
            raise ValueError(f"unknown experiment source keys: {', '.join(unknown)}")
        return value


@dataclass(frozen=True)
class LoadedExperiment:
    experiment_id: str
    table_id: str | None
    figure_ids: tuple[str, ...]
    claim_id: str
    origin: str | None
    disposition: str
    scope: str | None
    maturity: str
    run_id: str | None
    config_hash: str | None
    source_hashes: tuple[str, ...]
    table_rows: tuple[dict[str, Any], ...]
    figure_points: tuple[dict[str, Any], ...]
    summary: dict[str, Any] | None
    sample_size: int | None
    uncertainty: str | None
    limits: tuple[str, ...]
    omission_reason: str | None


@dataclass(frozen=True)
class LoadedBundle:
    artifact_root: Path
    output_root: Path
    experiments: tuple[LoadedExperiment, ...]
    environment_hash: str
    generator_source_closure_hash: str


def _path_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _generator_source_closure_hash() -> str:
    root = Path(__file__).resolve().parents[3]
    relative_paths = (
        Path("src/poi_mpp/reporting/__init__.py"),
        Path("src/poi_mpp/reporting/load.py"),
        Path("src/poi_mpp/reporting/statistics.py"),
        Path("src/poi_mpp/reporting/tables.py"),
        Path("src/poi_mpp/reporting/figures.py"),
        Path("src/poi_mpp/reporting/manifest.py"),
        Path("scripts/build_artifact_manifest.py"),
        Path("scripts/generate_figures.py"),
        Path("scripts/report_all.py"),
        Path("pyproject.toml"),
        Path("requirements.lock"),
    )
    payload = {
        str(relative_path): _path_hash(root / relative_path)
        for relative_path in relative_paths
    }
    return digest("REPORT_GENERATOR_CLOSURE", payload)


def _reject_synthetic_origin(origin: str | None, *, experiment_id: str) -> None:
    if origin == EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value:
        raise PublicationEligibilityError((f"{experiment_id} synthetic non-evidence inputs cannot build publication artifacts",))


def _reject_nonfinite(value: Any, *, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise PublicationEligibilityError((f"non-finite numeric value at {path}",))
    if isinstance(value, dict):
        for key in sorted(value):
            _reject_nonfinite(value[key], path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_nonfinite(item, path=f"{path}[{index}]")


def _resolved_anchored_path(root: Path, candidate: str | Path) -> Path:
    path = Path(candidate)
    if not path.is_absolute():
        path = root / path
    try:
        resolved_root = root.resolve(strict=True)
    except FileNotFoundError as error:
        raise PublicationEligibilityError((f"artifact_root does not exist: {root}",)) from error
    current = path
    while True:
        try:
            candidate_stat = os.lstat(current)
        except OSError as error:
            raise PublicationEligibilityError((f"unable to stat input path: {current}",)) from error
        if os.path.islink(current):
            raise PublicationEligibilityError((f"symlinked input path is forbidden: {path}",))
        if current == resolved_root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise PublicationEligibilityError((f"configured input path is missing: {path}",)) from error
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise PublicationEligibilityError((f"path escapes artifact_root: {path}",)) from error
    if not resolved.is_file():
        raise PublicationEligibilityError((f"input path must be a regular file: {path}",))
    return resolved


def _load_json(root: Path, candidate: str | Path, *, label: str) -> tuple[Path, Any, str]:
    path = _resolved_anchored_path(root, candidate)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PublicationEligibilityError((f"{label} is not valid JSON: {path}",)) from error
    _reject_nonfinite(payload, path=label)
    return path, payload, _path_hash(path)


def _load_yaml_text(root: Path, candidate: str | Path, *, label: str) -> tuple[Path, str, str]:
    path = _resolved_anchored_path(root, candidate)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PublicationEligibilityError((f"unable to read {label}: {path}",)) from error
    return path, text, _path_hash(path)


def _rows_payload(root: Path, candidate: str | Path, *, label: str) -> tuple[tuple[dict[str, Any], ...], str]:
    _, payload, payload_hash = _load_json(root, candidate, label=label)
    rows: Any = payload
    if isinstance(payload, dict) and "rows" in payload:
        rows = payload["rows"]
    if not isinstance(rows, list) or not rows:
        raise PublicationEligibilityError((f"{label} must contain a non-empty rows list",))
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PublicationEligibilityError((f"{label} row {index} must be an object",))
        _reject_nonfinite(row, path=f"{label}.rows[{index}]")
        normalized.append(dict(row))
    return tuple(normalized), payload_hash


def _limits_from_summary(summary: dict[str, Any]) -> tuple[str, ...]:
    limits: list[str] = []
    for key in ("assumption_ledger", "residual_surface_ledger"):
        value = summary.get(key)
        if isinstance(value, list):
            limits.extend(str(item) for item in value if str(item).strip())
        elif isinstance(value, tuple):
            limits.extend(str(item) for item in value if str(item).strip())
    return tuple(dict.fromkeys(limits))


def _missing_experiment(experiment_id: str, reason: str) -> LoadedExperiment:
    table_id, primary_figure = _DATA_ARTIFACTS[experiment_id]
    figure_ids = tuple(
        artifact_id
        for artifact_id in (
            primary_figure,
            "F10" if experiment_id == "E6" else None,
        )
        if artifact_id is not None
    )
    return LoadedExperiment(
        experiment_id=experiment_id,
        table_id=table_id,
        figure_ids=figure_ids,
        claim_id=f"{experiment_id}_MISSING",
        origin=None,
        disposition="MISSING" if "missing" in reason.lower() else "WAITING_EXTERNAL",
        scope=None,
        maturity="ABSENT",
        run_id=None,
        config_hash=None,
        source_hashes=(),
        table_rows=(),
        figure_points=(),
        summary=None,
        sample_size=None,
        uncertainty=None,
        limits=(),
        omission_reason=reason,
    )


def _e8_loaded(root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.rows_path is None or source.contract_path is None:
        return _missing_experiment("E8", "missing E8 rows_path or contract_path")
    rows_payload, rows_hash = _rows_payload(root, source.rows_path, label="E8 rows")
    _, contract_text, contract_hash = _load_yaml_text(root, source.contract_path, label="E8 contract")
    contract = load_e8_confirmatory_contract(_resolved_anchored_path(root, source.contract_path))
    try:
        rows = tuple(E8ScenarioRow.model_validate(row) for row in rows_payload)
    except Exception as error:
        raise PublicationEligibilityError((f"E8 rows failed canonical validation: {error}",)) from error
    origins = {row.origin.value for row in rows}
    if len(origins) != 1:
        raise PublicationEligibilityError(("E8 rows mix origins",))
    origin = next(iter(origins))
    _reject_synthetic_origin(origin, experiment_id="E8")
    summary = summarize_e8_rows(rows, contract=contract).model_dump(mode="json")
    return LoadedExperiment(
        experiment_id="E8",
        table_id="T13",
        figure_ids=("F11",),
        claim_id=str(summary["claim_id"]),
        origin=origin,
        disposition=str(summary["claim_disposition"]),
        scope=rows[0].publication_scope,
        maturity="REPRODUCIBLE_SIMULATION",
        run_id=rows[0].run_id,
        config_hash=rows[0].run_config_hash,
        source_hashes=(rows_hash, contract_hash),
        table_rows=tuple(row.model_dump(mode="json") for row in t13_rows(rows)),
        figure_points=tuple(point.model_dump(mode="json") for point in f11_points(rows)),
        summary=summary,
        sample_size=len(rows),
        uncertainty="wilson_from_replay" if any("interval" in key for key in summary) else None,
        limits=_limits_from_summary(summary) + tuple(str(line) for line in yaml.safe_load(contract_text).get("notes", ())),
        omission_reason=None,
    )


def _e7_loaded(root: Path, output_root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.run_config_path is not None:
        run_config = load_run_config(_resolved_anchored_path(root, source.run_config_path))
        bundle_output = output_root / "raw" / "E7_live_bundle.json"
        result = collect_and_summarize_e7_publication(
            contracts_root=source.contracts_root or str(Path(__file__).resolve().parents[3] / "contracts"),
            run_config=run_config,
            bundle_output_path=bundle_output,
            contract=default_measurement_contract(),
            timeout=source.timeout_seconds,
        )
        summary = result.summary.model_dump(mode="json")
        return LoadedExperiment(
            experiment_id="E7",
            table_id="T12",
            figure_ids=("F12",),
            claim_id=str(summary["claim_id"]),
            origin=result.bundle.run_config_snapshot.origin.value,
            disposition=str(summary["claim_disposition"]),
            scope=result.bundle.run_config_snapshot.authorization_scope,
        maturity="LOCAL_FOUNDRY_MEASUREMENT",
        run_id=result.bundle.run_config_snapshot.run_id,
        config_hash=result.bundle.run_config_hash,
            source_hashes=(
                result.bundle.raw_report_hash,
                result.bundle.run_config_hash,
                result.parity_verification.source_closure_hash,
                result.parity_verification.protocol_vectors_hash,
                result.parity_verification.protocol_witness_hash,
            ),
            table_rows=tuple(row.model_dump(mode="json") for row in t12_rows(result.bundle.rows)),
            figure_points=tuple(point.model_dump(mode="json") for point in f12_points(result.bundle.rows)),
            summary=summary,
            sample_size=len(result.bundle.rows),
            uncertainty="N/A_single_measurement",
            limits=(),
            omission_reason=None,
        )
    if source.bundle_path is None:
        return _missing_experiment("E7", "missing E7 run_config_path for live measurement")
    _, bundle_payload, bundle_hash = _load_json(root, source.bundle_path, label="E7 bundle")
    bundle = E7Bundle.model_validate(bundle_payload)
    parity_attachment: E7ParityAttachment | None = None
    if source.parity_attachment_path is not None:
        _, parity_payload, parity_hash = _load_json(root, source.parity_attachment_path, label="E7 parity attachment")
        parity_attachment = E7ParityAttachment.model_validate(parity_payload)
        source_hashes = (bundle_hash, parity_hash)
    else:
        source_hashes = (bundle_hash,)
    summary = summarize_e7_bundle(
        bundle,
        contract=default_measurement_contract(),
        parity_attachment=parity_attachment,
    ).model_dump(mode="json")
    return LoadedExperiment(
        experiment_id="E7",
        table_id="T12",
        figure_ids=("F12",),
        claim_id=str(summary["claim_id"]),
        origin=bundle.run_config_snapshot.origin.value,
        disposition=str(summary["claim_disposition"]),
        scope=bundle.run_config_snapshot.authorization_scope,
        maturity="LOCAL_FOUNDRY_METADATA_ONLY",
        run_id=bundle.run_config_snapshot.run_id,
        config_hash=bundle.run_config_hash,
        source_hashes=source_hashes,
        table_rows=(),
        figure_points=(),
        summary=summary,
        sample_size=len(bundle.rows),
        uncertainty=None,
        limits=(),
        omission_reason="stored E7 bundle metadata is non-authoritative; live collection is required",
    )


def _e6_loaded(root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.rows_path is None or source.contract_path is None:
        return _missing_experiment("E6", "missing E6 rows_path or contract_path")
    rows_payload, rows_hash = _rows_payload(root, source.rows_path, label="E6 rows")
    contract_path = _resolved_anchored_path(root, source.contract_path)
    contract = load_e6_confirmatory_contract(contract_path)
    rows = tuple(E6ScenarioRow.model_validate(row) for row in rows_payload)
    origins = {row.origin.value for row in rows}
    if len(origins) != 1:
        raise PublicationEligibilityError(("E6 rows mix origins",))
    origin = next(iter(origins))
    _reject_synthetic_origin(origin, experiment_id="E6")
    summary = summarize_e6_rows(rows, contract=contract).model_dump(mode="json")
    return LoadedExperiment(
        experiment_id="E6",
        table_id="T11",
        figure_ids=("F9", "F10"),
        claim_id=str(summary["claim_id"]),
        origin=origin,
        disposition=str(summary["claim_disposition"]),
        scope=rows[0].publication_scope,
        maturity="REPRODUCIBLE_SIMULATION",
        run_id=rows[0].run_id,
        config_hash=rows[0].run_config_hash,
        source_hashes=(rows_hash, _path_hash(contract_path)),
        table_rows=tuple(row.model_dump(mode="json") for row in t11_rows(rows)),
        figure_points=tuple(point.model_dump(mode="json") for point in f9_points(rows))
        + tuple(point.model_dump(mode="json") for point in f10_points(rows)),
        summary=summary,
        sample_size=len(rows),
        uncertainty="confidence_interval_micros",
        limits=_limits_from_summary(summary),
        omission_reason=None,
    )


def _e5_loaded(root: Path, source: ExperimentSource) -> LoadedExperiment:
    if source.rows_path is None or source.contract_path is None:
        return _missing_experiment("E5", "missing E5 rows_path or contract_path")
    rows_payload, rows_hash = _rows_payload(root, source.rows_path, label="E5 rows")
    contract_path = _resolved_anchored_path(root, source.contract_path)
    contract = load_e5_confirmatory_contract(contract_path)
    rows = tuple(E5ScenarioRow.model_validate(row) for row in rows_payload)
    origins = {row.origin.value for row in rows}
    if len(origins) != 1:
        raise PublicationEligibilityError(("E5 rows mix origins",))
    origin = next(iter(origins))
    _reject_synthetic_origin(origin, experiment_id="E5")
    summary = summarize_e5_rows(rows, contract=contract).model_dump(mode="json")
    return LoadedExperiment(
        experiment_id="E5",
        table_id="T10",
        figure_ids=("F10",),
        claim_id=str(summary["claim_id"]),
        origin=origin,
        disposition=str(summary["claim_disposition"]),
        scope=rows[0].publication_scope,
        maturity="REPRODUCIBLE_SIMULATION",
        run_id=rows[0].run_id,
        config_hash=rows[0].run_config_hash,
        source_hashes=(rows_hash, _path_hash(contract_path)),
        table_rows=tuple(row.model_dump(mode="json") for row in t10_rows(rows)),
        figure_points=tuple(point.model_dump(mode="json") for point in invalid_maturity_sensitivity_points(rows)),
        summary=summary,
        sample_size=len(rows),
        uncertainty="invalid_maturity_interval",
        limits=_limits_from_summary(summary),
        omission_reason=None,
    )


def _unimplemented_loaded(experiment_id: str, reason: str) -> LoadedExperiment:
    return _missing_experiment(experiment_id, reason)


def load_publication_inputs(spec: ReportBuildSpec) -> LoadedBundle:
    artifact_root = Path(spec.artifact_root).resolve()
    output_root = Path(spec.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    loaders = {
        "E5": lambda source: _e5_loaded(artifact_root, source),
        "E6": lambda source: _e6_loaded(artifact_root, source),
        "E7": lambda source: _e7_loaded(artifact_root, output_root, source),
        "E8": lambda source: _e8_loaded(artifact_root, source),
    }
    experiments: list[LoadedExperiment] = []
    for experiment_id in ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"):
        source = spec.sources.get(experiment_id)
        if source is None:
            experiments.append(_missing_experiment(experiment_id, f"missing configured source for {experiment_id}"))
            continue
        source = ExperimentSource.model_validate(source)
        if experiment_id in loaders:
            experiments.append(loaders[experiment_id](source))
            continue
        experiments.append(_unimplemented_loaded(experiment_id, f"{experiment_id} authoritative input is not configured in this publication build"))
    environment = collect_environment(repo_root=Path(__file__).resolve().parents[3], lock_path=Path(__file__).resolve().parents[3] / "requirements.lock")
    return LoadedBundle(
        artifact_root=artifact_root,
        output_root=output_root,
        experiments=tuple(experiments),
        environment_hash=environment_hash(environment),
        generator_source_closure_hash=_generator_source_closure_hash(),
    )


__all__ = [
    "ExperimentSource",
    "LoadedBundle",
    "LoadedExperiment",
    "PublicationEligibilityError",
    "ReportBuildSpec",
    "load_publication_inputs",
]
