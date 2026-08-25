from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from poi_mpp.evidence.dataset_manifest_v2 import (
    DatasetManifestRecordV2,
    DatasetManifestV2,
    DatasetSplitV2,
)
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e3_confirmatory_freeze import (
    E3ConfirmatoryFreezeError,
    E3ConfirmatoryFreezeStatus,
    assert_confirmatory_split_isolation,
    assert_phase3_development_manifest_contract,
    prepare_e3_phase4_confirmatory_freeze,
    reconcile_annotation_material,
    reconcile_license_privacy_material,
    validate_confirmatory_decision_counts,
    validate_e3_phase4_confirmatory_freeze_materials,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _token(value: str) -> str:
    return _sha256(value.encode("utf-8"))


def _plumbing_record(index: int, *, split: str = "PLUMBING") -> dict[str, object]:
    if index < 200:
        decision = "ACCEPT"
        outcome = "SUPPORTED_GROUNDS"
    elif index < 400:
        decision = "REJECT"
        outcome = "REJECTED_GROUNDS"
    else:
        decision = "ABSTAIN"
        outcome = "ABSTAIN_GROUNDS"
    record_id = f"synthetic-non-evidence-{index:03d}"
    item = f"SYNTHETIC_NON_EVIDENCE::{record_id}".encode()
    label = _canonical_bytes({"decision": decision, "record_id": record_id})
    return {
        "record_id": record_id,
        "item_path": f"items/{record_id}.txt",
        "label_path": f"labels/{record_id}.json",
        "item_hash": _sha256(item),
        "label_hash": _sha256(label),
        "content_hash": _token(f"content::{record_id}"),
        "split": split,
        "license_id": "CC0-1.0",
        "privacy_status": "AUTHORIZED_PUBLIC",
        "expected_decision": decision,
        "expected_semantic_outcome": outcome,
        "error_family": "SYNTHETIC_PLUMBING_ONLY",
        "subgroup": "synthetic",
        "difficulty": "plumbing",
        "deduplication_group": f"synthetic-group-{index:03d}",
        "annotation": {
            "annotation_scope": "synthetic-plumbing-only",
            "annotation_hash": _token(f"annotation-row::{record_id}"),
            "agreement_fraction": 1.0,
        },
        "evidence_origin": EvidenceOrigin.SYNTHETIC_NON_EVIDENCE.value,
    }


def _write_synthetic_bundle(
    root: Path,
    *,
    canonical_manifest: bool = True,
    manifest_schema_version: str = "POI_MPP_E3_V2_CONFIRMATORY_FREEZE_MANIFEST_V1",
) -> Path:
    records = [_plumbing_record(index) for index in range(500)]
    payloads: dict[str, object] = {
        "dataset_manifest_v2.json": {
            "schema_version": "POI_MPP_DATASET_MANIFEST_V2",
            "dataset_id": "synthetic-confirmatory-plumbing-only",
            "split": "PLUMBING",
            "records": records,
        },
        "annotation_ledger.json": {
            "schema_version": "POI_MPP_E3_V2_ANNOTATION_LEDGER_V1",
            "rows": [],
        },
        "annotation_agreement.json": {
            "schema_version": "POI_MPP_E3_V2_ANNOTATION_AGREEMENT_V1",
            "numerator": 500,
            "denominator": 500,
            "rate": 1.0,
        },
        "adjudication_ledger.json": {
            "schema_version": "POI_MPP_E3_V2_ADJUDICATION_LEDGER_V1",
            "rows": [],
        },
        "license_privacy_ledger.json": {
            "schema_version": "POI_MPP_E3_V2_LICENSE_PRIVACY_LEDGER_V1",
            "rows": [],
        },
    }
    for relative_path, payload in payloads.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_canonical_bytes(payload))
    for record in records:
        record_id = str(record["record_id"])
        item = f"SYNTHETIC_NON_EVIDENCE::{record_id}".encode()
        label = _canonical_bytes({"decision": record["expected_decision"], "record_id": record_id})
        for relative_path, raw in ((record["item_path"], item), (record["label_path"], label)):
            path = root / str(relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
    entries = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path.read_bytes())}
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    manifest = {
        "schema_version": manifest_schema_version,
        "files": entries,
    }
    manifest_path = root / "manifest.json"
    if canonical_manifest:
        manifest_path.write_bytes(_canonical_bytes(manifest))
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return root


