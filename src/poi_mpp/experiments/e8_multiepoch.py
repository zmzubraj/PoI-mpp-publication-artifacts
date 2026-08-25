"""Deterministic, replay-authoritative E8 multi-epoch simulation artifact."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import config_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e8_consensus import (
    CommitteeScenario,
    E8ResolvedPublicationPlan,
    E8ScenarioRow,
    E8SimulationConfig,
    _atomic_write_json,
    _resolve_existing_plain_file,
    _validate_output_target,
    load_e8_publication_plan,
    run_committee_scenario,
    run_e8_publication_plan,
)


_SCHEMA_VERSION = "POI_MPP_E8_MULTI_EPOCH_ARTIFACT_V1"
_SOURCE_FILES = (
    Path("src/poi_mpp/experiments/e8_consensus.py"),
    Path("src/poi_mpp/experiments/e8_multiepoch.py"),
    Path("experiments/e8_multiepoch_publication.py"),
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class E8BasePlanBinding(_FrozenModel):
    plan_hash: str
    contract_hash: str
    base_source_closure_hash: str
    run_config_hash: str
    model_hash: str
    dataset_hash: str

    @field_validator(
        "plan_hash",
        "contract_hash",
        "base_source_closure_hash",
        "run_config_hash",
        "model_hash",
        "dataset_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("base plan bindings must be lowercase SHA-256 digests")
        return value


class E8EpochArtifact(_FrozenModel):
    epoch: int = Field(ge=1)
    epoch_offset: int = Field(ge=0)
    epoch_lineage_hash: str
    rows: tuple[E8ScenarioRow, ...]

    @field_validator("epoch_lineage_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("epoch_lineage_hash must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def validate_epoch(self) -> "E8EpochArtifact":
        if not self.rows:
            raise ValueError("multi-epoch rows must not be empty")
        if any(row.target_epoch != self.epoch for row in self.rows):
            raise ValueError("multi-epoch rows must bind the declared epoch")
        expected = _epoch_lineage_hash(self.epoch, self.epoch_offset, self.rows)
        if self.epoch_lineage_hash != expected:
            raise ValueError("epoch_lineage_hash must match canonical epoch rows")
        return self


class E8MultiEpochArtifact(_FrozenModel):
    schema_version: str = _SCHEMA_VERSION
    base_plan: E8BasePlanBinding
    plan_hash: str
    contract_hash: str
    run_config_hash: str
    model_hash: str
    dataset_hash: str
    source_closure_hash: str
    origin: EvidenceOrigin
    transition_model: str
    start_epoch: int = Field(ge=1)
    epoch_count: int = Field(ge=3)
    seed_stride: int = Field(gt=0)
    claim_disposition: str
    limitations: tuple[str, ...]
    epochs: tuple[E8EpochArtifact, ...]
    artifact_lineage_hash: str

    @field_validator(
        "plan_hash",
        "contract_hash",
        "run_config_hash",
        "model_hash",
        "dataset_hash",
        "source_closure_hash",
        "artifact_lineage_hash",
    )
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("multi-epoch bindings must be lowercase SHA-256 digests")
        return value

    @model_validator(mode="after")
    def validate_artifact(self) -> "E8MultiEpochArtifact":
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {_SCHEMA_VERSION}")
        if self.origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
            raise ValueError("origin must equal REPRODUCIBLE_SIMULATION")
        if self.claim_disposition != "INCONCLUSIVE":
            raise ValueError("multi-epoch claim_disposition must remain INCONCLUSIVE")
        if self.transition_model != "FROZEN_SCENARIO_REISSUANCE_V1":
            raise ValueError("unsupported multi-epoch transition model")
        if len(self.epochs) != self.epoch_count:
            raise ValueError("epochs must exactly match epoch_count")
        if tuple(item.epoch for item in self.epochs) != tuple(
            range(self.start_epoch, self.start_epoch + self.epoch_count)
        ):
            raise ValueError("epochs must be contiguous from start_epoch")
        if any(row.origin is not self.origin for item in self.epochs for row in item.rows):
            raise ValueError("all multi-epoch rows must remain REPRODUCIBLE_SIMULATION")
        for field_name in ("plan_hash", "contract_hash", "run_config_hash", "model_hash", "dataset_hash"):
            if getattr(self, field_name) != getattr(self.base_plan, field_name):
                raise ValueError(f"{field_name} must bind base_plan")
        if self.artifact_lineage_hash != _artifact_lineage_hash(self):
            raise ValueError("artifact_lineage_hash must match canonical multi-epoch material")
        return self


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_closure_hash(base_source_closure_hash: str) -> str:
    root = _repo_root()
    material: dict[str, str] = {"BASE_E8_PUBLICATION_SOURCE_CLOSURE": base_source_closure_hash}
    for relative_path in _SOURCE_FILES:
        path = root / relative_path
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"E8 multi-epoch source dependency is not a plain file: {relative_path.as_posix()}")
        material[relative_path.as_posix()] = _sha256_file(path)
    return digest("E8_MULTI_EPOCH_SOURCE_CLOSURE", material)


def _epoch_lineage_hash(epoch: int, epoch_offset: int, rows: tuple[E8ScenarioRow, ...]) -> str:
    return digest(
        "E8_MULTI_EPOCH_ROWS",
        {
            "epoch": epoch,
            "epoch_offset": epoch_offset,
            "result_contract_hashes": [row.result_contract_hash for row in rows],
        },
    )


def _lineage_material(artifact: E8MultiEpochArtifact) -> Mapping[str, object]:
    return {
        "schema_version": artifact.schema_version,
        "base_plan": artifact.base_plan.model_dump(mode="json"),
        "source_closure_hash": artifact.source_closure_hash,
        "origin": artifact.origin.value,
        "transition_model": artifact.transition_model,
        "start_epoch": artifact.start_epoch,
        "epoch_count": artifact.epoch_count,
        "seed_stride": artifact.seed_stride,
        "claim_disposition": artifact.claim_disposition,
        "limitations": list(artifact.limitations),
        "epoch_lineage_hashes": [item.epoch_lineage_hash for item in artifact.epochs],
    }


def _artifact_lineage_hash(artifact: E8MultiEpochArtifact) -> str:
    return digest("E8_MULTI_EPOCH_ARTIFACT_LINEAGE", _lineage_material(artifact))


def _shift_scenario(base: CommitteeScenario, *, epoch_offset: int) -> CommitteeScenario:
    return base.model_copy(
        update={
            "target_epoch": base.target_epoch + epoch_offset,
            "task_batches": tuple(
                batch.model_copy(
                    update={
                        "task": batch.task.model_copy(update={"epoch": batch.task.epoch + epoch_offset}),
                        "receipts": tuple(
                            receipt.model_copy(
                                update={
                                    "epoch_issued": receipt.epoch_issued + epoch_offset,
                                    "activated_epoch": (
                                        None
                                        if receipt.activated_epoch is None
                                        else receipt.activated_epoch + epoch_offset
                                    ),
                                }
                            )
                            for receipt in batch.receipts
                        ),
                    }
                )
                for batch in base.task_batches
            ),
        }
    )


def run_e8_multiepoch(plan: E8ResolvedPublicationPlan) -> E8MultiEpochArtifact:
    policy = plan.contract_snapshot.multi_epoch_policy
    base_artifact = run_e8_publication_plan(plan)
    if base_artifact.claim_disposition != policy.required_claim_disposition:
        raise ValueError("multi_epoch_policy disposition must match the frozen base E8 decision rule")
    base_start = min(item.scenario.target_epoch for item in plan.plan_snapshot.scenarios)
    if base_start != policy.start_epoch:
        raise ValueError("multi_epoch_policy start_epoch must match the frozen base plan")

    epoch_artifacts: list[E8EpochArtifact] = []
    for epoch_offset in range(policy.epoch_count):
        epoch = policy.start_epoch + epoch_offset
        rows = tuple(
            run_committee_scenario(
                run_id=plan.plan_snapshot.run_config.run_id,
                experiment_id=plan.plan_snapshot.run_config.experiment_id,
                run_config=plan.plan_snapshot.run_config,
                scenario=_shift_scenario(item.scenario, epoch_offset=epoch_offset),
                config=E8SimulationConfig(
                    simulations=plan.plan_snapshot.simulations,
                    seed=item.seed + epoch_offset * policy.seed_stride,
                    origin=plan.plan_snapshot.run_config.origin,
                    publication_scope=plan.plan_snapshot.publication_scope,
                ),
            )
            for item in plan.plan_snapshot.scenarios
        )
        epoch_artifacts.append(
            E8EpochArtifact(
                epoch=epoch,
                epoch_offset=epoch_offset,
                epoch_lineage_hash=_epoch_lineage_hash(epoch, epoch_offset, rows),
                rows=rows,
            )
        )

    run_config = plan.plan_snapshot.run_config
    base_plan = E8BasePlanBinding(
        plan_hash=plan.plan_hash,
        contract_hash=plan.contract_hash,
        base_source_closure_hash=plan.source_closure_hash,
        run_config_hash=config_hash(run_config),
        model_hash=run_config.model_hash,
        dataset_hash=run_config.dataset_hash,
    )
    material = {
        "schema_version": _SCHEMA_VERSION,
        "base_plan": base_plan,
        "plan_hash": plan.plan_hash,
        "contract_hash": plan.contract_hash,
        "run_config_hash": config_hash(run_config),
        "model_hash": run_config.model_hash,
        "dataset_hash": run_config.dataset_hash,
        "source_closure_hash": _source_closure_hash(plan.source_closure_hash),
        "origin": run_config.origin,
        "transition_model": policy.transition_model,
        "start_epoch": policy.start_epoch,
        "epoch_count": policy.epoch_count,
        "seed_stride": policy.seed_stride,
        "claim_disposition": policy.required_claim_disposition,
        "limitations": (
            "REPRODUCIBLE_SIMULATION only; not live consensus evidence.",
            "Frozen scenarios are reissued independently per epoch; no endogenous adaptation, entry, exit, learning, or network feedback is modeled.",
            "Multi-epoch execution expands deterministic temporal stress coverage but does not establish general consensus security.",
        ),
        "epochs": tuple(epoch_artifacts),
    }
    provisional = E8MultiEpochArtifact.model_construct(**material, artifact_lineage_hash="0" * 64)
    return E8MultiEpochArtifact(**material, artifact_lineage_hash=_artifact_lineage_hash(provisional))


def load_and_run_e8_multiepoch(
    plan_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> E8MultiEpochArtifact:
    plan = load_e8_publication_plan(plan_path)
    artifact = run_e8_multiepoch(plan)
    if output_path is not None:
        target = _validate_output_target(Path(output_path))
        _atomic_write_json(target, artifact.model_dump(mode="json"))
    return artifact


def _load_canonical_json(path: Path) -> dict[str, object]:
    plain_path = _resolve_existing_plain_file(path, label="E8 multi-epoch artifact")
    if os.stat(plain_path).st_nlink != 1:
        raise ValueError("E8 multi-epoch artifact cannot be hardlinked")
    contents = plain_path.read_bytes()
    try:
        payload = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=lambda pairs: (
                (_ for _ in ()).throw(ValueError("duplicate JSON keys are forbidden"))
                if len({key for key, _ in pairs}) != len(pairs)
                else dict(pairs)
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"unable to load E8 multi-epoch artifact: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("E8 multi-epoch artifact must be a JSON object")
    canonical = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if contents != canonical:
        raise ValueError("E8 multi-epoch artifact must use canonical JSON encoding")
    return payload


def load_e8_multiepoch_artifact(
    path: str | Path,
    *,
    plan_path: str | Path | None = None,
) -> E8MultiEpochArtifact:
    payload = _load_canonical_json(Path(path))
    artifact = E8MultiEpochArtifact.model_validate(payload)
    resolved_path = plan_path if plan_path is not None else (
        _repo_root() / "configs" / "confirmatory" / "e8.publication.yaml"
    )
    rerun = load_and_run_e8_multiepoch(resolved_path)
    if artifact.model_dump(mode="json") != rerun.model_dump(mode="json"):
        raise ValueError("E8 multi-epoch artifact does not match deterministic replay")
    return artifact
