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
from poi_mpp.evidence.publication_paths import publication_path_ref
from poi_mpp.experiments.e7_evm import (
    AuthorityBoundaryError,
    _atomic_write_json,
    assert_cli_authority_boundary,
)
from poi_mpp.reporting.e7 import collect_and_summarize_e7_publication, f12_points, t12_rows


def _public_command_transcript(payload: dict[str, object]) -> dict[str, object]:
    command = payload.get("command")
    if not isinstance(command, (list, tuple)):
        raise TypeError("E7 command transcript command must be a sequence")
    cwd = payload.get("cwd")
    if not isinstance(cwd, str):
        raise TypeError("E7 command transcript cwd must be text")
    return {
        **payload,
        "command": [
            publication_path_ref(part, repo_root=REPO_ROOT)
            if isinstance(part, str) and Path(part).is_absolute()
            else part
            for part in command
        ],
        "cwd": publication_path_ref(cwd, repo_root=REPO_ROOT),
    }


def _public_parity_verification_payload(parity_verification) -> dict[str, object]:
    payload = parity_verification.model_dump(mode="json")
    for field in ("protocol_vectors_path", "protocol_witness_path"):
        value = payload.get(field)
        if not isinstance(value, str):
            raise TypeError(f"E7 parity verification {field} must be text")
        payload[field] = publication_path_ref(value, repo_root=REPO_ROOT)
    for field in (
        "export_vectors_transcript",
        "hashvectors_test_transcript",
        "python_parity_transcript",
    ):
        value = payload.get(field)
        if not isinstance(value, dict):
            raise TypeError(f"E7 parity verification {field} must be a mapping")
        payload[field] = _public_command_transcript(value)
    return payload


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
        publication_result = collect_and_summarize_e7_publication(
            contracts_root=Path(args.contracts_root),
            run_config=run_config,
            bundle_output_path=Path(args.bundle_out),
        )
    except (AuthorityBoundaryError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    bundle = publication_result.bundle
    summary = publication_result.summary

    payload = {
        "bundle_path": publication_path_ref(Path(args.bundle_out), repo_root=REPO_ROOT),
        "t12_rows": [row.model_dump(mode="json") for row in t12_rows(bundle.rows)],
        "f12_points": [point.model_dump(mode="json") for point in f12_points(bundle.rows)],
        "parity_verification": _public_parity_verification_payload(
            publication_result.parity_verification
        ),
        "summary": summary.model_dump(mode="json"),
    }
    output_path = Path(args.summary_out)
    _atomic_write_json(output_path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
