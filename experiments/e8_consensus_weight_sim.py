from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.evidence.config import load_run_config
from poi_mpp.experiments.e8_consensus import (
    AuthorityBoundaryError,
    assert_cli_authority_boundary,
    load_e8_confirmatory_contract,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate authority for manual E8 next-epoch committee publication routing."
    )
    parser.add_argument("--run-config", required=True, help="Path to a frozen E8 run configuration.")
    parser.add_argument(
        "--confirmatory-contract",
        required=True,
        help="Path to the frozen E8 confirmatory contract.",
    )
    args = parser.parse_args(argv)

    try:
        run_config = load_run_config(Path(args.run_config))
        contract = load_e8_confirmatory_contract(Path(args.confirmatory_contract))
        assert_cli_authority_boundary(run_config, contract)
    except (AuthorityBoundaryError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
