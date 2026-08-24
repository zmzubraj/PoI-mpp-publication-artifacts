from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from collections.abc import Mapping

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from poi_mpp.experiments.e3_semantic import (  # noqa: E402
    E3ConfirmatoryConfig,
    E3SemanticRow,
    PublicationEligibilityError,
    run_confirmatory_semantic,
)
from poi_mpp.reporting.e3_artifacts import (  # noqa: E402
    E3ArtifactExportError,
    E3ExecutionBindings,
    E3RawExecutionMembers,
    export_e3_artifacts,
)
from poi_mpp.worker.model_manifest import PinnedModelManifest  # noqa: E402
from verify_e3_authority import AuthorityVerificationError, verify_authority  # noqa: E402


def _read_regular_bytes(path: Path, *, label: str) -> bytes:
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, FileNotFoundError) as error:
        raise ValueError(f"unable to read {label}: {path}") from error
    if not resolved.is_file():
        raise ValueError(f"{label} must be a regular file")
    try:
        payload = resolved.read_bytes()
    except OSError as error:
        raise ValueError(f"unable to read {label}: {path}") from error
    if not payload:
        raise ValueError(f"{label} must not be empty")
    return payload


def _parse_json(payload: bytes, *, label: str) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"{label} must contain valid UTF-8 JSON") from error


def _parse_jsonl(payload: bytes, *, label: str) -> tuple[Mapping[str, object], ...]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label} must contain valid UTF-8 JSONL") from error
    rows: list[Mapping[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"{label} contains a blank JSONL row at line {line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{label} contains invalid JSON at line {line_number}") from error
        if not isinstance(value, Mapping):
            raise ValueError(f"{label} row {line_number} must be a JSON object")
        rows.append(value)
    if not rows:
        raise ValueError(f"{label} must contain at least one JSONL row")
    return tuple(rows)


def _case_ids(rows: tuple[Mapping[str, object], ...], *, label: str) -> tuple[str, ...]:
    values: list[str] = []
    for row in rows:
        value = row.get("case_id")
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} rows require a non-empty case_id")
        values.append(value)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} case_id values must be unique")
    return tuple(values)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an externally authorized E3 semantic evaluation.")
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--authority-record", type=Path, required=True)
    parser.add_argument("--authority-signature", type=Path, required=True)
    parser.add_argument("--allowed-signers", type=Path, required=True)
    parser.add_argument("--confirmatory-config", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--raw-config", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        # This is deliberately the only trust-verification boundary. No execution
        # input is opened until the detached external signature has verified.
        grant = verify_authority(
            args.request_manifest,
            args.authority_record,
            allowed_signers_path=args.allowed_signers,
            signature_path=args.authority_signature,
        )

        paths_and_labels = (
            (args.confirmatory_config, "confirmatory config"),
            (args.model_manifest, "model manifest"),
            (args.raw_config, "raw config"),
            (args.inputs, "inputs"),
            (args.outputs, "outputs"),
            (args.trace, "trace"),
            (args.provenance, "provenance"),
        )
        payloads = {
            label: _read_regular_bytes(path, label=label) for path, label in paths_and_labels
        }

        config_payload = _parse_json(payloads["confirmatory config"], label="confirmatory config")
        if not isinstance(config_payload, Mapping):
            raise ValueError("confirmatory config must be a JSON object")
        config = E3ConfirmatoryConfig.model_validate(dict(config_payload))

        model_payload = _parse_json(payloads["model manifest"], label="model manifest")
        if not isinstance(model_payload, Mapping):
            raise ValueError("model manifest must be a JSON object")
        PinnedModelManifest.model_validate(dict(model_payload))

        raw_config_payload = _parse_json(payloads["raw config"], label="raw config")
        if raw_config_payload != config.run_config.model_dump(mode="json"):
            raise ValueError("raw config must exactly match confirmatory config run_config")

        provenance_payload = _parse_json(payloads["provenance"], label="provenance")
        expected_provenance = {
            "experiment_id": config.run_config.experiment_id,
            "origin": config.run_config.origin.value,
            "run_id": config.run_config.run_id,
            "config": config.provenance_bundle.config.model_dump(mode="json"),
            "environment": config.provenance_bundle.environment.model_dump(mode="json"),
            "manifest": config.provenance_bundle.manifest.model_dump(mode="json"),
        }
        if provenance_payload != expected_provenance:
            raise ValueError("raw provenance must exactly match confirmatory config provenance_bundle")

        input_rows = _parse_jsonl(payloads["inputs"], label="inputs")
        output_rows = _parse_jsonl(payloads["outputs"], label="outputs")
        trace_rows = _parse_jsonl(payloads["trace"], label="trace")
        rows = tuple(E3SemanticRow.model_validate(row) for row in output_rows)
        result = run_confirmatory_semantic(config=config, rows=rows, authority_grant=grant)

        evaluated_case_ids = tuple(row.case_id for row in result.evaluated_rows)
        if _case_ids(input_rows, label="inputs") != evaluated_case_ids:
            raise ValueError("inputs case_id order must exactly match evaluated outputs")
        if _case_ids(trace_rows, label="trace") != evaluated_case_ids:
            raise ValueError("trace case_id order must exactly match evaluated outputs")

        bindings = E3ExecutionBindings(
            model_hash=_sha256(payloads["model manifest"]),
            config_hash=_sha256(payloads["raw config"]),
            input_hash=_sha256(payloads["inputs"]),
            output_hash=_sha256(payloads["outputs"]),
            trace_hash=_sha256(payloads["trace"]),
            provenance_hash=_sha256(payloads["provenance"]),
            pre_execution_authority_record_sha256=grant.authority_record_sha256,
        )
        receipt = export_e3_artifacts(
            result=result,
            authority_grant=grant,
            bindings=bindings,
            raw_members=E3RawExecutionMembers(
                model_manifest=args.model_manifest,
                config=args.raw_config,
                inputs=args.inputs,
                outputs=args.outputs,
                trace=args.trace,
                provenance=args.provenance,
            ),
            artifact_root=args.artifact_root,
        )
    except (
        AuthorityVerificationError,
        PublicationEligibilityError,
        E3ArtifactExportError,
        ValidationError,
        ValueError,
        OSError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "schema_version": "POI_MPP_E3_CLI_RESULT_V1",
                "export_receipt": receipt.model_dump(mode="json"),
                "summary": result.summary.model_dump(mode="json"),
                "authority_record_sha256": grant.authority_record_sha256,
                "publication_support_decision_status": "NOT_EVALUATED_BY_THIS_EXECUTION",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
