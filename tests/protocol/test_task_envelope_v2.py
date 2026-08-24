from __future__ import annotations

from collections import OrderedDict

import pytest

from poi_mpp.evidence.canonical import canonical_bytes, digest
from poi_mpp.protocol.task_envelope import (
    TASK_ENVELOPE_V2_DOMAIN,
    TASK_ENVELOPE_V2_SCHEMA,
    TaskEnvelopeScopeV2,
    TaskEnvelopeV2,
)
from poi_mpp.protocol.types import TaskClass


def _word(seed: str) -> str:
    return f"0x{seed * 64}"


def _scope() -> TaskEnvelopeScopeV2:
    return TaskEnvelopeScopeV2(
        publication_scope="E3_CONFIRMATORY_PUBLICATION_V2",
        authorization_scope="PUBLICATION_EVIDENCE_AUTHORIZED",
        evidence_origin="REAL_MODEL_EXECUTION",
        task_class=TaskClass.CONSENSUS,
    )


def _envelope(**overrides: object) -> TaskEnvelopeV2:
    payload: dict[str, object] = {
        "claim_spec_hash": _word("1"),
        "task_payload_hash": _word("2"),
        "semantic_policy_hash": _word("3"),
        "dataset_manifest_hash": _word("4"),
        "authority_registry_snapshot_hash": _word("5"),
        "model_manifest_hash": _word("6"),
        "runtime_environment_hash": _word("7"),
        "evidence_origin_policy_hash": _word("8"),
        "experiment_protocol_hash": _word("9"),
        "epoch": 7,
        "expiry": 500,
        "scope": _scope(),
    }
    payload.update(overrides)
    return TaskEnvelopeV2.model_validate(payload)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("claim_spec_hash", "0x1234"),
        ("task_payload_hash", "0x" + "AB" * 32),
        ("semantic_policy_hash", "f" * 63),
        ("dataset_manifest_hash", "z" * 64),
    ],
)
def test_task_envelope_v2_rejects_malformed_hashes(field_name: str, value: str) -> None:
    with pytest.raises(ValueError, match="32-byte lowercase hex word"):
        _envelope(**{field_name: value})


def test_task_envelope_v2_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _envelope(unexpected_field="drift")


def test_task_envelope_v2_rejects_unknown_scope_fields() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _envelope(scope={**_scope().model_dump(mode="json"), "shadow_scope": "drift"})


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("epoch", -1, "epoch must be non-negative"),
        ("expiry", 0, "expiry must be positive"),
    ],
)
def test_task_envelope_v2_rejects_invalid_epoch_and_expiry(
    field_name: str, value: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _envelope(**{field_name: value})


def test_task_envelope_v2_rejects_ambiguous_scope_bindings() -> None:
    with pytest.raises(ValueError, match="scope bindings must be pairwise distinct"):
        _envelope(
            scope={
                "publication_scope": "PUBLICATION_EVIDENCE_AUTHORIZED",
                "authorization_scope": "PUBLICATION_EVIDENCE_AUTHORIZED",
                "evidence_origin": "REAL_MODEL_EXECUTION",
                "task_class": int(TaskClass.CONSENSUS),
            }
        )


def test_task_envelope_v2_root_changes_when_bound_material_changes() -> None:
    baseline = _envelope()
    mutated = baseline.model_copy(update={"epoch": baseline.epoch + 1})

    assert mutated.task_root != baseline.task_root


def test_task_envelope_v2_root_is_ordering_deterministic() -> None:
    baseline = _envelope()
    shuffled = TaskEnvelopeV2.model_validate(
        OrderedDict(
            [
                ("scope", OrderedDict(reversed(list(_scope().model_dump(mode="json").items())))),
                ("expiry", 500),
                ("epoch", 7),
                ("experiment_protocol_hash", _word("9")),
                ("evidence_origin_policy_hash", _word("8")),
                ("runtime_environment_hash", _word("7")),
                ("model_manifest_hash", _word("6")),
                ("authority_registry_snapshot_hash", _word("5")),
                ("dataset_manifest_hash", _word("4")),
                ("semantic_policy_hash", _word("3")),
                ("task_payload_hash", _word("2")),
                ("claim_spec_hash", _word("1")),
            ]
        )
    )

    assert shuffled.task_root == baseline.task_root
    assert shuffled.canonical_bytes() == baseline.canonical_bytes()


def test_task_envelope_v2_uses_domain_separated_task_root() -> None:
    envelope = _envelope()

    assert envelope.task_root == f"0x{digest(TASK_ENVELOPE_V2_DOMAIN, envelope.canonical_payload())}"
    assert envelope.task_root != f"0x{digest('TASK_ENVELOPE_V2_MUTATED_DOMAIN', envelope.canonical_payload())}"


def test_task_envelope_v2_canonical_serialization_is_stable() -> None:
    envelope = _envelope()

    expected_payload = {
        "authority_registry_snapshot_hash": _word("5"),
        "claim_spec_hash": _word("1"),
        "dataset_manifest_hash": _word("4"),
        "epoch": 7,
        "evidence_origin_policy_hash": _word("8"),
        "experiment_protocol_hash": _word("9"),
        "expiry": 500,
        "model_manifest_hash": _word("6"),
        "runtime_environment_hash": _word("7"),
        "schema_version": TASK_ENVELOPE_V2_SCHEMA,
        "scope": {
            "authorization_scope": "PUBLICATION_EVIDENCE_AUTHORIZED",
            "evidence_origin": "REAL_MODEL_EXECUTION",
            "publication_scope": "E3_CONFIRMATORY_PUBLICATION_V2",
            "task_class": int(TaskClass.CONSENSUS),
        },
        "semantic_policy_hash": _word("3"),
        "task_payload_hash": _word("2"),
    }

    assert envelope.canonical_payload() == expected_payload
    assert envelope.canonical_bytes() == canonical_bytes(TASK_ENVELOPE_V2_DOMAIN, expected_payload)
