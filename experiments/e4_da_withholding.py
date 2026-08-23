from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Callable

import yaml
from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.evidence import (
    ARTIFACT_RECORD_SCHEMA_VERSION,
    ArtifactRegistry,
    ArtifactStage,
    ProvenanceBundle,
    artifact_content_material,
    collect_environment,
    digest,
    evaluate_publication_gate,
    freeze_run,
    load_run_config,
    publication_path_ref,
)
from poi_mpp.evidence.config import config_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e4_da import (
    AuthorityBoundaryError,
    AvailabilityScenario,
    ClaimTarget,
    E4ScenarioRow,
    assert_cli_authority_boundary,
    build_e4_row,
)
from poi_mpp.reporting.e4 import summarize_e4_rows


PUBLICATION_EVIDENCE_AUTHORIZED = "PUBLICATION_EVIDENCE_AUTHORIZED"
E4_CONFIRMATORY_SCOPE = "E4_CONFIRMATORY_PUBLICATION_V1"
E4_MODEL_VERSION = "POI_MPP_E4_DECLARED_SIMULATION_V1"
E4_METHOD_BOUNDARY = "DECLARED_OUTCOME_PLAYBACK"
E4_INCONCLUSIVE_REASON = "DECLARED_OUTCOME_PLAYBACK_NOT_EXECUTED_RECONSTRUCTION"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class E4AllowedScenario(_FrozenModel):
    scenario_id: str
    scenario_hash: str
    required_reconstruction_status: str

    @field_validator("scenario_id", "scenario_hash", "required_reconstruction_status")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("scenario_hash")
    @classmethod
    def validate_hash_shape(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("scenario_hash must be a lowercase SHA-256 hex digest")
        return value


class E4PublicationContract(_FrozenModel):
    schema_version: str = "POI_MPP_E4_CONFIRMATORY_CONTRACT_V1"
    publication_scope: str
    required_run_origin: EvidenceOrigin
    required_run_authorization_scope: str
    required_claim_target: ClaimTarget
    required_model_version: str
    allowed_scenarios: tuple[E4AllowedScenario, ...]
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_contract(self) -> "E4PublicationContract":
        if self.publication_scope != E4_CONFIRMATORY_SCOPE:
            raise ValueError(f"publication_scope must equal {E4_CONFIRMATORY_SCOPE}")
        if self.required_run_origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
            raise ValueError("required_run_origin must equal REPRODUCIBLE_SIMULATION")
        if self.required_run_authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
            raise ValueError(
                f"required_run_authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
            )
        if self.required_claim_target is not ClaimTarget.ATTACK_DETECTION:
            raise ValueError("required_claim_target must equal ATTACK_DETECTION")
        if self.required_model_version != E4_MODEL_VERSION:
            raise ValueError(f"required_model_version must equal {E4_MODEL_VERSION}")
        if len({item.scenario_id for item in self.allowed_scenarios}) != len(self.allowed_scenarios):
            raise ValueError("allowed_scenarios must use unique scenario_id values")
        if len({item.scenario_hash for item in self.allowed_scenarios}) != len(self.allowed_scenarios):
            raise ValueError("allowed_scenarios must use unique scenario_hash values")
        return self


class E4PublicationPlanEntry(_FrozenModel):
    scenario: AvailabilityScenario
    reconstruction_status: str

    @model_validator(mode="after")
    def validate_entry(self) -> "E4PublicationPlanEntry":
        if self.scenario.claim_target is not ClaimTarget.ATTACK_DETECTION:
            raise ValueError("scenario.claim_target must equal ATTACK_DETECTION")
        if self.reconstruction_status != self.scenario.expected_outcome:
            raise ValueError("reconstruction_status must exactly match scenario.expected_outcome")
        return self


class E4PublicationPlan(_FrozenModel):
    schema_version: str = "POI_MPP_E4_PUBLICATION_PLAN_V1"
    contract_path: str
    publication_scope: str
    required_model_version: str
    entries: tuple[E4PublicationPlanEntry, ...]

    @field_validator("contract_path", "publication_scope", "required_model_version")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("plan text fields must not be blank")
        return value

    @model_validator(mode="after")
    def validate_plan(self) -> "E4PublicationPlan":
        if self.publication_scope != E4_CONFIRMATORY_SCOPE:
            raise ValueError(f"publication_scope must equal {E4_CONFIRMATORY_SCOPE}")
        if self.required_model_version != E4_MODEL_VERSION:
            raise ValueError(f"required_model_version must equal {E4_MODEL_VERSION}")
        if len({entry.scenario.scenario_id for entry in self.entries}) != len(self.entries):
            raise ValueError("entries must use unique scenario_id values")
        return self


class E4ResolvedPublicationPlanEntry(_FrozenModel):
    scenario: AvailabilityScenario
    reconstruction_status: str
    expected_row: E4ScenarioRow


class E4ResolvedPublicationPlan(_FrozenModel):
    schema_version: str = "POI_MPP_E4_RESOLVED_PUBLICATION_PLAN_V1"
    publication_scope: str
    required_model_version: str
    entries: tuple[E4ResolvedPublicationPlanEntry, ...]


@dataclass(frozen=True)
class E4PublicationRunResult:
    rows_path: Path
    summary_path: Path
    metadata_path: Path
    rows: tuple[E4ScenarioRow, ...]
    summary: object
    publication_record: dict[str, object]
    publication_decision: object
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


def e4_scenario_hash(scenario: AvailabilityScenario) -> str:
    return digest("E4_PUBLICATION_SCENARIO", scenario.model_dump(mode="json"))


def e4_model_hash(contract: E4PublicationContract) -> str:
    return digest("E4_PUBLICATION_MODEL_HASH", contract.model_dump(mode="json"))


def e4_dataset_hash(plan: E4ResolvedPublicationPlan) -> str:
    return digest("E4_PUBLICATION_DATASET_HASH", plan.model_dump(mode="json"))


def load_e4_publication_contract(path: str | Path) -> E4PublicationContract:
    raw = _load_yaml_mapping(path, label="E4 confirmatory contract")
    return E4PublicationContract.model_validate(raw)


def load_e4_publication_plan(path: str | Path) -> E4ResolvedPublicationPlan:
    plan_path = Path(path)
    raw = _load_yaml_mapping(plan_path, label="E4 publication plan")
    plan = E4PublicationPlan.model_validate(raw)
    contract = load_e4_publication_contract(
        _resolve_contained_relative_file(plan_path.parent, plan.contract_path, label="E4 confirmatory contract")
    )
    if plan.publication_scope != contract.publication_scope:
        raise ValueError("publication_scope must exactly match the confirmatory contract")
    if plan.required_model_version != contract.required_model_version:
        raise ValueError("required_model_version must exactly match the confirmatory contract")
    allowed_by_id = {item.scenario_id: item for item in contract.allowed_scenarios}
    plan_by_id = {entry.scenario.scenario_id: entry for entry in plan.entries}
    if set(plan_by_id) != set(allowed_by_id):
        raise ValueError("entries must exactly close against the confirmatory contract")
    resolved_entries: list[E4ResolvedPublicationPlanEntry] = []
    for scenario_id, entry in plan_by_id.items():
        allowed = allowed_by_id[scenario_id]
        if e4_scenario_hash(entry.scenario) != allowed.scenario_hash:
            raise ValueError(f"scenario_hash mismatch for {scenario_id}")
        if entry.reconstruction_status != allowed.required_reconstruction_status:
            raise ValueError(f"reconstruction_status mismatch for {scenario_id}")
        expected_row = build_e4_row(
            run_id="PLAN-CLOSURE",
            experiment_id="E4",
            origin=contract.required_run_origin,
            scenario=entry.scenario,
            reconstruction=SimpleNamespace(status=entry.reconstruction_status),
        )
        resolved_entries.append(
            E4ResolvedPublicationPlanEntry(
                scenario=entry.scenario,
                reconstruction_status=entry.reconstruction_status,
                expected_row=expected_row,
            )
        )
    return E4ResolvedPublicationPlan(
        publication_scope=plan.publication_scope,
        required_model_version=plan.required_model_version,
        entries=tuple(sorted(resolved_entries, key=lambda item: item.scenario.scenario_id)),
    )


def _require_cli_authority(
    run_config,
    contract: E4PublicationContract,
    plan: E4ResolvedPublicationPlan,
    *,
    publication_authorized: bool,
) -> None:
    if run_config.experiment_id != "E4":
        raise SystemExit("E4 publication CLI requires experiment_id E4")
    if run_config.origin is not contract.required_run_origin:
        raise SystemExit("E4 publication CLI is reserved for REPRODUCIBLE_SIMULATION runs")
    if run_config.authorization_scope != contract.required_run_authorization_scope:
        raise SystemExit(
            f"E4 publication CLI requires {PUBLICATION_EVIDENCE_AUTHORIZED} authorization_scope"
        )
    if not publication_authorized:
        raise SystemExit("E4 publication CLI requires explicit --publication-authorized confirmation")
    if run_config.model_hash != e4_model_hash(contract):
        raise SystemExit("run_config.model_hash must equal the frozen E4 confirmatory contract hash")
    if run_config.dataset_hash != e4_dataset_hash(plan):
        raise SystemExit("run_config.dataset_hash must equal the frozen E4 publication plan hash")


def _publication_record(
    *,
    summary: object,
    rows: tuple[E4ScenarioRow, ...],
    run_config,
    provenance_bundle: ProvenanceBundle,
) -> dict[str, object]:
    origins = {row.origin.value for row in rows}
    origin = next(iter(origins)) if len(origins) == 1 else "MIXED_ROW_ORIGINS"
    record = {
        "schema_version": ARTIFACT_RECORD_SCHEMA_VERSION,
        "artifact_id": "E4-SUMMARY",
        "run_id": run_config.run_id,
        "experiment_id": run_config.experiment_id,
        "origin": origin,
        "stage": ArtifactStage.FROZEN.value,
        "parent_hashes": list(run_config.parent_hashes),
        "payload": {
            "scenario_count": summary.scenario_count,
            "exact_scenario_count": summary.exact_scenario_count,
            "observed_scenario_count": summary.observed_scenario_count,
            "expected_outcome_detected_count": summary.expected_outcome_detected_count,
            "claim_target": summary.claim_target.value,
            "method_boundary": E4_METHOD_BOUNDARY,
            "claim_disposition_reason": E4_INCONCLUSIVE_REASON,
        },
        "denominator": summary.denominator,
        "ci_required": True,
        "confidence_interval": [0.0, summary.maximum_supported_interval_width],
        "claim_id": summary.claim_id,
        "claim_disposition": summary.claim_disposition,
        "provenance": provenance_bundle.manifest.model_dump(mode="json"),
    }
    record["content_hash"] = digest("ARTIFACT_CONTENT", artifact_content_material(record))
    return record


def run_publication_e4(
    *,
    config_path: str | Path,
    contract_path: str | Path,
    plan_path: str | Path,
    output_root: str | Path,
    publication_authorized: bool,
    repo_root: str | Path = REPO_ROOT,
    lock_path: str | Path | None = None,
    registry_root: str | Path | None = None,
    environment_collector: Callable[..., object] = collect_environment,
    registry_factory: Callable[[str | Path], object] = ArtifactRegistry,
) -> E4PublicationRunResult:
    run_config = load_run_config(config_path)
    contract = load_e4_publication_contract(contract_path)
    plan = load_e4_publication_plan(plan_path)
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
        rows = tuple(
            build_e4_row(
                run_id=run_config.run_id,
                experiment_id=run_config.experiment_id,
                origin=run_config.origin,
                scenario=entry.scenario,
                reconstruction=SimpleNamespace(status=entry.reconstruction_status),
            )
            for entry in plan.entries
        )
        summary = summarize_e4_rows(rows, claim_id="C4").model_copy(
            update={"claim_disposition": "INCONCLUSIVE"}
        )
        record = _publication_record(
            summary=summary,
            rows=rows,
            run_config=run_config,
            provenance_bundle=provenance_bundle,
        )
        decision = evaluate_publication_gate(summary.claim_id, [record], provenance_bundles=[provenance_bundle])
        decision = replace(
            decision,
            reasons=tuple(dict.fromkeys((*decision.reasons, E4_INCONCLUSIVE_REASON))),
        )
        frozen_artifact_path = registry.write_atomic(record, provenance_bundle=provenance_bundle) if decision.completeness == "COMPLETE" else None
        rows_path = _atomic_write_json(target_output_root / "e4_rows.json", [row.model_dump(mode="json") for row in rows])
        summary_path = _atomic_write_json(target_output_root / "e4_summary.json", summary.model_dump(mode="json"))
        metadata_path = _atomic_write_json(
            target_output_root / "e4_metadata.json",
            {
                "schema_version": "POI_MPP_E4_PUBLICATION_METADATA_V1",
                "run_config_hash": config_hash(run_config),
                "contract_hash": e4_model_hash(contract),
                "plan_hash": e4_dataset_hash(plan),
                "publication_scope": contract.publication_scope,
                "required_model_version": contract.required_model_version,
                "method_boundary": E4_METHOD_BOUNDARY,
                "claim_disposition_reason": E4_INCONCLUSIVE_REASON,
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
        return E4PublicationRunResult(
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or execute the frozen E4 authority boundary.")
    parser.add_argument("--config", required=True, help="Path to a frozen E4 run configuration.")
    parser.add_argument("--contract", help="Path to the frozen E4 confirmatory contract YAML.")
    parser.add_argument("--plan", help="Path to the frozen E4 publication plan YAML.")
    parser.add_argument("--output-root", help="Directory for E4 publication outputs.")
    parser.add_argument("--registry-root", help="Directory for the publication registry root.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--lock-path")
    parser.add_argument("--publication-authorized", action="store_true")
    args = parser.parse_args(argv)

    if not (args.contract and args.plan and args.output_root):
        try:
            run_config = load_run_config(Path(args.config))
            assert_cli_authority_boundary(run_config)
        except (AuthorityBoundaryError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 2
        return 0

    try:
        run_publication_e4(
            config_path=args.config,
            contract_path=args.contract,
            plan_path=args.plan,
            output_root=args.output_root,
            publication_authorized=args.publication_authorized,
            repo_root=args.repo_root,
            lock_path=args.lock_path,
            registry_root=args.registry_root,
        )
    except (SystemExit, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
