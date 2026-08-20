"""Deterministic aggregation for E2 tamper-detection artifacts."""

from __future__ import annotations

from collections.abc import Mapping
import math

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


MIN_E2_SUPPORTED_DENOMINATOR = 2
MIN_E2_UNIQUE_ATTACK_SEEDS = 2


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class E2Summary(_FrozenModel):
    schema_version: str = "POI_MPP_E2_SUMMARY_V1"
    claim_id: str
    denominator: int = Field(ge=0)
    minimum_supported_denominator: int = Field(ge=MIN_E2_SUPPORTED_DENOMINATOR)
    minimum_unique_attack_seeds: int = Field(ge=MIN_E2_UNIQUE_ATTACK_SEEDS)
    unique_attack_seed_count: int = Field(ge=0)
    exact_denominator: int = Field(ge=0)
    exact_detected: int = Field(ge=0)
    exact_detection_rate: float = Field(ge=0.0, le=1.0)
    exact_confidence_interval: tuple[float, float]
    empirical_denominator: int = Field(ge=0)
    empirical_detected: int = Field(ge=0)
    empirical_detection_rate: float = Field(ge=0.0, le=1.0)
    empirical_confidence_interval: tuple[float, float]
    unsupported_attack_count: int = Field(ge=0)
    honest_control_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_positive_rate: float = Field(ge=0.0, le=1.0)
    confidence_interval: tuple[float, float]
    residual_surface_ledger: tuple[str, ...] = ()
    claim_disposition: str

    @field_validator("claim_id", "claim_disposition")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary text fields must not be blank")
        return value

    @field_validator(
        "confidence_interval",
        "exact_confidence_interval",
        "empirical_confidence_interval",
    )
    @classmethod
    def validate_ci_bounds(
        cls,
        value: tuple[float, float],
        info: ValidationInfo,
    ) -> tuple[float, float]:
        if len(value) != 2 or value[0] > value[1]:
            raise ValueError(f"{info.field_name} must contain ordered bounds")
        if any(not math.isfinite(bound) for bound in value):
            raise ValueError(f"{info.field_name} must contain finite bounds")
        return value

    @model_validator(mode="after")
    def validate_counts(self) -> "E2Summary":
        if self.denominator != self.exact_denominator + self.empirical_denominator:
            raise ValueError("denominator must equal exact + empirical supported counts")
        if self.exact_detected > self.exact_denominator:
            raise ValueError("exact_detected cannot exceed exact_denominator")
        if self.empirical_detected > self.empirical_denominator:
            raise ValueError("empirical_detected cannot exceed empirical_denominator")
        if self.false_positive_count > self.honest_control_count:
            raise ValueError("false_positive_count cannot exceed honest_control_count")
        if self.unique_attack_seed_count > self.denominator + self.unsupported_attack_count:
            raise ValueError("unique_attack_seed_count exceeds total attacked observations")
        return self


def _require_str(row: Mapping[str, object], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"E2 rows require non-blank {field_name}")
    return value


def _require_bool(row: Mapping[str, object], field_name: str) -> bool:
    value = row.get(field_name)
    if not isinstance(value, bool):
        raise ValueError(f"E2 rows require boolean {field_name}")
    return value


def _manifest_mapping(row: Mapping[str, object]) -> Mapping[str, object] | None:
    manifest = row.get("attack_manifest")
    if manifest is None:
        return None
    if isinstance(manifest, Mapping):
        return manifest
    if isinstance(manifest, BaseModel):
        dumped = manifest.model_dump(mode="python")
        if isinstance(dumped, Mapping):
            return dumped
    raise ValueError("E2 rows require attack_manifest to be a mapping when present")


def _wilson_interval(successes: int, trials: int, *, z: float = 1.959963984540054) -> tuple[float, float]:
    if trials <= 0:
        return (0.0, 1.0)
    proportion = successes / trials
    z_squared = z * z
    denominator = 1.0 + (z_squared / trials)
    centre = proportion + (z_squared / (2.0 * trials))
    margin = z * math.sqrt(
        ((proportion * (1.0 - proportion)) / trials) + (z_squared / (4.0 * trials * trials))
    )
    lower = max(0.0, (centre - margin) / denominator)
    upper = min(1.0, (centre + margin) / denominator)
    return (lower, upper)


