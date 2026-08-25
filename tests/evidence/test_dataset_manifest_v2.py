import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from poi_mpp.evidence.dataset_manifest_v2 import (
    DatasetAnnotationProvenanceV2,
    DatasetExpectedDecision,
    DatasetExpectedSemanticOutcome,
    DatasetManifestRecordV2,
    DatasetManifestV2,
    DatasetPrivacyStatus,
    DatasetSplitV2,
    assert_v2_split_isolation,
)
from poi_mpp.evidence.models import EvidenceOrigin


def _word(seed: str) -> str:
    return seed * 64


def _annotation(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "annotation_scope": "E3_CONFIRMATORY_LABELS_V2",
        "annotation_hash": _word("a"),
        "agreement_fraction": 0.875,
    }
    payload.update(overrides)
    return payload


def _record(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "record_id": "case-001",
        "item_path": "items/case-001.json",
        "label_path": "labels/case-001.json",
        "item_hash": _word("1"),
        "label_hash": _word("2"),
        "content_hash": _word("3"),
        "split": "CONFIRMATORY",
        "license_id": "cc-by-4.0",
        "privacy_status": "AUTHORIZED_PUBLIC",
        "expected_decision": "ACCEPT",
        "expected_semantic_outcome": "SUPPORTED_GROUNDS",
        "error_family": "grounded_citation",
        "subgroup": "citation-present",
        "difficulty": "medium",
        "deduplication_group": "group-a",
        "annotation": _annotation(),
        "evidence_origin": "REAL_MODEL_EXECUTION",
    }
    payload.update(overrides)
    return payload


def _manifest(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "POI_MPP_DATASET_MANIFEST_V2",
        "dataset_id": "E3_CONFIRMATORY_SET_V2",
        "split": "CONFIRMATORY",
        "records": (
            _record(),
            _record(
                record_id="case-002",
                item_path="items/case-002.json",
                label_path="labels/case-002.json",
                item_hash=_word("4"),
                label_hash=_word("5"),
                content_hash=_word("6"),
                deduplication_group="group-b",
            ),
        ),
    }
    payload.update(overrides)
    return payload


def test_dataset_manifest_v2_is_immutable_and_forbids_unknown_fields() -> None:
    manifest = DatasetManifestV2.model_validate(_manifest())

    with pytest.raises(ValidationError):
        manifest.dataset_id = "mutated"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DatasetManifestV2.model_validate({**_manifest(), "unexpected": True})


def test_dataset_manifest_v2_rejects_split_origin_boundary_violations() -> None:
    with pytest.raises(ValidationError, match="synthetic non-evidence cannot enter"):
        DatasetManifestV2.model_validate(
            _manifest(records=(_record(evidence_origin="SYNTHETIC_NON_EVIDENCE"),))
        )

    with pytest.raises(ValidationError, match="plumbing fixtures must remain SYNTHETIC_NON_EVIDENCE"):
        DatasetManifestV2.model_validate(
            _manifest(
                split="PLUMBING",
                dataset_id="E3_PLUMBING_SET_V2",
                records=(
                    _record(
                        split="PLUMBING",
                        evidence_origin="REAL_MODEL_EXECUTION",
                        item_path="items/plumbing-001.json",
                        label_path="labels/plumbing-001.json",
                    ),
                ),
            )
        )


def test_dataset_manifest_v2_rejects_duplicate_bindings_and_split_drift() -> None:
    with pytest.raises(ValidationError, match="duplicate record_id"):
        DatasetManifestV2.model_validate(_manifest(records=(_record(), _record())))

    with pytest.raises(ValidationError, match="duplicate item_hash"):
        DatasetManifestV2.model_validate(
            _manifest(
                records=(
                    _record(),
                    _record(
                        record_id="case-002",
                        item_path="items/case-002.json",
                        label_path="labels/case-002.json",
                        label_hash=_word("7"),
                        content_hash=_word("8"),
                        deduplication_group="group-b",
                    ),
                )
            )
        )

    with pytest.raises(ValidationError, match="all records must match the manifest split"):
        DatasetManifestV2.model_validate(
            _manifest(records=(_record(split="DEVELOPMENT"),))
        )


