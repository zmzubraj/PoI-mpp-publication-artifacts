"""E2 execution-audit tamper fixtures, evaluation, and publication records."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poi_mpp.attacks.execution import (
    AttackAnalysisSurface,
    AttackFamily,
    AttackManifest,
    ExecutionAuditBundle,
    committed_target_hash,
    observed_target_hash,
)
from poi_mpp.auditor.algebraic.finite_field import verify_freivalds_field
from poi_mpp.auditor.algebraic.floating_point import verify_freivalds_float
from poi_mpp.auditor.exact.checks import verify_exact
from poi_mpp.evidence import (
    ARTIFACT_RECORD_SCHEMA_VERSION,
    ArtifactValidationError,
    ArtifactStage,
    EvidenceOrigin,
    RunConfig,
    approved_schema_hash,
    artifact_content_material,
    digest,
)
from poi_mpp.protocol import ModelManifest, TaskClass, TaskSpec, commit_response
from poi_mpp.reporting.e2 import E2Summary


PUBLICATION_EVIDENCE_AUTHORIZED = "PUBLICATION_EVIDENCE_AUTHORIZED"
_FIELD_MODULUS = 2_147_483_647


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class E2ReceiptRow(_FrozenModel):
    schema_version: str = "POI_MPP_E2_RECEIPT_ROW_V1"
    run_id: str
    experiment_id: str
    receipt_id: str
    task_id: int = Field(ge=0)
    origin: EvidenceOrigin
    attack_family: AttackFamily | None = None
    attack_manifest: AttackManifest | None = None
    analysis_surface: str
    assurance_class: str
    audit_rate: float = Field(gt=0.0, le=1.0)
    freivalds_rounds: int = Field(gt=0)
    detected: bool
    accepted: bool
    abstained: bool
    false_positive: bool
    original_commitment: str
    original_target_hash: str
    observed_target_hash: str
    response_hash: str
    trace_root: str
    evidence_root: str
    nullifier: str
    residual_risk: tuple[str, ...] = ()

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> "E2ReceiptRow":
        if not update:
            return super().model_copy(deep=deep)
        merged = self.model_dump(mode="python")
        merged.update(update)
        return type(self).model_validate(merged)

    @field_validator(
        "run_id",
        "experiment_id",
        "receipt_id",
        "analysis_surface",
        "assurance_class",
        "original_commitment",
        "original_target_hash",
        "observed_target_hash",
        "response_hash",
        "trace_root",
        "evidence_root",
        "nullifier",
    )
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("E2 row text fields must not be blank")
        return value

    @model_validator(mode="after")
    def validate_attack_semantics(self) -> "E2ReceiptRow":
        if self.attack_family is None:
            if self.attack_manifest is not None:
                raise ValueError("honest control rows cannot carry an attack manifest")
        else:
            if self.attack_manifest is not None and self.original_target_hash == self.observed_target_hash:
                raise ValueError("attacked rows must change the targeted surface")
        if self.abstained and self.detected:
            raise ValueError("abstained rows cannot also count as detected")
        if self.false_positive and self.attack_family is not None:
            raise ValueError("false positives apply only to honest controls")
        return self


def _word(label: str, payload: object) -> str:
    return "0x" + digest(label, payload)


def _field_product(
    left: tuple[tuple[int, ...], ...],
    right: tuple[tuple[int, ...], ...],
) -> tuple[tuple[int, ...], ...]:
    transpose = tuple(zip(*right, strict=True))
    rows: list[tuple[int, ...]] = []
    for row in left:
        current: list[int] = []
        for column in transpose:
            total = 0
            for lhs, rhs in zip(row, column, strict=True):
                total = (total + (lhs * rhs)) % _FIELD_MODULUS
            current.append(total)
        rows.append(tuple(current))
    return tuple(rows)


def _float_product(
    left: tuple[tuple[float, ...], ...],
    right: tuple[tuple[float, ...], ...],
) -> tuple[tuple[float, ...], ...]:
    transpose = tuple(zip(*right, strict=True))
    rows: list[tuple[float, ...]] = []
    for row in left:
        current: list[float] = []
        for column in transpose:
            current.append(sum(lhs * rhs for lhs, rhs in zip(row, column, strict=True)))
        rows.append(tuple(current))
    return tuple(rows)


def build_fixture_bundle(
    *,
    origin: EvidenceOrigin,
    receipt_id: str = "receipt-0001",
    seed: int = 1,
) -> ExecutionAuditBundle:
    run_config = RunConfig.model_validate(
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": f"fixture-e2-{seed:04d}",
            "experiment_id": "E2",
            "origin": origin.value,
            "authorization_scope": "LOCAL_TEST_ONLY",
            "model_hash": digest("E2_MODEL_HASH", {"seed": seed}),
            "dataset_hash": digest("E2_DATASET_HASH", {"seed": seed}),
            "parent_hashes": [],
            "data_availability": {
                "total_shards": 16,
                "samples": 8,
                "replacement": False,
            },
        }
    )
    task = TaskSpec(
        task_id=seed,
        task_root=_word("E2_TASK_ROOT", {"seed": seed}),
        worker_id=f"0x{seed:040x}"[-42:],
        task_class=TaskClass.CONSENSUS,
        active=True,
        registered=True,
        credit_budget=90,
        epoch=3,
        deadline=100,
        commitment_height=50,
        commitment_finality_depth=5,
        challenge_window_blocks=8,
        audit_domain_size=16,
    )
    model_manifest = ModelManifest(
        model_root=_word("E2_MODEL_ROOT", {"seed": seed}),
        runtime_root=_word("E2_RUNTIME_ROOT", {"seed": seed}),
        model_manifest_hash=_word("E2_MODEL_MANIFEST", {"seed": seed}),
        assurance_class=1,
    )
    response_hash = _word("E2_RESPONSE_HASH", {"seed": seed})
    trace_root = _word("E2_TRACE_ROOT", {"seed": seed})
    evidence_root = _word("E2_EVIDENCE_ROOT", {"seed": seed})
    artifact_root = _word("E2_ARTIFACT_ROOT", {"seed": seed})
    commitment = commit_response(
        task,
        model_manifest,
        response_hash,
        trace_root,
        evidence_root,
        artifact_root,
        bytes.fromhex(digest("E2_NONCE", {"seed": seed})),
    )
    field_matrix_a = ((1, 2), (3, 4))
    field_matrix_b = ((5, 6), (7, 8))
    field_matrix_c = _field_product(field_matrix_a, field_matrix_b)
    float_matrix_a = ((1.5, 2.0), (0.5, 3.0))
    float_matrix_b = ((2.0, 1.0), (4.0, 2.0))
    float_matrix_c = _float_product(float_matrix_a, float_matrix_b)
    return ExecutionAuditBundle(
        bundle_id=f"{run_config.run_id}:{receipt_id}",
        run_id=run_config.run_id,
        experiment_id=run_config.experiment_id,
        receipt_id=receipt_id,
        origin=origin,
        run_config=run_config,
        task=task,
        model_manifest=model_manifest,
        commitment=commitment,
        response_hash=response_hash,
        trace_root=trace_root,
        evidence_root=evidence_root,
        artifact_root=artifact_root,
        model_root=model_manifest.model_root,
        committed_weight_root=_word("E2_WEIGHT_ROOT", {"seed": seed}),
        weight_root=_word("E2_WEIGHT_ROOT", {"seed": seed}),
        committed_decode_policy_hash=_word("E2_DECODE_POLICY", {"seed": seed}),
        decode_policy_hash=_word("E2_DECODE_POLICY", {"seed": seed}),
        committed_iec_index_hash=_word("E2_IEC_INDEX", {"seed": seed}),
        iec_index_hash=_word("E2_IEC_INDEX", {"seed": seed}),
        committed_nullifier=_word("E2_NULLIFIER", {"seed": seed}),
        nullifier=_word("E2_NULLIFIER", {"seed": seed}),
        committed_field_matrix_c=field_matrix_c,
        field_matrix_a=field_matrix_a,
        field_matrix_b=field_matrix_b,
        field_matrix_c=field_matrix_c,
        committed_float_matrix_c=float_matrix_c,
        float_matrix_a=float_matrix_a,
        float_matrix_b=float_matrix_b,
        float_matrix_c=float_matrix_c,
    )


def validate_attack_receipt(row: E2ReceiptRow) -> E2ReceiptRow:
    reasons: list[str] = []
    manifest = row.attack_manifest
    if row.attack_family is None:
        if manifest is not None:
            reasons.append("honest control rows cannot include attack manifests")
    else:
        if manifest is None:
            reasons.append("attacked rows require attack manifests")
        else:
            if manifest.family is not row.attack_family:
                reasons.append("attack manifest family does not match row attack_family")
            if manifest.origin is not row.origin:
                reasons.append("attack manifest origin does not match row origin")
            if manifest.original_commitment != row.original_commitment:
                reasons.append("attack manifest original_commitment does not bind row commitment")
            if manifest.original_target_hash != row.original_target_hash:
                reasons.append("attack manifest original_target_hash does not match row target")
            if manifest.attacked_target_hash != row.observed_target_hash:
                reasons.append("attack manifest attacked_target_hash does not match row target")
    if reasons:
        raise ArtifactValidationError(tuple(dict.fromkeys(reasons)))
    return row


def _exact_row(
    bundle: ExecutionAuditBundle,
    *,
    family: AttackFamily | None,
    manifest: AttackManifest | None,
) -> tuple[bool, str, tuple[str, ...]]:
    if family is AttackFamily.MODEL_ROOT_SUBSTITUTION:
        audit = verify_exact(bundle.model_manifest.model_root[2:], bundle.model_root[2:], evidence_origin=bundle.origin)
    elif family is AttackFamily.WEIGHT_CORRUPTION:
        audit = verify_exact(bundle.committed_weight_root[2:], bundle.weight_root[2:], evidence_origin=bundle.origin)
    elif family is AttackFamily.TRACE_NODE_MUTATION:
        audit = verify_exact(bundle.commitment.trace_root[2:], bundle.trace_root[2:], evidence_origin=bundle.origin)
    elif family is AttackFamily.RESPONSE_BINDING_MISMATCH:
        audit = verify_exact(
            digest(
                "E2_RESPONSE_BINDING",
                {
                    "response_hash": bundle.commitment.response_hash,
                    "trace_root": bundle.commitment.trace_root,
                },
            ),
            digest(
                "E2_RESPONSE_BINDING",
                {"response_hash": bundle.response_hash, "trace_root": bundle.trace_root},
            ),
            evidence_origin=bundle.origin,
        )
    elif family is AttackFamily.IEC_EVIDENCE_INDEX_MUTATION:
        audit = verify_exact(bundle.committed_iec_index_hash[2:], bundle.iec_index_hash[2:], evidence_origin=bundle.origin)
    elif family is AttackFamily.DECODE_POLICY_MUTATION:
        audit = verify_exact(
            bundle.committed_decode_policy_hash[2:],
            bundle.decode_policy_hash[2:],
            evidence_origin=bundle.origin,
        )
    elif family is AttackFamily.CROSS_REQUEST_SPLICE:
        audit = verify_exact(
            digest(
                "E2_RESPONSE_BINDING",
                {
                    "response_hash": bundle.commitment.response_hash,
                    "trace_root": bundle.commitment.trace_root,
                },
            ),
            digest(
                "E2_RESPONSE_BINDING",
                {"response_hash": bundle.response_hash, "trace_root": bundle.trace_root},
            ),
            evidence_origin=bundle.origin,
        )
    elif family is AttackFamily.REPLAY_NULLIFIER:
        audit = verify_exact(bundle.committed_nullifier[2:], bundle.nullifier[2:], evidence_origin=bundle.origin)
    else:
        audit = verify_exact(bundle.commitment.response_hash[2:], bundle.response_hash[2:], evidence_origin=bundle.origin)
    return (
        audit.accepted,
        audit.assurance_class.value,
        tuple(audit.residual_risk),
    )


def evaluate_receipt(
    bundle: ExecutionAuditBundle,
    *,
    attack_manifest: AttackManifest | None = None,
    audit_rate: float,
    freivalds_rounds: int,
    prior_nullifiers: Iterable[str] = (),
) -> E2ReceiptRow:
    family = attack_manifest.family if attack_manifest is not None else None
    analysis_surface = (
        attack_manifest.analysis_surface
        if attack_manifest is not None
        else AttackAnalysisSurface.EXACT_MATCH
    )
    original_hash = (
        committed_target_hash(bundle, family, analysis_surface=analysis_surface)
        if family is not None
        else bundle.commitment.response_hash
    )
    observed_hash = (
        observed_target_hash(bundle, family, analysis_surface=analysis_surface)
        if family is not None
        else bundle.response_hash
    )
    residual_risk: tuple[str, ...]
    assurance_class: str
    accepted: bool
    abstained = False

    if family is None:
        accepted, assurance_class, residual_risk = _exact_row(bundle, family=None, manifest=None)
    elif analysis_surface is AttackAnalysisSurface.UNSUPPORTED:
        accepted = False
        abstained = True
        assurance_class = analysis_surface.value
        residual_risk = ("unsupported kernel surface requires abstention",)
    elif analysis_surface is AttackAnalysisSurface.EXACT_FIELD:
        audit = verify_freivalds_field(
            bundle.field_matrix_a,
            bundle.field_matrix_b,
            bundle.field_matrix_c,
            rounds=freivalds_rounds,
            seed=attack_manifest.seed,
            modulus=_FIELD_MODULUS,
            evidence_origin=bundle.origin,
        )
        accepted = audit.accepted
        assurance_class = audit.assurance_class.value
        residual_risk = tuple(audit.residual_risk)
    elif analysis_surface is AttackAnalysisSurface.EMPIRICAL_FLOAT:
        audit = verify_freivalds_float(
            bundle.float_matrix_a,
            bundle.float_matrix_b,
            bundle.float_matrix_c,
            rounds=freivalds_rounds,
            seed=attack_manifest.seed,
            atol=1e-9,
            rtol=1e-6,
            evidence_origin=bundle.origin,
        )
        accepted = audit.accepted
        assurance_class = audit.assurance_class.value
        residual_risk = tuple(audit.residual_risk)
    else:
        accepted, assurance_class, residual_risk = _exact_row(
            bundle,
            family=family,
            manifest=attack_manifest,
        )

    if family is AttackFamily.REPLAY_NULLIFIER and bundle.nullifier in set(prior_nullifiers):
        accepted = False
        residual_risk = tuple(
            dict.fromkeys(
                (*residual_risk, "observed nullifier already appeared in prior receipts")
            )
        )

    detected = family is not None and not accepted and not abstained
    false_positive = family is None and not accepted
    row = E2ReceiptRow(
        run_id=bundle.run_id,
        experiment_id=bundle.experiment_id,
        receipt_id=bundle.receipt_id,
        task_id=bundle.task.task_id,
        origin=bundle.origin,
        attack_family=family,
        attack_manifest=attack_manifest,
        analysis_surface=analysis_surface.value,
        assurance_class=assurance_class,
        audit_rate=audit_rate,
        freivalds_rounds=freivalds_rounds,
        detected=detected,
        accepted=accepted,
        abstained=abstained,
        false_positive=false_positive,
        original_commitment=bundle.commitment.commitment_hash,
        original_target_hash=original_hash,
        observed_target_hash=observed_hash,
        response_hash=bundle.response_hash,
        trace_root=bundle.trace_root,
        evidence_root=bundle.evidence_root,
        nullifier=bundle.nullifier,
        residual_risk=residual_risk,
    )
    return validate_attack_receipt(row)


def build_publication_record(
    *,
    summary: E2Summary,
    rows: list[E2ReceiptRow],
    run_config: RunConfig,
) -> dict[str, object]:
    origins = {row.origin.value for row in rows}
    origin = next(iter(origins)) if len(origins) == 1 else "MIXED_ROW_ORIGINS"
    publication_authorized = (
        run_config.authorization_scope == PUBLICATION_EVIDENCE_AUTHORIZED
        and origin != EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value
    )
    record: dict[str, object] = {
        "schema_version": ARTIFACT_RECORD_SCHEMA_VERSION,
        "artifact_id": f"{run_config.experiment_id}-E2-SUMMARY",
        "run_id": run_config.run_id,
        "experiment_id": run_config.experiment_id,
        "origin": origin,
        "stage": (
            ArtifactStage.FROZEN.value
            if publication_authorized
            else ArtifactStage.SEMANTICALLY_VALID.value
        ),
        "content_hash": "",
        "parent_hashes": list(run_config.parent_hashes),
        "payload": {
            "exact_denominator": summary.exact_denominator,
            "exact_detected": summary.exact_detected,
            "exact_detection_rate": summary.exact_detection_rate,
            "empirical_denominator": summary.empirical_denominator,
            "empirical_detected": summary.empirical_detected,
            "empirical_detection_rate": summary.empirical_detection_rate,
            "unsupported_attack_count": summary.unsupported_attack_count,
            "honest_control_count": summary.honest_control_count,
            "false_positive_count": summary.false_positive_count,
            "false_positive_rate": summary.false_positive_rate,
            "residual_surface_ledger": list(summary.residual_surface_ledger),
        },
        "denominator": max(summary.denominator, 1),
        "ci_required": False,
        "claim_id": summary.claim_id,
        "claim_disposition": summary.claim_disposition,
        "provenance": {"status": "UNVERIFIED_LOCAL_ONLY"},
    }
    record["content_hash"] = digest("ARTIFACT_CONTENT", artifact_content_material(record))
    return record
