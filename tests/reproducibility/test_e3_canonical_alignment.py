from __future__ import annotations

import csv
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FINAL_ROOT = REPO_ROOT / "docs" / "paper_artifacts" / "final"

EXPECTED_METRICS = {
    "FAR": (0.5, 2),
    "FRR": (1 / 6, 6),
    "ABSTAIN": (0.125, 8),
    "coverage": (0.875, 8),
    "calibration": (0.17840000000000003, 7),
}


def test_e3_attested_metrics_and_negative_disposition_are_exact() -> None:
    t4 = json.loads(
        (REPO_ROOT / "publication" / "tables" / "T4_dataset_composition.json").read_text(
            encoding="utf-8"
        )
    )
    assert t4["experiment_id"] == "E3"
    assert t4["claim_id"] == "C3"
    assert t4["evidence_origin"] == "REAL_MODEL_EXECUTION"
    assert t4["record_count"] == 8
    assert t4["class_counts"] == {"invalid": 2, "valid": 6}

    with (REPO_ROOT / "publication" / "tables" / "T8_semantic_verification.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = {row["metric"]: row for row in csv.DictReader(handle)}
    assert set(rows) == set(EXPECTED_METRICS)
    for metric, (value, sample_count) in EXPECTED_METRICS.items():
        assert float(rows[metric]["value"]) == value
        assert int(rows[metric]["sample_count"]) == sample_count
        assert rows[metric]["evidence_origin"] == "REAL_MODEL_EXECUTION"

    claim_rows = json.loads(
        (REPO_ROOT / "publication" / "tables" / "claim_matrix.json").read_text(
            encoding="utf-8"
        )
    )
    e3_rows = [row for row in claim_rows if row["experiment_id"] == "E3"]
    assert {row["artifact_id"] for row in e3_rows} == {"T4", "T8"}
    assert {row["claim_id"] for row in e3_rows} == {"C3"}
    assert {row["disposition"] for row in e3_rows} == {"NOT_SUPPORTED"}
    assert {row["origin"] for row in e3_rows} == {"REAL_MODEL_EXECUTION"}
    assert all(row["omission_reason"] == "" for row in e3_rows)

    omissions = json.loads(
        (REPO_ROOT / "publication" / "tables" / "omissions.json").read_text(
            encoding="utf-8"
        )
    )
    assert not [row for row in omissions if row["experiment_id"] == "E3"]


def test_current_canonical_prose_preserves_e3_negative_result_and_scope() -> None:
    current_surfaces = [
        FINAL_ROOT / "manuscript" / "POI_SUBMISSION_MANUSCRIPT.md",
        FINAL_ROOT / "tables" / "README.md",
        FINAL_ROOT / "tables" / "T2_evidence_origin_rules.md",
        FINAL_ROOT / "tables" / "T4_experiment_design_and_current_status.md",
        FINAL_ROOT / "tables" / "T7_limitations_and_nonclaims.md",
        FINAL_ROOT / "review" / "MPP_ALIGNMENT_AND_SCORECARD.md",
        FINAL_ROOT / "review" / "MPP_ALIGNMENT_EXPLANATION_BN.md",
        FINAL_ROOT / "review" / "SUBMISSION_READINESS_VALIDATION.md",
        REPO_ROOT / "docs" / "MAIN_RESULTS_TARGETS.md",
        REPO_ROOT / "docs" / "PAPER_ARTIFACT_MAP.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in current_surfaces)
    for required in (
        "NOT_SUPPORTED",
        "FAR 0.500",
        "FRR 0.167",
        "ABSTAIN 0.125",
        "coverage 0.875",
        "Brier 0.178",
        "alpha_sem 0.25",
        "n=8",
        "invalid n=2",
    ):
        assert required in combined

    forbidden = (
        "E3 remains `WAITING_EXTERNAL`",
        "E3 is `WAITING_EXTERNAL`",
        "E3 has no evidence",
        "E3 is absent pending external authority",
        "E3 remains absent pending external evaluator authority",
        "E3 remains blocked for external authority",
        "external evaluator authority has not been supplied",
    )
    for phrase in forbidden:
        assert phrase not in combined

    manuscript = current_surfaces[0].read_text(encoding="utf-8")
    assert "does not establish general semantic reliability" in manuscript
    assert "cryptographic validity" in manuscript
    assert "private-key custody" in manuscript


def test_e3_status_table_has_no_superseded_waiting_authority_row() -> None:
    status_table = (
        FINAL_ROOT / "tables" / "T4_experiment_design_and_current_status.md"
    ).read_text(encoding="utf-8")
    e3_row = next(line for line in status_table.splitlines() if line.startswith("| E3 |"))

    assert "NOT_SUPPORTED" in e3_row
    assert "FAR 0.500 (1/2)" in e3_row
    assert "WAITING_EXTERNAL" not in e3_row
    assert "no authorized confirmatory artifact" not in e3_row