def test_dataset_manifest_v2_hash_is_order_stable_but_changes_on_mutation() -> None:
    first = DatasetManifestV2.model_validate(_manifest())
    reordered = DatasetManifestV2.model_validate(
        _manifest(records=tuple(reversed(_manifest()["records"])))
    )
    mutated = DatasetManifestV2.model_validate(
        _manifest(
            records=(
                _record(),
                _record(
                    record_id="case-002",
                    item_path="items/case-002.json",
                    label_path="labels/case-002.json",
                    item_hash=_word("4"),
                    label_hash=_word("5"),
                    content_hash=_word("6"),
                    difficulty="hard",
                    deduplication_group="group-b",
                ),
            )
        )
    )

    assert first.dataset_manifest_hash() == reordered.dataset_manifest_hash()
    assert first.canonical_material() == reordered.canonical_material()
    assert first.dataset_manifest_hash() != mutated.dataset_manifest_hash()


def test_dataset_manifest_v2_resolves_rooted_files_and_rejects_unsafe_paths(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    (root / "items").mkdir(parents=True)
    (root / "labels").mkdir(parents=True)
    (root / "items" / "case-001.json").write_text("{}", encoding="utf-8")
    (root / "labels" / "case-001.json").write_text("{}", encoding="utf-8")
    manifest = DatasetManifestV2.model_validate(_manifest(records=(_record(),)))

    bindings = manifest.rooted_file_bindings(root)

    assert bindings[0].record_id == "case-001"
    assert bindings[0].item_path == (root / "items" / "case-001.json").resolve(strict=True)
    assert bindings[0].label_path == (root / "labels" / "case-001.json").resolve(strict=True)

    with pytest.raises(ValidationError, match="item_path cannot contain parent traversal"):
        DatasetManifestV2.model_validate(
            _manifest(records=(_record(item_path="../escape.json"),))
        )

    external = tmp_path / "external.json"
    external.write_text("{}", encoding="utf-8")
    (root / "items" / "case-001.json").unlink()
    (root / "items" / "case-001.json").symlink_to(external)
    with pytest.raises(ValueError, match="may not be a symlink"):
        manifest.rooted_file_bindings(root)

    symlink_root = tmp_path / "dataset-link"
    symlink_root.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="root may not be a symlink"):
        manifest.rooted_file_bindings(symlink_root)


def test_dataset_manifest_v2_exports_frozen_enums_and_annotation_schema() -> None:
    annotation = DatasetAnnotationProvenanceV2.model_validate(_annotation())
    record = DatasetManifestRecordV2.model_validate(_record(annotation=annotation))

    assert DatasetSplitV2.CONFIRMATORY.value == "CONFIRMATORY"
    assert DatasetPrivacyStatus.AUTHORIZED_PUBLIC.value == "AUTHORIZED_PUBLIC"
    assert DatasetExpectedDecision.ACCEPT.value == "ACCEPT"
    assert DatasetExpectedSemanticOutcome.SUPPORTED_GROUNDS.value == "SUPPORTED_GROUNDS"
    assert record.annotation.annotation_scope == "E3_CONFIRMATORY_LABELS_V2"


def test_dataset_manifest_v2_verifies_bound_file_bytes_and_detects_tampering(
    tmp_path: Path,
) -> None:
    root = tmp_path / "dataset"
    (root / "items").mkdir(parents=True)
    (root / "labels").mkdir(parents=True)
    item = b'{"prompt":"grounded"}\n'
    label = b'{"expected_decision":"ACCEPT"}\n'
    (root / "items" / "case-001.json").write_bytes(item)
    (root / "labels" / "case-001.json").write_bytes(label)
    manifest = DatasetManifestV2.model_validate(
        _manifest(
            records=(
                _record(
                    item_hash=hashlib.sha256(item).hexdigest(),
                    label_hash=hashlib.sha256(label).hexdigest(),
                ),
            )
        )
    )

    verified = manifest.verify_rooted_file_hashes(root)
    assert verified == ("case-001",)

    (root / "labels" / "case-001.json").write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="label_hash mismatch for case-001"):
        manifest.verify_rooted_file_hashes(root)


