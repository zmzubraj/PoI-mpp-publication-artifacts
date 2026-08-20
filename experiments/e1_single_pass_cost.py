from __future__ import annotations

import argparse
from pathlib import Path

from poi_mpp.evidence import load_run_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config = load_run_config(args.config)
    if config.origin.value != "REAL_MODEL_EXECUTION":
        raise SystemExit("E1 pilot CLI is reserved for authorized REAL_MODEL_EXECUTION runs")
    raise SystemExit(
        "authorized local model adapter and frozen provenance bundle are required for the real E1 pilot; "
        f"loaded config from {Path(args.config).resolve()}"
    )


if __name__ == "__main__":
    main()
