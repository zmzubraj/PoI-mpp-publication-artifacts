"""Executable, deterministic E4 local data-availability reconstruction simulation.

This module deliberately produces ``REPRODUCIBLE_SIMULATION`` evidence only.
It creates real local shard stores, issues deterministic sample certificates,
applies named faults, and invokes the canonical reconstruction verifier.  It
does not emulate a network or mint support for Claim C4.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import yaml

from poi_mpp.auditor.availability import ReconstructionStatus, verify_reconstruction
from poi_mpp.evidence import EvidenceOrigin, digest
from poi_mpp.protocol.availability import (
    ErasureParameters,
    LocalShardStore,
    SamplingAssumption,
    SamplingMode,
    issue_sample_certificate,
)


E4_EXECUTION_SCHEMA_VERSION = "POI_MPP_E4_EXECUTION_CONFIG_V2"
E4_EXECUTION_METHOD_BOUNDARY = "EXECUTABLE_LOCAL_DA_RECONSTRUCTION_SIMULATION"
E4_EXECUTION_MANIFEST_VERSION = "POI_MPP_E4_EXECUTION_MANIFEST_V2"
E4_EXECUTION_MODEL_VERSION = "POI_MPP_E4_LOCAL_DA_RECONSTRUCTION_V2"
E4_INCONCLUSIVE_REASON = "LOCAL_DETERMINISTIC_SIMULATION_DOES_NOT_ESTABLISH_NETWORK_GENERALITY"
REPO_ROOT = Path(__file__).resolve().parents[3]


class E4ExecutionError(ValueError):
    """Raised when E4 execution or replay cannot remain fail-closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class E4ScenarioKind(StrEnum):
    HONEST_NEGATIVE_CONTROL = "HONEST_NEGATIVE_CONTROL"
    RANDOM_WITHHOLDING = "RANDOM_WITHHOLDING"
    TARGETED_WITHHOLDING = "TARGETED_WITHHOLDING"
    CORRUPT_SHARD = "CORRUPT_SHARD"
    DUPLICATE_SHARD = "DUPLICATE_SHARD"
    REORDERED_SHARD = "REORDERED_SHARD"
    SELECTIVE_SERVICE = "SELECTIVE_SERVICE"


class E4ExecutionModel(_FrozenModel):
    model_version: str
    total_shards: int = Field(gt=1)
    reconstruction_threshold: int = Field(gt=0)
    sample_count: int = Field(gt=0)
    replacement: bool
    shard_payload_bytes: int = Field(ge=32)

    @model_validator(mode="after")
    def validate_model(self) -> "E4ExecutionModel":
        if self.model_version != E4_EXECUTION_MODEL_VERSION:
            raise ValueError(f"model_version must equal {E4_EXECUTION_MODEL_VERSION}")
        if self.reconstruction_threshold > self.total_shards:
            raise ValueError("reconstruction_threshold cannot exceed total_shards")
        if not self.replacement and self.sample_count > self.total_shards:
            raise ValueError("sample_count cannot exceed total_shards without replacement")
        return self


