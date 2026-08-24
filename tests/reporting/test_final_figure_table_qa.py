from __future__ import annotations

import csv
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_ROOT = REPO_ROOT / "docs" / "paper_artifacts" / "final" / "review"


def test_figure_table_fidelity_ledger_covers_manuscript_outputs() -> None:
    ledger_path = REVIEW_ROOT / "FIGURE_TABLE_FIDELITY_LEDGER.csv"
    rows = list(csv.DictReader(ledger_path.open(encoding="utf-8", newline="")))

    assert len(rows) == 17
    assert {row["artifact_id"] for row in rows if row["artifact_type"] == "FIGURE"} == {
        "F1",
        "F2",
        "F4",
        "F5",
        "F6",
        "F8",
        "F9",
        "F10",
        "F11",
        "F12",
    }
    assert {row["artifact_id"] for row in rows if row["artifact_type"] == "TABLE"} == {
        "T1",
        "T2",
        "T3",
        "T4",
        "T5",
        "T6",
        "T7",
    }
    for row in rows:
        assert len(row["output_sha256"]) == 64
        assert row["source_paths"]
        assert row["evidence_scope"]
        assert row["developmental_qa_status"] in {"PASS", "PARTIAL", "NOT_APPLICABLE"}
        assert row["qualified_human_status"] == "WAITING_EXTERNAL"


def test_visual_review_record_is_unsigned_and_fail_closed() -> None:
    schema = json.loads(
        (REVIEW_ROOT / "figure_table_external_review_record.schema.json").read_text(
            encoding="utf-8"
        )
    )
    report = (REVIEW_ROOT / "FIGURE_TABLE_INTEGRITY_QA.md").read_text(encoding="utf-8")

    assert "DEVELOPMENTAL_QA_ONLY" in report
    normalized = report.lower()
    assert "grayscale" in normalized
    assert "color-vision" in normalized
    assert "final-size" in normalized
    assert "WAITING_EXTERNAL" in report
    assert "reviewer_identity" in schema["required"]
    assert "independence_basis" in schema["required"]
    assert "reviewed_ledger_sha256" in schema["required"]
    assert "decision" in schema["required"]
