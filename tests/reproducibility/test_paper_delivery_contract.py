from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FINAL_ROOT = REPO_ROOT / "docs" / "paper_artifacts" / "final"


def test_final_deliverables_expose_only_the_canonical_evidence_bound_manuscript() -> None:
    deliverables = {
        path.name for path in (FINAL_ROOT / "deliverables").iterdir() if path.is_file()
    }

    assert deliverables == {
        "POI_MPP_EVIDENCE_BOUND_MANUSCRIPT.docx",
        "POI_MPP_EVIDENCE_BOUND_MANUSCRIPT.pdf",
    }


def test_docx_export_dependency_is_revision_pinned() -> None:
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["scripts"]["build:paper-docx"] == "node scripts/build_paper_docx.js"
    assert package["dependencies"] == {"docx": "9.6.1"}
    assert (REPO_ROOT / "package-lock.json").is_file()


def test_manuscript_embeds_every_available_quantitative_experiment_figure() -> None:
    manuscript = (FINAL_ROOT / "manuscript" / "POI_SUBMISSION_MANUSCRIPT.md").read_text(
        encoding="utf-8"
    )
    expected = {
        "F5_single_pass_cost.png",
        "F6_audit_soundness.png",
        "F7_semantic_verification_quality.png",
        "F8_da_withholding.png",
        "F9_sybil_advantage.png",
        "F10_economic_security.png",
        "F11_consensus_dynamics.png",
        "F12_evm_gas_state_scaling.png",
    }

    assert all(figure in manuscript for figure in expected)


def test_manuscript_uses_canonical_hotstuff_venue_title() -> None:
    manuscript = (FINAL_ROOT / "manuscript" / "POI_SUBMISSION_MANUSCRIPT.md").read_text(
        encoding="utf-8"
    )
    assert "Symposium on Principles of Distributed Computing" in manuscript
    assert "Symposium on Principles in Distributed Computing" not in manuscript


def test_manuscript_exposes_six_evidence_bound_keywords() -> None:
    manuscript = (FINAL_ROOT / "manuscript" / "POI_SUBMISSION_MANUSCRIPT.md").read_text(
        encoding="utf-8"
    )
    keyword_line = next(
        line for line in manuscript.splitlines() if line.startswith("**Keywords:** ")
    )
    keywords = [keyword.strip() for keyword in keyword_line.removeprefix("**Keywords:** ").split(",")]

    assert keywords == [
        "proof of intelligence",
        "verifiable AI inference",
        "blockchain consensus",
        "optimistic verification",
        "evidence provenance",
        "smart contracts",
    ]
