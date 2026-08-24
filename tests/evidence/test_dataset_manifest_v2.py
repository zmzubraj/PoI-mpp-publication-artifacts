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