def _write_external_placeholder(path: Path) -> Path:
    path.write_bytes(_canonical_bytes({"schema_version": "TEST_ONLY_PLACEHOLDER"}))
    return path


def _synthetic_annotation_material(*, disagreement: bool = False) -> tuple[list[dict[str, object]], dict[str, object], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    adjudications: list[dict[str, object]] = []
    agreements = 0
    for index in range(500):
        record_id = f"synthetic-non-evidence-{index:03d}"
        first = "ACCEPT"
        second = "REJECT" if disagreement and index == 0 else first
        if first == second:
            agreements += 1
        else:
            adjudications.append(
                {
                    "record_id": record_id,
                    "adjudicator_id": "synthetic-adjudicator-plumbing-only",
                    "decision": "REJECT",
                    "adjudication_path": f"adjudications/{record_id}.json",
                    "adjudication_hash": _token(f"adjudication::{record_id}"),
                }
            )
        rows.append(
            {
                "record_id": record_id,
                "annotations": [
                    {
                        "annotator_id": "synthetic-annotator-a-plumbing-only",
                        "decision": first,
                        "annotation_path": f"annotations/{record_id}-a.json",
                        "annotation_hash": _token(f"annotation-a::{record_id}"),
                    },
                    {
                        "annotator_id": "synthetic-annotator-b-plumbing-only",
                        "decision": second,
                        "annotation_path": f"annotations/{record_id}-b.json",
                        "annotation_hash": _token(f"annotation-b::{record_id}"),
                    },
                ],
                "provenance_reference": "SYNTHETIC_NON_EVIDENCE_PLUMBING_ONLY",
            }
        )
    agreement = {
        "numerator": agreements,
        "denominator": 500,
        "rate": agreements / 500,
    }
    return rows, agreement, adjudications


def test_prepare_returns_waiting_external_for_missing_accountable_materials(tmp_path: Path) -> None:
    result = prepare_e3_phase4_confirmatory_freeze(
        bundle_root=tmp_path / "missing-confirmatory-bundle",
        development_manifest_path=tmp_path / "missing-development.json",
    )

    assert result.status is E3ConfirmatoryFreezeStatus.WAITING_EXTERNAL
    assert result.missing_inputs == ("bundle_root", "development_manifest")
    assert result.reason == "missing_accountable_inputs"


def test_decision_count_contract_is_exact_500_200_200_100() -> None:
    decisions = ["ACCEPT"] * 200 + ["REJECT"] * 200 + ["ABSTAIN"] * 100
    assert validate_confirmatory_decision_counts(decisions) == {
        "ACCEPT": 200,
        "REJECT": 200,
        "ABSTAIN": 100,
    }

    with pytest.raises(E3ConfirmatoryFreezeError, match="exactly 200 ACCEPT"):
        validate_confirmatory_decision_counts(decisions[:-1] + ["ACCEPT"])


def test_annotation_reconciliation_requires_two_distinct_annotators_and_exact_agreement() -> None:
    record_ids = tuple(f"synthetic-non-evidence-{index:03d}" for index in range(500))
    rows, agreement, adjudications = _synthetic_annotation_material(disagreement=True)
    summary = reconcile_annotation_material(
        record_ids=record_ids,
        annotation_rows=rows,
        agreement=agreement,
        adjudication_rows=adjudications,
        record_agreement_fractions={
            record_id: (0.0 if index == 0 else 1.0)
            for index, record_id in enumerate(record_ids)
        },
    )
    assert summary == {"numerator": 499, "denominator": 500, "rate": 0.998}

    rows[1]["annotations"][1]["annotator_id"] = rows[1]["annotations"][0]["annotator_id"]
    with pytest.raises(E3ConfirmatoryFreezeError, match="two distinct nonblank annotator IDs"):
        reconcile_annotation_material(
            record_ids=record_ids,
            annotation_rows=rows,
            agreement=agreement,
            adjudication_rows=adjudications,
            record_agreement_fractions={
                record_id: (0.0 if index == 0 else 1.0)
                for index, record_id in enumerate(record_ids)
            },
        )


def test_annotation_reconciliation_requires_adjudication_for_every_disagreement() -> None:
    record_ids = tuple(f"synthetic-non-evidence-{index:03d}" for index in range(500))
    rows, agreement, adjudications = _synthetic_annotation_material(disagreement=True)

    with pytest.raises(E3ConfirmatoryFreezeError, match="adjudication closure mismatch"):
        reconcile_annotation_material(
            record_ids=record_ids,
            annotation_rows=rows,
            agreement=agreement,
            adjudication_rows=[],
            record_agreement_fractions={
                record_id: (0.0 if index == 0 else 1.0)
                for index, record_id in enumerate(record_ids)
            },
        )

    agreement["numerator"] = 500
    with pytest.raises(E3ConfirmatoryFreezeError, match="agreement numerator does not reconcile"):
        reconcile_annotation_material(
            record_ids=record_ids,
            annotation_rows=rows,
            agreement=agreement,
            adjudication_rows=adjudications,
            record_agreement_fractions={
                record_id: (0.0 if index == 0 else 1.0)
                for index, record_id in enumerate(record_ids)
            },
        )


def test_annotation_reconciliation_rejects_per_record_fraction_and_adjudicator_conflicts() -> None:
    record_ids = tuple(f"synthetic-non-evidence-{index:03d}" for index in range(500))
    rows, agreement, adjudications = _synthetic_annotation_material(disagreement=True)
    fractions = {record_id: 1.0 for record_id in record_ids}

    with pytest.raises(E3ConfirmatoryFreezeError, match="record agreement_fraction mismatch"):
        reconcile_annotation_material(
            record_ids=record_ids,
            annotation_rows=rows,
            agreement=agreement,
            adjudication_rows=adjudications,
            record_agreement_fractions=fractions,
        )

    fractions[record_ids[0]] = 0.0
    adjudications[0]["adjudicator_id"] = "synthetic-annotator-a-plumbing-only"
    with pytest.raises(E3ConfirmatoryFreezeError, match="adjudicator must be distinct"):
        reconcile_annotation_material(
            record_ids=record_ids,
            annotation_rows=rows,
            agreement=agreement,
            adjudication_rows=adjudications,
            record_agreement_fractions=fractions,
        )


def test_license_privacy_ledger_requires_exact_record_closure_and_binding() -> None:
    records = [_plumbing_record(index) for index in range(500)]
    rows = [
        {
            "record_id": record["record_id"],
            "license_id": record["license_id"],
            "privacy_status": record["privacy_status"],
            "source_reference": "SYNTHETIC_NON_EVIDENCE_PLUMBING_ONLY",
            "authorization_reference": "SYNTHETIC_NON_EVIDENCE_PLUMBING_ONLY",
        }
        for record in records
    ]
    assert reconcile_license_privacy_material(records=records, ledger_rows=rows) == 500

    rows.pop()
    with pytest.raises(E3ConfirmatoryFreezeError, match="license/privacy ledger closure mismatch"):
        reconcile_license_privacy_material(records=records, ledger_rows=rows)


def test_split_isolation_uses_all_bound_identity_fields_and_rejects_group_leakage() -> None:
    development_record = DatasetManifestRecordV2.model_construct(**_plumbing_record(0))
    confirmatory_payload = _plumbing_record(1)
    confirmatory_payload["deduplication_group"] = development_record.deduplication_group
    confirmatory_record = DatasetManifestRecordV2.model_construct(**confirmatory_payload)
    development = DatasetManifestV2.model_construct(
        dataset_id="synthetic-development-plumbing-only",
        split=DatasetSplitV2.DEVELOPMENT,
        records=(development_record,),
    )
    confirmatory = DatasetManifestV2.model_construct(
        dataset_id="synthetic-confirmatory-plumbing-only",
        split=DatasetSplitV2.CONFIRMATORY,
        records=(confirmatory_record,),
    )

    with pytest.raises(E3ConfirmatoryFreezeError, match="deduplication_group overlap"):
        assert_confirmatory_split_isolation(development, confirmatory)


def test_phase3_development_lineage_rejects_synthetic_non_evidence() -> None:
    records = tuple(
        DatasetManifestRecordV2.model_construct(**_plumbing_record(index, split="DEVELOPMENT"))
        for index in range(120)
    )
    development = DatasetManifestV2.model_construct(
        dataset_id="synthetic-development-plumbing-only",
        split=DatasetSplitV2.DEVELOPMENT,
        records=records,
    )

    with pytest.raises(
        E3ConfirmatoryFreezeError,
        match="development manifest requires REAL_MODEL_EXECUTION evidence origin",
    ):
        assert_phase3_development_manifest_contract(development)


def test_end_to_end_rejects_synthetic_non_evidence_instead_of_proving_ready(tmp_path: Path) -> None:
    bundle_root = _write_synthetic_bundle(tmp_path / "synthetic-confirmatory-bundle")
    development = {
        "schema_version": "POI_MPP_DATASET_MANIFEST_V2",
        "dataset_id": "synthetic-development-plumbing-only",
        "split": "PLUMBING",
        "records": [_plumbing_record(700)],
    }
    development_path = tmp_path / "synthetic-development.json"
    development_path.write_bytes(_canonical_bytes(development))

    with pytest.raises(E3ConfirmatoryFreezeError, match="confirmatory dataset must use CONFIRMATORY split"):
        validate_e3_phase4_confirmatory_freeze_materials(
            bundle_root=bundle_root,
            development_manifest_path=development_path,
        )


def test_bundle_rejects_repository_local_root_and_noncanonical_manifest(tmp_path: Path) -> None:
    repo_bundle = REPO_ROOT / "tmp-e3-phase4-synthetic-only"
    _write_synthetic_bundle(repo_bundle)
    try:
        with pytest.raises(E3ConfirmatoryFreezeError, match="bundle root must live outside the repository"):
            validate_e3_phase4_confirmatory_freeze_materials(
                bundle_root=repo_bundle,
                development_manifest_path=tmp_path / "unused.json",
            )
    finally:
        shutil.rmtree(repo_bundle, ignore_errors=True)

    bundle_root = _write_synthetic_bundle(
        tmp_path / "noncanonical-synthetic-bundle",
        canonical_manifest=False,
    )
    development_path = _write_external_placeholder(tmp_path / "development-placeholder.json")
    with pytest.raises(E3ConfirmatoryFreezeError, match="manifest.json must use canonical JSON"):
        validate_e3_phase4_confirmatory_freeze_materials(
            bundle_root=bundle_root,
            development_manifest_path=development_path,
        )


def test_bundle_rejects_repository_local_development_manifest(tmp_path: Path) -> None:
    bundle_root = _write_synthetic_bundle(tmp_path / "synthetic-confirmatory-bundle")
    repository_manifest = REPO_ROOT / "tmp-e3-phase4-development-manifest.json"
    repository_manifest.write_bytes(
        _canonical_bytes(
            {
                "schema_version": "POI_MPP_DATASET_MANIFEST_V2",
                "dataset_id": "synthetic-development-plumbing-only",
                "split": "PLUMBING",
                "records": [_plumbing_record(700)],
            }
        )
    )
    try:
        with pytest.raises(
            E3ConfirmatoryFreezeError,
            match="development manifest must live outside the repository",
        ):
            validate_e3_phase4_confirmatory_freeze_materials(
                bundle_root=bundle_root,
                development_manifest_path=repository_manifest,
            )
    finally:
        repository_manifest.unlink(missing_ok=True)


def test_bundle_rejects_symlink_member(tmp_path: Path) -> None:
    bundle_root = _write_synthetic_bundle(tmp_path / "symlink-synthetic-bundle")
    target = bundle_root / "annotation_agreement.json"
    target.unlink()
    target.symlink_to(bundle_root / "annotation_ledger.json")
    development_path = _write_external_placeholder(tmp_path / "development-placeholder.json")

    with pytest.raises(E3ConfirmatoryFreezeError, match="may not be a symlink"):
        validate_e3_phase4_confirmatory_freeze_materials(
            bundle_root=bundle_root,
            development_manifest_path=development_path,
        )


def test_bundle_rejects_unknown_manifest_schema_version(tmp_path: Path) -> None:
    bundle_root = _write_synthetic_bundle(
        tmp_path / "wrong-schema-synthetic-bundle",
        manifest_schema_version="POI_MPP_E3_V2_CONFIRMATORY_FREEZE_MANIFEST_V999",
    )
    development_path = _write_external_placeholder(tmp_path / "development-placeholder.json")

    with pytest.raises(E3ConfirmatoryFreezeError, match="schema validation failed"):
        validate_e3_phase4_confirmatory_freeze_materials(
            bundle_root=bundle_root,
            development_manifest_path=development_path,
        )
