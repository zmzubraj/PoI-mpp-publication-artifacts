from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.reporting.load import ReportBuildSpec
from poi_mpp.reporting.manifest import build_publication_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build publication figures through the deterministic report pipeline.")
    parser.add_argument("--spec", required=True, help="JSON build spec path.")
    args = parser.parse_args(argv)
    spec = ReportBuildSpec.model_validate(json.loads(Path(args.spec).read_text(encoding="utf-8")))
    build_publication_report(spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
