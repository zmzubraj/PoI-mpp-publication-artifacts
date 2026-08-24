from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
NOVELTY_ROOT = REPO_ROOT / "docs" / "paper_artifacts" / "final" / "novelty"
MANIFEST = NOVELTY_ROOT / "NOVELTY_MANIFEST.json"


def test_novelty_package_is_deterministic_and_explicitly_unresolved() -> None:
    subprocess.run(
        [sys.executable, "scripts/build_novelty_package.py", "--check"],
        cwd=REPO_ROOT,
        check=True,
    )
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "POI_MPP_NOVELTY_PACKAGE_V1"
    assert payload["status"] == "NOVELTY_UNRESOLVED"
    assert payload["independent_challenge_status"] == "WAITING_EXTERNAL_INDEPENDENT_CHALLENGE"
    assert payload["cutoff_date"] == "2026-08-25"
    assert payload["package_input_count"] == len(payload["package_inputs"])
    assert payload["raw_snapshot_count"] == len(payload["raw_snapshots"])
    assert payload["known_item_recovery"] == {
        "CommitLLM": "RECOVERED",
        "opML": "RECOVERED",
        "zkGPT": "RECOVERED",
        "EigenAI": "RECOVERED",
    }


def test_novelty_package_preserves_scope_limits_and_non_universal_language() -> None:
    readme = (NOVELTY_ROOT / "README.md").read_text(encoding="utf-8")
    case = (NOVELTY_ROOT / "NOVELTY_CASE.md").read_text(encoding="utf-8")

    assert "1B-8B open-weight" in readme
    assert "local EVM/Foundry" in readme
    assert "70B/MoE" in readme
    assert "NOVELTY_UNRESOLVED" in case
    assert "Absence from this bounded search is not universal proof of novelty." in case
    assert "independent search challenge remains open" in case


def test_novelty_package_ledgers_cover_screening_and_contradictions() -> None:
    screening = (NOVELTY_ROOT / "screening_ledger.csv").read_text(encoding="utf-8")
    predecessor_matrix = (
        NOVELTY_ROOT / "closest_predecessor_matrix.csv"
    ).read_text(encoding="utf-8")
    contradictions = (
        NOVELTY_ROOT / "contradiction_ledger.csv"
    ).read_text(encoding="utf-8")
    chaining = (NOVELTY_ROOT / "citation_chaining.csv").read_text(encoding="utf-8")

    assert "include_exclude_reason" in screening
    assert "CommitLLM" in predecessor_matrix
    assert "opML" in predecessor_matrix
    assert "zkGPT" in predecessor_matrix
    assert "EigenAI" in predecessor_matrix
    assert "defeating_evidence" in contradictions
    assert "backward" in chaining
    assert "forward" in chaining


def test_submission_readiness_report_exposes_p1_p2_gate_table() -> None:
    validation = (
        REPO_ROOT
        / "docs"
        / "paper_artifacts"
        / "final"
        / "review"
        / "SUBMISSION_READINESS_VALIDATION.md"
    ).read_text(encoding="utf-8")

    assert "## P1/P2 gate table" in validation
    assert "INCONCLUSIVE/CLAIM_NARROWED" in validation
    assert "WAITING_EXTERNAL" in validation
    assert "WAITING_USER" in validation