@pytest.mark.parametrize(
    ("field_name", "expected_message"),
    [
        ("record_id", "record_id overlap"),
        ("item_hash", "item_hash overlap"),
        ("label_hash", "label_hash overlap"),
        ("content_hash", "content_hash overlap"),
        ("deduplication_group", "deduplication_group overlap"),
    ],
)
def test_v2_split_isolation_rejects_every_bound_overlap(
    field_name: str,
    expected_message: str,
) -> None:
    development_record = _record(
        record_id="development-001",
        item_path="items/development-001.json",
        label_path="labels/development-001.json",
        item_hash=_word("a"),
        label_hash=_word("b"),
        content_hash=_word("c"),
        split="DEVELOPMENT",
        deduplication_group="development-group",
        evidence_origin="REAL_MODEL_EXECUTION",
    )
    confirmatory_record = _record(
        record_id="confirmatory-001",
        item_path="items/confirmatory-001.json",
        label_path="labels/confirmatory-001.json",
        item_hash=_word("d"),
        label_hash=_word("e"),
        content_hash=_word("f"),
        split="CONFIRMATORY",
        deduplication_group="confirmatory-group",
    )
    confirmatory_record[field_name] = development_record[field_name]
    development = DatasetManifestV2.model_validate(
        _manifest(
            dataset_id="E3_DEVELOPMENT_SET_V2",
            split="DEVELOPMENT",
            records=(development_record,),
        )
    )
    confirmatory = DatasetManifestV2.model_validate(
        _manifest(records=(confirmatory_record,))
    )

    with pytest.raises(ValueError, match=expected_message):
        assert_v2_split_isolation(development, confirmatory)


def test_v2_split_isolation_requires_development_then_confirmatory_and_reports_counts() -> None:
    development = DatasetManifestV2.model_validate(
        _manifest(
            dataset_id="E3_DEVELOPMENT_SET_V2",
            split="DEVELOPMENT",
            records=(
                _record(
                    record_id="development-accept",
                    item_path="items/development-accept.json",
                    label_path="labels/development-accept.json",
                    item_hash=_word("a"),
                    label_hash=_word("b"),
                    content_hash=_word("c"),
                    split="DEVELOPMENT",
                    deduplication_group="development-accept",
                    evidence_origin="REAL_MODEL_EXECUTION",
                ),
                _record(
                    record_id="development-abstain",
                    item_path="items/development-abstain.json",
                    label_path="labels/development-abstain.json",
                    item_hash=_word("d"),
                    label_hash=_word("e"),
                    content_hash=_word("f"),
                    split="DEVELOPMENT",
                    expected_decision="ABSTAIN",
                    expected_semantic_outcome="ABSTAIN_GROUNDS",
                    deduplication_group="development-abstain",
                    evidence_origin="REAL_MODEL_EXECUTION",
                ),
            ),
        )
    )
    confirmatory = DatasetManifestV2.model_validate(
        _manifest(
            records=(
                _record(
                    record_id="confirmatory-001",
                    item_path="items/confirmatory-001.json",
                    label_path="labels/confirmatory-001.json",
                    item_hash=_word("1"),
                    label_hash=_word("2"),
                    content_hash=_word("3"),
                    deduplication_group="confirmatory-group",
                ),
            )
        )
    )

    assert_v2_split_isolation(development, confirmatory)
    assert development.decision_counts() == {"ABSTAIN": 1, "ACCEPT": 1, "REJECT": 0}
    assert development.error_family_counts() == {"grounded_citation": 2}

    with pytest.raises(ValueError, match="development manifest must use DEVELOPMENT split"):
        assert_v2_split_isolation(confirmatory, development)