class E4ExecutionScenario(_FrozenModel):
    scenario_id: str
    kind: E4ScenarioKind
    seed_offset: int = Field(ge=0)
    expected_status: str
    mutation_count: int = Field(ge=0)

    @field_validator("scenario_id")
    @classmethod
    def require_scenario_id(cls, value: str) -> str:
        if not value.strip() or Path(value).name != value or value in {".", ".."}:
            raise ValueError("scenario_id must be a nonblank path-safe name")
        return value

    @model_validator(mode="after")
    def validate_scenario(self) -> "E4ExecutionScenario":
        expected_by_kind = {
            E4ScenarioKind.HONEST_NEGATIVE_CONTROL: ReconstructionStatus.VERIFIED,
            E4ScenarioKind.RANDOM_WITHHOLDING: ReconstructionStatus.WITHHELD,
            E4ScenarioKind.TARGETED_WITHHOLDING: ReconstructionStatus.WITHHELD,
            E4ScenarioKind.CORRUPT_SHARD: ReconstructionStatus.CORRUPT,
            E4ScenarioKind.DUPLICATE_SHARD: ReconstructionStatus.CORRUPT,
            E4ScenarioKind.REORDERED_SHARD: ReconstructionStatus.CORRUPT,
            E4ScenarioKind.SELECTIVE_SERVICE: ReconstructionStatus.SELECTIVE_SERVICE,
        }
        if self.expected_status != expected_by_kind[self.kind]:
            raise ValueError("expected_status must match the frozen scenario kind")
        required_mutations = {
            E4ScenarioKind.HONEST_NEGATIVE_CONTROL: 0,
            E4ScenarioKind.CORRUPT_SHARD: 1,
            E4ScenarioKind.DUPLICATE_SHARD: 1,
            E4ScenarioKind.REORDERED_SHARD: 2,
            E4ScenarioKind.SELECTIVE_SERVICE: 1,
        }
        required = required_mutations.get(self.kind)
        if required is not None and self.mutation_count != required:
            raise ValueError(f"{self.kind.value} requires mutation_count={required}")
        if self.kind in {
            E4ScenarioKind.RANDOM_WITHHOLDING,
            E4ScenarioKind.TARGETED_WITHHOLDING,
        } and self.mutation_count <= 0:
            raise ValueError("withholding scenarios require a positive mutation_count")
        return self


