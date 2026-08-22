from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.experiments.e8_consensus import (
    load_and_run_e8_publication,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen E8 publication replay plan and write its canonical rows artifact."
    )
    parser.add_argument(
        "--plan",
        required=True,
        help="Path to the frozen E8 publication plan.",
    )
    parser.add_argument("--output", required=True, help="Path for the canonical E8 rows artifact.")
    args = parser.parse_args(argv)

    try:
        load_and_run_e8_publication(Path(args.plan), output_path=Path(args.output))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
