from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "docs" / "paper_artifacts" / "final" / "external_reproduction"
MANIFEST = PACKAGE_ROOT / "EXTERNAL_REPRODUCTION_MANIFEST.json"


def test_external_reproduction_manifest_is_deterministic_and_fail_closed() -> None:
    subprocess.run(
        [sys.executable, "scripts/build_external_reproduction_package.py", "--check"],
        cwd=REPO_ROOT,
        check=True,
    )
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "POI_MPP_EXTERNAL_REPRODUCTION_PACKAGE_V1"
    assert payload["status"] == "WAITING_EXTERNAL_REPRODUCTION"
    assert payload["independent_reproduction_complete"] is False
    assert payload["self_digest"]
    assert payload["input_count"] == len(payload["inputs"])
    assert all(len(item["sha256"]) == 64 for item in payload["inputs"])
    assert all(not item["path"].startswith("results/publication/") for item in payload["inputs"])
    paths = {item["path"] for item in payload["inputs"]}
    assert "docs/paper_artifacts/final/review/FIGURE_TABLE_FIDELITY_LEDGER.csv" in paths
    assert "docs/paper_artifacts/final/review/FIGURE_TABLE_INTEGRITY_QA.md" in paths
    assert "docs/paper_artifacts/final/novelty/NOVELTY_MANIFEST.json" in paths
    assert "docs/paper_artifacts/final/novelty/NOVELTY_CASE.md" in paths
    assert "scripts/build_novelty_package.py" in paths


def test_external_reproduction_manifest_excludes_ambient_untracked_files() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    tracked_paths = {path for path in tracked if path}
    packaged_paths = {item["path"] for item in payload["inputs"]}

    assert packaged_paths <= tracked_paths


def test_external_reproduction_handoff_requires_real_identity_and_signature() -> None:
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    protocol = (PACKAGE_ROOT / "CLEAN_ROOM_PROTOCOL.md").read_text(encoding="utf-8")
    discrepancy_schema = json.loads(
        (PACKAGE_ROOT / "discrepancy_report.schema.json").read_text(encoding="utf-8")
    )
    attestation_schema = json.loads(
        (PACKAGE_ROOT / "external_reproduction_attestation.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert "WAITING_EXTERNAL_REPRODUCTION" in readme
    assert "SYNTHETIC_NON_EVIDENCE" in protocol
    assert "ssh-keygen -Y verify" in protocol
    assert "repository-local" in protocol
    assert "independence_basis" in attestation_schema["required"]
    assert "reviewed_manifest_sha256" in attestation_schema["required"]
    assert "discrepancies" in discrepancy_schema["required"]


def test_e1_e2_claim_narrowing_is_permanent_until_new_frozen_evidence() -> None:
    audit = (
        REPO_ROOT
        / "docs"
        / "paper_artifacts"
        / "final"
        / "review"
        / "E1_E2_CLAIM_NARROWING_AUDIT.md"
    ).read_text(encoding="utf-8")
    manuscript = (
        REPO_ROOT
        / "docs"
        / "paper_artifacts"
        / "final"
        / "manuscript"
        / "POI_SUBMISSION_MANUSCRIPT.md"
    ).read_text(encoding="utf-8")
    claim_matrix = json.loads(
        (REPO_ROOT / "publication" / "tables" / "claim_matrix.json").read_text(
            encoding="utf-8"
        )
    )

    assert "CLAIM_NARROWED" in audit
    assert "No new E1 or E2 execution was authorized by a frozen confirmatory design" in audit
    assert "fixed-order" in manuscript
    assert "four attacked observations" in manuscript
    by_id = {row["claim_id"]: row for row in claim_matrix}
    assert by_id["C1"]["disposition"] == "INCONCLUSIVE"
    assert "counterbalanced" in by_id["C1"]["limits"]
    assert by_id["C2"]["disposition"] == "INCONCLUSIVE"
    assert "floating-point checks do not provide exact field soundness" in by_id["C2"]["limits"]


def test_submission_readiness_records_narrowing_and_external_reproduction_handoff() -> None:
    readiness = (
        REPO_ROOT
        / "docs"
        / "paper_artifacts"
        / "final"
        / "review"
        / "SUBMISSION_READINESS_VALIDATION.md"
    ).read_text(encoding="utf-8")

    assert "E1/E2 claim narrowing" in readiness
    assert "`CLAIM_NARROWED`" in readiness
    assert "External reproduction package" in readiness
    assert "`WAITING_EXTERNAL`" in readiness
