from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_external_review_handoff.py"


def _canonical_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_external_review_handoff_binds_exact_review_inputs(tmp_path: Path) -> None:
    output = tmp_path / "handoff.json"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=REPO_ROOT,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "POI_MPP_EXTERNAL_REVIEW_HANDOFF_V1"
    assert payload["status"] == "UNSIGNED_REVIEW_INPUT_ONLY"
    assert payload["external_gates"] == {
        "e3_semantic_evaluator_authority": "WAITING_EXTERNAL",
        "independent_domain_expert_review": "WAITING_EXTERNAL",
        "publication_freeze_sentinel": "BLOCKED_UNTIL_EXTERNAL_GATES_CLOSE",
    }
    assert payload["self_digest"] == _canonical_digest(payload)

    entries = payload["review_inputs"]
    paths = {entry["path"] for entry in entries}
    assert "publication/artifact_manifest.json" in paths
    assert "docs/paper_artifacts/final/manuscript/POI_SUBMISSION_MANUSCRIPT.md" in paths
    assert "docs/paper_artifacts/final/deliverables/POI_MPP_EVIDENCE_BOUND_MANUSCRIPT.docx" in paths
    assert "docs/paper_artifacts/final/deliverables/POI_MPP_EVIDENCE_BOUND_MANUSCRIPT.pdf" in paths
    assert "docs/paper_artifacts/final/visuals_algorithms/F1_single_pass_end_to_end.mmd" in paths
    assert "docs/paper_artifacts/final/tables/T4_experiment_design_and_current_status.csv" in paths
    assert "docs/algorithms/A1_SPAI.md" in paths
    assert "docs/paper_artifacts/final/review/SUBMISSION_READINESS_VALIDATION.md" not in paths
    assert all(not Path(path).is_absolute() and ".." not in Path(path).parts for path in paths)

    for entry in entries:
        artifact = REPO_ROOT / entry["path"]
        assert entry["size_bytes"] == artifact.stat().st_size
        assert entry["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()

    subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output), "--check"],
        cwd=REPO_ROOT,
        check=True,
    )


def test_external_review_handoff_check_rejects_stale_manifest(tmp_path: Path) -> None:
    output = tmp_path / "handoff.json"
    subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)], cwd=REPO_ROOT, check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["status"] = "COMPLETE"
    output.write_text(json.dumps(payload), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output), "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0
    assert "stale or non-canonical" in completed.stderr
