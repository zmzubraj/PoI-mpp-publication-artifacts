from __future__ import annotations

import argparse
import sys

from poi_mpp.evidence.config import load_run_config
from poi_mpp.experiments.e6_sybil import assert_cli_authority_boundary, load_e6_confirmatory_contract


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the frozen E6 authority boundary.")
    parser.add_argument("--run-config", required=True, help="Path to the frozen run configuration YAML")
    parser.add_argument(
        "--confirmatory-contract",
        required=True,
        help="Path to the frozen E6 confirmatory contract YAML",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    run_config = load_run_config(args.run_config)
    contract = load_e6_confirmatory_contract(args.confirmatory_contract)
    try:
        assert_cli_authority_boundary(run_config, contract)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    print("E6 publication execution remains manual.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
