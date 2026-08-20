from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from poi_mpp.evidence import load_run_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config = load_run_config(args.config)
    if config.origin.value != "REAL_MODEL_EXECUTION":
        raise SystemExit("E3 confirmatory CLI is reserved for authorized REAL_MODEL_EXECUTION runs")
    raise SystemExit(
        "frozen confirmatory dataset manifest, verified evaluator registry proof, "
        "frozen development calibration artifact, and verified provenance bundle are required "
        "for the real E3 confirmatory run; "
        f"loaded config from {Path(args.config).resolve()}"
    )


if __name__ == "__main__":
    main()
