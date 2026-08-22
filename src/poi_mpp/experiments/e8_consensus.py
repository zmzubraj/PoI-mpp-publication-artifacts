"""Deterministic E8 next-epoch committee simulation with replay-authoritative rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import yaml
from yaml.tokens import AliasToken, AnchorToken
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.config import RunConfig, config_hash, load_run_config
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.protocol.committee import sample_committee
from poi_mpp.protocol.credit import allocate_credit, derive_active_weight
from poi_mpp.protocol.types import AuditDecision, Receipt, ReceiptState, TaskClass, TaskSpec


PUBLICATION_EVIDENCE_AUTHORIZED = "PUBLICATION_EVIDENCE_AUTHORIZED"
E8_CONFIRMATORY_SCOPE = "E8_CONFIRMATORY_PUBLICATION_V1"
MIN_SUPPORTED_SIMULATIONS = 128
MAX_REPLAY_SIMULATIONS = 2048
E8_SIMULATION_MODEL_VERSION = "POI_MPP_E8_SIMULATOR_V1"
COMMITTEE_ALGORITHM_VERSION = "POI_MPP_COMMITTEE_SAMPLER_SHA256_NO_REPLACEMENT_V1"
_MICRO_QUANTUM = Decimal("0.000001")
_WILSON_Z = 1.959963984540054


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CommitteeScenarioRole(StrEnum):
    SUPPORT = "SUPPORT"
    NEGATIVE_CONTROL = "NEGATIVE_CONTROL"
    BOUNDARY = "BOUNDARY"


class CommitteeAblation(StrEnum):
    NONE = "NONE"
    HIGH_COMPUTE = "HIGH_COMPUTE"
    SYBIL_SPLIT = "SYBIL_SPLIT"
    COLLATERAL_RICH_ZERO_CREDIT = "COLLATERAL_RICH_ZERO_CREDIT"
    SUBSIDIZED_COMPUTE = "SUBSIDIZED_COMPUTE"
    COLLUSION = "COLLUSION"
    MISSING_RECEIPTS = "MISSING_RECEIPTS"
    CHURN = "CHURN"
    CONCENTRATION_CAP_REMOVED = "CONCENTRATION_CAP_REMOVED"


class OperatorClass(StrEnum):
    ATTACKER = "ATTACKER"
    HONEST = "HONEST"


class SamplingDisposition(StrEnum):
    COMMITTEE_SAMPLED = "COMMITTEE_SAMPLED"
    ZERO_TOTAL_WEIGHT = "ZERO_TOTAL_WEIGHT"
    INSUFFICIENT_ELIGIBLE_OPERATORS = "INSUFFICIENT_ELIGIBLE_OPERATORS"


class E8SeedPolicy(StrEnum):
    FIXED_PER_SCENARIO = "FIXED_PER_SCENARIO"


class AuthorityBoundaryError(ValueError):
    """Raised when the E8 CLI would overstate publication authority."""


_REQUIRED_PUBLICATION_SCENARIO_IDS = (
    "support-honest-baseline",
    "support-high-compute-capped",
    "support-sybil-split",
    "support-subsidized-compute",
    "support-collusion-bounded",
    "support-receipt-churn",
    "negative-cap-removed",
    "boundary-zero-credit-rich",
    "boundary-pending-only",
    "boundary-zero-total-weight",
)


class OperatorProfile(_FrozenModel):
    operator_id: str
    operator_class: OperatorClass
    collateral_micros: int = Field(ge=0)
    compute_cost_micros: int = Field(ge=0)
    compute_subsidy_micros: int = Field(ge=0)

    @field_validator("operator_id")
    @classmethod
    def require_nonblank_operator_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("operator_id must not be blank")
        return value


class WorkerBinding(_FrozenModel):
    worker_id: str
    operator_id: str

    @field_validator("worker_id", "operator_id")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value


class CommitteeTaskBatch(_FrozenModel):
    task: TaskSpec
    receipts: tuple[Receipt, ...]

    @model_validator(mode="after")
    def validate_receipt_bindings(self) -> "CommitteeTaskBatch":
        for receipt in self.receipts:
            if receipt.task_id != self.task.task_id:
                raise ValueError("receipts must bind the containing task.task_id")
        return self


class CommitteeScenario(_FrozenModel):
    scenario_id: str
    role: CommitteeScenarioRole
    ablation: CommitteeAblation
    committee_size: int = Field(gt=0)
    target_epoch: int = Field(ge=0)
    beta_micros: int = Field(gt=0)
    concentration_cap_micros: int = Field(ge=0)
    attacker_operator_ids: tuple[str, ...]
    operator_profiles: tuple[OperatorProfile, ...]
    worker_bindings: tuple[WorkerBinding, ...]
    task_batches: tuple[CommitteeTaskBatch, ...]

    @field_validator("scenario_id")
    @classmethod
    def require_nonblank_scenario_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scenario_id must not be blank")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> "CommitteeScenario":
        if not self.operator_profiles:
            raise ValueError("operator_profiles must not be empty")
        if not self.worker_bindings:
            raise ValueError("worker_bindings must not be empty")
        if not self.task_batches:
            raise ValueError("task_batches must not be empty")
        operator_ids = [profile.operator_id for profile in self.operator_profiles]
        if len(set(operator_ids)) != len(operator_ids):
            raise ValueError("operator_profiles must use unique operator_id values")
        if len(set(self.attacker_operator_ids)) != len(self.attacker_operator_ids):
            raise ValueError("attacker_operator_ids must be unique")
        unknown_attackers = set(self.attacker_operator_ids) - set(operator_ids)
        if unknown_attackers:
            raise ValueError("attacker_operator_ids must reference known operator profiles")
        worker_ids = [binding.worker_id for binding in self.worker_bindings]
        if len(set(worker_ids)) != len(worker_ids):
            raise ValueError("worker_bindings must use unique worker_id values")
        unknown_bindings = {binding.operator_id for binding in self.worker_bindings} - set(operator_ids)
        if unknown_bindings:
            raise ValueError("worker_bindings must reference known operator profiles")
        return self


class E8AllowedScenario(_FrozenModel):
    scenario_id: str
    scenario_contract_hash: str
    required_role: CommitteeScenarioRole
    required_ablation: CommitteeAblation
    required_seed: int = Field(ge=0)
    support_assertions: "E8SupportAssertions | None" = None
    boundary_assertions: "E8BoundaryAssertions | None" = None
    negative_assertions: "E8NegativeAssertions | None" = None

    @field_validator("scenario_id", "scenario_contract_hash")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("scenario_contract_hash")
    @classmethod
    def validate_hash_shape(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("scenario_contract_hash must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def validate_role_assertions(self) -> "E8AllowedScenario":
        placeholder_hashes = {character * 64 for character in "0123456789abcdef"}
        if self.scenario_contract_hash in placeholder_hashes:
            raise ValueError("scenario_contract_hash cannot use a placeholder or sentinel digest")
        if self.required_role is CommitteeScenarioRole.SUPPORT:
            if self.support_assertions is None:
                raise ValueError("support scenarios require support_assertions")
            if self.boundary_assertions is not None or self.negative_assertions is not None:
                raise ValueError("support scenarios cannot declare boundary or negative assertions")
        elif self.required_role is CommitteeScenarioRole.BOUNDARY:
            if self.boundary_assertions is None:
                raise ValueError("boundary scenarios require boundary_assertions")
            if self.support_assertions is not None or self.negative_assertions is not None:
                raise ValueError("boundary scenarios cannot declare support or negative assertions")
        elif self.required_role is CommitteeScenarioRole.NEGATIVE_CONTROL:
            if self.negative_assertions is None:
                raise ValueError("negative-control scenarios require negative_assertions")
            if self.support_assertions is not None or self.boundary_assertions is not None:
                raise ValueError("negative-control scenarios cannot declare support or boundary assertions")
        return self


class E8SupportAssertions(_FrozenModel):
    max_attacker_active_weight_share: float = Field(ge=0.0, le=1.0)
    max_attacker_weight_probability_ge_one_third: float = Field(ge=0.0, le=1.0)
    max_attacker_weight_probability_ge_one_third_upper_bound: float = Field(ge=0.0, le=1.0)
    max_attacker_weight_probability_ge_two_thirds: float = Field(ge=0.0, le=1.0)
    max_attacker_weight_probability_ge_two_thirds_upper_bound: float = Field(ge=0.0, le=1.0)
    max_attacker_seat_probability_ge_one_third: float = Field(ge=0.0, le=1.0)
    max_attacker_seat_probability_ge_one_third_upper_bound: float = Field(ge=0.0, le=1.0)
    max_attacker_seat_probability_ge_two_thirds: float = Field(ge=0.0, le=1.0)
    max_attacker_seat_probability_ge_two_thirds_upper_bound: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_coherence(self) -> "E8SupportAssertions":
        probability_caps = (
            self.max_attacker_active_weight_share,
            self.max_attacker_weight_probability_ge_one_third,
            self.max_attacker_weight_probability_ge_one_third_upper_bound,
            self.max_attacker_weight_probability_ge_two_thirds,
            self.max_attacker_weight_probability_ge_two_thirds_upper_bound,
            self.max_attacker_seat_probability_ge_one_third,
            self.max_attacker_seat_probability_ge_one_third_upper_bound,
            self.max_attacker_seat_probability_ge_two_thirds,
            self.max_attacker_seat_probability_ge_two_thirds_upper_bound,
        )
        if any(value >= 1.0 for value in probability_caps):
            raise ValueError("support assertion probability caps must be strictly less than 1.0")
        if (
            self.max_attacker_weight_probability_ge_one_third_upper_bound
            < self.max_attacker_weight_probability_ge_one_third
        ):
            raise ValueError("weight >=1/3 upper-bound cap must be >= the point cap")
        if (
            self.max_attacker_weight_probability_ge_two_thirds_upper_bound
            < self.max_attacker_weight_probability_ge_two_thirds
        ):
            raise ValueError("weight >=2/3 upper-bound cap must be >= the point cap")
        if (
            self.max_attacker_seat_probability_ge_one_third_upper_bound
            < self.max_attacker_seat_probability_ge_one_third
        ):
            raise ValueError("seat >=1/3 upper-bound cap must be >= the point cap")
        if (
            self.max_attacker_seat_probability_ge_two_thirds_upper_bound
            < self.max_attacker_seat_probability_ge_two_thirds
        ):
            raise ValueError("seat >=2/3 upper-bound cap must be >= the point cap")
        if (
            self.max_attacker_weight_probability_ge_two_thirds
            > self.max_attacker_weight_probability_ge_one_third
        ):
            raise ValueError("weight >=2/3 point cap must be <= the weight >=1/3 point cap")
        if (
            self.max_attacker_weight_probability_ge_two_thirds_upper_bound
            > self.max_attacker_weight_probability_ge_one_third_upper_bound
        ):
            raise ValueError("weight >=2/3 upper-bound cap must be <= the weight >=1/3 upper-bound cap")
        if (
            self.max_attacker_seat_probability_ge_two_thirds
            > self.max_attacker_seat_probability_ge_one_third
        ):
            raise ValueError("seat >=2/3 point cap must be <= the seat >=1/3 point cap")
        if (
            self.max_attacker_seat_probability_ge_two_thirds_upper_bound
            > self.max_attacker_seat_probability_ge_one_third_upper_bound
        ):
            raise ValueError("seat >=2/3 upper-bound cap must be <= the seat >=1/3 upper-bound cap")
        return self


class E8BoundaryAssertions(_FrozenModel):
    required_sampling_disposition: SamplingDisposition
    required_total_active_weight_micros: int = Field(ge=0)
    required_attacker_active_weight_micros: int = Field(ge=0)
    require_zero_credit_implies_zero_weight: bool = True


class E8NegativeAssertions(_FrozenModel):
    pair_id: str
    paired_support_scenario_id: str
    paired_support_scenario_hash: str
    required_pair_exogenous_hash: str
    min_attacker_active_weight_share_delta: float = Field(ge=0.0, le=1.0)
    min_attacker_weight_probability_ge_one_third_lower_advantage: float | None = Field(default=None, ge=0.0, le=1.0)
    min_attacker_weight_probability_ge_two_thirds_lower_advantage: float | None = Field(default=None, ge=0.0, le=1.0)
    min_attacker_seat_probability_ge_one_third_lower_advantage: float | None = Field(default=None, ge=0.0, le=1.0)
    min_attacker_seat_probability_ge_two_thirds_lower_advantage: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("pair_id", "paired_support_scenario_id", "paired_support_scenario_hash", "required_pair_exogenous_hash")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("paired_support_scenario_hash", "required_pair_exogenous_hash")
    @classmethod
    def validate_hash_shape(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("negative-control assertion hashes must be lowercase SHA-256 hex digests")
        return value

    @model_validator(mode="after")
    def validate_nonvacuous_deltas(self) -> "E8NegativeAssertions":
        if self.min_attacker_active_weight_share_delta <= 0.0:
            raise ValueError("negative-control attacker active-weight-share delta must be nonzero")
        optional_deltas = (
            self.min_attacker_weight_probability_ge_one_third_lower_advantage,
            self.min_attacker_weight_probability_ge_two_thirds_lower_advantage,
            self.min_attacker_seat_probability_ge_one_third_lower_advantage,
            self.min_attacker_seat_probability_ge_two_thirds_lower_advantage,
        )
        if all(value is None for value in optional_deltas):
            raise ValueError("negative-control assertions must include at least one non-null probabilistic delta")
        for value in optional_deltas:
            if value is not None and value <= 0.0:
                raise ValueError("negative-control probabilistic deltas must be strictly positive when declared")
        return self


class E8ConfirmatoryContract(_FrozenModel):
    schema_version: str = "POI_MPP_E8_CONFIRMATORY_CONTRACT_V1"
    publication_scope: str
    required_run_origin: EvidenceOrigin
    required_run_authorization_scope: str
    required_simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS)
    maximum_replay_simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS, le=MAX_REPLAY_SIMULATIONS)
    required_model_version: str
    required_committee_size: int = Field(gt=0)
    required_algorithm_version: str
    required_target_epoch_delta: int = Field(gt=0)
    minimum_scenario_breadth: int = Field(ge=1)
    minimum_negative_controls: int = Field(ge=1)
    minimum_boundary_rows: int = Field(ge=1)
    seed_policy: E8SeedPolicy
    allowed_scenarios: tuple[E8AllowedScenario, ...]
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_contract(self) -> "E8ConfirmatoryContract":
        if self.schema_version != "POI_MPP_E8_CONFIRMATORY_CONTRACT_V1":
            raise ValueError("schema_version must equal POI_MPP_E8_CONFIRMATORY_CONTRACT_V1")
        if self.publication_scope != E8_CONFIRMATORY_SCOPE:
            raise ValueError(f"publication_scope must equal {E8_CONFIRMATORY_SCOPE}")
        if self.required_run_origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
            raise ValueError("required_run_origin must equal REPRODUCIBLE_SIMULATION")
        if self.required_run_authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
            raise ValueError(
                f"required_run_authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
            )
        if self.required_model_version != E8_SIMULATION_MODEL_VERSION:
            raise ValueError(f"required_model_version must equal {E8_SIMULATION_MODEL_VERSION}")
        if self.required_algorithm_version != COMMITTEE_ALGORITHM_VERSION:
            raise ValueError(f"required_algorithm_version must equal {COMMITTEE_ALGORITHM_VERSION}")
        if self.required_target_epoch_delta != 1:
            raise ValueError("required_target_epoch_delta must equal 1")
        if not self.allowed_scenarios:
            raise ValueError("allowed_scenarios must not be empty")
        if len({item.scenario_id for item in self.allowed_scenarios}) != len(self.allowed_scenarios):
            raise ValueError("allowed_scenarios must use unique scenario_id values")
        if len({item.scenario_contract_hash for item in self.allowed_scenarios}) != len(self.allowed_scenarios):
            raise ValueError("allowed_scenarios must use unique scenario_contract_hash values")
        if tuple(item.scenario_id for item in self.allowed_scenarios) != _REQUIRED_PUBLICATION_SCENARIO_IDS:
            raise ValueError("allowed_scenarios must exactly match the frozen E8 publication scenario closure")
        negative_controls = sum(
            1 for item in self.allowed_scenarios if item.required_role is CommitteeScenarioRole.NEGATIVE_CONTROL
        )
        if negative_controls < self.minimum_negative_controls:
            raise ValueError("allowed_scenarios must include at least minimum_negative_controls negative scenarios")
        boundary_rows = sum(
            1 for item in self.allowed_scenarios if item.required_role is CommitteeScenarioRole.BOUNDARY
        )
        if boundary_rows < self.minimum_boundary_rows:
            raise ValueError("allowed_scenarios must include at least minimum_boundary_rows boundary scenarios")
        if self.minimum_scenario_breadth < len(_REQUIRED_PUBLICATION_SCENARIO_IDS):
            raise ValueError("minimum_scenario_breadth cannot weaken the frozen E8 publication closure")
        allowed_by_id = {item.scenario_id: item for item in self.allowed_scenarios}
        for item in self.allowed_scenarios:
            if item.required_role is not CommitteeScenarioRole.NEGATIVE_CONTROL:
                continue
            assert item.negative_assertions is not None
            pair = item.negative_assertions
            paired = allowed_by_id.get(pair.paired_support_scenario_id)
            if paired is None:
                raise ValueError("negative-control scenarios must pair to a declared support scenario")
            if paired.required_role is not CommitteeScenarioRole.SUPPORT:
                raise ValueError("negative-control pairs must reference support scenarios")
            if paired.scenario_contract_hash != pair.paired_support_scenario_hash:
                raise ValueError("negative-control paired_support_scenario_hash must match the paired support entry")
        return self


_PLACEHOLDER_DIGESTS = frozenset(character * 64 for character in "0123456789abcdef")
_E8_PUBLICATION_PLAN_SCHEMA_VERSION = "POI_MPP_E8_PUBLICATION_PLAN_V1"
_E8_PUBLICATION_ARTIFACT_SCHEMA_VERSION = "POI_MPP_E8_PUBLICATION_ARTIFACT_V1"


class _StrictYAMLLoader(yaml.SafeLoader):
    pass


def _construct_mapping_without_duplicates(
    loader: _StrictYAMLLoader,
    node: yaml.nodes.MappingNode,
    *,
    deep: bool = False,
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictYAMLLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_without_duplicates,
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_placeholder_digest(value: str) -> bool:
    return value in _PLACEHOLDER_DIGESTS


def _reject_yaml_aliases(text: str, *, label: str) -> None:
    try:
        for token in yaml.scan(text):
            if isinstance(token, (AliasToken, AnchorToken)):
                raise ValueError(f"{label} cannot contain YAML anchors or aliases")
    except yaml.YAMLError as error:
        raise ValueError(f"unable to parse {label}") from error


def _load_strict_yaml_mapping(path: Path, *, label: str) -> tuple[dict[str, object], bytes]:
    try:
        contents = path.read_bytes()
    except OSError as error:
        raise ValueError(f"unable to load {label}: {path}") from error
    text = contents.decode("utf-8")
    _reject_yaml_aliases(text, label=label)
    try:
        loaded = yaml.load(text, Loader=_StrictYAMLLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"unable to load {label}: {path}") from error
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return dict(loaded), contents


def _resolve_existing_plain_file(path: str | Path, *, label: str) -> Path:
    candidate = Path(path)
    current = candidate
    while True:
        if current.exists() and os.path.islink(current):
            raise ValueError(f"{label} cannot be symlinked: {candidate}")
        if current == current.parent:
            break
        current = current.parent
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError(f"{label} is missing: {candidate}") from error
    if not resolved.is_file():
        raise ValueError(f"{label} must be a regular file: {candidate}")
    if os.path.islink(resolved):
        raise ValueError(f"{label} cannot be symlinked: {candidate}")
    if os.stat(resolved).st_nlink != 1:
        raise ValueError(f"{label} cannot be hardlinked: {candidate}")
    return resolved


def _resolve_contained_relative_file(base_dir: Path, relative_path: str, *, label: str) -> Path:
    if not relative_path.strip():
        raise ValueError(f"{label} must not be blank")
    candidate = base_dir / relative_path
    resolved = _resolve_existing_plain_file(candidate, label=label)
    try:
        resolved.relative_to(base_dir.resolve(strict=True))
    except ValueError as error:
        raise ValueError(f"{label} must stay inside {base_dir}") from error
    return resolved


def _validate_output_target(path: Path) -> Path:
    candidate = path if path.is_absolute() else Path.cwd() / path
    if candidate.exists():
        if not candidate.is_file():
            raise ValueError(f"E8 publication output must be a regular file: {path}")
        if os.path.islink(candidate):
            raise ValueError(f"E8 publication output cannot be symlinked: {path}")
        if os.stat(candidate).st_nlink != 1:
            raise ValueError(f"E8 publication output cannot be hardlinked: {path}")
    return candidate


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        if path.read_bytes() != contents:
            raise ValueError(f"atomic E8 publication write verification failed for {path}")
        if os.stat(path).st_nlink != 1:
            raise ValueError(f"E8 publication output cannot be hardlinked: {path}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return _sha256_bytes(contents)


def _path_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _e8_publication_source_closure_hash() -> str:
    repo_root = Path(__file__).resolve().parents[3]
    relative_paths = (
        Path("src/poi_mpp/experiments/e8_consensus.py"),
        Path("src/poi_mpp/reporting/e8.py"),
        Path("experiments/e8_consensus_weight_sim.py"),
    )
    return digest(
        "E8_PUBLICATION_SOURCE_CLOSURE",
        {str(item): _path_sha256(repo_root / item) for item in relative_paths},
    )


def load_e8_confirmatory_contract(path: str | Path) -> E8ConfirmatoryContract:
    contract_path = _resolve_existing_plain_file(path, label="E8 confirmatory contract")
    raw, _ = _load_strict_yaml_mapping(contract_path, label="E8 confirmatory contract")
    return E8ConfirmatoryContract.model_validate(raw)


class E8PublicationScenario(_FrozenModel):
    seed: int = Field(ge=0)
    scenario: CommitteeScenario


class E8PublicationPlan(_FrozenModel):
    schema_version: str = _E8_PUBLICATION_PLAN_SCHEMA_VERSION
    contract_path: str
    run_config: RunConfig
    simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS, le=MAX_REPLAY_SIMULATIONS)
    publication_scope: str
    required_model_version: str
    required_algorithm_version: str
    scenarios: tuple[E8PublicationScenario, ...]
    notes: tuple[str, ...] = ()

    @field_validator("contract_path", "publication_scope", "required_model_version", "required_algorithm_version")
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @model_validator(mode="after")
    def validate_plan(self) -> "E8PublicationPlan":
        if self.schema_version != _E8_PUBLICATION_PLAN_SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {_E8_PUBLICATION_PLAN_SCHEMA_VERSION}")
        if self.publication_scope != E8_CONFIRMATORY_SCOPE:
            raise ValueError(f"publication_scope must equal {E8_CONFIRMATORY_SCOPE}")
        if self.required_model_version != E8_SIMULATION_MODEL_VERSION:
            raise ValueError(f"required_model_version must equal {E8_SIMULATION_MODEL_VERSION}")
        if self.required_algorithm_version != COMMITTEE_ALGORITHM_VERSION:
            raise ValueError(f"required_algorithm_version must equal {COMMITTEE_ALGORITHM_VERSION}")
        if self.run_config.experiment_id != "E8":
            raise ValueError("run_config.experiment_id must equal E8")
        if self.run_config.origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
            raise ValueError("run_config.origin must equal REPRODUCIBLE_SIMULATION")
        if self.run_config.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
            raise ValueError(
                f"run_config.authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
            )
        if _is_placeholder_digest(self.run_config.model_hash) or _is_placeholder_digest(self.run_config.dataset_hash):
            raise ValueError("run_config model_hash and dataset_hash cannot use placeholder or sentinel digests")
        if tuple(item.scenario.scenario_id for item in self.scenarios) != _REQUIRED_PUBLICATION_SCENARIO_IDS:
            raise ValueError("scenarios must exactly match the frozen E8 publication scenario closure")
        if len({item.scenario.scenario_id for item in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenarios must use unique scenario_id values")
        return self


class E8ResolvedPublicationPlan(_FrozenModel):
    schema_version: str = _E8_PUBLICATION_PLAN_SCHEMA_VERSION
    plan_path: str
    plan_hash: str
    contract_path: str
    contract_hash: str
    source_closure_hash: str
    contract: E8ConfirmatoryContract
    run_config: RunConfig
    simulations: int
    publication_scope: str
    scenarios: tuple[E8PublicationScenario, ...]
    notes: tuple[str, ...] = ()


class E8PublicationArtifact(_FrozenModel):
    schema_version: str = _E8_PUBLICATION_ARTIFACT_SCHEMA_VERSION
    plan_path: str
    plan_hash: str
    contract_path: str
    contract_hash: str
    source_closure_hash: str
    run_id: str
    run_config_hash: str
    publication_scope: str
    origin: EvidenceOrigin
    claim_disposition: str
    limitations: tuple[str, ...]
    rows: tuple[E8ScenarioRow, ...]

    @field_validator(
        "plan_path",
        "plan_hash",
        "contract_path",
        "contract_hash",
        "source_closure_hash",
        "run_id",
        "run_config_hash",
        "publication_scope",
        "claim_disposition",
    )
    @classmethod
    def require_nonblank_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("plan_hash", "contract_hash", "source_closure_hash", "run_config_hash")
    @classmethod
    def require_hash_shape(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("publication artifact hashes must be lowercase SHA-256 hex digests")
        return value

    @model_validator(mode="after")
    def validate_artifact(self) -> "E8PublicationArtifact":
        if self.schema_version != _E8_PUBLICATION_ARTIFACT_SCHEMA_VERSION:
            raise ValueError(f"schema_version must equal {_E8_PUBLICATION_ARTIFACT_SCHEMA_VERSION}")
        if self.publication_scope != E8_CONFIRMATORY_SCOPE:
            raise ValueError(f"publication_scope must equal {E8_CONFIRMATORY_SCOPE}")
        if self.origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION:
            raise ValueError("origin must equal REPRODUCIBLE_SIMULATION")
        if not self.rows:
            raise ValueError("rows must not be empty")
        if any(row.origin is not EvidenceOrigin.REPRODUCIBLE_SIMULATION for row in self.rows):
            raise ValueError("rows must remain REPRODUCIBLE_SIMULATION evidence")
        if any(row.run_id != self.run_id for row in self.rows):
            raise ValueError("rows must bind the artifact run_id")
        if any(row.run_config_hash != self.run_config_hash for row in self.rows):
            raise ValueError("rows must bind the artifact run_config_hash")
        if any(row.publication_scope != self.publication_scope for row in self.rows):
            raise ValueError("rows must bind the artifact publication_scope")
        return self


class E8SimulationConfig(_FrozenModel):
    schema_version: str = "POI_MPP_E8_SIMULATION_CONFIG_V1"
    simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS, le=MAX_REPLAY_SIMULATIONS)
    seed: int = Field(ge=0)
    origin: EvidenceOrigin
    publication_scope: str | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> "E8SimulationConfig":
        if self.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE and self.publication_scope is not None:
            raise ValueError("synthetic plumbing runs cannot declare publication_scope")
        if self.publication_scope is not None and self.publication_scope != E8_CONFIRMATORY_SCOPE:
            raise ValueError(f"publication_scope must equal {E8_CONFIRMATORY_SCOPE}")
        return self


def simulation_config_contract_hash(config: E8SimulationConfig) -> str:
    return digest(
        "E8_SIMULATION_CONFIG",
        {
            "schema_version": config.schema_version,
            "simulations": config.simulations,
            "seed": config.seed,
            "origin": config.origin.value,
            "publication_scope": config.publication_scope,
        },
    )


class OperatorWeightSnapshot(_FrozenModel):
    operator_id: str
    operator_class: OperatorClass
    credit_micros: int = Field(ge=0)
    collateral_micros: int = Field(ge=0)
    active_weight_micros: int = Field(ge=0)

    @field_validator("operator_id")
    @classmethod
    def require_nonblank_operator_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("operator_id must not be blank")
        return value


class CommitteeHistory(_FrozenModel):
    trial_index: int = Field(ge=0)
    committee: tuple[str, ...]
    attacker_seat_share: float = Field(ge=0.0, le=1.0)
    attacker_weight_share: float = Field(ge=0.0, le=1.0)

    @field_validator("committee")
    @classmethod
    def require_nonempty_committee(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("committee must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("committee must not repeat operators")
        return value


class OperatorWeightState(_FrozenModel):
    operator_weights: tuple[OperatorWeightSnapshot, ...]
    total_active_weight_micros: int = Field(ge=0)
    attacker_active_weight_micros: int = Field(ge=0)
    attacker_active_weight_share: float = Field(ge=0.0, le=1.0)
    positive_operator_count: int = Field(ge=0)
    sampling_disposition: SamplingDisposition
    assumption_ledger: tuple[str, ...]


def _result_contract_material(row: "E8ScenarioRow") -> dict[str, object]:
    return {
        "scenario_id": row.scenario_id,
        "role": row.role.value,
        "ablation": row.ablation.value,
        "seed": row.seed,
        "simulations": row.simulations,
        "origin": row.origin.value,
        "committee_size": row.committee_size,
        "target_epoch": row.target_epoch,
        "simulation_model_version": row.simulation_model_version,
        "committee_algorithm_version": row.committee_algorithm_version,
        "config_contract_hash": row.config_contract_hash,
        "scenario_contract_hash": row.scenario_contract_hash,
        "operator_weights": [item.model_dump(mode="json") for item in row.operator_weights],
        "total_active_weight_micros": row.total_active_weight_micros,
        "attacker_active_weight_micros": row.attacker_active_weight_micros,
        "attacker_active_weight_share": row.attacker_active_weight_share,
        "positive_operator_count": row.positive_operator_count,
        "sampling_disposition": row.sampling_disposition.value,
        "committee_histories": [history.model_dump(mode="json") for history in row.committee_histories],
        "attacker_seat_threshold_probability_ge_one_third": row.attacker_seat_threshold_probability_ge_one_third,
        "attacker_seat_threshold_probability_ge_one_third_interval": row.attacker_seat_threshold_probability_ge_one_third_interval,
        "attacker_seat_threshold_probability_ge_two_thirds": row.attacker_seat_threshold_probability_ge_two_thirds,
        "attacker_seat_threshold_probability_ge_two_thirds_interval": row.attacker_seat_threshold_probability_ge_two_thirds_interval,
        "attacker_weight_threshold_probability_ge_one_third": row.attacker_weight_threshold_probability_ge_one_third,
        "attacker_weight_threshold_probability_ge_one_third_interval": row.attacker_weight_threshold_probability_ge_one_third_interval,
        "attacker_weight_threshold_probability_ge_two_thirds": row.attacker_weight_threshold_probability_ge_two_thirds,
        "attacker_weight_threshold_probability_ge_two_thirds_interval": row.attacker_weight_threshold_probability_ge_two_thirds_interval,
        "max_operator_weight_share": row.max_operator_weight_share,
        "estimated_attacker_cost_micros": row.estimated_attacker_cost_micros,
        "zero_credit_implies_zero_weight": row.zero_credit_implies_zero_weight,
        "assumption_ledger": row.assumption_ledger,
        "publication_scope": row.publication_scope,
    }


def result_contract_hash(row: "E8ScenarioRow") -> str:
    return digest("E8_CONSENSUS_RESULT", _result_contract_material(row))


class E8ScenarioRow(_FrozenModel):
    schema_version: str = "POI_MPP_E8_SCENARIO_ROW_V1"
    run_id: str
    experiment_id: str
    run_config_snapshot: RunConfig
    run_config_hash: str
    scenario_id: str
    role: CommitteeScenarioRole
    ablation: CommitteeAblation
    seed: int = Field(ge=0)
    simulations: int = Field(ge=MIN_SUPPORTED_SIMULATIONS, le=MAX_REPLAY_SIMULATIONS)
    origin: EvidenceOrigin
    committee_size: int = Field(gt=0)
    target_epoch: int = Field(ge=0)
    beta_micros: int = Field(gt=0)
    concentration_cap_micros: int = Field(ge=0)
    attacker_operator_ids: tuple[str, ...]
    operator_profiles: tuple[OperatorProfile, ...]
    worker_bindings: tuple[WorkerBinding, ...]
    task_batches: tuple[CommitteeTaskBatch, ...]
    simulation_model_version: str
    committee_algorithm_version: str
    config_contract_hash: str
    scenario_contract_hash: str
    result_contract_hash: str
    operator_weights: tuple[OperatorWeightSnapshot, ...]
    total_active_weight_micros: int = Field(ge=0)
    attacker_active_weight_micros: int = Field(ge=0)
    attacker_active_weight_share: float = Field(ge=0.0, le=1.0)
    positive_operator_count: int = Field(ge=0)
    sampling_disposition: SamplingDisposition
    committee_histories: tuple[CommitteeHistory, ...]
    attacker_seat_threshold_probability_ge_one_third: float | None = Field(default=None, ge=0.0, le=1.0)
    attacker_seat_threshold_probability_ge_one_third_interval: tuple[float, float] | None = None
    attacker_seat_threshold_probability_ge_two_thirds: float | None = Field(default=None, ge=0.0, le=1.0)
    attacker_seat_threshold_probability_ge_two_thirds_interval: tuple[float, float] | None = None
    attacker_weight_threshold_probability_ge_one_third: float | None = Field(default=None, ge=0.0, le=1.0)
    attacker_weight_threshold_probability_ge_one_third_interval: tuple[float, float] | None = None
    attacker_weight_threshold_probability_ge_two_thirds: float | None = Field(default=None, ge=0.0, le=1.0)
    attacker_weight_threshold_probability_ge_two_thirds_interval: tuple[float, float] | None = None
    max_operator_weight_share: float = Field(ge=0.0, le=1.0)
    estimated_attacker_cost_micros: str
    zero_credit_implies_zero_weight: bool
    assumption_ledger: tuple[str, ...]
    publication_scope: str | None = None

    @field_validator(
        "run_id",
        "experiment_id",
        "scenario_id",
        "simulation_model_version",
        "committee_algorithm_version",
        "config_contract_hash",
        "scenario_contract_hash",
        "result_contract_hash",
        "estimated_attacker_cost_micros",
        mode="before",
    )
    @classmethod
    def require_nonblank_text(cls, value: object, info: ValidationInfo) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("config_contract_hash", "scenario_contract_hash", "result_contract_hash", "run_config_hash")
    @classmethod
    def validate_hash_shape(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("contract hashes must be lowercase SHA-256 hex digests")
        return value

    @field_validator(
        "attacker_seat_threshold_probability_ge_one_third_interval",
        "attacker_seat_threshold_probability_ge_two_thirds_interval",
        "attacker_weight_threshold_probability_ge_one_third_interval",
        "attacker_weight_threshold_probability_ge_two_thirds_interval",
    )
    @classmethod
    def validate_probability_interval(
        cls,
        value: tuple[float, float] | None,
    ) -> tuple[float, float] | None:
        if value is None:
            return value
        if len(value) != 2 or value[0] > value[1]:
            raise ValueError("probability intervals must contain ordered bounds")
        if any(not math.isfinite(bound) or bound < 0.0 or bound > 1.0 for bound in value):
            raise ValueError("probability intervals must be finite and inside [0, 1]")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> "E8ScenarioRow":
        if self.simulation_model_version != E8_SIMULATION_MODEL_VERSION:
            raise ValueError(f"simulation_model_version must equal {E8_SIMULATION_MODEL_VERSION}")
        if self.committee_algorithm_version != COMMITTEE_ALGORITHM_VERSION:
            raise ValueError(f"committee_algorithm_version must equal {COMMITTEE_ALGORITHM_VERSION}")
        if self.run_config_hash != config_hash(self.run_config_snapshot):
            raise ValueError("run_config_hash must match canonical RunConfig material")
        if self.run_id != self.run_config_snapshot.run_id:
            raise ValueError("run_id must exactly bind run_config_snapshot.run_id")
        if self.experiment_id != self.run_config_snapshot.experiment_id:
            raise ValueError("experiment_id must exactly bind run_config_snapshot.experiment_id")
        if self.origin is not self.run_config_snapshot.origin:
            raise ValueError("origin must exactly bind run_config_snapshot.origin")
        expected_config_hash = digest(
            "E8_SIMULATION_CONFIG",
            {
                "schema_version": "POI_MPP_E8_SIMULATION_CONFIG_V1",
                "simulations": self.simulations,
                "seed": self.seed,
                "origin": self.origin.value,
                "publication_scope": self.publication_scope,
            },
        )
        if self.config_contract_hash != expected_config_hash:
            raise ValueError("config_contract_hash must match canonical E8 simulation-config material")
        expected_scenario_hash = scenario_contract_hash(scenario_from_row(self))
        if self.scenario_contract_hash != expected_scenario_hash:
            raise ValueError("scenario_contract_hash must match canonical E8 scenario material")
        if self.result_contract_hash != result_contract_hash(self):
            raise ValueError("result_contract_hash must match canonical E8 result material")
        sampled = self.sampling_disposition is SamplingDisposition.COMMITTEE_SAMPLED
        if sampled and len(self.committee_histories) != self.simulations:
            raise ValueError("sampled rows must retain one committee history per trial")
        if not sampled and self.committee_histories:
            raise ValueError("non-sampled rows cannot retain committee histories")
        return self


def scenario_contract_hash(scenario: CommitteeScenario) -> str:
    return digest(
        "E8_CONSENSUS_SCENARIO",
        {
            "scenario_id": scenario.scenario_id,
            "role": scenario.role.value,
            "ablation": scenario.ablation.value,
            "committee_size": scenario.committee_size,
            "target_epoch": scenario.target_epoch,
            "beta_micros": scenario.beta_micros,
            "concentration_cap_micros": scenario.concentration_cap_micros,
            "attacker_operator_ids": scenario.attacker_operator_ids,
            "operator_profiles": [profile.model_dump(mode="json") for profile in scenario.operator_profiles],
            "worker_bindings": [binding.model_dump(mode="json") for binding in scenario.worker_bindings],
            "task_batches": [
                {
                    "task": batch.task.model_dump(mode="json"),
                    "receipts": [receipt.model_dump(mode="json") for receipt in batch.receipts],
                }
                for batch in scenario.task_batches
            ],
        },
    )


def pair_exogenous_hash(scenario: CommitteeScenario) -> str:
    return digest(
        "E8_CONSENSUS_PAIR_EXOGENOUS",
        {
            "committee_size": scenario.committee_size,
            "target_epoch": scenario.target_epoch,
            "beta_micros": scenario.beta_micros,
            "attacker_operator_ids": scenario.attacker_operator_ids,
            "operator_profiles": [profile.model_dump(mode="json") for profile in scenario.operator_profiles],
            "worker_bindings": [binding.model_dump(mode="json") for binding in scenario.worker_bindings],
            "task_batches": [
                {
                    "task": {
                        **batch.task.model_dump(mode="json"),
                        "task_id": None,
                    },
                    "receipts": [
                        {
                            **receipt.model_dump(mode="json"),
                            "receipt_id": None,
                            "task_id": None,
                            "nullifier": None,
                            "commitment_hash": None,
                            "audit_id": None,
                        }
                        for receipt in batch.receipts
                    ],
                }
                for batch in scenario.task_batches
            ],
        },
    )


def _decimal_text(value: Decimal) -> str:
    return str(value.quantize(_MICRO_QUANTUM, rounding=ROUND_HALF_UP))


def _probability_or_none(count: int, total: int) -> float | None:
    if total == 0:
        return None
    return count / total


def _wilson_interval(count: int, total: int) -> tuple[float, float] | None:
    if total == 0:
        return None
    phat = count / total
    denominator = 1.0 + (_WILSON_Z * _WILSON_Z) / total
    centre = phat + (_WILSON_Z * _WILSON_Z) / (2.0 * total)
    margin = _WILSON_Z * math.sqrt(
        (phat * (1.0 - phat) / total) + (_WILSON_Z * _WILSON_Z) / (4.0 * total * total)
    )
    lower = max(0.0, (centre - margin) / denominator)
    upper = min(1.0, (centre + margin) / denominator)
    return (lower, upper)


def _assumption_ledger(scenario: CommitteeScenario) -> tuple[str, ...]:
    return (
        f"role={scenario.role.value}",
        f"ablation={scenario.ablation.value}",
        f"committee_size={scenario.committee_size}",
        f"target_epoch={scenario.target_epoch}",
        f"beta_micros={scenario.beta_micros}",
        f"concentration_cap_micros={scenario.concentration_cap_micros}",
        f"attacker_operator_ids={','.join(sorted(scenario.attacker_operator_ids))}",
        f"committee_algorithm_version={COMMITTEE_ALGORITHM_VERSION}",
    )


def _attacker_cost_micros(scenario: CommitteeScenario) -> str:
    total = Decimal("0")
    for profile in scenario.operator_profiles:
        if profile.operator_class is not OperatorClass.ATTACKER:
            continue
        total += Decimal(profile.compute_cost_micros)
        total += Decimal(profile.collateral_micros)
        total -= Decimal(profile.compute_subsidy_micros)
    return _decimal_text(max(total, Decimal("0")))


def _eligible_receipt_for_weight(receipt: Receipt, *, task: TaskSpec, target_epoch: int) -> bool:
    if task.task_class is not TaskClass.CONSENSUS or not task.active or not task.registered or task.credit_budget == 0:
        return False
    if receipt.task_id != task.task_id:
        return False
    if receipt.state is not ReceiptState.ACTIVE:
        return False
    if receipt.audit_decision is not AuditDecision.ACCEPT or not receipt.audit_accepted:
        return False
    if receipt.da_decision is not True or not receipt.data_availability_passed:
        return False
    if receipt.challenge_reason is not None or receipt.slash_reason is not None:
        return False
    if receipt.epoch_issued != task.epoch or receipt.activated_epoch != target_epoch:
        return False
    return True


def derive_operator_weights(scenario: CommitteeScenario) -> OperatorWeightState:
    operator_by_id = {profile.operator_id: profile for profile in scenario.operator_profiles}
    worker_to_operator = {binding.worker_id: binding.operator_id for binding in scenario.worker_bindings}
    credit_by_operator = {profile.operator_id: 0 for profile in scenario.operator_profiles}
    seen_receipt_ids: set[int] = set()
    seen_nullifiers: set[str] = set()
    previously_credited_receipt_ids: set[int] = set()

    for batch in sorted(scenario.task_batches, key=lambda item: item.task.task_id):
        eligible: list[Receipt] = []
        for receipt in sorted(batch.receipts, key=lambda item: item.receipt_id):
            if receipt.receipt_id in seen_receipt_ids or receipt.nullifier in seen_nullifiers:
                continue
            seen_receipt_ids.add(receipt.receipt_id)
            seen_nullifiers.add(receipt.nullifier)
            if not _eligible_receipt_for_weight(receipt, task=batch.task, target_epoch=scenario.target_epoch):
                continue
            eligible.append(receipt)
        if not eligible:
            continue
        allocation = allocate_credit(
            batch.task,
            eligible,
            target_epoch=scenario.target_epoch,
            previously_credited_receipt_ids=previously_credited_receipt_ids,
        )
        for receipt_id in allocation.ordered_receipt_ids:
            previously_credited_receipt_ids.add(receipt_id)
        for worker_id, credit in allocation.by_worker.items():
            operator_id = worker_to_operator.get(worker_id)
            if operator_id is None:
                raise ValueError("worker_bindings must cover credited workers")
            credit_by_operator[operator_id] += credit

    snapshots: list[OperatorWeightSnapshot] = []
    attacker_weight = 0
    total_weight = 0
    for profile in sorted(scenario.operator_profiles, key=lambda item: item.operator_id):
        credit = credit_by_operator[profile.operator_id]
        weight = derive_active_weight(
            credit=credit,
            collateral=profile.collateral_micros,
            beta=scenario.beta_micros,
            concentration_cap=scenario.concentration_cap_micros,
        )
        total_weight += weight
        if profile.operator_id in scenario.attacker_operator_ids:
            attacker_weight += weight
        snapshots.append(
            OperatorWeightSnapshot(
                operator_id=profile.operator_id,
                operator_class=profile.operator_class,
                credit_micros=credit,
                collateral_micros=profile.collateral_micros,
                active_weight_micros=weight,
            )
        )

    positive_operator_count = sum(1 for snapshot in snapshots if snapshot.active_weight_micros > 0)
    if total_weight == 0:
        disposition = SamplingDisposition.ZERO_TOTAL_WEIGHT
    elif positive_operator_count < scenario.committee_size:
        disposition = SamplingDisposition.INSUFFICIENT_ELIGIBLE_OPERATORS
    else:
        disposition = SamplingDisposition.COMMITTEE_SAMPLED
    share = 0.0 if total_weight == 0 else attacker_weight / total_weight
    return OperatorWeightState(
        operator_weights=tuple(snapshots),
        total_active_weight_micros=total_weight,
        attacker_active_weight_micros=attacker_weight,
        attacker_active_weight_share=share,
        positive_operator_count=positive_operator_count,
        sampling_disposition=disposition,
        assumption_ledger=_assumption_ledger(scenario),
    )


def _committee_seed(*, base_seed: int, trial_index: int) -> bytes:
    return f"{base_seed}:{trial_index}".encode("ascii")


def run_committee_scenario(
    *,
    run_id: str,
    experiment_id: str,
    run_config: RunConfig,
    scenario: CommitteeScenario,
    config: E8SimulationConfig,
) -> E8ScenarioRow:
    if experiment_id != "E8":
        raise ValueError("experiment_id must equal E8")
    if run_config.run_id != run_id:
        raise ValueError("run_config.run_id must match run_id")
    if run_config.experiment_id != experiment_id:
        raise ValueError("run_config.experiment_id must match experiment_id")
    if run_config.origin is not config.origin:
        raise ValueError("run_config.origin must match config.origin")

    weight_state = derive_operator_weights(scenario)
    committee_histories: list[CommitteeHistory] = []
    seat_one_third = 0
    seat_two_thirds = 0
    weight_one_third = 0
    weight_two_thirds = 0
    max_operator_weight_share = 0.0
    if weight_state.total_active_weight_micros > 0:
        max_operator_weight_share = max(
            snapshot.active_weight_micros / weight_state.total_active_weight_micros
            for snapshot in weight_state.operator_weights
            if snapshot.active_weight_micros > 0
        )
    zero_credit_implies_zero_weight = all(
        snapshot.active_weight_micros == 0 if snapshot.credit_micros == 0 else True
        for snapshot in weight_state.operator_weights
    )

    if weight_state.sampling_disposition is SamplingDisposition.COMMITTEE_SAMPLED:
        weights = {
            snapshot.operator_id: snapshot.active_weight_micros
            for snapshot in weight_state.operator_weights
            if snapshot.active_weight_micros > 0
        }
        operator_weight_map = {
            snapshot.operator_id: snapshot.active_weight_micros for snapshot in weight_state.operator_weights
        }
        for trial_index in range(config.simulations):
            committee = sample_committee(
                weights,
                committee_size=scenario.committee_size,
                seed=_committee_seed(base_seed=config.seed, trial_index=trial_index),
            )
            attacker_seats = sum(1 for operator_id in committee if operator_id in scenario.attacker_operator_ids)
            seat_share = attacker_seats / scenario.committee_size
            committee_weight = sum(operator_weight_map[operator_id] for operator_id in committee)
            attacker_committee_weight = sum(
                operator_weight_map[operator_id]
                for operator_id in committee
                if operator_id in scenario.attacker_operator_ids
            )
            weight_share = 0.0 if committee_weight == 0 else attacker_committee_weight / committee_weight
            seat_one_third += int(seat_share >= (1.0 / 3.0))
            seat_two_thirds += int(seat_share >= (2.0 / 3.0))
            weight_one_third += int(weight_share >= (1.0 / 3.0))
            weight_two_thirds += int(weight_share >= (2.0 / 3.0))
            committee_histories.append(
                CommitteeHistory(
                    trial_index=trial_index,
                    committee=committee,
                    attacker_seat_share=seat_share,
                    attacker_weight_share=weight_share,
                )
            )

    payload = {
        "run_id": run_id,
        "experiment_id": experiment_id,
        "run_config_snapshot": run_config,
        "run_config_hash": config_hash(run_config),
        "scenario_id": scenario.scenario_id,
        "role": scenario.role,
        "ablation": scenario.ablation,
        "seed": config.seed,
        "simulations": config.simulations,
        "origin": config.origin,
        "committee_size": scenario.committee_size,
        "target_epoch": scenario.target_epoch,
        "beta_micros": scenario.beta_micros,
        "concentration_cap_micros": scenario.concentration_cap_micros,
        "attacker_operator_ids": scenario.attacker_operator_ids,
        "operator_profiles": scenario.operator_profiles,
        "worker_bindings": scenario.worker_bindings,
        "task_batches": scenario.task_batches,
        "simulation_model_version": E8_SIMULATION_MODEL_VERSION,
        "committee_algorithm_version": COMMITTEE_ALGORITHM_VERSION,
        "config_contract_hash": simulation_config_contract_hash(config),
        "scenario_contract_hash": scenario_contract_hash(scenario),
        "result_contract_hash": "0" * 64,
        "operator_weights": weight_state.operator_weights,
        "total_active_weight_micros": weight_state.total_active_weight_micros,
        "attacker_active_weight_micros": weight_state.attacker_active_weight_micros,
        "attacker_active_weight_share": weight_state.attacker_active_weight_share,
        "positive_operator_count": weight_state.positive_operator_count,
        "sampling_disposition": weight_state.sampling_disposition,
        "committee_histories": tuple(committee_histories),
        "attacker_seat_threshold_probability_ge_one_third": _probability_or_none(seat_one_third, len(committee_histories)),
        "attacker_seat_threshold_probability_ge_one_third_interval": _wilson_interval(seat_one_third, len(committee_histories)),
        "attacker_seat_threshold_probability_ge_two_thirds": _probability_or_none(seat_two_thirds, len(committee_histories)),
        "attacker_seat_threshold_probability_ge_two_thirds_interval": _wilson_interval(seat_two_thirds, len(committee_histories)),
        "attacker_weight_threshold_probability_ge_one_third": _probability_or_none(weight_one_third, len(committee_histories)),
        "attacker_weight_threshold_probability_ge_one_third_interval": _wilson_interval(weight_one_third, len(committee_histories)),
        "attacker_weight_threshold_probability_ge_two_thirds": _probability_or_none(weight_two_thirds, len(committee_histories)),
        "attacker_weight_threshold_probability_ge_two_thirds_interval": _wilson_interval(weight_two_thirds, len(committee_histories)),
        "max_operator_weight_share": max_operator_weight_share,
        "estimated_attacker_cost_micros": _attacker_cost_micros(scenario),
        "zero_credit_implies_zero_weight": zero_credit_implies_zero_weight,
        "assumption_ledger": weight_state.assumption_ledger,
        "publication_scope": config.publication_scope,
    }
    provisional = E8ScenarioRow.model_construct(**payload)
    return E8ScenarioRow.model_validate(
        {
            **payload,
            "result_contract_hash": result_contract_hash(provisional),
        }
    )


def scenario_from_row(row: E8ScenarioRow) -> CommitteeScenario:
    return CommitteeScenario.model_validate(
        {
            "scenario_id": row.scenario_id,
            "role": row.role,
            "ablation": row.ablation,
            "committee_size": row.committee_size,
            "target_epoch": row.target_epoch,
            "beta_micros": row.beta_micros,
            "concentration_cap_micros": row.concentration_cap_micros,
            "attacker_operator_ids": row.attacker_operator_ids,
            "operator_profiles": row.operator_profiles,
            "worker_bindings": row.worker_bindings,
            "task_batches": row.task_batches,
        }
    )


def simulation_config_from_row(row: E8ScenarioRow) -> E8SimulationConfig:
    return E8SimulationConfig(
        simulations=row.simulations,
        seed=row.seed,
        origin=row.origin,
        publication_scope=row.publication_scope,
    )


def replay_row(row: E8ScenarioRow) -> E8ScenarioRow:
    return run_committee_scenario(
        run_id=row.run_id,
        experiment_id=row.experiment_id,
        run_config=row.run_config_snapshot,
        scenario=scenario_from_row(row),
        config=simulation_config_from_row(row),
    )


def default_e8_publication_plan_path() -> Path:
    return Path(__file__).resolve().parents[3] / "configs" / "confirmatory" / "e8.publication.yaml"


def _summary_and_limits(rows: Sequence[E8ScenarioRow], contract: E8ConfirmatoryContract) -> tuple[str, tuple[str, ...]]:
    from poi_mpp.reporting.e8 import summarize_e8_rows

    summary = summarize_e8_rows(tuple(rows), contract=contract)
    limits = (
        "REPRODUCIBLE_SIMULATION only; not live consensus evidence.",
        "Non-real-world limits: fixed scenario closure, fixed seeds, bounded committee sampling, and replay-authoritative publication checks.",
        *contract.notes,
    )
    return summary.claim_disposition, tuple(dict.fromkeys(limits))


def load_e8_publication_plan(path: str | Path) -> E8ResolvedPublicationPlan:
    plan_path = _resolve_existing_plain_file(path, label="E8 publication plan")
    raw, plan_bytes = _load_strict_yaml_mapping(plan_path, label="E8 publication plan")
    plan = E8PublicationPlan.model_validate(raw)
    contract_path = _resolve_contained_relative_file(
        plan_path.parent,
        plan.contract_path,
        label="E8 publication contract",
    )
    contract = load_e8_confirmatory_contract(contract_path)
    if plan.publication_scope != contract.publication_scope:
        raise ValueError("publication_scope must exactly match the confirmatory contract")
    if plan.simulations != contract.required_simulations:
        raise ValueError("simulations must exactly match the confirmatory contract")
    if plan.required_model_version != contract.required_model_version:
        raise ValueError("required_model_version must exactly match the confirmatory contract")
    if plan.required_algorithm_version != contract.required_algorithm_version:
        raise ValueError("required_algorithm_version must exactly match the confirmatory contract")
    if plan.run_config.origin is not contract.required_run_origin:
        raise ValueError("run_config.origin must exactly match the confirmatory contract")
    if plan.run_config.authorization_scope != contract.required_run_authorization_scope:
        raise ValueError("run_config.authorization_scope must exactly match the confirmatory contract")

    allowed_by_id = {item.scenario_id: item for item in contract.allowed_scenarios}
    plan_by_id = {item.scenario.scenario_id: item for item in plan.scenarios}
    if set(plan_by_id) != set(allowed_by_id):
        raise ValueError("scenarios must exactly close against the confirmatory contract")

    for scenario_id in _REQUIRED_PUBLICATION_SCENARIO_IDS:
        published = plan_by_id[scenario_id]
        allowed = allowed_by_id[scenario_id]
        scenario = published.scenario
        if scenario.role is not allowed.required_role:
            raise ValueError(f"role mismatch for {scenario_id}")
        if scenario.ablation is not allowed.required_ablation:
            raise ValueError(f"ablation mismatch for {scenario_id}")
        if published.seed != allowed.required_seed:
            raise ValueError(f"seed mismatch for {scenario_id}")
        if scenario.committee_size != contract.required_committee_size:
            raise ValueError(f"committee_size mismatch for {scenario_id}")
        epoch_deltas = {scenario.target_epoch - batch.task.epoch for batch in scenario.task_batches}
        if epoch_deltas != {contract.required_target_epoch_delta}:
            raise ValueError(f"target_epoch delta mismatch for {scenario_id}")
        if scenario_contract_hash(scenario) != allowed.scenario_contract_hash:
            raise ValueError(f"scenario_contract_hash mismatch for {scenario_id}")

    for allowed in contract.allowed_scenarios:
        if allowed.required_role is not CommitteeScenarioRole.NEGATIVE_CONTROL:
            continue
        assert allowed.negative_assertions is not None
        negative_scenario = plan_by_id[allowed.scenario_id].scenario
        support_scenario = plan_by_id[allowed.negative_assertions.paired_support_scenario_id].scenario
        expected_hash = allowed.negative_assertions.required_pair_exogenous_hash
        if pair_exogenous_hash(support_scenario) != expected_hash:
            raise ValueError(f"paired support exogenous hash mismatch for {allowed.scenario_id}")
        if pair_exogenous_hash(negative_scenario) != expected_hash:
            raise ValueError(f"negative exogenous hash mismatch for {allowed.scenario_id}")

    return E8ResolvedPublicationPlan(
        plan_path=str(plan_path),
        plan_hash=_sha256_bytes(plan_bytes),
        contract_path=str(contract_path),
        contract_hash=_path_sha256(contract_path),
        source_closure_hash=_e8_publication_source_closure_hash(),
        contract=contract,
        run_config=plan.run_config,
        simulations=plan.simulations,
        publication_scope=plan.publication_scope,
        scenarios=plan.scenarios,
        notes=plan.notes,
    )


def run_e8_publication_plan(plan: E8ResolvedPublicationPlan) -> E8PublicationArtifact:
    rows = tuple(
        run_committee_scenario(
            run_id=plan.run_config.run_id,
            experiment_id=plan.run_config.experiment_id,
            run_config=plan.run_config,
            scenario=item.scenario,
            config=E8SimulationConfig(
                simulations=plan.simulations,
                seed=item.seed,
                origin=plan.run_config.origin,
                publication_scope=plan.publication_scope,
            ),
        )
        for item in plan.scenarios
    )
    claim_disposition, limits = _summary_and_limits(rows, plan.contract)
    return E8PublicationArtifact(
        plan_path=plan.plan_path,
        plan_hash=plan.plan_hash,
        contract_path=plan.contract_path,
        contract_hash=plan.contract_hash,
        source_closure_hash=plan.source_closure_hash,
        run_id=plan.run_config.run_id,
        run_config_hash=config_hash(plan.run_config),
        publication_scope=plan.publication_scope,
        origin=plan.run_config.origin,
        claim_disposition=claim_disposition,
        limitations=limits,
        rows=rows,
    )


def load_and_run_e8_publication(
    plan_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> E8PublicationArtifact:
    plan = load_e8_publication_plan(plan_path)
    artifact = run_e8_publication_plan(plan)
    if output_path is not None:
        target = _validate_output_target(Path(output_path))
        _atomic_write_json(target, artifact.model_dump(mode="json"))
    return artifact


def load_e8_publication_artifact(path: str | Path) -> E8PublicationArtifact:
    artifact_path = _resolve_existing_plain_file(path, label="E8 publication artifact")
    try:
        payload = json.loads(
            artifact_path.read_text(encoding="utf-8"),
            object_pairs_hook=lambda pairs: (
                (_ for _ in ()).throw(ValueError("duplicate JSON keys are forbidden"))
                if len({key for key, _ in pairs}) != len(pairs)
                else dict(pairs)
            ),
        )
    except Exception as error:
        raise ValueError(f"unable to load E8 publication artifact: {artifact_path}") from error
    artifact = E8PublicationArtifact.model_validate(payload)
    rerun = load_and_run_e8_publication(artifact.plan_path)
    if artifact.model_dump(mode="json") != rerun.model_dump(mode="json"):
        raise ValueError("E8 publication artifact does not match deterministic plan replay")
    return artifact


def assert_cli_authority_boundary(run_config: RunConfig, contract: E8ConfirmatoryContract) -> None:
    if run_config.experiment_id != "E8":
        raise AuthorityBoundaryError("E8 wrapper requires experiment_id E8")
    if run_config.origin is not contract.required_run_origin:
        raise AuthorityBoundaryError("E8 publication CLI is reserved for REPRODUCIBLE_SIMULATION runs")
    if run_config.authorization_scope != contract.required_run_authorization_scope:
        raise AuthorityBoundaryError(
            "E8 publication CLI requires PUBLICATION_EVIDENCE_AUTHORIZED authorization_scope"
        )
    raise AuthorityBoundaryError(
        "explicit publication freeze and artifact routing remain manual for E8; "
        "validated reproducible-simulation authority but will not auto-run publication artifacts"
    )
