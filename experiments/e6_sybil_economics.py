from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Callable

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.evidence import (
    ARTIFACT_RECORD_SCHEMA_VERSION,
    ArtifactRegistry,
    ArtifactStage,
    GateDecision,
    ProvenanceBundle,
    artifact_content_material,
    collect_environment,
    digest,
    evaluate_publication_gate,
    freeze_run,
    load_run_config,
    publication_path_ref,
)
from poi_mpp.evidence.config import RunConfig, config_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e6_sybil import (
    E6_CONFIRMATORY_SCOPE,
    E6_SIMULATION_MODEL_VERSION,
    E6ConfirmatoryContract,
    E6SimulationConfig,
    PUBLICATION_EVIDENCE_AUTHORIZED,
    SybilScenario,
    assert_cli_authority_boundary,
    load_e6_confirmatory_contract,
    run_sybil_scenario,
    scenario_contract_hash,
)
from poi_mpp.reporting.e6 import publication_precheck_reasons, summarize_e6_rows


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class E6PublicationPlanEntry(_FrozenModel):
    scenario: SybilScenario
    required_seed: int = Field(ge=0)


class E6PublicationPlan(_FrozenModel):
    schema_version: str = "POI_MPP_E6_PUBLICATION_PLAN_V1"
    contract_path: str
    publication_scope: str
    simulations: int = Field(ge=1)
    required_model_version: str
    entries: tuple[E6PublicationPlanEntry, ...]

    @field_validator("contract_path", "publication_scope", "required_model_version")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @model_validator(mode="after")
    def validate_plan(self) -> "E6PublicationPlan":
        if self.publication_scope != E6_CONFIRMATORY_SCOPE:
            raise ValueError(f"publication_scope must equal {E6_CONFIRMATORY_SCOPE}")
        if self.required_model_version != E6_SIMULATION_MODEL_VERSION:
            raise ValueError(f"required_model_version must equal {E6_SIMULATION_MODEL_VERSION}")
        if len({entry.scenario.scenario_id for entry in self.entries}) != len(self.entries):
            raise ValueError("entries must use unique scenario_id values")
        return self


@dataclass(frozen=True)
class E6PublicationRunResult:
    rows_path: Path
    summary_path: Path
    metadata_path: Path
    rows: tuple[object, ...]
    summary: object
    publication_record: dict[str, object]
    publication_decision: GateDecision
    registry: object
    frozen_artifact_path: Path | None = None


def _load_yaml_mapping(path: str | Path, *, label: str) -> dict[str, object]:
    candidate = Path(path)
    try:
        loaded = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"unable to load {label}: {candidate}") from error
    if not isinstance(loaded, dict):
        raise ValueError(f"{label} must be a mapping")
    return loaded


def _resolve_contained_relative_file(base_dir: Path, relative_path: str, *, label: str) -> Path:
    candidate = (base_dir / relative_path).resolve()
    try:
        candidate.relative_to(REPO_ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"{label} must stay within the repository") from error
    if not candidate.is_file():
        raise ValueError(f"{label} does not exist: {candidate}")
    return candidate


def _atomic_write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def e6_model_hash(contract: E6ConfirmatoryContract) -> str:
    return digest("E6_PUBLICATION_MODEL_HASH", contract.model_dump(mode="json"))


def e6_dataset_hash(plan: E6PublicationPlan) -> str:
    return digest("E6_PUBLICATION_DATASET_HASH", plan.model_dump(mode="json"))


def load_e6_publication_plan(path: str | Path) -> E6PublicationPlan:
    plan_path = Path(path)
    plan = E6PublicationPlan.model_validate(_load_yaml_mapping(plan_path, label="E6 publication plan"))
    contract = load_e6_confirmatory_contract(
        _resolve_contained_relative_file(plan_path.parent, plan.contract_path, label="E6 confirmatory contract")
    )
    if plan.publication_scope != contract.publication_scope:
        raise ValueError("publication_scope must exactly match the confirmatory contract")
    if plan.simulations != contract.required_simulations:
        raise ValueError("simulations must exactly match the confirmatory contract")
    if plan.required_model_version != contract.required_model_version:
        raise ValueError("required_model_version must exactly match the confirmatory contract")
    allowed_by_id = {item.scenario_id: item for item in contract.allowed_scenarios}
    plan_by_id = {entry.scenario.scenario_id: entry for entry in plan.entries}
    if set(plan_by_id) != set(allowed_by_id):
        raise ValueError("entries must exactly close against the confirmatory contract")
    for scenario_id, entry in plan_by_id.items():
        allowed = allowed_by_id[scenario_id]
        if scenario_contract_hash(entry.scenario) != allowed.scenario_contract_hash:
            raise ValueError(f"scenario_contract_hash mismatch for {scenario_id}")
        if entry.required_seed != allowed.required_seed:
            raise ValueError(f"required_seed mismatch for {scenario_id}")
        if entry.scenario.role is not allowed.required_role:
            raise ValueError(f"role mismatch for {scenario_id}")
        if entry.scenario.capacity_model is not allowed.required_capacity_model:
            raise ValueError(f"capacity_model mismatch for {scenario_id}")
    return plan


