from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.experiments.e5_multiseed import execute_e5_multiseed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute frozen E5 multi-seed sensitivity simulation.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="explicitly authorize the reproducible-simulation sensitivity execution",
    )
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("--execute is required; sensitivity execution is never implicit")
    result = execute_e5_multiseed(args.config, args.output, repo_root=REPO_ROOT)
    print(json.dumps({"artifact_hash": result["artifact_hash"], "claim_disposition": result["claim_disposition"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
