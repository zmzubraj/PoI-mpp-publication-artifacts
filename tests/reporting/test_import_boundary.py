from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    path_value = env.get("PYTHONPATH")
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = src_path if not path_value else f"{src_path}{os.pathsep}{path_value}"
    return env


def test_e1_cost_import_does_not_trigger_reporting_cycle():
    result = subprocess.run(
        [sys.executable, "-c", "import poi_mpp.experiments.e1_cost"],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_reporting_public_exports_remain_available():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from poi_mpp.reporting import "
                "PublicationEligibilityError, ReportBuildSpec, summarize_e1_rows; "
                "assert PublicationEligibilityError.__name__ == 'PublicationEligibilityError'; "
                "assert ReportBuildSpec.__name__ == 'ReportBuildSpec'; "
                "assert callable(summarize_e1_rows)"
            ),
        ],
        cwd=REPO_ROOT,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
