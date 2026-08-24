"""Frozen semantic policy bindings for V2 confirmatory execution."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

from poi_mpp.auditor.semantic.models import (
    SemanticCalibrationFreezeStatus,
    SemanticCalibrationFreezeV2,
    SemanticOutcome,
    VerificationDecision,
    VerificationMode,
)
from poi_mpp.evidence.canonical import digest
from poi_mpp.evidence.models import EvidenceOrigin


SEMANTIC_POLICY_V2_SCHEMA = "POI_MPP_SEMANTIC_POLICY_V2"
SEMANTIC_POLICY_V2_DOMAIN = "SEMANTIC_POLICY_V2"

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_REQUIRED_HASH_FIELDS = (
    "claim_spec_hash",
    "dataset_manifest_hash",
    "authority_registry_snapshot_hash",
    "model_manifest_hash",
    "runtime_environment_hash",
    "task_payload_hash",
    "prompt_template_hash",
    "calibration_hash",
    "calibration_error_ledger_hash",
    "confirmatory_leakage_report_hash",
)


class _FrozenPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _normalize_probability_value(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if normalized < 0.0 or normalized > 1.0:
        raise ValueError(f"{field_name} must lie within [0, 1]")
    return normalized


class SemanticPolicyV2(_FrozenPolicyModel):
    schema_version: Literal[SEMANTIC_POLICY_V2_SCHEMA] = SEMANTIC_POLICY_V2_SCHEMA
    claim_spec_hash: str
    dataset_manifest_hash: str
    authority_registry_snapshot_hash: str
    model_manifest_hash: str
    runtime_environment_hash: str
    task_payload_hash: str
    prompt_template_hash: str
    calibration_hash: str
    calibration_error_ledger_hash: str
    confirmatory_leakage_report_hash: str
    mode: VerificationMode
    calibration_split: VerificationMode = VerificationMode.DEVELOPMENT
    support_threshold: float
    reject_threshold: float
    minimum_calibrated_confidence: float
    freeze_locked: bool = True
    require_output_trace_agreement: bool = True
    allowed_evidence_origins: tuple[EvidenceOrigin, ...]
    allowed_metric_ids: tuple[str, ...]
    required_artifact_ids: tuple[str, ...]
    accept_outcomes: tuple[SemanticOutcome, ...]
    reject_outcomes: tuple[SemanticOutcome, ...]
    abstain_outcomes: tuple[SemanticOutcome, ...]

    @field_validator(*_REQUIRED_HASH_FIELDS, mode="before")
    @classmethod
    def normalize_hashes(cls, value: Any, info: ValidationInfo) -> str:
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 hex digest")
        return value

    @field_validator(
        "support_threshold",
        "reject_threshold",
        "minimum_calibrated_confidence",
        mode="before",
    )
    @classmethod
    def normalize_probabilities(cls, value: Any, info: ValidationInfo) -> float:
        return _normalize_probability_value(value, field_name=info.field_name)

    @field_validator("allowed_evidence_origins", mode="before")
    @classmethod
    def normalize_allowed_origins(cls, value: Any) -> tuple[EvidenceOrigin, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("allowed_evidence_origins must be a sequence")
        normalized = tuple(
            item if isinstance(item, EvidenceOrigin) else EvidenceOrigin(item) for item in value
        )
        if not normalized:
            raise ValueError("allowed_evidence_origins must not be empty")
        if EvidenceOrigin.SYNTHETIC_NON_EVIDENCE in normalized:
            raise ValueError("allowed_evidence_origins must not include SYNTHETIC_NON_EVIDENCE")
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed_evidence_origins must not contain duplicates")
        return tuple(sorted(normalized, key=lambda item: item.value))

    @field_validator("allowed_metric_ids", "required_artifact_ids", mode="before")
    @classmethod
    def normalize_string_sets(cls, value: Any, info: ValidationInfo) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{info.field_name} must be a sequence")
        normalized = []
        for item in value:
            if not isinstance(item, str) or _SAFE_TOKEN.fullmatch(item.strip()) is None:
                raise ValueError(f"{info.field_name} contains an invalid identifier")
            normalized.append(item.strip())
        if not normalized:
            raise ValueError(f"{info.field_name} must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"{info.field_name} must not contain duplicates")
        return tuple(sorted(normalized))

    @field_validator("accept_outcomes", "reject_outcomes", "abstain_outcomes", mode="before")
    @classmethod
    def normalize_outcome_sets(cls, value: Any, info: ValidationInfo) -> tuple[SemanticOutcome, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{info.field_name} must be a sequence")
        normalized = tuple(
            item if isinstance(item, SemanticOutcome) else SemanticOutcome(item) for item in value
        )
        if not normalized:
            raise ValueError(f"{info.field_name} must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"{info.field_name} must not contain duplicates")
        return tuple(sorted(normalized, key=lambda item: item.value))

    @model_validator(mode="after")
    def validate_policy_contract(self) -> "SemanticPolicyV2":
        if self.reject_threshold > self.support_threshold:
            raise ValueError("reject_threshold must not exceed support_threshold")
        if self.mode is VerificationMode.CONFIRMATORY:
            if self.calibration_split is not VerificationMode.DEVELOPMENT:
                raise ValueError("confirmatory execution requires development-only calibration")
            if self.allowed_evidence_origins != (EvidenceOrigin.REAL_MODEL_EXECUTION,):
                raise ValueError(
                    "confirmatory publication evidence must allow only REAL_MODEL_EXECUTION"
                )
            if not self.freeze_locked:
                raise ValueError("confirmatory execution requires freeze_locked == True")
        used = (
            set(self.accept_outcomes)
            | set(self.reject_outcomes)
            | set(self.abstain_outcomes)
        )
        overlaps = (
            set(self.accept_outcomes) & set(self.reject_outcomes)
            or set(self.accept_outcomes) & set(self.abstain_outcomes)
            or set(self.reject_outcomes) & set(self.abstain_outcomes)
        )
        if overlaps or used != set(SemanticOutcome):
            raise ValueError("accept/reject/abstain outcomes must partition SemanticOutcome")
        return self

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def policy_hash(self, *, domain: str = SEMANTIC_POLICY_V2_DOMAIN) -> str:
        return digest(domain, self.canonical_payload())

    def bound_hashes(self) -> dict[str, str]:
        return {
            field_name: getattr(self, field_name)
            for field_name in _REQUIRED_HASH_FIELDS
        }

    def assert_frozen_inputs(self, bindings: Mapping[str, str]) -> None:
        missing = sorted(set(_REQUIRED_HASH_FIELDS) - set(bindings))
        unknown = sorted(set(bindings) - set(_REQUIRED_HASH_FIELDS))
        if missing:
            raise ValueError(
                f"missing frozen input hashes: {', '.join(missing)}"
            )
        if unknown:
            raise ValueError(
                f"unknown frozen input hashes: {', '.join(unknown)}"
            )
        for field_name in _REQUIRED_HASH_FIELDS:
            value = bindings[field_name]
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
            if value != getattr(self, field_name):
                raise ValueError(f"{field_name} does not match the frozen policy binding")

    def assert_calibration_freeze(self, freeze: SemanticCalibrationFreezeV2) -> None:
        if freeze.status is not SemanticCalibrationFreezeStatus.FROZEN_DEVELOPMENT_ONLY:
            raise ValueError(
                "confirmatory execution requires a FROZEN_DEVELOPMENT_ONLY calibration freeze"
            )
        field_pairs = (
            ("calibration_hash", self.calibration_hash, freeze.content_hash),
            ("claim_spec_hash", self.claim_spec_hash, freeze.claim_spec_hash),
            ("prompt_template_hash", self.prompt_template_hash, freeze.prompt_template_hash),
            ("model_manifest_hash", self.model_manifest_hash, freeze.model_manifest_hash),
            (
                "runtime_environment_hash",
                self.runtime_environment_hash,
                freeze.runtime_environment_hash,
            ),
        )
        for field_name, policy_value, freeze_value in field_pairs:
            if policy_value != freeze_value:
                raise ValueError(f"{field_name} does not match the frozen calibration binding")

        threshold_pairs = (
            ("support_threshold", self.support_threshold, freeze.support_threshold),
            ("reject_threshold", self.reject_threshold, freeze.reject_threshold),
            (
                "minimum_calibrated_confidence",
                self.minimum_calibrated_confidence,
                freeze.minimum_calibrated_confidence,
            ),
        )
        for field_name, policy_value, freeze_value in threshold_pairs:
            if not math.isclose(policy_value, freeze_value, rel_tol=0.0, abs_tol=0.0):
                raise ValueError(f"{field_name} does not match the frozen calibration binding")

    def require_evidence_origin(self, origin: EvidenceOrigin) -> None:
        normalized = origin if isinstance(origin, EvidenceOrigin) else EvidenceOrigin(origin)
        if normalized not in self.allowed_evidence_origins:
            raise ValueError(f"unsupported evidence origin: {normalized.value}")

    def _decision_from_outcome(
        self,
        *,
        outcome: SemanticOutcome,
        support_fraction: float,
        calibrated_confidence: float,
    ) -> VerificationDecision:
        if outcome in self.reject_outcomes:
            return VerificationDecision.REJECT
        if outcome in self.abstain_outcomes:
            return VerificationDecision.ABSTAIN
        if support_fraction <= self.reject_threshold:
            return VerificationDecision.REJECT
        if (
            support_fraction < self.support_threshold
            or calibrated_confidence < self.minimum_calibrated_confidence
        ):
            return VerificationDecision.ABSTAIN
        return VerificationDecision.ACCEPT

    def adjudicate(
        self,
        *,
        outcome: SemanticOutcome,
        support_fraction: float,
        calibrated_confidence: float,
        output_decision: VerificationDecision,
        trace_decision: VerificationDecision,
        evidence_origin: EvidenceOrigin,
    ) -> VerificationDecision:
        self.require_evidence_origin(evidence_origin)
        output = (
            output_decision
            if isinstance(output_decision, VerificationDecision)
            else VerificationDecision(output_decision)
        )
        trace = (
            trace_decision
            if isinstance(trace_decision, VerificationDecision)
            else VerificationDecision(trace_decision)
        )
        if self.require_output_trace_agreement and output is not trace:
            raise ValueError("output decision and trace decision must agree exactly")
        expected = self._decision_from_outcome(
            outcome=outcome if isinstance(outcome, SemanticOutcome) else SemanticOutcome(outcome),
            support_fraction=_normalize_probability_value(
                support_fraction,
                field_name="support_fraction",
            ),
            calibrated_confidence=_normalize_probability_value(
                calibrated_confidence,
                field_name="calibrated_confidence",
            ),
        )
        if output is not expected or trace is not expected:
            raise ValueError("output/trace decision must equal the policy decision")
        return expected


class SemanticPolicyVerdict(StrEnum):
    ACCEPT = VerificationDecision.ACCEPT.value
    REJECT = VerificationDecision.REJECT.value
    ABSTAIN = VerificationDecision.ABSTAIN.value