class E4ExecutionConfig(_FrozenModel):
    schema_version: str
    experiment_id: str
    claim_id: str
    origin: EvidenceOrigin
    method_boundary: str
    claim_disposition: str
    claim_disposition_reason: str
    seed: int = Field(ge=0)
    model: E4ExecutionModel
    scenarios: tuple[E4ExecutionScenario, ...]
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_config(self) -> "E4ExecutionConfig":
        if self.schema_version != E4_EXECUTION_SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {E4_EXECUTION_SCHEMA_VERSION}")
        if self.experiment_id != "E4" or self.claim_id != "C4":
            raise ValueError("executable E4 config requires experiment_id E4 and claim_id C4")
        if self.origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
            raise ValueError("E4 executable evidence origin must equal REPRODUCIBLE_SIMULATION")
        if self.method_boundary != E4_EXECUTION_METHOD_BOUNDARY:
            raise ValueError(f"method_boundary must equal {E4_EXECUTION_METHOD_BOUNDARY}")
        if self.claim_disposition != "INCONCLUSIVE":
            raise ValueError("E4 executable local simulation must keep claim_disposition INCONCLUSIVE")
        if self.claim_disposition_reason != E4_INCONCLUSIVE_REASON:
            raise ValueError(f"claim_disposition_reason must equal {E4_INCONCLUSIVE_REASON}")
        if len({item.scenario_id for item in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenarios must use unique scenario_id values")
        if len({item.kind for item in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenarios must use unique scenario kinds")
        if set(item.kind for item in self.scenarios) != set(E4ScenarioKind):
            raise ValueError("scenarios must contain exactly the seven frozen E4 scenario kinds")
        minimum_withholding = self.model.total_shards - self.model.reconstruction_threshold + 1
        if any(
            item.mutation_count < minimum_withholding
            for item in self.scenarios
            if item.kind in {E4ScenarioKind.RANDOM_WITHHOLDING, E4ScenarioKind.TARGETED_WITHHOLDING}
        ):
            raise ValueError("each withholding mutation_count must cross reconstruction threshold")
        return self


class E4ExecutionRow(_FrozenModel):
    schema_version: str = "POI_MPP_E4_EXECUTION_ROW_V2"
    experiment_id: str = "E4"
    claim_id: str = "C4"
    origin: EvidenceOrigin
    method_boundary: str
    scenario_id: str
    scenario_kind: E4ScenarioKind
    scenario_seed: int
    sampling_mode: str
    assumption_label: str
    expected_status: str
    actual_status: str
    expected_outcome_detected: bool
    layout_hash: str
    certificate_hash: str
    beacon_hash: str
    store_hash_before: str
    store_hash_after: str
    action_indices: tuple[int, ...]
    sample_indices: tuple[int, ...]
    served_indices: tuple[int, ...]
    missing_indices: tuple[int, ...]
    corrupt_indices: tuple[int, ...]
    omitted_indices: tuple[int, ...]
    verified_sample_count: int = Field(ge=0)
    verified_total_shards: int = Field(ge=0)
    reconstruction_threshold: int = Field(gt=0)
    failure_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row(self) -> "E4ExecutionRow":
        if self.origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
            raise ValueError("E4 execution rows must remain REPRODUCIBLE_SIMULATION")
        if self.method_boundary != E4_EXECUTION_METHOD_BOUNDARY:
            raise ValueError("E4 execution row method boundary mismatch")
        if self.expected_outcome_detected != (self.actual_status == self.expected_status):
            raise ValueError("expected_outcome_detected must be derived from actual status")
        return self


class E4ExecutionSummary(_FrozenModel):
    schema_version: str = "POI_MPP_E4_EXECUTION_SUMMARY_V2"
    experiment_id: str = "E4"
    claim_id: str = "C4"
    origin: str
    method_boundary: str
    scenario_count: int
    expected_outcome_detected_count: int
    honest_negative_control_status: str
    adverse_failure_states: tuple[str, ...]
    claim_disposition: str
    claim_disposition_reason: str
    method_limitations: tuple[str, ...]


class E4ReplayReceipt(_FrozenModel):
    schema_version: str = "POI_MPP_E4_REPLAY_RECEIPT_V2"
    artifact_hash: str
    config_hash: str
    verified_file_count: int


@dataclass(frozen=True)
class E4ExecutionResult:
    output_root: Path
    rows_path: Path
    summary_path: Path
    provenance_path: Path
    manifest_path: Path
    rows: tuple[E4ExecutionRow, ...]
    summary: E4ExecutionSummary
    artifact_hash: str


def _read_regular_file(path: Path, *, label: str) -> bytes:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        stat_result = path.stat()
    except OSError as error:
        raise ValueError(f"unable to read {label}") from error
    if not path.is_file() or stat_result.st_nlink != 1:
        raise ValueError(f"{label} must be one regular file")
    return path.read_bytes()


def load_e4_execution_config(path: str | Path) -> E4ExecutionConfig:
    candidate = Path(path)
    payload = _read_regular_file(candidate, label="E4 execution config")
    try:
        raw = yaml.safe_load(payload)
    except yaml.YAMLError as error:
        raise ValueError("unable to parse E4 execution config") from error
    if not isinstance(raw, dict):
        raise ValueError("E4 execution config must be a mapping")
    return E4ExecutionConfig.model_validate(raw)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(payload))
    return path


def _source_closure() -> tuple[dict[str, str], ...]:
    paths = (
        Path(__file__).resolve(),
        REPO_ROOT / "src" / "poi_mpp" / "experiments" / "e4_da.py",
        REPO_ROOT / "src" / "poi_mpp" / "auditor" / "availability" / "sampling.py",
        REPO_ROOT / "src" / "poi_mpp" / "protocol" / "availability.py",
    )
    return tuple(
        {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": _sha256(_read_regular_file(path, label="E4 source dependency")),
        }
        for path in paths
    )


def _hashes(config: E4ExecutionConfig) -> tuple[str, str, str, str]:
    config_material = config.model_dump(mode="json")
    config_hash = digest("E4_EXECUTION_CONFIG_V2", config_material)
    source_closure = _source_closure()
    implementation_hash = digest("E4_EXECUTION_SOURCE_CLOSURE_V2", source_closure)
    model_hash = digest(
        "E4_EXECUTION_MODEL_V2",
        {
            "model": config.model.model_dump(mode="json"),
            "implementation_hash": implementation_hash,
        },
    )
    data_hash = digest(
        "E4_EXECUTION_DATA_V2",
        {
            "seed": config.seed,
            "total_shards": config.model.total_shards,
            "shard_payload_bytes": config.model.shard_payload_bytes,
            "payload_hashes": [
                _sha256(_payload(config, index)) for index in range(config.model.total_shards)
            ],
        },
    )
    return config_hash, model_hash, data_hash, implementation_hash


def _payload(config: E4ExecutionConfig, index: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < config.model.shard_payload_bytes:
        output.extend(
            hashlib.sha256(
                f"POI-MPP:E4:{config.seed}:{index}:{counter}".encode("utf-8")
            ).digest()
        )
        counter += 1
    return bytes(output[: config.model.shard_payload_bytes])


def _store_fingerprint(store: LocalShardStore, layout: Any) -> str:
    return digest(
        "E4_LOCAL_SHARD_STORE_STATE_V2",
        [
            {"index": record.index, "observed_hash": store.shard_hash(layout, record.index)}
            for record in layout.shards
        ],
    )


def _deterministic_rank(indices: tuple[int, ...], *, seed: int, domain: str) -> tuple[int, ...]:
    ranked = sorted(
        indices,
        key=lambda index: digest(
            "E4_SCENARIO_INDEX_RANK_V2",
            {"seed": seed, "domain": domain, "index": index},
        ),
    )
    return tuple(ranked)


def _apply_scenario(
    *,
    config: E4ExecutionConfig,
    scenario: E4ExecutionScenario,
    store: LocalShardStore,
    layout: Any,
    sample_indices: tuple[int, ...],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    all_indices = tuple(range(config.model.total_shards))
    scenario_seed = config.seed + scenario.seed_offset
    action_indices: tuple[int, ...] = ()
    served_indices = sample_indices
    if scenario.kind is E4ScenarioKind.HONEST_NEGATIVE_CONTROL:
        return action_indices, served_indices
    if scenario.kind is E4ScenarioKind.RANDOM_WITHHOLDING:
        ranked = _deterministic_rank(all_indices, seed=scenario_seed, domain="RANDOM_WITHHOLDING")
        action_indices = ranked[: scenario.mutation_count]
        for index in action_indices:
            store.shard_path(index).unlink()
    elif scenario.kind is E4ScenarioKind.TARGETED_WITHHOLDING:
        first = sample_indices[0]
        remainder = tuple(index for index in all_indices if index != first)
        action_indices = (first,) + _deterministic_rank(
            remainder, seed=scenario_seed, domain="TARGETED_WITHHOLDING"
        )[: scenario.mutation_count - 1]
        for index in action_indices:
            store.shard_path(index).unlink()
    elif scenario.kind is E4ScenarioKind.CORRUPT_SHARD:
        target = sample_indices[0]
        action_indices = (target,)
        store.shard_path(target).write_bytes(
            b"POI-MPP-E4-CORRUPT:" + hashlib.sha256(str(scenario_seed).encode()).digest()
        )
    elif scenario.kind is E4ScenarioKind.DUPLICATE_SHARD:
        target = sample_indices[0]
        source = next(index for index in all_indices if index != target)
        action_indices = (target,)
        store.shard_path(target).write_bytes(store.shard_path(source).read_bytes())
    elif scenario.kind is E4ScenarioKind.REORDERED_SHARD:
        first, second = sample_indices[:2]
        first_payload = store.shard_path(first).read_bytes()
        second_payload = store.shard_path(second).read_bytes()
        store.shard_path(first).write_bytes(second_payload)
        store.shard_path(second).write_bytes(first_payload)
        action_indices = (first, second)
    elif scenario.kind is E4ScenarioKind.SELECTIVE_SERVICE:
        action_indices = (sample_indices[0],)
        served_indices = tuple(index for index in sample_indices if index not in action_indices)
    return action_indices, served_indices


def _execute_scenario(
    *,
    config: E4ExecutionConfig,
    scenario: E4ExecutionScenario,
    raw_root: Path,
    data_hash: str,
) -> E4ExecutionRow:
    scenario_root = raw_root / scenario.scenario_id
    store = LocalShardStore(scenario_root / "store")
    erasure = ErasureParameters(
        total_shards=config.model.total_shards,
        reconstruction_threshold=config.model.reconstruction_threshold,
    )
    layout = store.initialize(
        finalized_commitment_hash=digest(
            "E4_FINALIZED_LOCAL_COMMITMENT_V2",
            {"data_hash": data_hash, "model_version": config.model.model_version},
        ),
        erasure=erasure,
        shard_payloads=tuple(_payload(config, index) for index in range(config.model.total_shards)),
    )
    scenario_seed = config.seed + scenario.seed_offset
    beacon = hashlib.sha256(f"POI-MPP:E4:BEACON:{scenario_seed}".encode()).digest()
    certificate = issue_sample_certificate(
        layout=layout,
        store=store,
        beacon=beacon,
        round_index=scenario.seed_offset,
        sample_count=config.model.sample_count,
        replacement=config.model.replacement,
    )
    before_hash = _store_fingerprint(store, layout)
    action_indices, served_indices = _apply_scenario(
        config=config,
        scenario=scenario,
        store=store,
        layout=layout,
        sample_indices=certificate.sample_indices,
    )
    mode_and_assumption = {
        E4ScenarioKind.HONEST_NEGATIVE_CONTROL: (
            SamplingMode.STATIC_WITHOUT_REPLACEMENT,
            SamplingAssumption.STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC,
        ),
        E4ScenarioKind.RANDOM_WITHHOLDING: (
            SamplingMode.STATIC_WITHOUT_REPLACEMENT,
            SamplingAssumption.STATIC_WITHOUT_REPLACEMENT_HYPERGEOMETRIC,
        ),
        E4ScenarioKind.TARGETED_WITHHOLDING: (
            SamplingMode.TARGETED_WITHHOLDING,
            SamplingAssumption.TARGETED_WITHHOLDING_DECLARED,
        ),
        E4ScenarioKind.CORRUPT_SHARD: (
            SamplingMode.CORRELATED_LOSS,
            SamplingAssumption.CORRELATED_LOSS_DECLARED,
        ),
        E4ScenarioKind.DUPLICATE_SHARD: (
            SamplingMode.CORRELATED_LOSS,
            SamplingAssumption.CORRELATED_LOSS_DECLARED,
        ),
        E4ScenarioKind.REORDERED_SHARD: (
            SamplingMode.CORRELATED_LOSS,
            SamplingAssumption.CORRELATED_LOSS_DECLARED,
        ),
        E4ScenarioKind.SELECTIVE_SERVICE: (
            SamplingMode.SELECTIVE_SERVING,
            SamplingAssumption.SELECTIVE_SERVING_DECLARED,
        ),
    }
    mode, assumption = mode_and_assumption[scenario.kind]
    reconstruction = verify_reconstruction(
        layout=layout,
        store=store,
        certificate=certificate,
        mode=mode,
        served_indices=served_indices,
    )
    row = E4ExecutionRow(
        origin=config.origin,
        method_boundary=config.method_boundary,
        scenario_id=scenario.scenario_id,
        scenario_kind=scenario.kind,
        scenario_seed=scenario_seed,
        sampling_mode=mode.value,
        assumption_label=assumption.value,
        expected_status=scenario.expected_status,
        actual_status=reconstruction.status,
        expected_outcome_detected=reconstruction.status == scenario.expected_status,
        layout_hash=digest("E4_EXECUTED_LAYOUT_V2", layout.model_dump(mode="json")),
        certificate_hash=certificate.certificate_hash,
        beacon_hash=certificate.beacon_hash,
        store_hash_before=before_hash,
        store_hash_after=_store_fingerprint(store, layout),
        action_indices=action_indices,
        sample_indices=certificate.sample_indices,
        served_indices=served_indices,
        missing_indices=reconstruction.missing_indices,
        corrupt_indices=reconstruction.corrupt_indices,
        omitted_indices=reconstruction.omitted_indices,
        verified_sample_count=reconstruction.verified_sample_count,
        verified_total_shards=reconstruction.verified_total_shards,
        reconstruction_threshold=reconstruction.reconstruction_threshold,
        failure_reasons=reconstruction.reasons,
    )
    if not row.expected_outcome_detected:
        raise E4ExecutionError(
            f"scenario {scenario.scenario_id} produced {row.actual_status}, expected {row.expected_status}"
        )
    _write_json(scenario_root / "layout.json", layout.model_dump(mode="json"))
    _write_json(scenario_root / "certificate.json", certificate.model_dump(mode="json"))
    _write_json(scenario_root / "observation.json", row.model_dump(mode="json"))
    return row


def _safe_output_root(output_root: str | Path) -> tuple[Path, bool]:
    lexical = Path(output_root).absolute()
    if lexical.is_symlink():
        raise E4ExecutionError("output root must not be a symlink")
    resolved = lexical.resolve(strict=False)
    if resolved == REPO_ROOT.resolve():
        raise E4ExecutionError("output root must not equal the repository root")
    if resolved in REPO_ROOT.resolve().parents:
        raise E4ExecutionError("output root must not contain the repository root")
    existed = resolved.exists()
    if existed:
        if not resolved.is_dir():
            raise E4ExecutionError("output root must be a directory")
        if any(resolved.iterdir()):
            raise E4ExecutionError("output root must be absent or empty")
    return resolved, existed


def _manifest_files(root: Path) -> tuple[dict[str, Any], ...]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        if path.is_symlink():
            raise E4ExecutionError("generated artifact files must not be symlinks")
        payload = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256(payload),
                "size_bytes": len(payload),
            }
        )
    return tuple(files)


def _build_outputs(config: E4ExecutionConfig, root: Path) -> E4ExecutionResult:
    config_hash, model_hash, data_hash, implementation_hash = _hashes(config)
    _write_json(root / "config_snapshot.json", config.model_dump(mode="json"))
    rows = tuple(
        _execute_scenario(
            config=config,
            scenario=scenario,
            raw_root=root / "raw",
            data_hash=data_hash,
        )
        for scenario in sorted(config.scenarios, key=lambda item: item.scenario_id)
    )
    negative_control = next(
        row for row in rows if row.scenario_kind is E4ScenarioKind.HONEST_NEGATIVE_CONTROL
    )
    summary = E4ExecutionSummary(
        origin=config.origin.value,
        method_boundary=config.method_boundary,
        scenario_count=len(rows),
        expected_outcome_detected_count=sum(row.expected_outcome_detected for row in rows),
        honest_negative_control_status=negative_control.actual_status,
        adverse_failure_states=tuple(
            sorted({row.actual_status for row in rows if row is not negative_control})
        ),
        claim_disposition=config.claim_disposition,
        claim_disposition_reason=config.claim_disposition_reason,
        method_limitations=(
            "deterministic local filesystem simulation; no network timing or peer diversity",
            "fixed shard count, threshold, payload generator, and seven frozen scenarios",
            "detects implementation behavior only within this simulated boundary",
        ),
    )
    rows_path = _write_json(root / "e4_execution_rows.json", [row.model_dump(mode="json") for row in rows])
    summary_path = _write_json(root / "e4_execution_summary.json", summary.model_dump(mode="json"))
    provenance = {
        "schema_version": "POI_MPP_E4_EXECUTION_PROVENANCE_V2",
        "experiment_id": config.experiment_id,
        "claim_id": config.claim_id,
        "origin": config.origin.value,
        "method_boundary": config.method_boundary,
        "claim_disposition": config.claim_disposition,
        "claim_disposition_reason": config.claim_disposition_reason,
        "seed": config.seed,
        "config_hash": config_hash,
        "model_hash": model_hash,
        "data_hash": data_hash,
        "implementation_hash": implementation_hash,
        "source_closure": list(_source_closure()),
        "scenario_lineage": [
            {
                "scenario_id": row.scenario_id,
                "layout_hash": row.layout_hash,
                "certificate_hash": row.certificate_hash,
                "store_hash_before": row.store_hash_before,
                "store_hash_after": row.store_hash_after,
            }
            for row in rows
        ],
    }
    provenance_path = _write_json(root / "provenance.json", provenance)
    files = _manifest_files(root)
    manifest_material = {
        "schema_version": E4_EXECUTION_MANIFEST_VERSION,
        "experiment_id": config.experiment_id,
        "claim_id": config.claim_id,
        "origin": config.origin.value,
        "method_boundary": config.method_boundary,
        "config_hash": config_hash,
        "model_hash": model_hash,
        "data_hash": data_hash,
        "implementation_hash": implementation_hash,
        "files": list(files),
    }
    artifact_hash = digest("E4_EXECUTION_ARTIFACT_BUNDLE_V2", manifest_material)
    manifest_path = _write_json(root / "manifest.json", {**manifest_material, "artifact_hash": artifact_hash})
    return E4ExecutionResult(
        output_root=root,
        rows_path=rows_path,
        summary_path=summary_path,
        provenance_path=provenance_path,
        manifest_path=manifest_path,
        rows=rows,
        summary=summary,
        artifact_hash=artifact_hash,
    )


def execute_e4_reconstruction_simulation(
    *,
    config_path: str | Path,
    output_root: str | Path,
) -> E4ExecutionResult:
    """Execute the frozen local simulation into an atomic, deterministic bundle."""

    config = load_e4_execution_config(config_path)
    target, existed = _safe_output_root(output_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.e4-stage-", dir=target.parent))
    try:
        staged = _build_outputs(config, stage)
        if existed:
            target.rmdir()
        os.replace(stage, target)
        return E4ExecutionResult(
            output_root=target,
            rows_path=target / staged.rows_path.relative_to(stage),
            summary_path=target / staged.summary_path.relative_to(stage),
            provenance_path=target / staged.provenance_path.relative_to(stage),
            manifest_path=target / staged.manifest_path.relative_to(stage),
            rows=staged.rows,
            summary=staged.summary,
            artifact_hash=staged.artifact_hash,
        )
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def _validate_manifest(root: Path) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(_read_regular_file(manifest_path, label="E4 manifest"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise E4ExecutionError("unable to parse E4 manifest") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != E4_EXECUTION_MANIFEST_VERSION:
        raise E4ExecutionError("invalid E4 execution manifest schema")
    listed = manifest.get("files")
    if not isinstance(listed, list):
        raise E4ExecutionError("E4 manifest files must be a list")
    seen: set[str] = set()
    for item in listed:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise E4ExecutionError("invalid E4 manifest file entry")
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or item["path"] in seen:
            raise E4ExecutionError("invalid or duplicate E4 manifest path")
        seen.add(item["path"])
        candidate = root / relative
        try:
            payload = _read_regular_file(candidate, label="manifested E4 artifact")
        except ValueError as error:
            raise E4ExecutionError(str(error)) from error
        if _sha256(payload) != item.get("sha256") or len(payload) != item.get("size_bytes"):
            raise E4ExecutionError(f"manifest hash mismatch for {item['path']}")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    expected = seen | {"manifest.json"}
    if actual != expected:
        raise E4ExecutionError("manifest file closure mismatch")
    material = {key: value for key, value in manifest.items() if key != "artifact_hash"}
    if digest("E4_EXECUTION_ARTIFACT_BUNDLE_V2", material) != manifest.get("artifact_hash"):
        raise E4ExecutionError("manifest artifact_hash mismatch")
    return manifest, tuple(listed)


def replay_e4_reconstruction_artifacts(output_root: str | Path) -> E4ReplayReceipt:
    """Verify file closure and reproduce the bundle from its embedded config snapshot."""

    root = Path(output_root)
    if root.is_symlink() or not root.is_dir():
        raise E4ExecutionError("replay root must be a regular directory, not a symlink")
    manifest, files = _validate_manifest(root)
    config_snapshot = root / "config_snapshot.json"
    with tempfile.TemporaryDirectory(prefix="poi-mpp-e4-replay-") as temporary:
        temporary_root = Path(temporary)
        reproduced = execute_e4_reconstruction_simulation(
            config_path=config_snapshot,
            output_root=temporary_root.resolve() / "reproduced",
        )
        if reproduced.artifact_hash != manifest["artifact_hash"]:
            raise E4ExecutionError("deterministic replay artifact hash mismatch")
    return E4ReplayReceipt(
        artifact_hash=manifest["artifact_hash"],
        config_hash=manifest["config_hash"],
        verified_file_count=len(files),
    )
