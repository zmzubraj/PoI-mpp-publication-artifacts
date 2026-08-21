from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.evidence import load_run_config
from poi_mpp.experiments.e5_watcher import (
    AuthorityBoundaryError,
    assert_cli_authority_boundary,
    load_e5_confirmatory_scope,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="E5 watcher/dispute economics wrapper with explicit authority boundaries."
    )
    parser.add_argument("--config", required=True, help="Path to a frozen E5 run configuration.")
    parser.add_argument(
        "--schema",
        default=str(REPO_ROOT / "configs" / "confirmatory" / "e5.yaml"),
        help="Path to the confirmatory E5 scope contract.",
    )
    args = parser.parse_args(argv)

    try:
        scope = load_e5_confirmatory_scope(Path(args.schema))
        run_config = load_run_config(Path(args.config))
        assert_cli_authority_boundary(run_config, scope)
    except (AuthorityBoundaryError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