def _require_cli_authority(
    run_config: RunConfig,
    contract: E6ConfirmatoryContract,
    plan: E6PublicationPlan,
    *,
    publication_authorized: bool,
) -> None:
    if run_config.experiment_id != "E6":
        raise SystemExit("E6 publication CLI requires experiment_id E6")
    if run_config.origin is not contract.required_run_origin:
        raise SystemExit("E6 publication CLI is reserved for REPRODUCIBLE_SIMULATION runs")
    if run_config.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
        raise SystemExit("E6 publication CLI rejects synthetic non-evidence runs")
    if run_config.authorization_scope != contract.required_run_authorization_scope:
        raise SystemExit(
            f"E6 publication CLI requires {PUBLICATION_EVIDENCE_AUTHORIZED} authorization_scope"
        )
    if not publication_authorized:
        raise SystemExit("E6 publication CLI requires explicit --publication-authorized confirmation")
    if run_config.model_hash != e6_model_hash(contract):
        raise SystemExit("run_config.model_hash must equal the frozen E6 confirmatory contract hash")
    if run_config.dataset_hash != e6_dataset_hash(plan):
        raise SystemExit("run_config.dataset_hash must equal the frozen E6 publication plan hash")


def _record_origin(rows: tuple[object, ...]) -> str:
    origins = {row.origin.value for row in rows}
    return next(iter(origins)) if len(origins) == 1 else "MIXED_ROW_ORIGINS"


def _publication_record(
    *,
    summary: object,
    rows: tuple[object, ...],
    run_config: RunConfig,
    provenance_bundle: ProvenanceBundle,
    publication_precheck_reasons: tuple[str, ...],
) -> dict[str, object]:
    origin = _record_origin(rows)
    stage = (
        ArtifactStage.FROZEN.value
        if not publication_precheck_reasons and origin != EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value
        else ArtifactStage.SEMANTICALLY_VALID.value
    )
    record = {
        "schema_version": ARTIFACT_RECORD_SCHEMA_VERSION,
        "artifact_id": "E6-SUMMARY",
        "run_id": run_config.run_id,
        "experiment_id": run_config.experiment_id,
        "origin": origin,
        "stage": stage,
        "parent_hashes": list(run_config.parent_hashes),
        "payload": {
            "scenario_count": summary.scenario_count,
            "support_row_count": summary.support_row_count,
            "negative_control_count": summary.negative_control_count,
            "boundary_row_count": summary.boundary_row_count,
            "epsilon_sybil": summary.epsilon_sybil,
            "minimum_negative_controls": summary.minimum_negative_controls,
        },
        "denominator": summary.denominator,
        "ci_required": True,
        "confidence_interval": [
            min(summary.min_negative_control_lower_advantage, summary.max_support_upper_advantage),
            max(summary.max_negative_control_upper_advantage, summary.max_support_upper_advantage),
        ],
        "claim_id": summary.claim_id,
        "claim_disposition": summary.claim_disposition,
        "provenance": provenance_bundle.manifest.model_dump(mode="json"),
    }
    record["content_hash"] = digest("ARTIFACT_CONTENT", artifact_content_material(record))
    return record


def _default_rows_builder(
    *,
    run_config: RunConfig,
    plan: E6PublicationPlan,
    contract: E6ConfirmatoryContract,
) -> tuple[object, ...]:
    return tuple(
        run_sybil_scenario(
            run_id=run_config.run_id,
            experiment_id=run_config.experiment_id,
            run_config=run_config,
            scenario=entry.scenario,
            config=E6SimulationConfig(
                simulations=plan.simulations,
                seed=entry.required_seed,
                origin=contract.required_run_origin,
                publication_scope=plan.publication_scope,
            ),
        )
        for entry in plan.entries
    )


