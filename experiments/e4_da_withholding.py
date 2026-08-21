from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.evidence import load_run_config
from poi_mpp.experiments.e4_da import AuthorityBoundaryError, assert_cli_authority_boundary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E4 DA wrapper with explicit authority boundary.")
    parser.add_argument("--config", required=True, help="Path to a frozen E4 run configuration.")
    args = parser.parse_args(argv)

    try:
        run_config = load_run_config(Path(args.config))
        assert_cli_authority_boundary(run_config)
    except (AuthorityBoundaryError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
