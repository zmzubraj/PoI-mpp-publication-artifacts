"""E2 execution-audit tamper fixtures, evaluation, and publication records."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

from poi_mpp.attacks.execution import (
    AttackAnalysisSurface,
    AttackFamily,
    AttackManifest,
    AttackNumericMode,
    ExecutionAuditBundle,
    canonical_attack_surface,
    committed_target_hash,
    observed_target_hash,
)
from poi_mpp.auditor.reports import AuditResult
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
from poi_mpp.evidence.validation import ProvenanceBundle
from poi_mpp.protocol import ModelManifest, TaskClass, TaskSpec, commit_response
from poi_mpp.reporting.e2 import E2Summary


PUBLICATION_EVIDENCE_AUTHORIZED = "PUBLICATION_EVIDENCE_AUTHORIZED"
_FIELD_MODULUS = 2_147_483_647
MIN_E2_SUPPORTED_DENOMINATOR = 2
MIN_E2_UNIQUE_ATTACK_SEEDS = 2
_REPLAY_CONTEXT_UNSET = object()


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReplayValidationDisposition(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNVALIDATED = "UNVALIDATED"
    CONFIRMED_REPLAY = "CONFIRMED_REPLAY"
    VERIFIED_NOT_REPLAY = "VERIFIED_NOT_REPLAY"


class E2ReceiptRow(_FrozenModel):
    _replay_disposition_validated: bool = PrivateAttr(default=False)

    schema_version: str = "POI_MPP_E2_RECEIPT_ROW_V1"
    run_id: str
    experiment_id: str
    receipt_id: str
    task_id: int = Field(ge=0)
    origin: EvidenceOrigin
    is_attacked: bool
    attack_family: AttackFamily | None = None
    attack_manifest: AttackManifest | None = None
    analysis_surface: str
    assurance_class: str
    attack_seed: int | None = Field(default=None, ge=0)
    peer_receipt_id: str | None = None
    observation_key: str | None = None
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
    audit_result: AuditResult | None = None
    replay_validation: str = ReplayValidationDisposition.NOT_APPLICABLE
    row_hash: str
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
        copied = type(self).model_validate(merged)
        if self._replay_disposition_validated and copied.replay_validation == self.replay_validation:
            object.__setattr__(copied, "_replay_disposition_validated", True)
        return copied

    @field_validator(
        "run_id",
        "experiment_id",
        "receipt_id",
        "analysis_surface",
        "assurance_class",
        "peer_receipt_id",
        "observation_key",
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
        if value is None:
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("E2 row text fields must not be blank")
        return value

    @field_validator("row_hash")
    @classmethod
    def require_row_hash(cls, value: str) -> str:
        if not isinstance(value, str) or not value.startswith("0x") or len(value) != 66:
            raise ValueError("row_hash must be a 32-byte hex word")
        return value

    @model_validator(mode="after")
    def validate_attack_semantics(self) -> "E2ReceiptRow":
        if self.audit_result is not None and self.audit_result.evidence_origin is not self.origin:
            raise ValueError("audit_result.evidence_origin must equal row.origin")
        if self.is_attacked != (self.attack_family is not None):
            raise ValueError("is_attacked must equal whether attack_family is present")
        if self.is_attacked:
            if self.attack_manifest is None:
                raise ValueError("attacked rows require attack_manifest")
            if self.attack_manifest.family is not self.attack_family:
                raise ValueError("attack_manifest.family must equal row.attack_family")
            if self.attack_manifest.origin is not self.origin:
                raise ValueError("attack_manifest.origin must equal row.origin")
            if self.attack_manifest.original_commitment != self.original_commitment:
                raise ValueError("attack_manifest.original_commitment must bind row.original_commitment")
            if self.attack_manifest.original_target_hash != self.original_target_hash:
                raise ValueError("attack_manifest.original_target_hash must bind row.original_target_hash")
            if self.attack_manifest.attacked_target_hash != self.observed_target_hash:
                raise ValueError("attack_manifest.attacked_target_hash must bind row.observed_target_hash")
            if self.original_target_hash == self.observed_target_hash:
                raise ValueError("attacked rows must change the targeted surface")
            if self.attack_seed is None:
                raise ValueError("attacked rows require attack_seed")
            if self.attack_seed != self.attack_manifest.seed:
                raise ValueError("attack_seed must equal attack_manifest.seed")
            if self.observation_key is None:
                raise ValueError("attacked rows require observation_key")
            expected_peer_receipt_id = next(
                (
                    str(parameter.value)
                    for parameter in self.attack_manifest.parameters
                    if parameter.key == "peer_receipt_id"
                ),
                None,
            )
            if self.peer_receipt_id != expected_peer_receipt_id:
                raise ValueError("peer_receipt_id must equal the canonical manifest peer binding")
            expected_observation_key = _observation_key(
                self.attack_manifest.family,
                self.attack_manifest.seed,
                self.attack_manifest.original_target_hash,
                expected_peer_receipt_id,
            )
            if self.observation_key != expected_observation_key:
                raise ValueError("observation_key must equal the canonical manifest observation key")
            if self.attack_family is AttackFamily.UNSUPPORTED_KERNEL:
                if self.audit_result is not None:
                    raise ValueError("unsupported attack rows cannot carry audit_result")
            else:
                if self.audit_result is None:
                    raise ValueError("supported attack rows require audit_result")
                if self.analysis_surface in {
                    AttackAnalysisSurface.EXACT_FIELD.value,
                    AttackAnalysisSurface.EMPIRICAL_FLOAT.value,
                }:
                    if self.audit_result.rounds != self.freivalds_rounds:
                        raise ValueError("algebraic audit_result.rounds must equal row.freivalds_rounds")
                    if self.audit_result.seed != self.attack_seed:
                        raise ValueError("algebraic audit_result.seed must equal row.attack_seed")
        else:
            if self.attack_manifest is not None:
                raise ValueError("honest control rows cannot carry attack_manifest")
            if self.attack_seed is not None or self.peer_receipt_id is not None or self.observation_key is not None:
                raise ValueError("honest control rows cannot carry attack observation metadata")
            if self.audit_result is None:
                raise ValueError("honest control rows require audit_result")
        expected = _expected_row_fields(self)
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"{field_name} does not match the canonical row contract")
        if self.row_hash != _row_hash_material(self):
            raise ValueError("row_hash does not match canonical row material")
        return self


def _replay_residual_risk(
    audit_result: AuditResult,
    replay_validation: str,
) -> tuple[str, ...]:
    base = tuple(audit_result.residual_risk)
    if replay_validation == ReplayValidationDisposition.CONFIRMED_REPLAY:
        return tuple(dict.fromkeys((*base, "observed nullifier already appeared in prior receipts")))
    if replay_validation == ReplayValidationDisposition.VERIFIED_NOT_REPLAY:
        return tuple(
            dict.fromkeys(
                (
                    *base,
                    "changed nullifier without prior membership is not replay and is excluded from replay detection",
                )
            )
        )
    if replay_validation == ReplayValidationDisposition.UNVALIDATED:
        return tuple(dict.fromkeys((*base, "replay prior-nullifier validation pending")))
    raise ValueError("invalid replay_validation for replay row")


def _expected_row_fields(row: E2ReceiptRow) -> dict[str, object]:
    if not row.is_attacked:
        assert row.audit_result is not None
        return {
            "analysis_surface": AttackAnalysisSurface.EXACT_MATCH.value,
            "assurance_class": row.audit_result.assurance_class.value,
            "accepted": row.audit_result.accepted,
            "abstained": False,
            "detected": False,
            "false_positive": not row.audit_result.accepted,
            "replay_validation": ReplayValidationDisposition.NOT_APPLICABLE,
            "residual_risk": tuple(row.audit_result.residual_risk),
        }

    assert row.attack_family is not None
    assert row.attack_manifest is not None
    expected_surface = canonical_attack_surface(
        row.attack_manifest.family,
        numeric_mode=row.attack_manifest.numeric_mode,
    )
    if row.attack_family is AttackFamily.UNSUPPORTED_KERNEL:
        return {
            "analysis_surface": expected_surface.value,
            "assurance_class": AttackAnalysisSurface.UNSUPPORTED.value,
            "accepted": False,
            "abstained": True,
            "detected": False,
            "false_positive": False,
            "residual_risk": ("unsupported kernel surface requires abstention",),
        }

    assert row.audit_result is not None
    if row.attack_family is AttackFamily.REPLAY_NULLIFIER:
        if row.replay_validation not in {
            ReplayValidationDisposition.UNVALIDATED,
            ReplayValidationDisposition.CONFIRMED_REPLAY,
            ReplayValidationDisposition.VERIFIED_NOT_REPLAY,
        }:
            raise ValueError("replay rows require explicit replay_validation status")
        accepted = row.replay_validation == ReplayValidationDisposition.VERIFIED_NOT_REPLAY
        detected = row.replay_validation == ReplayValidationDisposition.CONFIRMED_REPLAY
        return {
            "analysis_surface": expected_surface.value,
            "assurance_class": row.audit_result.assurance_class.value,
            "accepted": accepted,
            "abstained": False,
            "detected": detected,
            "false_positive": False,
            "residual_risk": _replay_residual_risk(row.audit_result, row.replay_validation),
        }

    return {
        "analysis_surface": expected_surface.value,
        "assurance_class": row.audit_result.assurance_class.value,
        "accepted": row.audit_result.accepted,
        "abstained": False,
        "detected": not row.audit_result.accepted,
        "false_positive": False,
        "replay_validation": ReplayValidationDisposition.NOT_APPLICABLE,
        "residual_risk": tuple(row.audit_result.residual_risk),
    }


def _row_hash_material(row: E2ReceiptRow) -> str:
    payload = row.model_dump(mode="python", exclude={"row_hash"})
    payload["origin"] = row.origin.value
    payload["attack_family"] = row.attack_family.value if row.attack_family is not None else None
    payload["replay_validation"] = str(row.replay_validation)
    payload["audit_result"] = (
        row.audit_result.model_dump(mode="json")
        if isinstance(row.audit_result, BaseModel)
        else row.audit_result
    )
    payload["residual_risk"] = list(row.residual_risk)
    payload["attack_manifest"] = (
        row.attack_manifest.model_dump(mode="json")
        if isinstance(row.attack_manifest, BaseModel)
        else row.attack_manifest
    )
    return "0x" + digest("E2_RECEIPT_ROW", payload)


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


def validate_attack_receipt(
    row: E2ReceiptRow,
    *,
    prior_nullifiers: Iterable[str] | object = _REPLAY_CONTEXT_UNSET,
    require_replay_validation: bool = False,
) -> E2ReceiptRow:
    reasons: list[str] = []
    if not row.is_attacked:
        return row
    assert row.attack_family is not None
    if row.attack_family is AttackFamily.REPLAY_NULLIFIER:
        if prior_nullifiers is _REPLAY_CONTEXT_UNSET:
            if row.replay_validation in {
                ReplayValidationDisposition.CONFIRMED_REPLAY,
                ReplayValidationDisposition.VERIFIED_NOT_REPLAY,
            } and not row._replay_disposition_validated:
                reasons.append("replay rows require explicit prior-nullifier validation before aggregation or freeze")
            if require_replay_validation and row.replay_validation == ReplayValidationDisposition.UNVALIDATED:
                reasons.append("replay rows require explicit prior-nullifier validation before aggregation or freeze")
            if reasons:
                raise ArtifactValidationError(tuple(dict.fromkeys(reasons)))
            return row
        prior_nullifier_set = frozenset(prior_nullifiers)
        replay_validation = (
            ReplayValidationDisposition.CONFIRMED_REPLAY
            if row.nullifier in prior_nullifier_set
            else ReplayValidationDisposition.VERIFIED_NOT_REPLAY
        )
        if row.replay_validation not in {
            ReplayValidationDisposition.UNVALIDATED,
            replay_validation,
        }:
            reasons.append("replay_validation does not match explicit prior-nullifier validation")
        if reasons:
            raise ArtifactValidationError(tuple(dict.fromkeys(reasons)))
        validated = row.model_copy(update={"replay_validation": replay_validation})
        object.__setattr__(validated, "_replay_disposition_validated", True)
        return validated
    if row.replay_validation != ReplayValidationDisposition.NOT_APPLICABLE:
        reasons.append("non-replay rows must use NOT_APPLICABLE replay_validation")
    if reasons:
        raise ArtifactValidationError(tuple(dict.fromkeys(reasons)))
    return row


def _observation_key(
    family: AttackFamily,
    seed: int,
    original_target_hash: str,
    peer_receipt_id: str | None,
) -> str:
    return "|".join(
        (
            family.value,
            str(seed),
            original_target_hash,
            peer_receipt_id or "",
        )
    )


def _exact_audit_result(
    bundle: ExecutionAuditBundle,
    *,
    family: AttackFamily | None,
    manifest: AttackManifest | None,
) -> AuditResult:
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
    return audit


def evaluate_receipt(
    bundle: ExecutionAuditBundle,
    *,
    attack_manifest: AttackManifest | None = None,
    audit_rate: float,
    freivalds_rounds: int,
    prior_nullifiers: Iterable[str] | object = _REPLAY_CONTEXT_UNSET,
) -> E2ReceiptRow:
    family = attack_manifest.family if attack_manifest is not None else None
    analysis_surface = (
        attack_manifest.analysis_surface
        if attack_manifest is not None
        else AttackAnalysisSurface.EXACT_MATCH
    )
    numeric_mode = attack_manifest.numeric_mode if attack_manifest is not None else None
    original_hash = (
        committed_target_hash(bundle, family, numeric_mode=numeric_mode)
        if family is not None
        else bundle.commitment.response_hash
    )
    observed_hash = (
        observed_target_hash(bundle, family, numeric_mode=numeric_mode)
        if family is not None
        else bundle.response_hash
    )
    audit_result: AuditResult | None
    replay_validation = ReplayValidationDisposition.NOT_APPLICABLE

    if family is None:
        audit_result = _exact_audit_result(bundle, family=None, manifest=None)
        attack_seed = None
        peer_receipt_id = None
        observation_key = None
    elif analysis_surface is AttackAnalysisSurface.UNSUPPORTED:
        audit_result = None
        attack_seed = attack_manifest.seed
        peer_receipt_id = next(
            (str(parameter.value) for parameter in attack_manifest.parameters if parameter.key == "peer_receipt_id"),
            None,
        )
        observation_key = _observation_key(family, attack_manifest.seed, original_hash, peer_receipt_id)
    elif analysis_surface is AttackAnalysisSurface.EXACT_FIELD:
        audit_result = verify_freivalds_field(
            bundle.field_matrix_a,
            bundle.field_matrix_b,
            bundle.field_matrix_c,
            rounds=freivalds_rounds,
            seed=attack_manifest.seed,
            modulus=_FIELD_MODULUS,
            evidence_origin=bundle.origin,
        )
        attack_seed = attack_manifest.seed
        peer_receipt_id = None
        observation_key = _observation_key(family, attack_manifest.seed, original_hash, None)
    elif analysis_surface is AttackAnalysisSurface.EMPIRICAL_FLOAT:
        audit_result = verify_freivalds_float(
            bundle.float_matrix_a,
            bundle.float_matrix_b,
            bundle.float_matrix_c,
            rounds=freivalds_rounds,
            seed=attack_manifest.seed,
            atol=1e-9,
            rtol=1e-6,
            evidence_origin=bundle.origin,
        )
        attack_seed = attack_manifest.seed
        peer_receipt_id = None
        observation_key = _observation_key(family, attack_manifest.seed, original_hash, None)
    else:
        audit_result = _exact_audit_result(
            bundle,
            family=family,
            manifest=attack_manifest,
        )
        attack_seed = attack_manifest.seed
        peer_receipt_id = next(
            (str(parameter.value) for parameter in attack_manifest.parameters if parameter.key == "peer_receipt_id"),
            None,
        )
        observation_key = _observation_key(family, attack_manifest.seed, original_hash, peer_receipt_id)
    if family is AttackFamily.REPLAY_NULLIFIER:
        replay_validation = ReplayValidationDisposition.UNVALIDATED
    if prior_nullifiers is not _REPLAY_CONTEXT_UNSET and family is AttackFamily.REPLAY_NULLIFIER:
        replay_validation = (
            ReplayValidationDisposition.CONFIRMED_REPLAY
            if bundle.nullifier in frozenset(prior_nullifiers)
            else ReplayValidationDisposition.VERIFIED_NOT_REPLAY
        )

    skeleton = E2ReceiptRow.model_construct(
        run_id=bundle.run_id,
        experiment_id=bundle.experiment_id,
        receipt_id=bundle.receipt_id,
        task_id=bundle.task.task_id,
        origin=bundle.origin,
        is_attacked=family is not None,
        attack_family=family,
        attack_manifest=attack_manifest,
        analysis_surface=analysis_surface.value,
        assurance_class=(
            AttackAnalysisSurface.UNSUPPORTED.value
            if analysis_surface is AttackAnalysisSurface.UNSUPPORTED
            else audit_result.assurance_class.value
        ),
        attack_seed=attack_seed,
        peer_receipt_id=peer_receipt_id,
        observation_key=observation_key,
        audit_rate=audit_rate,
        freivalds_rounds=freivalds_rounds,
        detected=False,
        accepted=False,
        abstained=analysis_surface is AttackAnalysisSurface.UNSUPPORTED,
        false_positive=False,
        original_commitment=bundle.commitment.commitment_hash,
        original_target_hash=original_hash,
        observed_target_hash=observed_hash,
        response_hash=bundle.response_hash,
        trace_root=bundle.trace_root,
        evidence_root=bundle.evidence_root,
        nullifier=bundle.nullifier,
        audit_result=audit_result,
        replay_validation=replay_validation,
        row_hash="0x" + ("0" * 64),
        residual_risk=(),
    )
    expected = _expected_row_fields(skeleton)
    payload = {
        **{
            field_name: getattr(skeleton, field_name)
            for field_name in type(skeleton).model_fields
        },
        **expected,
    }
    payload.pop("row_hash", None)
    payload["row_hash"] = _row_hash_material(
        E2ReceiptRow.model_construct(
            **payload,
            row_hash="0x" + ("0" * 64),
        )
    )
    canonical = E2ReceiptRow.model_validate(payload)
    if family is AttackFamily.REPLAY_NULLIFIER and prior_nullifiers is not _REPLAY_CONTEXT_UNSET:
        return validate_attack_receipt(canonical, prior_nullifiers=prior_nullifiers)
    return canonical


def build_publication_record(
    *,
    summary: E2Summary,
    rows: list[E2ReceiptRow],
    run_config: RunConfig,
    provenance_bundle: ProvenanceBundle | None = None,
) -> dict[str, object]:
    canonical_rows = [validate_attack_receipt(row, require_replay_validation=True) for row in rows]
    origins = {row.origin.value for row in canonical_rows}
    origin = next(iter(origins)) if len(origins) == 1 else "MIXED_ROW_ORIGINS"
    publication_reasons = _publication_precheck_reasons(
        summary=summary,
        rows=canonical_rows,
        run_config=run_config,
        provenance_bundle=provenance_bundle,
    )
    publication_authorized = not publication_reasons
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
            "minimum_supported_denominator": summary.minimum_supported_denominator,
            "minimum_unique_attack_seeds": summary.minimum_unique_attack_seeds,
            "unique_attack_seed_count": summary.unique_attack_seed_count,
            "exact_denominator": summary.exact_denominator,
            "exact_detected": summary.exact_detected,
            "exact_detection_rate": summary.exact_detection_rate,
            "exact_confidence_interval": list(summary.exact_confidence_interval),
            "empirical_denominator": summary.empirical_denominator,
            "empirical_detected": summary.empirical_detected,
            "empirical_detection_rate": summary.empirical_detection_rate,
            "empirical_confidence_interval": list(summary.empirical_confidence_interval),
            "unsupported_attack_count": summary.unsupported_attack_count,
            "honest_control_count": summary.honest_control_count,
            "false_positive_count": summary.false_positive_count,
            "false_positive_rate": summary.false_positive_rate,
            "residual_surface_ledger": list(summary.residual_surface_ledger),
            "publication_precheck_reasons": list(publication_reasons),
        },
        "denominator": max(summary.denominator, 1),
        "ci_required": True,
        "confidence_interval": list(summary.confidence_interval),
        "claim_id": summary.claim_id,
        "claim_disposition": summary.claim_disposition,
        "provenance": (
            provenance_bundle.manifest.model_dump(mode="json")
            if provenance_bundle is not None
            else {"status": "UNVERIFIED_LOCAL_ONLY"}
        ),
    }
    record["content_hash"] = digest("ARTIFACT_CONTENT", artifact_content_material(record))
    return record


def _publication_precheck_reasons(
    *,
    summary: E2Summary,
    rows: list[E2ReceiptRow],
    run_config: RunConfig,
    provenance_bundle: ProvenanceBundle | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    row_origins = {row.origin.value for row in rows}
    if row_origins != {run_config.origin.value}:
        reasons.append("rows.origin must exactly match run_config.origin")
    if run_config.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        reasons.append(
            f"run_config.authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
        )
    if run_config.origin is EvidenceOrigin.SYNTHETIC_NON_EVIDENCE:
        reasons.append("synthetic non-evidence origin can never freeze")
    if summary.denominator < summary.minimum_supported_denominator:
        reasons.append("summary.denominator does not meet the frozen E2 minimum supported denominator")
    if summary.unique_attack_seed_count < summary.minimum_unique_attack_seeds:
        reasons.append("summary.unique_attack_seed_count does not meet the frozen E2 minimum seed contract")
    if provenance_bundle is None:
        reasons.append("publication freeze requires a verified provenance bundle")
        return tuple(dict.fromkeys(reasons))
    manifest = provenance_bundle.manifest
    if provenance_bundle.config.model_dump(mode="json") != run_config.model_dump(mode="json"):
        reasons.append("provenance bundle config must exactly match run_config")
    if manifest.run_id != run_config.run_id:
        reasons.append("provenance manifest run_id must equal run_config.run_id")
    if manifest.experiment_id != run_config.experiment_id:
        reasons.append("provenance manifest experiment_id must equal run_config.experiment_id")
    if manifest.origin is not run_config.origin:
        reasons.append("provenance manifest origin must equal run_config.origin")
    if manifest.authorization_scope != PUBLICATION_EVIDENCE_AUTHORIZED:
        reasons.append(
            f"provenance.authorization_scope must equal {PUBLICATION_EVIDENCE_AUTHORIZED}"
        )
    return tuple(dict.fromkeys(reasons))
