from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.evidence.config import load_run_config
from poi_mpp.experiments.e7_evm import (
    AuthorityBoundaryError,
    _atomic_write_json,
    assert_cli_authority_boundary,
    collect_foundry_measurements,
    default_measurement_contract,
    load_default_parity_attachment,
)
from poi_mpp.reporting.e7 import f12_points, summarize_e7_bundle, t12_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect and summarize local E7 Foundry boundedness evidence.")
    parser.add_argument("--run-config", required=True, help="Path to a frozen E7 run configuration.")
    parser.add_argument("--bundle-out", required=True, help="Path to write the raw E7 bundle JSON.")
    parser.add_argument("--summary-out", required=True, help="Path to write the T12/F12-ready summary JSON.")
    parser.add_argument(
        "--contracts-root",
        default=str(REPO_ROOT / "contracts"),
        help="Contracts workspace root containing foundry.toml.",
    )
    args = parser.parse_args(argv)

    try:
        run_config = load_run_config(Path(args.run_config))
        assert_cli_authority_boundary(run_config)
        bundle = collect_foundry_measurements(
            contracts_root=Path(args.contracts_root),
            run_config=run_config,
            output_path=Path(args.bundle_out),
            measurement_contract=default_measurement_contract(),
        )
        parity = load_default_parity_attachment(REPO_ROOT)
        summary = summarize_e7_bundle(
            bundle,
            contract=default_measurement_contract(),
            parity_attachment=parity,
        )
    except (AuthorityBoundaryError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    payload = {
        "bundle_path": str(Path(args.bundle_out).resolve()),
        "t12_rows": [row.model_dump(mode="json") for row in t12_rows(bundle.rows)],
        "f12_points": [point.model_dump(mode="json") for point in f12_points(bundle.rows)],
        "summary": summary.model_dump(mode="json"),
    }
    output_path = Path(args.summary_out)
    _atomic_write_json(output_path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
