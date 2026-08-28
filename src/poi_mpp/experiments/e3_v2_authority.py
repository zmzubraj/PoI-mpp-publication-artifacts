"""E3-v2 verified authority grant capability.

Process-local capability emitted only by the canonical external verifier
(``scripts/verify_e3_v2_authority.py``) after detached SSH signature
verification of a pre-execution E3-v2 scope authorization.  Mirrors the V1
grant contract in ``e3_semantic.py`` and extends it with the E3-v2 generation
markers, the development bundle bindings, the confirmatory freeze lineage, the
calibration freeze content hash, and the frozen C3-v2 Wilson support rule.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import Mapping, Sequence
import weakref


_CANONICAL_AUTHORITY_VERIFIER = (
    Path(__file__).resolve().parents[3] / "scripts" / "verify_e3_v2_authority.py"
)


def _authority_grant_contract():
    issued: weakref.WeakSet[VerifiedE3V2AuthorityGrant] = weakref.WeakSet()

    class VerifiedE3V2AuthorityGrant:
        """Process-local capability emitted after canonical external verification.

        The constructor guard is defense in depth against accidental/lookalike
        grants, not a hostile same-process Python security boundary. Detached
        SSH verification in ``scripts/verify_e3_v2_authority.py`` is the trust
        boundary used by the production CLI.
        """

        __slots__ = (
            "_experiment_id",
            "_experiment_generation",
            "_claim_id",
            "_claim_generation",
            "_task_class",
            "_evidence_origin",
            "_metric_scope",
            "_artifact_scope",
            "_privacy_scope",
            "_request_scope_digest",
            "_authority_record_sha256",
            "_decision",
            "_authority_identity",
            "_request_manifest_sha256",
            "_request_manifest_self_digest",
            "_result_attestation_status",
            "_development_bundle_manifest_sha256",
            "_development_dataset_manifest_hash",
            "_development_model_manifest_hash",
            "_development_decode_policy_hash",
            "_development_environment_manifest_hash",
            "_development_policy_inputs_digest",
            "_confirmatory_freeze_material_lineage_hash",
            "_confirmatory_dataset_manifest_hash",
            "_confirmatory_development_manifest_hash",
            "_calibration_freeze_content_hash",
            "_support_rule_id",
            "_wilson_z_value",
            "_far_wilson_upper_bound_max",
            "_frr_wilson_upper_bound_max",
            "_coverage_min",
            "_confirmatory_composition",
            "_locked",
            "__weakref__",
        )

        def __init__(
            self,
            *,
            experiment_id: str,
            experiment_generation: str,
            claim_id: str,
            claim_generation: str,
            task_class: str,
            evidence_origin: str,
            metric_scope: Sequence[str],
            artifact_scope: Sequence[str],
            privacy_scope: str,
            request_scope_digest: str,
            authority_record_sha256: str,
            decision: str,
            authority_identity: str,
            request_manifest_sha256: str,
            request_manifest_self_digest: str,
            result_attestation_status: str,
            development_bundle_manifest_sha256: str,
            development_dataset_manifest_hash: str,
            development_model_manifest_hash: str,
            development_decode_policy_hash: str,
            development_environment_manifest_hash: str,
            development_policy_inputs_digest: str,
            confirmatory_freeze_material_lineage_hash: str,
            confirmatory_dataset_manifest_hash: str,
            confirmatory_development_manifest_hash: str,
            calibration_freeze_content_hash: str,
            support_rule_id: str,
            wilson_z_value: str,
            far_wilson_upper_bound_max: str,
            frr_wilson_upper_bound_max: str,
            coverage_min: str,
            confirmatory_composition: Mapping[str, int],
            _verification_transcript: object | None,
        ) -> None:
            caller = inspect.currentframe().f_back
            caller_locals = caller.f_locals if caller is not None else {}
            completed = caller_locals.get("completed")
            transcript_bytes = getattr(_verification_transcript, "record_bytes", None)
            canonical_call = (
                caller is not None
                and caller.f_code.co_name == "verify_authority"
                and Path(caller.f_code.co_filename).resolve() == _CANONICAL_AUTHORITY_VERIFIER
                and caller_locals.get("verification_transcript") is _verification_transcript
                and getattr(completed, "returncode", None) == 0
                and isinstance(transcript_bytes, bytes)
                and transcript_bytes == caller_locals.get("record_bytes")
                and hashlib.sha256(transcript_bytes).hexdigest() == authority_record_sha256
            )
            if not canonical_call:
                raise TypeError(
                    "VerifiedE3V2AuthorityGrant: only verify_authority may produce a verified grant"
                )
            values = {
                "_experiment_id": experiment_id,
                "_experiment_generation": experiment_generation,
                "_claim_id": claim_id,
                "_claim_generation": claim_generation,
                "_task_class": task_class,
                "_evidence_origin": evidence_origin,
                "_metric_scope": tuple(metric_scope),
                "_artifact_scope": tuple(artifact_scope),
                "_privacy_scope": privacy_scope,
                "_request_scope_digest": request_scope_digest,
                "_authority_record_sha256": authority_record_sha256,
                "_decision": decision,
                "_authority_identity": authority_identity,
                "_request_manifest_sha256": request_manifest_sha256,
                "_request_manifest_self_digest": request_manifest_self_digest,
                "_result_attestation_status": result_attestation_status,
                "_development_bundle_manifest_sha256": development_bundle_manifest_sha256,
                "_development_dataset_manifest_hash": development_dataset_manifest_hash,
                "_development_model_manifest_hash": development_model_manifest_hash,
                "_development_decode_policy_hash": development_decode_policy_hash,
                "_development_environment_manifest_hash": development_environment_manifest_hash,
                "_development_policy_inputs_digest": development_policy_inputs_digest,
                "_confirmatory_freeze_material_lineage_hash": (
                    confirmatory_freeze_material_lineage_hash
                ),
                "_confirmatory_dataset_manifest_hash": confirmatory_dataset_manifest_hash,
                "_confirmatory_development_manifest_hash": confirmatory_development_manifest_hash,
                "_calibration_freeze_content_hash": calibration_freeze_content_hash,
                "_support_rule_id": support_rule_id,
                "_wilson_z_value": wilson_z_value,
                "_far_wilson_upper_bound_max": far_wilson_upper_bound_max,
                "_frr_wilson_upper_bound_max": frr_wilson_upper_bound_max,
                "_coverage_min": coverage_min,
                "_confirmatory_composition": dict(confirmatory_composition),
                "_locked": True,
            }
            for name, value in values.items():
                object.__setattr__(self, name, value)
            issued.add(self)

        def __setattr__(self, name: str, value: object) -> None:
            if getattr(self, "_locked", False):
                raise AttributeError("VerifiedE3V2AuthorityGrant is read-only")
            object.__setattr__(self, name, value)

        @property
        def experiment_id(self) -> str:
            return self._experiment_id

        @property
        def experiment_generation(self) -> str:
            return self._experiment_generation

        @property
        def claim_id(self) -> str:
            return self._claim_id

        @property
        def claim_generation(self) -> str:
            return self._claim_generation

        @property
        def task_class(self) -> str:
            return self._task_class

        @property
        def evidence_origin(self) -> str:
            return self._evidence_origin

        @property
        def metric_scope(self) -> tuple[str, ...]:
            return self._metric_scope

        @property
        def artifact_scope(self) -> tuple[str, ...]:
            return self._artifact_scope

        @property
        def privacy_scope(self) -> str:
            return self._privacy_scope

        @property
        def request_scope_digest(self) -> str:
            return self._request_scope_digest

        @property
        def authority_record_sha256(self) -> str:
            return self._authority_record_sha256

        @property
        def request_manifest_sha256(self) -> str:
            return self._request_manifest_sha256

        @property
        def request_manifest_self_digest(self) -> str:
            return self._request_manifest_self_digest

        @property
        def decision(self) -> str:
            return self._decision

        @property
        def authority_identity(self) -> str:
            return self._authority_identity

        @property
        def development_bundle_manifest_sha256(self) -> str:
            return self._development_bundle_manifest_sha256

        @property
        def development_dataset_manifest_hash(self) -> str:
            return self._development_dataset_manifest_hash

        @property
        def development_model_manifest_hash(self) -> str:
            return self._development_model_manifest_hash

        @property
        def development_decode_policy_hash(self) -> str:
            return self._development_decode_policy_hash

        @property
        def development_environment_manifest_hash(self) -> str:
            return self._development_environment_manifest_hash

        @property
        def development_policy_inputs_digest(self) -> str:
            return self._development_policy_inputs_digest

        @property
        def confirmatory_freeze_material_lineage_hash(self) -> str:
            return self._confirmatory_freeze_material_lineage_hash

        @property
        def confirmatory_dataset_manifest_hash(self) -> str:
            return self._confirmatory_dataset_manifest_hash

        @property
        def confirmatory_development_manifest_hash(self) -> str:
            return self._confirmatory_development_manifest_hash

        @property
        def calibration_freeze_content_hash(self) -> str:
            return self._calibration_freeze_content_hash

        @property
        def support_rule_id(self) -> str:
            return self._support_rule_id

        @property
        def wilson_z_value(self) -> str:
            return self._wilson_z_value

        @property
        def far_wilson_upper_bound_max(self) -> str:
            return self._far_wilson_upper_bound_max

        @property
        def frr_wilson_upper_bound_max(self) -> str:
            return self._frr_wilson_upper_bound_max

        @property
        def coverage_min(self) -> str:
            return self._coverage_min

        @property
        def confirmatory_composition(self) -> dict[str, int]:
            return dict(self._confirmatory_composition)

        @property
        def verification_summary(self) -> dict[str, str]:
            return {
                "schema_version": "POI_MPP_E3_AUTHORITY_VERIFICATION_V2",
                "status": "VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY",
                "experiment_id": self.experiment_id,
                "experiment_generation": self.experiment_generation,
                "claim_id": self.claim_id,
                "claim_generation": self.claim_generation,
                "decision": self.decision,
                "authority_identity": self.authority_identity,
                "request_manifest_sha256": self._request_manifest_sha256,
                "request_manifest_self_digest": self._request_manifest_self_digest,
                "result_attestation_status": self._result_attestation_status,
                "authority_record_sha256": self.authority_record_sha256,
                "authority_boundary": (
                    "Signature verification authenticates pre-execution E3-v2 scope authorization "
                    "only; it does not attest to any E3 result or publication claim."
                ),
            }

        def __getitem__(self, key: str) -> str:
            """Narrow compatibility for the post-execution verifier's decision lookup."""
            if key != "decision":
                raise KeyError(key)
            return self.decision

    def is_authentic(value: object) -> bool:
        return isinstance(value, VerifiedE3V2AuthorityGrant) and value in issued

    return VerifiedE3V2AuthorityGrant, is_authentic


VerifiedE3V2AuthorityGrant, _grant_is_authentic = _authority_grant_contract()
