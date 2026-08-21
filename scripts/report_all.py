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
from poi_mpp.reporting.manifest import build_publication_report, validate_existing_manifest


def _load_spec(path: Path) -> ReportBuildSpec:
    return ReportBuildSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or build deterministic publication reporting artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate an existing publication artifact manifest.")
    validate_parser.add_argument("--output-root", required=True, help="Existing report output root.")

    build_parser = subparsers.add_parser("build", help="Build deterministic publication artifacts from a frozen spec.")
    build_parser.add_argument("--spec", required=True, help="JSON build spec path.")

    freeze_parser = subparsers.add_parser("freeze", help="Reserved for publication-freeze handoff.")
    freeze_parser.add_argument("--spec", required=True, help="JSON build spec path.")

    args = parser.parse_args(argv)
    if args.command == "validate":
        validate_existing_manifest(Path(args.output_root))
        return 0
    if args.command == "build":
        build_publication_report(_load_spec(Path(args.spec)))
        return 0
    print("Publication freeze remains a later phase and is intentionally unavailable in Task 20.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