def summarize_e2_rows(
    rows: list[dict[str, object]] | list[Mapping[str, object]],
    *,
    claim_id: str = "C2",
) -> E2Summary:
    from poi_mpp.attacks.execution import AttackAnalysisSurface, AttackFamily
    from poi_mpp.experiments.e2_tamper import E2ReceiptRow, validate_attack_receipt

    if not rows:
        raise ValueError("E2 summary requires receipt rows")

    canonical_rows = [
        validate_attack_receipt(
            E2ReceiptRow.model_validate(
                row.model_dump(mode="python") if isinstance(row, E2ReceiptRow) else row
            ),
            require_replay_validation=True,
        )
        for row in rows
    ]
    run_ids = {row.run_id for row in canonical_rows}
    experiment_ids = {row.experiment_id for row in canonical_rows}
    if len(run_ids) != 1 or len(experiment_ids) != 1:
        raise ValueError("E2 rows must share a single run_id and experiment_id")

    seen_receipt_ids: set[str] = set()
    seen_observation_keys: set[str] = set()
    seen_attack_instance_ids: set[str] = set()
    unique_seed_sensitive_instances: set[str] = set()
    exact_denominator = 0
    exact_detected = 0
    empirical_denominator = 0
    empirical_detected = 0
    unsupported_attack_count = 0
    honest_control_count = 0
    false_positive_count = 0
    residuals: list[str] = []

    for row in canonical_rows:
        receipt_id = row.receipt_id
        if receipt_id in seen_receipt_ids:
            raise ValueError(f"duplicate E2 receipt_id: {receipt_id}")
        seen_receipt_ids.add(receipt_id)
        family = row.attack_family
        if row.false_positive:
            false_positive_count += 1
        residuals.extend(str(item) for item in row.residual_risk if str(item).strip())

        if family is None:
            honest_control_count += 1
            continue
        assert row.observation_key is not None
        observation_key = row.observation_key
        if observation_key in seen_observation_keys:
            raise ValueError(f"duplicate E2 observation_key: {observation_key}")
        seen_observation_keys.add(observation_key)
        assert row.attack_seed is not None
        manifest = row.attack_manifest
        assert manifest is not None
        attack_instance_id = manifest.replay_proof.attack_instance_id
        if attack_instance_id in seen_attack_instance_ids:
            raise ValueError(f"duplicate E2 attack_instance_id: {attack_instance_id}")
        seen_attack_instance_ids.add(attack_instance_id)
        if manifest.replay_proof.seed_sensitive:
            unique_seed_sensitive_instances.add(attack_instance_id)
        if family in {AttackFamily.CROSS_REQUEST_SPLICE, AttackFamily.REPLAY_NULLIFIER}:
            peer_receipt_id = row.peer_receipt_id
            if peer_receipt_id is None or not peer_receipt_id.strip():
                raise ValueError("paired E2 attacks require peer_receipt_id")
            if peer_receipt_id == receipt_id:
                raise ValueError("paired E2 attacks cannot reference the same receipt_id as peer")
            manifest_parameters = manifest.parameters
            peer_values = [
                str(parameter.value)
                for parameter in manifest_parameters
                if parameter.key == "peer_receipt_id"
            ]
            if peer_values != [peer_receipt_id]:
                raise ValueError("paired E2 attacks require manifest peer_receipt_id parity")
        if row.analysis_surface == AttackAnalysisSurface.UNSUPPORTED.value:
            if not row.abstained:
                raise ValueError("unsupported E2 attacks must abstain")
            unsupported_attack_count += 1
            continue
        if row.analysis_surface == AttackAnalysisSurface.EXACT_MATCH.value:
            exact_denominator += 1
            exact_detected += int(row.detected)
            continue
        if row.analysis_surface in {
            AttackAnalysisSurface.EXACT_FIELD.value,
            AttackAnalysisSurface.EMPIRICAL_FLOAT.value,
        }:
            if row.analysis_surface == AttackAnalysisSurface.EXACT_FIELD.value:
                exact_denominator += 1
                exact_detected += int(row.detected)
            else:
                empirical_denominator += 1
                empirical_detected += int(row.detected)
            continue
        raise ValueError(f"unknown E2 analysis_surface: {row.analysis_surface}")

    denominator = exact_denominator + empirical_denominator
    exact_rate = exact_detected / exact_denominator if exact_denominator else 0.0
    empirical_rate = empirical_detected / empirical_denominator if empirical_denominator else 0.0
    false_positive_rate = (
        false_positive_count / honest_control_count if honest_control_count else 0.0
    )
    overall_detected = exact_detected + empirical_detected
    if (
        denominator < MIN_E2_SUPPORTED_DENOMINATOR
        or len(unique_seed_sensitive_instances) < MIN_E2_UNIQUE_ATTACK_SEEDS
    ):
        disposition = "INCONCLUSIVE"
    elif overall_detected != denominator:
        disposition = "NOT_SUPPORTED"
    elif false_positive_count:
        disposition = "INCONCLUSIVE"
    else:
        disposition = "SUPPORTED"
    return E2Summary(
        claim_id=claim_id,
        denominator=denominator,
        minimum_supported_denominator=MIN_E2_SUPPORTED_DENOMINATOR,
        minimum_unique_attack_seeds=MIN_E2_UNIQUE_ATTACK_SEEDS,
        unique_attack_seed_count=len(unique_seed_sensitive_instances),
        exact_denominator=exact_denominator,
        exact_detected=exact_detected,
        exact_detection_rate=exact_rate,
        exact_confidence_interval=_wilson_interval(exact_detected, exact_denominator),
        empirical_denominator=empirical_denominator,
        empirical_detected=empirical_detected,
        empirical_detection_rate=empirical_rate,
        empirical_confidence_interval=_wilson_interval(empirical_detected, empirical_denominator),
        unsupported_attack_count=unsupported_attack_count,
        honest_control_count=honest_control_count,
        false_positive_count=false_positive_count,
        false_positive_rate=false_positive_rate,
        confidence_interval=_wilson_interval(overall_detected, denominator),
        residual_surface_ledger=tuple(dict.fromkeys(residuals)),
        claim_disposition=disposition,
    )
