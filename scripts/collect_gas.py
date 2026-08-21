from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.evidence.config import load_run_config
from poi_mpp.experiments.e7_evm import (
    AuthorityBoundaryError,
    assert_cli_authority_boundary,
    collect_foundry_measurements,
    default_measurement_contract,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect bounded E7 Foundry gas/state evidence.")
    parser.add_argument("--run-config", required=True, help="Path to a frozen E7 run configuration.")
    parser.add_argument(
        "--out",
        required=True,
        help="Path to the JSON bundle to write.",
    )
    parser.add_argument(
        "--contracts-root",
        default=str(REPO_ROOT / "contracts"),
        help="Contracts workspace root containing foundry.toml.",
    )
    args = parser.parse_args(argv)

    try:
        run_config = load_run_config(Path(args.run_config))
        assert_cli_authority_boundary(run_config)
        collect_foundry_measurements(
            contracts_root=Path(args.contracts_root),
            run_config=run_config,
            output_path=Path(args.out),
            measurement_contract=default_measurement_contract(),
        )
    except (AuthorityBoundaryError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
