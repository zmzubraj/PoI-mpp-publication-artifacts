from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.reporting.manifest import validate_existing_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate closure and hashes for an existing publication artifact manifest.")
    parser.add_argument("--output-root", required=True, help="Existing report output root.")
    args = parser.parse_args(argv)
    validate_existing_manifest(Path(args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
