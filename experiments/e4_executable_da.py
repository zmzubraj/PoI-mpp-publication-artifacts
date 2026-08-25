#!/usr/bin/env python3
"""Validate or execute the frozen E4 V2 local reconstruction simulation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.experiments.e4_execution import (
    E4ExecutionError,
    execute_e4_reconstruction_simulation,
    load_e4_execution_config,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="E4 deterministic executable local data-availability reconstruction simulation."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="Validate the frozen config without writing outputs.")
    validate.add_argument("--config", required=True)
    execute = subparsers.add_parser("execute", help="Execute into an absent or empty output directory.")
    execute.add_argument("--config", required=True)
    execute.add_argument("--output-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_e4_execution_config(args.config)
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "schema_version": config.schema_version,
                        "experiment_id": config.experiment_id,
                        "origin": config.origin.value,
                        "method_boundary": config.method_boundary,
                        "claim_disposition": config.claim_disposition,
                        "scenario_count": len(config.scenarios),
                        "status": "VALID",
                    },
                    sort_keys=True,
                )
            )
            return 0
        result = execute_e4_reconstruction_simulation(
            config_path=args.config,
            output_root=args.output_root,
        )
        print(
            json.dumps(
                {
                    "artifact_hash": result.artifact_hash,
                    "claim_disposition": result.summary.claim_disposition,
                    "origin": result.summary.origin,
                    "scenario_count": len(result.rows),
                    "status": "EXECUTED",
                },
                sort_keys=True,
            )
        )
        return 0
    except (E4ExecutionError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
