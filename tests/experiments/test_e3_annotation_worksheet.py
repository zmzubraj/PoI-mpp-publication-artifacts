"""TDD tests for the E3-v2 annotation worksheet compiler and dataset sealer.

These builders feed the Phase-3/Phase-4 external-bundle compilers with the
dataset-side materials (items, labels, annotations, ledgers). They are
fail-closed: worksheet emission is deterministic and self-digested, and the
sealer only emits a dataset manifest that closes every binding the canonical
validators in ``e3_confirmatory_freeze`` demand.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from poi_mpp.evidence.dataset_manifest_v2 import (
    DatasetManifestV2,
    DatasetExpectedDecision,
)
from poi_mpp.experiments.e3_confirmatory_freeze import (
    _verify_bound_annotation_files,
    reconcile_annotation_material,
    reconcile_license_privacy_material,
)
from poi_mpp.experiments.e3_annotation_worksheet import (
    AnnotationWorksheetCompiler,
    AnnotatedDatasetSealer,
    WorksheetCompilerError,
    SealerError,
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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_counter = {"n": 0}


def _fresh_text() -> str:
    _counter["n"] += 1
    return f"claim text { _counter['n']:06d}"


def _item(record_id: str, text: str | None = None) -> dict[str, object]:
    return {
        "source_id": record_id,
        "text": text if text is not None else _fresh_text(),
        "evidence": f"evidence for {record_id}",
        "error_family": "BASELINE",
        "subgroup": "core",
        "difficulty": "standard",
    }


def _write_items(path: Path, items: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(item, sort_keys=True, ensure_ascii=False) for item in items) + "\n",
        encoding="utf-8",
    )
    return path


def _claim_spec_bytes() -> bytes:
    return _canonical_bytes(
        {
            "schema_version": "POI_MPP_E3_CLAIM_SPEC_V1",
            "claim_id": "C3",
            "scope": "GROUNDED_SEMANTIC_ASSURANCE",
        }
    )


# --- Worksheet compiler: dedup + canonical self-digest ---


def test_development_worksheet_dedupes_by_content_hash(tmp_path: Path) -> None:
    items = [_item(f"src-{i}") for i in range(120)]
    # Add duplicates that must collapse into dedup groups (repeat text of src-0 and src-1).
    items += [_item("src-dup-0", text=items[0]["text"]), _item("src-dup-1", text=items[1]["text"])]
    items_path = _write_items(tmp_path / "items.jsonl", items)
    spec = tmp_path / "claim_spec.json"
    spec.write_bytes(_claim_spec_bytes())
    worksheet_root = tmp_path / "worksheet"

    result = AnnotationWorksheetCompiler.build(
        items_path=items_path,
        claim_spec_path=spec,
        split="DEVELOPMENT",
        dataset_id="e3-v2-dev-test",
        allocation={"ACCEPT": 50, "REJECT": 50, "ABSTAIN": 20},
        output_root=worksheet_root,
    )

    # 122 raw inputs collapse to 120 unique content hashes (2 dups share existing text).
    unique_records = [r for r in result["records"] if not r["is_duplicate"]]
    duplicate_records = [r for r in result["records"] if r["is_duplicate"]]
    assert len(unique_records) == 120
    assert len(duplicate_records) == 2
    # The first occurrence of each duplicate text forms a dedup group.
    dup_group_ids = {r["deduplication_group"] for r in duplicate_records}
    assert len(dup_group_ids) == 2
    assert result["manifest"]["split"] == "DEVELOPMENT"
    assert result["manifest"]["dataset_id"] == "e3-v2-dev-test"


def test_worksheet_manifest_is_canonical_and_self_digested(tmp_path: Path) -> None:
    items_path = _write_items(tmp_path / "items.jsonl", [_item(f"src-{i}") for i in range(120)])
    spec = tmp_path / "claim_spec.json"
    spec.write_bytes(_claim_spec_bytes())
    worksheet_root = tmp_path / "worksheet"

    result = AnnotationWorksheetCompiler.build(
        items_path=items_path,
        claim_spec_path=spec,
        split="DEVELOPMENT",
        dataset_id="e3-v2-dev-test",
        allocation={"ACCEPT": 50, "REJECT": 50, "ABSTAIN": 20},
        output_root=worksheet_root,
    )

    manifest_path = worksheet_root / "manifest.json"
    raw = manifest_path.read_bytes()
    # Canonical emission: bytes must equal canonical serialization of parsed payload.
    payload = json.loads(raw)
    assert raw == _canonical_bytes(payload)
    # self_digest closes over the canonical bytes with the field removed.
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    assert result["manifest"]["self_digest"] == _sha256(_canonical_bytes(unsigned))
    assert manifest_path.read_bytes() == _canonical_bytes(payload)


def test_worksheet_emits_one_item_file_per_unique_record(tmp_path: Path) -> None:
    items_path = _write_items(
        tmp_path / "items.jsonl",
        [_item(f"src-{i}", text=f"text-{i}") for i in range(80)],
    )
    spec = tmp_path / "claim_spec.json"
    spec.write_bytes(_claim_spec_bytes())
    worksheet_root = tmp_path / "worksheet"

    result = AnnotationWorksheetCompiler.build(
        items_path=items_path,
        claim_spec_path=spec,
        split="DEVELOPMENT",
        dataset_id="e3-v2-dev-test",
        allocation={"ACCEPT": 50, "REJECT": 30},
        output_root=worksheet_root,
    )

    items_dir = worksheet_root / "items"
    emitted = sorted(path.stem for path in items_dir.glob("*.txt"))
    record_ids = sorted(r["record_id"] for r in result["records"] if not r["is_duplicate"])
    assert emitted == record_ids


def test_worksheet_rejects_allocation_exceeding_item_count(tmp_path: Path) -> None:
    items_path = _write_items(tmp_path / "items.jsonl", [_item(f"src-{i}") for i in range(110)])
    spec = tmp_path / "claim_spec.json"
    spec.write_bytes(_claim_spec_bytes())
    worksheet_root = tmp_path / "worksheet"

    with pytest.raises(WorksheetCompilerError, match="allocation"):
        AnnotationWorksheetCompiler.build(
            items_path=items_path,
            claim_spec_path=spec,
            split="DEVELOPMENT",
            dataset_id="e3-v2-dev-test",
            allocation={"ACCEPT": 60, "REJECT": 60, "ABSTAIN": 60},
            output_root=worksheet_root,
        )


# --- Sealer: two-annotator agreement, ledgers close ---


def _make_worksheet(tmp_path: Path, count: int, text_prefix: str = "text") -> tuple[
    Path, Path, Path, list[dict[str, object]]
]:
    items = [_item(f"src-{i}", text=f"{text_prefix}-{i}") for i in range(count)]
    items_path = _write_items(tmp_path / "items.jsonl", items)
    spec = tmp_path / "claim_spec.json"
    spec.write_bytes(_claim_spec_bytes())
    worksheet_root = tmp_path / "worksheet"
    result = AnnotationWorksheetCompiler.build(
        items_path=items_path,
        claim_spec_path=spec,
        split="DEVELOPMENT",
        dataset_id="e3-v2-dev-test",
        allocation={"ACCEPT": 50, "REJECT": 50, "ABSTAIN": 20},
        output_root=worksheet_root,
    )
    return items_path, spec, worksheet_root, result["records"]


def _write_annotation(worksheet_root: Path, record_id: str, annotator: str, decision: str) -> None:
    ann_dir = worksheet_root / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "annotator_id": annotator,
        "decision": decision,
        "record_id": record_id,
    }
    (ann_dir / f"{record_id}-{annotator}.json").write_bytes(_canonical_bytes(payload))


def _write_adjudication(worksheet_root: Path, record_id: str, adjudicator: str, decision: str) -> None:
    adj_dir = worksheet_root / "adjudications"
    adj_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "adjudicator_id": adjudicator,
        "decision": decision,
        "record_id": record_id,
    }
    (adj_dir / f"{record_id}.json").write_bytes(_canonical_bytes(payload))


def _write_license(tmp_path: Path) -> Path:
    license_root = tmp_path / "license"
    rows = [
        {
            "record_id": f"dev-{i:04d}",
            "license_id": "CC-BY-4.0",
            "privacy_status": "AUTHORIZED_PUBLIC",
            "source_reference": f"source::{i}",
            "authorization_reference": f"auth::{i}",
        }
        for i in range(120)
    ]
    license_root.write_bytes(_canonical_bytes({"schema_version": "POI_MPP_E3_LICENSE_PRIVACY_LEDGER_V1", "rows": rows}))
    return license_root


def test_sealer_builds_dataset_manifest_passing_real_validators(tmp_path: Path) -> None:
    items_path, spec, worksheet_root, records = _make_worksheet(tmp_path, 120)

    annotator_a = "annotator-anna"
    annotator_b = "annotator-bob"
    # Both annotators agree on every item; dev allocation is 50/50/20.
    decisions = []
    for idx, record in enumerate(records):
        if not record["is_duplicate"]:
            decision = "ACCEPT" if idx < 50 else ("REJECT" if idx < 100 else "ABSTAIN")
            decisions.append((record["record_id"], decision))
            _write_annotation(worksheet_root, record["record_id"], annotator_a, decision)
            _write_annotation(worksheet_root, record["record_id"], annotator_b, decision)

    sealer = AnnotatedDatasetSealer(
        worksheet_root=worksheet_root,
        claim_spec_hash=_sha256(_claim_spec_bytes()),
        annotator_ids=(annotator_a, annotator_b),
    )
    bundle = sealer.seal(
        output_root=tmp_path / "bundle",
        decisions_source=decisions,
        license_ledger_path=_write_license(tmp_path),
        evidence_origin="REAL_MODEL_EXECUTION",
    )

    manifest = DatasetManifestV2.model_validate(
        json.loads((bundle.dataset_root / "dataset_manifest_v2.json").read_bytes())
    )
    counts = manifest.decision_counts()
    assert counts == {"ACCEPT": 50, "REJECT": 50, "ABSTAIN": 20}

    # Ledger rows reconcile exactly.
    annotation_rows = json.loads((bundle.dataset_root / "annotation_ledger.json").read_bytes())["rows"]
    agreement = json.loads((bundle.dataset_root / "annotation_agreement.json").read_bytes())
    adjudication_rows = json.loads((bundle.dataset_root / "adjudication_ledger.json").read_bytes())["rows"]
    license_rows = json.loads((bundle.dataset_root / "license_privacy_ledger.json").read_bytes())["rows"]

    record_ids = [r.record_id for r in manifest.records]
    reconcile_annotation_material(
        record_ids=record_ids,
        annotation_rows=annotation_rows,
        agreement=agreement,
        adjudication_rows=adjudication_rows,
        record_agreement_fractions={r.record_id: r.annotation.agreement_fraction for r in manifest.records},
    )
    assert agreement == {
        "schema_version": "POI_MPP_E3_V2_ANNOTATION_AGREEMENT_V1",
        "numerator": 120,
        "denominator": 120,
        "rate": "1",
    }

    reconcile_license_privacy_material(
        records=[r.model_dump(mode="json") for r in manifest.records],
        ledger_rows=license_rows,
    )

    # Per-file annotation hash closures (the canonical validator's tightest check).
    _verify_bound_annotation_files(
        bundle_root=bundle.dataset_root,
        dataset_manifest=manifest,
        annotation_rows=annotation_rows,
        adjudication_rows=adjudication_rows,
    )


def test_sealer_adjudicates_disagreement_and_reconciles_rate(tmp_path: Path) -> None:
    items_path, spec, worksheet_root, records = _make_worksheet(tmp_path, 120)

    annotator_a = "annotator-anna"
    annotator_b = "annotator-bob"
    adjudicator = "adjudicator-carol"

    decisions = []
    disagreements = []
    for idx, record in enumerate(records):
        if record["is_duplicate"]:
            continue
        decision = "ACCEPT" if idx < 50 else ("REJECT" if idx < 100 else "ABSTAIN")
        decisions.append((record["record_id"], decision))
        _write_annotation(worksheet_root, record["record_id"], annotator_a, decision)
        # Force exactly one disagreement on the first record.
        if idx == 0:
            second = "ABSTAIN"
            disagreements.append(record["record_id"])
            _write_adjudication(worksheet_root, record["record_id"], adjudicator, decision)
        else:
            second = decision
        _write_annotation(worksheet_root, record["record_id"], annotator_b, second)

    assert len(disagreements) == 1

    sealer = AnnotatedDatasetSealer(
        worksheet_root=worksheet_root,
        claim_spec_hash=_sha256(_claim_spec_bytes()),
        annotator_ids=(annotator_a, annotator_b),
    )
    bundle = sealer.seal(
        output_root=tmp_path / "bundle",
        decisions_source=decisions,
        license_ledger_path=_write_license(tmp_path),
        evidence_origin="REAL_MODEL_EXECUTION",
    )

    manifest = DatasetManifestV2.model_validate(
        json.loads((bundle.dataset_root / "dataset_manifest_v2.json").read_bytes())
    )
    annotation_rows = json.loads((bundle.dataset_root / "annotation_ledger.json").read_bytes())["rows"]
    agreement = json.loads((bundle.dataset_root / "annotation_agreement.json").read_bytes())
    adjudication_rows = json.loads((bundle.dataset_root / "adjudication_ledger.json").read_bytes())["rows"]

    record_ids = [r.record_id for r in manifest.records]
    reconcile_annotation_material(
        record_ids=record_ids,
        annotation_rows=annotation_rows,
        agreement=agreement,
        adjudication_rows=adjudication_rows,
        record_agreement_fractions={r.record_id: r.annotation.agreement_fraction for r in manifest.records},
    )
    assert agreement == {
        "schema_version": "POI_MPP_E3_V2_ANNOTATION_AGREEMENT_V1",
        "numerator": 119,
        "denominator": 120,
        "rate": str(Decimal(119) / Decimal(120)),
    }
    # Adjudicator distinct from both annotators on the disagreed record.
    disagreed_row = next(r for r in adjudication_rows if r["record_id"] == disagreements[0])
    assert disagreed_row["adjudicator_id"] == adjudicator
    assert disagreed_row["adjudicator_id"] not in {annotator_a, annotator_b}


def test_sealer_rejects_duplicate_annotator_or_single_annotator(tmp_path: Path) -> None:
    items_path, spec, worksheet_root, records = _make_worksheet(tmp_path, 120)

    for record in records[:50]:
        if record["is_duplicate"]:
            continue
        rid = record["record_id"]
        _write_annotation(worksheet_root, rid, "annotator-anna", "ACCEPT")
        _write_annotation(worksheet_root, rid, "annotator-anna", "ACCEPT")  # duplicate annotator
    sealer = AnnotatedDatasetSealer(
        worksheet_root=worksheet_root,
        claim_spec_hash=_sha256(_claim_spec_bytes()),
        annotator_ids=("annotator-anna", "annotator-bob"),
    )
    with pytest.raises(SealerError):
        sealer.seal(
            output_root=tmp_path / "bundle",
            decisions_source=[(r["record_id"], "ACCEPT") for r in records if not r["is_duplicate"]],
            license_ledger_path=_write_license(tmp_path),
            evidence_origin="REAL_MODEL_EXECUTION",
        )


def test_sealer_rejects_synthetic_origin_for_real_split(tmp_path: Path) -> None:
    items_path, spec, worksheet_root, records = _make_worksheet(tmp_path, 120)
    annotator_a = "annotator-anna"
    annotator_b = "annotator-bob"
    for idx, record in enumerate(records):
        if record["is_duplicate"]:
            continue
        decision = "ACCEPT" if idx < 50 else ("REJECT" if idx < 100 else "ABSTAIN")
        _write_annotation(worksheet_root, record["record_id"], annotator_a, decision)
        _write_annotation(worksheet_root, record["record_id"], annotator_b, decision)
    sealer = AnnotatedDatasetSealer(
        worksheet_root=worksheet_root,
        claim_spec_hash=_sha256(_claim_spec_bytes()),
        annotator_ids=(annotator_a, annotator_b),
    )
    with pytest.raises(SealerError, match="evidence_origin"):
        sealer.seal(
            output_root=tmp_path / "bundle",
            decisions_source=[(r["record_id"], "ACCEPT") for r in records if not r["is_duplicate"]],
            license_ledger_path=_write_license(tmp_path),
            evidence_origin="SYNTHETIC_NON_EVIDENCE",
        )


def test_sealer_rejects_claim_spec_binding_mismatch(tmp_path: Path) -> None:
    _, _, worksheet_root, _ = _make_worksheet(tmp_path, 120)
    with pytest.raises(SealerError, match="claim_spec_hash does not match worksheet manifest"):
        AnnotatedDatasetSealer(
            worksheet_root=worksheet_root,
            claim_spec_hash="0" * 64,
            annotator_ids=("annotator-anna", "annotator-bob"),
        )


def test_sealer_rejects_annotation_payload_identity_mismatch(tmp_path: Path) -> None:
    _, _, worksheet_root, records = _make_worksheet(tmp_path, 120)
    decisions = []
    for idx, record in enumerate(records):
        if record["is_duplicate"]:
            continue
        decision = "ACCEPT" if idx < 50 else ("REJECT" if idx < 100 else "ABSTAIN")
        decisions.append((record["record_id"], decision))
        _write_annotation(worksheet_root, record["record_id"], "annotator-anna", decision)
        _write_annotation(worksheet_root, record["record_id"], "annotator-bob", decision)
    tampered = worksheet_root / "annotations" / "dev-0000-annotator-anna.json"
    tampered.write_bytes(
        _canonical_bytes(
            {
                "annotator_id": "different-person",
                "decision": "ACCEPT",
                "record_id": "dev-0000",
            }
        )
    )

    sealer = AnnotatedDatasetSealer(
        worksheet_root=worksheet_root,
        claim_spec_hash=_sha256(_claim_spec_bytes()),
        annotator_ids=("annotator-anna", "annotator-bob"),
    )
    with pytest.raises(SealerError, match="annotation identity mismatch"):
        sealer.seal(
            output_root=tmp_path / "bundle",
            decisions_source=decisions,
            license_ledger_path=_write_license(tmp_path),
            evidence_origin="REAL_MODEL_EXECUTION",
        )


def test_sealer_rejects_duplicate_or_unknown_decision_rows(tmp_path: Path) -> None:
    _, _, worksheet_root, records = _make_worksheet(tmp_path, 120)
    decisions = [
        (record["record_id"], "ACCEPT")
        for record in records
        if not record["is_duplicate"]
    ]
    decisions.append(decisions[0])
    sealer = AnnotatedDatasetSealer(
        worksheet_root=worksheet_root,
        claim_spec_hash=_sha256(_claim_spec_bytes()),
        annotator_ids=("annotator-anna", "annotator-bob"),
    )
    with pytest.raises(SealerError, match="duplicate decision row"):
        sealer.seal(
            output_root=tmp_path / "bundle",
            decisions_source=decisions,
            license_ledger_path=_write_license(tmp_path),
            evidence_origin="REAL_MODEL_EXECUTION",
        )


def test_sealer_does_not_mutate_source_worksheet_with_derived_labels(tmp_path: Path) -> None:
    _, _, worksheet_root, records = _make_worksheet(tmp_path, 120)
    decisions = []
    for idx, record in enumerate(records):
        if record["is_duplicate"]:
            continue
        decision = "ACCEPT" if idx < 50 else ("REJECT" if idx < 100 else "ABSTAIN")
        decisions.append((record["record_id"], decision))
        _write_annotation(worksheet_root, record["record_id"], "annotator-anna", decision)
        _write_annotation(worksheet_root, record["record_id"], "annotator-bob", decision)

    sealer = AnnotatedDatasetSealer(
        worksheet_root=worksheet_root,
        claim_spec_hash=_sha256(_claim_spec_bytes()),
        annotator_ids=("annotator-anna", "annotator-bob"),
    )
    sealer.seal(
        output_root=tmp_path / "bundle",
        decisions_source=decisions,
        license_ledger_path=_write_license(tmp_path),
        evidence_origin="REAL_MODEL_EXECUTION",
    )

    assert not (worksheet_root / "labels").exists()
    assert len(list((tmp_path / "bundle" / "labels").glob("*.json"))) == 120


def test_sealer_rejects_items_jsonl_tampering_after_worksheet_build(tmp_path: Path) -> None:
    _, _, worksheet_root, _ = _make_worksheet(tmp_path, 120)
    items_path = worksheet_root / "items.jsonl"
    items_path.write_bytes(items_path.read_bytes() + b'{"text":"tampered"}\n')

    with pytest.raises(SealerError, match="items.jsonl hash mismatch"):
        AnnotatedDatasetSealer(
            worksheet_root=worksheet_root,
            claim_spec_hash=_sha256(_claim_spec_bytes()),
            annotator_ids=("annotator-anna", "annotator-bob"),
        )


def test_sealer_rejects_symlinked_annotation_input(tmp_path: Path) -> None:
    _, _, worksheet_root, records = _make_worksheet(tmp_path, 120)
    decisions = []
    for idx, record in enumerate(records):
        if record["is_duplicate"]:
            continue
        decision = "ACCEPT" if idx < 50 else ("REJECT" if idx < 100 else "ABSTAIN")
        decisions.append((record["record_id"], decision))
        _write_annotation(worksheet_root, record["record_id"], "annotator-anna", decision)
        _write_annotation(worksheet_root, record["record_id"], "annotator-bob", decision)

    target = worksheet_root / "annotations" / "dev-0000-annotator-anna.json"
    external = tmp_path / "external-annotation.json"
    external.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(external)

    sealer = AnnotatedDatasetSealer(
        worksheet_root=worksheet_root,
        claim_spec_hash=_sha256(_claim_spec_bytes()),
        annotator_ids=("annotator-anna", "annotator-bob"),
    )
    with pytest.raises(SealerError, match="symlink"):
        sealer.seal(
            output_root=tmp_path / "bundle",
            decisions_source=decisions,
            license_ledger_path=_write_license(tmp_path),
            evidence_origin="REAL_MODEL_EXECUTION",
        )


def test_sealer_rejects_symlinked_license_input(tmp_path: Path) -> None:
    _, _, worksheet_root, records = _make_worksheet(tmp_path, 120)
    decisions = []
    for idx, record in enumerate(records):
        if record["is_duplicate"]:
            continue
        decision = "ACCEPT" if idx < 50 else ("REJECT" if idx < 100 else "ABSTAIN")
        decisions.append((record["record_id"], decision))
        _write_annotation(worksheet_root, record["record_id"], "annotator-anna", decision)
        _write_annotation(worksheet_root, record["record_id"], "annotator-bob", decision)

    external = _write_license(tmp_path)
    linked = tmp_path / "linked-license.json"
    linked.symlink_to(external)
    sealer = AnnotatedDatasetSealer(
        worksheet_root=worksheet_root,
        claim_spec_hash=_sha256(_claim_spec_bytes()),
        annotator_ids=("annotator-anna", "annotator-bob"),
    )
    with pytest.raises(SealerError, match="symlink"):
        sealer.seal(
            output_root=tmp_path / "bundle",
            decisions_source=decisions,
            license_ledger_path=linked,
            evidence_origin="REAL_MODEL_EXECUTION",
        )


def test_failed_seal_leaves_no_partial_output(tmp_path: Path) -> None:
    _, _, worksheet_root, records = _make_worksheet(tmp_path, 120)
    output_root = tmp_path / "bundle"
    sealer = AnnotatedDatasetSealer(
        worksheet_root=worksheet_root,
        claim_spec_hash=_sha256(_claim_spec_bytes()),
        annotator_ids=("annotator-anna", "annotator-bob"),
    )

    with pytest.raises(SealerError, match="missing annotations"):
        sealer.seal(
            output_root=output_root,
            decisions_source=[
                (record["record_id"], "ACCEPT")
                for record in records
                if not record["is_duplicate"]
            ],
            license_ledger_path=_write_license(tmp_path),
            evidence_origin="REAL_MODEL_EXECUTION",
        )

    assert not output_root.exists()
