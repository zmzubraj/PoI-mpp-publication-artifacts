from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from poi_mpp.experiments.e3_semantic import WAITING_EXTERNAL_EVALUATOR_AUTHORITY, load_e3_confirmatory_schema
from poi_mpp.evidence import load_run_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--schema",
        default=str(ROOT / "configs" / "confirmatory" / "e3.schema.yaml"),
    )
    args = parser.parse_args()

    schema = load_e3_confirmatory_schema(args.schema)
    config = load_run_config(args.config)
    if config.origin is not schema.required_run_origin:
        raise SystemExit("E3 confirmatory CLI is reserved for authorized REAL_MODEL_EXECUTION runs")
    raise SystemExit(
        f"{WAITING_EXTERNAL_EVALUATOR_AUTHORITY}: frozen confirmatory dataset manifest, "
        "frozen annotation manifest, frozen development calibration artifact, "
        "verified provenance bundle, and external registry-backed evaluator authority are required "
        "for the real E3 confirmatory run; "
        f"validated schema from {Path(args.schema).resolve()} and loaded config from {Path(args.config).resolve()}"
    )


if __name__ == "__main__":
    main()
