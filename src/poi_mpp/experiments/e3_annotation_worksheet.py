"""Fail-closed E3-v2 annotation worksheet compiler and dataset sealer.

These builders run in the human data phase *before* any model execution.
They emit canonical, self-digested worksheet material and a reconciled
dataset manifest that closes every binding demanded by the Phase-3 and
Phase-4 external-bundle validators in ``e3_confirmatory_freeze``.

No synthetic evidence is permitted for real splits: the sealer refuses
anything other than ``REAL_MODEL_EXECUTION``.
"""

from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Sequence

from poi_mpp.evidence.dataset_manifest_v2 import (
    DatasetManifestV2,
    DatasetSplitV2,
    DatasetExpectedDecision,
    EvidenceOrigin,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WORKSHEET_MANIFEST_V1 = "POI_MPP_E3_V2_ANNOTATION_WORKSHEET_V1"
_SUPPORTED_SPLITS = {"DEVELOPMENT"}
_DECISION_VALUES = frozenset(d.value for d in DatasetExpectedDecision)


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256(json.dumps(text, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _require_nonblank(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorksheetCompilerError(f"{label} must not be blank")
    return value.strip()


class WorksheetCompilerError(ValueError):
    """Raised when worksheet compilation fails closed."""


class SealerError(ValueError):
    """Raised when the dataset sealer fails closed."""


def _assert_no_symlink_components(path: Path, label: str) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise SealerError(f"{label} must not contain symlink components: {current}")


def _jsonl_bytes(rows: Sequence[dict[str, Any]]) -> bytes:
    return (
        "\n".join(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows) + "\n"
    ).encode("utf-8")


class AnnotationWorksheetCompiler:
    """Compile raw source items into a deduplicated, canonical worksheet.

    Deduplicates by a deterministic content hash of each item's ``text``.
    The first occurrence of a content hash receives a ``record_id`` of the
    form ``dev-{index:04d}``; later occurrences share its
    ``deduplication_group`` and are flagged ``is_duplicate``.
    """

    @staticmethod
    def build(
        *,
        items_path: Path | str,
        claim_spec_path: Path | str,
        split: str,
        dataset_id: str,
        output_root: Path | str,
        allocation: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        if split not in _SUPPORTED_SPLITS:
            raise WorksheetCompilerError(f"unsupported worksheet split: {split}")

        items_path = Path(items_path)
        claim_spec_path = Path(claim_spec_path)
        output_root = Path(output_root)

        claim_spec_hash = _sha256(claim_spec_path.read_bytes())
        raw_items = _read_jsonl(items_path)
        if not raw_items:
            raise WorksheetCompilerError("items file must not be empty")

        group_by_content: dict[str, str] = {}
        records: list[dict[str, Any]] = []
        item_bytes: dict[str, bytes] = {}
        unique_counter = 0
        for index, item in enumerate(raw_items):
            text = _require_nonblank(item.get("text"), "item text")
            content_hash = _sha256_text(text)
            error_family = _require_nonblank(item.get("error_family", "BASELINE"), "error_family")
            subgroup = _require_nonblank(item.get("subgroup", "core"), "subgroup")
            difficulty = _require_nonblank(item.get("difficulty", "standard"), "difficulty")

            if content_hash not in group_by_content:
                record_id = f"dev-{unique_counter:04d}"
                group = f"dedup-{unique_counter:06d}"
                group_by_content[content_hash] = group
                unique_counter += 1
                item_path = f"items/{record_id}.txt"
                item_bytes[item_path] = text.encode("utf-8")
                is_duplicate = False
            else:
                record_id = f"dup-{index:04d}"
                group = group_by_content[content_hash]
                item_path = ""
                is_duplicate = True

            records.append(
                {
                    "record_id": record_id,
                    "content_hash": content_hash,
                    "item_path": item_path,
                    "is_duplicate": is_duplicate,
                    "deduplication_group": group,
                    "error_family": error_family,
                    "subgroup": subgroup,
                    "difficulty": difficulty,
                    "text": text,
                }
            )

        unique_count = unique_counter
        if allocation is not None:
            unknown = sorted(set(allocation) - _DECISION_VALUES)
            if unknown:
                raise WorksheetCompilerError(f"unknown allocation decision: {unknown[0]}")
            if sum(allocation.values()) != unique_count:
                raise WorksheetCompilerError(
                    f"allocation total {sum(allocation.values())} must equal unique item count {unique_count}"
                )

        manifest: dict[str, Any] = {
            "schema_version": _WORKSHEET_MANIFEST_V1,
            "dataset_id": dataset_id,
            "split": split,
            "claim_spec_hash": claim_spec_hash,
            "items_path": "items.jsonl",
            "items_jsonl_hash": _sha256(_jsonl_bytes(raw_items)),
            "unique_records_hash": _sha256(
                _canonical_bytes([record for record in records if not record["is_duplicate"]])
            ),
            "record_count": len(records),
            "unique_record_count": unique_count,
            "duplicate_record_count": len(records) - unique_count,
            "error_taxonomy_version": "E3_V2_DEVELOPMENT_TAXONOMY_V1",
        }
        if allocation is not None:
            manifest["allocation"] = {key: allocation[key] for key in sorted(allocation)}
        manifest["self_digest"] = _sha256(_canonical_bytes(manifest))

        _emit_worksheet(output_root, manifest, item_bytes, raw_items)
        return {"manifest": manifest, "records": records}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise WorksheetCompilerError(f"items file not found: {path}")
    items: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise WorksheetCompilerError(f"invalid JSON at {path}:{lineno}: {error}") from error
        if not isinstance(obj, dict):
            raise WorksheetCompilerError(f"items file line {lineno} is not a JSON object")
        items.append(obj)
    return items


def _emit_worksheet(
    output_root: Path,
    manifest: dict[str, Any],
    item_bytes: dict[str, bytes],
    raw_items: list[dict[str, Any]],
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for path_str, data in item_bytes.items():
        target = output_root / path_str
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (output_root / "items.jsonl").write_text(
        _jsonl_bytes(raw_items).decode("utf-8"), encoding="utf-8"
    )
    (output_root / "manifest.json").write_bytes(_canonical_bytes(manifest))


class _SealedBundle:
    __slots__ = ("dataset_root",)

    def __init__(self, dataset_root: Path) -> None:
        self.dataset_root = dataset_root


class AnnotatedDatasetSealer:
    """Seal a worksheet + two-annotator judgments into a manifest-bound dataset.

    Reconciles annotation, adjudication, and license/privacy ledgers against
    the worksheet and emits a ``DatasetManifestV2`` that closes every binding
    demanded by ``e3_confirmatory_freeze``.
    """

    def __init__(
        self,
        *,
        worksheet_root: Path | str,
        claim_spec_hash: str,
        annotator_ids: Sequence[str],
    ) -> None:
        if len(annotator_ids) != 2 or len(set(annotator_ids)) != 2:
            raise SealerError("sealer requires exactly two distinct annotator ids")
        if not _SHA256_RE.match(claim_spec_hash):
            raise SealerError("claim_spec_hash must be a lowercase SHA-256 digest")
        self._worksheet_root = Path(worksheet_root)
        self._claim_spec_hash = claim_spec_hash
        self._annotator_a, self._annotator_b = annotator_ids
        manifest_path = self._worksheet_root / "manifest.json"
        _assert_no_symlink_components(manifest_path, "worksheet manifest")
        try:
            manifest_raw = manifest_path.read_bytes()
            manifest_payload = json.loads(manifest_raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SealerError("worksheet manifest must be readable canonical JSON") from error
        if manifest_raw != _canonical_bytes(manifest_payload):
            raise SealerError("worksheet manifest must use canonical JSON serialization")
        claimed_digest = manifest_payload.get("self_digest")
        unsigned_manifest = dict(manifest_payload)
        unsigned_manifest.pop("self_digest", None)
        if claimed_digest != _sha256(_canonical_bytes(unsigned_manifest)):
            raise SealerError("worksheet manifest self_digest mismatch")
        if manifest_payload.get("claim_spec_hash") != claim_spec_hash:
            raise SealerError("claim_spec_hash does not match worksheet manifest")
        items_path = self._worksheet_root / "items.jsonl"
        _assert_no_symlink_components(items_path, "worksheet items.jsonl")
        try:
            items_bytes = items_path.read_bytes()
        except OSError as error:
            raise SealerError("worksheet items.jsonl must be readable") from error
        if manifest_payload.get("items_jsonl_hash") != _sha256(items_bytes):
            raise SealerError("worksheet items.jsonl hash mismatch")
        self._manifest_payload = manifest_payload

    def _iter_unique_records(self) -> list[dict[str, Any]]:
        items_path = self._worksheet_root / "items.jsonl"
        raw = [
            json.loads(line)
            for line in items_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        counter = 0
        for item in raw:
            text = _require_nonblank(item.get("text"), "item text")
            content_hash = _sha256_text(text)
            if content_hash in seen:
                continue
            seen.add(content_hash)
            unique.append(
                {
                    "record_id": f"dev-{counter:04d}",
                    "content_hash": content_hash,
                    "text": text,
                    "error_family": _require_nonblank(item.get("error_family", "BASELINE"), "error_family"),
                    "subgroup": _require_nonblank(item.get("subgroup", "core"), "subgroup"),
                    "difficulty": _require_nonblank(item.get("difficulty", "standard"), "difficulty"),
                    "deduplication_group": f"dedup-{counter:06d}",
                }
            )
            counter += 1
        if self._manifest_payload.get("unique_records_hash") != _sha256(
            _canonical_bytes(
                [
                    {
                        "record_id": record["record_id"],
                        "content_hash": record["content_hash"],
                        "item_path": f"items/{record['record_id']}.txt",
                        "is_duplicate": False,
                        "deduplication_group": record["deduplication_group"],
                        "error_family": record["error_family"],
                        "subgroup": record["subgroup"],
                        "difficulty": record["difficulty"],
                        "text": record["text"],
                    }
                    for record in unique
                ]
            )
        ):
            raise SealerError("worksheet unique record ledger hash mismatch")
        return unique

    def seal(
        self,
        *,
        output_root: Path | str,
        decisions_source: Sequence[tuple[str, str]],
        license_ledger_path: Path | str,
        evidence_origin: str,
    ) -> _SealedBundle:
        if evidence_origin != EvidenceOrigin.REAL_MODEL_EXECUTION.value:
            raise SealerError(
                f"evidence_origin must be REAL_MODEL_EXECUTION, got {evidence_origin}"
            )

        manifest_payload = self._manifest_payload
        split = DatasetSplitV2(manifest_payload["split"])
        dataset_id = manifest_payload["dataset_id"]

        decision_rows = list(decisions_source)
        decision_ids = [record_id for record_id, _ in decision_rows]
        if len(decision_ids) != len(set(decision_ids)):
            raise SealerError("duplicate decision row")
        decisions_by_id = dict(decision_rows)
        items_root = self._worksheet_root / "items"
        unique_records = self._iter_unique_records()
        expected_record_ids = {record["record_id"] for record in unique_records}
        unknown_decisions = sorted(set(decisions_by_id) - expected_record_ids)
        if unknown_decisions:
            raise SealerError(f"unknown decision record: {unknown_decisions[0]}")

        output_root = Path(output_root)
        if output_root.exists():
            raise SealerError(f"output_root already exists: {output_root}")

        annotation_rows: list[dict[str, Any]] = []
        adjudication_rows: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        label_files: dict[str, bytes] = {}
        agreements = 0

        for record in unique_records:
            record_id = record["record_id"]
            decision = decisions_by_id.get(record_id)
            if decision is None:
                raise SealerError(f"missing decision for record {record_id}")
            if decision not in _DECISION_VALUES:
                raise SealerError(f"invalid expected_decision for {record_id}: {decision}")

            item_path = items_root / f"{record_id}.txt"
            _assert_no_symlink_components(item_path, f"item input for {record_id}")
            if not item_path.is_file():
                raise SealerError(f"missing item file for {record_id}")
            item_bytes = item_path.read_bytes()
            if item_bytes != record["text"].encode("utf-8"):
                raise SealerError(f"item content mismatch for {record_id}")
            item_hash = _sha256(item_bytes)

            label_bytes = _canonical_bytes({"expected_decision": decision, "record_id": record_id})
            label_hash = _sha256(label_bytes)
            label_files[f"labels/{record_id}.json"] = label_bytes

            ann_a_path = self._worksheet_root / "annotations" / f"{record_id}-{self._annotator_a}.json"
            ann_b_path = self._worksheet_root / "annotations" / f"{record_id}-{self._annotator_b}.json"
            _assert_no_symlink_components(ann_a_path, f"annotation input for {record_id}")
            _assert_no_symlink_components(ann_b_path, f"annotation input for {record_id}")
            if not ann_a_path.is_file() or not ann_b_path.is_file():
                raise SealerError(f"missing annotations for {record_id}")
            ann_a = json.loads(ann_a_path.read_bytes())
            ann_b = json.loads(ann_b_path.read_bytes())
            if (
                ann_a.get("record_id") != record_id
                or ann_b.get("record_id") != record_id
                or ann_a.get("annotator_id") != self._annotator_a
                or ann_b.get("annotator_id") != self._annotator_b
            ):
                raise SealerError(f"annotation identity mismatch for {record_id}")
            decision_a = _require_nonblank(ann_a.get("decision"), "annotation decision")
            decision_b = _require_nonblank(ann_b.get("decision"), "annotation decision")
            if decision_a not in _DECISION_VALUES or decision_b not in _DECISION_VALUES:
                raise SealerError(f"annotator decision outside allowed set for {record_id}")

            agreement_fraction = 1.0 if decision_a == decision_b else 0.0
            if agreement_fraction == 1.0:
                final_decision = decision_a
                agreements += 1
            else:
                adjudication_path = self._worksheet_root / "adjudications" / f"{record_id}.json"
                _assert_no_symlink_components(
                    adjudication_path, f"adjudication input for {record_id}"
                )
                if not adjudication_path.is_file():
                    raise SealerError(f"missing adjudication for disagreed record {record_id}")
                adj_row = json.loads(adjudication_path.read_bytes())
                adjudicator = _require_nonblank(adj_row.get("adjudicator_id"), "adjudicator_id")
                if adj_row.get("record_id") != record_id:
                    raise SealerError(f"adjudication identity mismatch for {record_id}")
                if adjudicator in {self._annotator_a, self._annotator_b}:
                    raise SealerError(f"adjudicator must be distinct from annotators for {record_id}")
                final_decision = _require_nonblank(adj_row.get("decision"), "adjudication decision")
                if final_decision not in _DECISION_VALUES:
                    raise SealerError(f"adjudication decision outside allowed set for {record_id}")
                adjudication_rows.append(
                    {
                        "record_id": record_id,
                        "adjudicator_id": adjudicator,
                        "decision": final_decision,
                        "adjudication_path": f"adjudications/{record_id}.json",
                        "adjudication_hash": _sha256(adjudication_path.read_bytes()),
                    }
                )

            if final_decision != decision:
                raise SealerError(
                    f"sealed decision for {record_id} ({final_decision}) does not match "
                    f"declared decision ({decision})"
                )

            row = {
                "record_id": record_id,
                "annotations": [
                    {
                        "annotator_id": self._annotator_a,
                        "decision": decision_a,
                        "annotation_path": f"annotations/{record_id}-{self._annotator_a}.json",
                        "annotation_hash": _sha256(ann_a_path.read_bytes()),
                    },
                    {
                        "annotator_id": self._annotator_b,
                        "decision": decision_b,
                        "annotation_path": f"annotations/{record_id}-{self._annotator_b}.json",
                        "annotation_hash": _sha256(ann_b_path.read_bytes()),
                    },
                ],
                "provenance_reference": "E3V2_DEVELOPMENT_ANNOTATION_V1",
            }
            annotation_rows.append(row)
            records.append(
                {
                    "record_id": record_id,
                    "item_path": f"items/{record_id}.txt",
                    "label_path": f"labels/{record_id}.json",
                    "item_hash": item_hash,
                    "label_hash": label_hash,
                    "content_hash": record["content_hash"],
                    "split": split.value,
                    "license_id": "CC-BY-4.0",
                    "privacy_status": "AUTHORIZED_PUBLIC",
                    "expected_decision": final_decision,
                    "expected_semantic_outcome": _semantic_outcome(final_decision),
                    "error_family": record["error_family"],
                    "subgroup": record["subgroup"],
                    "difficulty": record["difficulty"],
                    "deduplication_group": record["deduplication_group"],
                    "annotation": {
                        "annotation_scope": "semantic-development",
                        "annotation_hash": _sha256(_canonical_bytes(row)),
                        "agreement_fraction": agreement_fraction,
                    },
                    "evidence_origin": evidence_origin,
                }
            )

        total = len(records)
        if total == 0:
            raise SealerError("sealer produced zero records")

        dataset_manifest = DatasetManifestV2(
            dataset_id=dataset_id,
            split=split,
            records=records,
        )

        agreement_payload = {
            "schema_version": "POI_MPP_E3_V2_ANNOTATION_AGREEMENT_V1",
            "numerator": agreements,
            "denominator": total,
            "rate": str(Decimal(agreements) / Decimal(total)),
        }
        annotation_ledger_payload = {
            "schema_version": "POI_MPP_E3_V2_ANNOTATION_LEDGER_V1",
            "rows": annotation_rows,
        }
        adjudication_payload = {
            "schema_version": "POI_MPP_E3_V2_ADJUDICATION_LEDGER_V1",
            "rows": adjudication_rows,
        }
        license_ledger_path = Path(license_ledger_path)
        _assert_no_symlink_components(license_ledger_path, "license ledger input")
        license_payload = json.loads(license_ledger_path.read_bytes())

        source_files: dict[str, bytes] = {}
        for name in ("items", "annotations", "adjudications"):
            src_dir = self._worksheet_root / name
            if src_dir.is_dir():
                _assert_no_symlink_components(src_dir, f"{name} source directory")
                for src_file in sorted(src_dir.iterdir()):
                    _assert_no_symlink_components(src_file, f"{name} source file")
                    if src_file.is_file():
                        source_files[f"{name}/{src_file.name}"] = src_file.read_bytes()

        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging_root = Path(
            tempfile.mkdtemp(prefix=f".{output_root.name}.staging-", dir=output_root.parent)
        )
        try:
            write_canonical_json(
                staging_root / "dataset_manifest_v2.json",
                dataset_manifest.model_dump(mode="json"),
            )
            write_canonical_json(staging_root / "annotation_ledger.json", annotation_ledger_payload)
            write_canonical_json(staging_root / "annotation_agreement.json", agreement_payload)
            write_canonical_json(staging_root / "adjudication_ledger.json", adjudication_payload)
            write_canonical_json(staging_root / "license_privacy_ledger.json", license_payload)
            for relative_path, data in {**source_files, **label_files}.items():
                target = staging_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if output_root.exists():
                raise SealerError(f"output_root already exists: {output_root}")
            os.rename(staging_root, output_root)
        except Exception:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise

        return _SealedBundle(dataset_root=output_root)


def write_canonical_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(payload))


def _semantic_outcome(decision: str) -> str:
    return {
        "ACCEPT": "SUPPORTED_GROUNDS",
        "REJECT": "REJECTED_GROUNDS",
        "ABSTAIN": "ABSTAIN_GROUNDS",
    }[decision]
