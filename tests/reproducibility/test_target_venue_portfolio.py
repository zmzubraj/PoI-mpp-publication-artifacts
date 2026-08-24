from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PORTFOLIO = (
    REPO_ROOT
    / "docs"
    / "paper_artifacts"
    / "final"
    / "review"
    / "TARGET_VENUE_PORTFOLIO.md"
)
AUTHOR_FORM = (
    REPO_ROOT
    / "docs"
    / "paper_artifacts"
    / "final"
    / "external_review"
    / "ACCOUNTABLE_AUTHOR_SUBMISSION_INPUT.md"
)
FINAL_APPROVAL_CHECKLIST = (
    REPO_ROOT
    / "docs"
    / "paper_artifacts"
    / "final"
    / "external_review"
    / "FINAL_PDF_PORTAL_APPROVAL_CHECKLIST.md"
)


def test_target_venue_portfolio_is_dated_bounded_and_source_linked() -> None:
    content = PORTFOLIO.read_text(encoding="utf-8")

    assert "Checked: 2026-08-25" in content
    assert "WAITING_ACCOUNTABLE_AUTHOR_VENUE_SELECTION" in content
    assert "Recommended primary candidate" in content
    assert "Blockchain: Research and Applications" in content
    assert (
        "https://www.sciencedirect.com/journal/blockchain-research-and-applications/publish/guide-for-authors"
        in content
    )
    assert (
        "https://www.computer.org/csdl/journal/tq/write-for-us/15068"
        in content
    )
    assert (
        "https://www.computer.org/digital-library/journals/oj/cfp-open-journal"
        in content
    )
    assert "fees/access model" in content
    assert "data/code policy" in content
    assert "AI policy" in content
    assert "review/anonymity model" in content
    assert "NOT ESTIMABLE" in content
    assert "E3 remains `WAITING_EXTERNAL`" in content
    assert "does not authorize submission" in content


def test_target_venue_portfolio_preserves_accountable_author_decisions() -> None:
    content = PORTFOLIO.read_text(encoding="utf-8")

    for required_human_field in (
        "author list and order",
        "corresponding author",
        "CRediT roles",
        "funding statement",
        "competing-interest statement",
        "AI-use declaration",
    ):
        assert required_human_field in content


def test_accountable_author_form_is_explicitly_unapproved_and_complete() -> None:
    content = AUTHOR_FORM.read_text(encoding="utf-8")

    assert "Status: `WAITING_ACCOUNTABLE_AUTHOR_INPUT`" in content
    assert "This unsigned form does not authorize submission" in content
    for field in (
        "Selected venue",
        "Article type",
        "Author order",
        "Corresponding author",
        "CRediT contribution record",
        "Funding and sponsor role",
        "Competing interests",
        "Ethics and privacy disposition",
        "Generative-AI declaration",
        "Data, code, and model availability",
        "Submission declaration",
        "Accountable approval",
    ):
        assert field in content


def test_final_pdf_portal_checklist_is_fail_closed_and_accountable() -> None:
    content = FINAL_APPROVAL_CHECKLIST.read_text(encoding="utf-8")

    assert "Status: `WAITING_ACCOUNTABLE_AUTHOR_FINAL_APPROVAL`" in content
    assert "Rendered PDF SHA-256: `UNRESOLVED`" in content
    assert "Submission package SHA-256: `UNRESOLVED`" in content
    assert "portal preview" in content
    assert "declarations" in content
    assert "does not authorize submission" in content
    assert "Publication freeze sentinel must remain blocked" in content
