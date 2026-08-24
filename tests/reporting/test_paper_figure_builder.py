from __future__ import annotations

from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_paper_figure_builder_emits_all_eight_valid_png_derivatives(tmp_path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_paper_figures.py"),
            "--output-dir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        check=True,
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
    assert {path.name for path in tmp_path.iterdir()} == expected
    for filename in expected:
        payload = (tmp_path / filename).read_bytes()
        assert payload.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(payload) > 10_000