def run_publication_e6(
    *,
    run_config_path: str | Path,
    contract_path: str | Path,
    plan_path: str | Path,
    output_root: str | Path,
    publication_authorized: bool,
    repo_root: str | Path = REPO_ROOT,
    lock_path: str | Path | None = None,
    registry_root: str | Path | None = None,
    rows_builder: Callable[..., tuple[object, ...]] | None = None,
    environment_collector: Callable[..., object] = collect_environment,
    registry_factory: Callable[[str | Path], object] = ArtifactRegistry,
) -> E6PublicationRunResult:
    run_config = load_run_config(run_config_path)
    contract = load_e6_confirmatory_contract(contract_path)
    plan = load_e6_publication_plan(plan_path)
    _require_cli_authority(run_config, contract, plan, publication_authorized=publication_authorized)
    environment = environment_collector(
        repo_root=Path(repo_root),
        lock_path=Path(lock_path) if lock_path is not None else Path(repo_root) / "requirements.lock",
    )
    provenance_bundle = ProvenanceBundle(
        config=run_config,
        environment=environment,
        manifest=freeze_run(run_config, environment),
    )
    target_output_root = Path(output_root)
    target_output_root.mkdir(parents=True, exist_ok=True)
    registry = registry_factory(registry_root or target_output_root / "registry")
    try:
        rows = (
            rows_builder(run_config=run_config, plan=plan, contract=contract)
            if rows_builder is not None
            else _default_rows_builder(run_config=run_config, plan=plan, contract=contract)
        )
        rows = tuple(rows)
        publication_reasons = publication_precheck_reasons(rows, contract=contract)
        summary = summarize_e6_rows(rows, claim_id="C6", contract=contract)
        record = _publication_record(
            summary=summary,
            rows=rows,
            run_config=run_config,
            provenance_bundle=provenance_bundle,
            publication_precheck_reasons=publication_reasons,
        )
        decision = evaluate_publication_gate(summary.claim_id, [record], provenance_bundles=[provenance_bundle])
        if publication_reasons:
            decision = GateDecision(
                decision.claim_id,
                "INCOMPLETE",
                "INCONCLUSIVE",
                tuple(dict.fromkeys((*publication_reasons, *decision.reasons))),
            )
        frozen_artifact_path = None
        if not publication_reasons and decision.completeness == "COMPLETE":
            frozen_artifact_path = registry.write_atomic(record, provenance_bundle=provenance_bundle)
        rows_path = _atomic_write_json(target_output_root / "e6_rows.json", [row.model_dump(mode="json") for row in rows])
        summary_path = _atomic_write_json(target_output_root / "e6_summary.json", summary.model_dump(mode="json"))
        metadata_path = _atomic_write_json(
            target_output_root / "e6_metadata.json",
            {
                "schema_version": "POI_MPP_E6_PUBLICATION_METADATA_V1",
                "run_config_hash": config_hash(run_config),
                "contract_hash": e6_model_hash(contract),
                "plan_hash": e6_dataset_hash(plan),
                "publication_scope": contract.publication_scope,
                "required_model_version": contract.required_model_version,
                "publication_precheck_reasons": list(publication_reasons),
                "publication_decision": {
                    "claim_id": decision.claim_id,
                    "completeness": decision.completeness,
                    "claim_support": decision.claim_support,
                    "reasons": list(decision.reasons),
                },
                "frozen_artifact_path": publication_path_ref(
                    frozen_artifact_path,
                    repo_root=repo_root,
                ),
            },
        )
        return E6PublicationRunResult(
            rows_path=rows_path,
            summary_path=summary_path,
            metadata_path=metadata_path,
            rows=rows,
            summary=summary,
            publication_record=record,
            publication_decision=decision,
            registry=registry,
            frozen_artifact_path=frozen_artifact_path,
        )
    finally:
        close = getattr(registry, "close", None)
        if callable(close):
            close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or execute the frozen E6 authority boundary.")
    parser.add_argument("--run-config", required=True, help="Path to the frozen run configuration YAML")
    parser.add_argument("--confirmatory-contract", required=True, help="Path to the frozen E6 confirmatory contract YAML")
    parser.add_argument("--plan", help="Path to the frozen E6 publication plan YAML")
    parser.add_argument("--output-root", help="Directory for E6 publication outputs")
    parser.add_argument("--registry-root")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--lock-path")
    parser.add_argument("--publication-authorized", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not (args.plan and args.output_root):
        run_config = load_run_config(args.run_config)
        contract = load_e6_confirmatory_contract(args.confirmatory_contract)
        try:
            assert_cli_authority_boundary(run_config, contract)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        print("E6 publication execution remains manual.", file=sys.stderr)
        return 1
    try:
        run_publication_e6(
            run_config_path=args.run_config,
            contract_path=args.confirmatory_contract,
            plan_path=args.plan,
            output_root=args.output_root,
            publication_authorized=args.publication_authorized,
            repo_root=args.repo_root,
            lock_path=args.lock_path,
            registry_root=args.registry_root,
        )
    except (SystemExit, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
