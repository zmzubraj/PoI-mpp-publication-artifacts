#!/usr/bin/env python3
"""Execute the development-only E3-v2 model over the 120-150 development items.

This runner operates ONLY on the sealed development bundle (never the confirmatory
freeze). It runs the pinned 1B-3B unquantized model in offline/local-files-only
mode after fail-closed validation of:

- the development bundle materials (dataset, model, policy),
- the development-only authority grant,
- the environment manifest (offline + local-only declarations).

It emits raw hash-bound execution evidence (outputs.jsonl, trace.jsonl,
summary.json, execution_manifest.json) under an external output root.

This script never decides C3-v2 support: the disposition is computed only by the
calibration importer under the frozen Wilson-bound rule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.experiments.e3_development import (  # noqa: E402
    E3DevelopmentBundleError,
    E3DevelopmentBundleStatus,
    prepare_e3_phase3_development_bundle,
)
from poi_mpp.experiments.e3_v2_development_authority import (  # noqa: E402
    verify_development_authority,  # retained as a test-visible trust boundary; never called here
)

EXECUTION_MANIFEST_SCHEMA_VERSION = "POI_MPP_E3_V2_DEVELOPMENT_EXECUTION_MANIFEST_V1"
EXECUTION_SUMMARY_SCHEMA_VERSION = "POI_MPP_E3_V2_DEVELOPMENT_EXECUTION_SUMMARY_V1"
STUB_ADAPTER_NAME = "stub-self-test-v1"
TRANSFORMERS_ADAPTER_NAME = "transformers-pinned-v1"
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_DECISION_TOKEN_RE = re.compile(r"\b(ACCEPT|REJECT|ABSTAIN)\b")


class E3V2DevelopmentExecutionError(ValueError):
    """Raised when the E3-v2 development execution gate or run fails closed."""


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    probe = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        probe = probe / component
        if probe.is_symlink():
            raise E3V2DevelopmentExecutionError(f"{label} may not be a symlink")


def _require_external(path: Path, *, label: str) -> Path:
    _assert_no_symlink_components(path, label=label)
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise E3V2DevelopmentExecutionError(f"{label} must live outside the repository")
    if not resolved.exists():
        raise E3V2DevelopmentExecutionError(f"{label} must exist")
    return resolved


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_decision(raw_output: str) -> tuple[str, str]:
    """Fail-closed tri-state parse of a raw model transcript."""
    distinct = set(_DECISION_TOKEN_RE.findall(raw_output))
    if len(distinct) == 1:
        return distinct.pop(), "OK"
    if len(distinct) > 1:
        return "ABSTAIN", "CONTRADICTION_FAIL_CLOSED"
    return "ABSTAIN", "UNPARSEABLE_FAIL_CLOSED"


def parse_model_output(
    raw_output: str, *, require_structured: bool
) -> tuple[str, float, float, str]:
    """Parse the frozen real-output schema, failing closed on any ambiguity."""
    if require_structured:
        try:
            payload = json.loads(raw_output)
            if not isinstance(payload, dict) or set(payload) != {
                "decision", "support_fraction", "calibrated_confidence"
            }:
                raise ValueError("unexpected output fields")
            decision = payload["decision"]
            support = payload["support_fraction"]
            confidence = payload["calibrated_confidence"]
            if decision not in {"ACCEPT", "REJECT", "ABSTAIN"}:
                raise ValueError("invalid decision")
            if (
                isinstance(support, bool)
                or isinstance(confidence, bool)
                or not isinstance(support, (int, float))
                or not isinstance(confidence, (int, float))
                or not 0.0 <= float(support) <= 1.0
                or not 0.0 <= float(confidence) <= 1.0
            ):
                raise ValueError("invalid probability")
            return decision, float(support), float(confidence), "OK"
        except (json.JSONDecodeError, TypeError, ValueError):
            return "ABSTAIN", 0.0, 0.0, "UNPARSEABLE_FAIL_CLOSED"
    decision, status = parse_decision(raw_output)
    support = 1.0 if decision == "ACCEPT" and status == "OK" else 0.0
    confidence = 1.0 if decision in {"ACCEPT", "REJECT"} and status == "OK" else 0.0
    return decision, support, confidence, status


def _verify_snapshot_files(snapshot_root: Path, model_manifest: Any) -> Path:
    """Rehash every authority-bound model/tokenizer byte before model loading."""
    from pathlib import PurePosixPath

    resolved_root = snapshot_root.resolve(strict=True)
    expected = dict(model_manifest.model_file_hashes)
    for filename, digest in model_manifest.tokenizer_file_hashes.items():
        if filename in expected and expected[filename] != digest:
            raise E3V2DevelopmentExecutionError("model/tokenizer hash declarations disagree")
        expected[filename] = digest
    for filename, expected_hash in sorted(expected.items()):
        pure = PurePosixPath(filename)
        if pure.is_absolute() or ".." in pure.parts:
            raise E3V2DevelopmentExecutionError(f"unsafe pinned model path: {filename}")
        candidate = resolved_root.joinpath(*pure.parts)
        _assert_no_symlink_components(candidate, label=f"pinned model file {filename}")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (FileNotFoundError, ValueError) as error:
            raise E3V2DevelopmentExecutionError(f"pinned model file is missing: {filename}") from error
        if not resolved.is_file() or _sha256_bytes(resolved.read_bytes()) != expected_hash:
            raise E3V2DevelopmentExecutionError(f"pinned model file hash mismatch: {filename}")
    return resolved_root


class StubAdapter:
    """Deterministic self-test adapter; its evidence is never publication evidence."""

    name = STUB_ADAPTER_NAME
    evidence_origin = "SYNTHETIC_NON_EVIDENCE"

    def generate(self, prompt: str) -> str:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        decision = ("ACCEPT", "REJECT", "ABSTAIN")[int(digest, 16) % 3]
        return f"STUB_DECISION:{decision}:{digest[:16]}"


class TransformersAdapter:
    """Authorized local-files-only adapter for the pinned transformers model."""

    name = TRANSFORMERS_ADAPTER_NAME
    evidence_origin = "REAL_MODEL_EXECUTION"

    def __init__(self, *, model_manifest: Any, decode_policy: Any) -> None:
        try:
            import torch
            from huggingface_hub import snapshot_download
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as error:
            raise E3V2DevelopmentExecutionError(
                f"transformers runtime is unavailable: {error}"
            ) from error
        precision = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "float32": torch.float32,
        }.get(model_manifest.precision)
        if precision is None:
            raise E3V2DevelopmentExecutionError("pinned model manifest precision is unsupported")
        self._torch = torch
        torch.manual_seed(decode_policy.seed)
        if model_manifest.repository != model_manifest.tokenizer_id:
            raise E3V2DevelopmentExecutionError(
                "separate model/tokenizer repositories are not supported by this closed hash manifest"
            )
        snapshot = Path(
            snapshot_download(
                repo_id=model_manifest.repository,
                revision=model_manifest.revision,
                local_files_only=True,
            )
        )
        verified_snapshot = _verify_snapshot_files(snapshot, model_manifest)
        self._tokenizer = AutoTokenizer.from_pretrained(
            verified_snapshot,
            local_files_only=True,
        )
        self._model = AutoModelForCausalLM.from_pretrained(
            verified_snapshot,
            local_files_only=True,
            torch_dtype=precision,
        )
        self._device = "mps" if torch.backends.mps.is_available() else "cpu"
        self._model.to(self._device)
        self._model.eval()
        self._policy = decode_policy

    def generate(self, prompt: str) -> str:  # pragma: no cover - requires pinned weights
        torch = self._torch
        policy = self._policy
        torch.manual_seed(policy.seed)
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._device)
        with torch.no_grad():
            generated = self._model.generate(
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
                max_new_tokens=policy.max_new_tokens,
                do_sample=False,
                temperature=0.0,
                top_p=1.0,
                top_k=0,
                repetition_penalty=1.0,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        new_tokens = generated[0][inputs["input_ids"].shape[1]:]
        return self._tokenizer.decode(new_tokens, skip_special_tokens=True)


def _read_bundle_member(bundle_root: Path, relative_path: str, *, label: str) -> bytes:
    from pathlib import PurePosixPath
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise E3V2DevelopmentExecutionError(f"unsafe bundle path: {relative_path}")
    candidate = bundle_root / pure
    _assert_no_symlink_components(candidate, label=label)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(bundle_root)
    except (FileNotFoundError, ValueError) as error:
        raise E3V2DevelopmentExecutionError(f"{label} is missing or escapes bundle root") from error
    if resolved.is_symlink():
        raise E3V2DevelopmentExecutionError(f"{label} may not be a symlink")
    return resolved.read_bytes()


def run_development_execution(
    *,
    bundle_root: Path,
    request_manifest_path: Path,
    authority_record_path: Path,
    allowed_signers_path: Path,
    signature_path: Path,
    output_root: Path,
    run_id: str,
    adapter_name: str,
) -> Path:
    """Run the pinned model over all development items in manifest order.

    Requires the bundle to be READY_FOR_EXECUTION (authority + materials validated).
    Does NOT require confirmatory freeze materials.
    """
    if not _RUN_ID_RE.match(run_id):
        raise E3V2DevelopmentExecutionError(
            "invalid run-id: must match ^[a-z0-9][a-z0-9-]{2,63}$"
        )
    resolved_output_root = _require_external(output_root, label="output root")
    run_dir = resolved_output_root / run_id
    if run_dir.exists():
        raise E3V2DevelopmentExecutionError(f"run directory already exists: {run_dir}")

    # Step 1: Validate the development bundle (authority + materials)
    try:
        prepared = prepare_e3_phase3_development_bundle(
            bundle_root=bundle_root,
            request_manifest_path=request_manifest_path,
            authority_record_path=authority_record_path,
            allowed_signers_path=allowed_signers_path,
            signature_path=signature_path,
        )
    except FileNotFoundError:
        raise E3V2DevelopmentExecutionError("development bundle not found")

    if prepared.status is not E3DevelopmentBundleStatus.READY_FOR_EXECUTION:
        missing = ", ".join(prepared.missing_inputs) if prepared.missing_inputs else "none"
        raise E3V2DevelopmentExecutionError(
            f"E3-v2 development execution is not authorized: {prepared.reason} (missing: {missing})"
        )

    # The preflight returns the single verified capability consumed below. Rechecking
    # through another path would split the trust decision and permit TOCTOU drift.
    grant = prepared.authority_grant

    # Step 3: Confirm environment is offline + local-only
    env_manifest = prepared.environment_manifest
    if env_manifest.network_access != "LOCAL_ONLY":
        raise E3V2DevelopmentExecutionError("environment must declare local-only execution")
    if env_manifest.external_services:
        raise E3V2DevelopmentExecutionError("development execution may not declare external services")

    # Step 4: Iterate over development items
    dataset_manifest = prepared.dataset_manifest
    decode_policy = prepared.decode_policy
    records = dataset_manifest.records

    # Validate composition (already enforced by _require_dataset_contract, but re-assert)
    if len(records) < 120 or len(records) > 150:
        raise E3V2DevelopmentExecutionError(
            f"development item count {len(records)} is outside the 120-150 allowance"
        )

    if adapter_name == "stub":
        adapter: StubAdapter | TransformersAdapter = StubAdapter()
    elif adapter_name == "transformers":
        output_schema_raw = _read_bundle_member(
            prepared.bundle_root, "policy/output_schema.json", label="policy/output_schema.json"
        )
        try:
            output_schema = json.loads(output_schema_raw)
        except json.JSONDecodeError as error:
            raise E3V2DevelopmentExecutionError("output schema must be valid JSON") from error
        required_fields = {"decision", "support_fraction", "calibrated_confidence"}
        if not required_fields.issubset(set(output_schema.get("fields", ()))):
            raise E3V2DevelopmentExecutionError(
                "real execution output schema must bind decision, support_fraction, and calibrated_confidence"
            )
        adapter = TransformersAdapter(
            model_manifest=prepared.model_manifest,
            decode_policy=decode_policy,
        )
    else:
        raise E3V2DevelopmentExecutionError(f"unknown adapter: {adapter_name}")

    template = _read_bundle_member(
        prepared.bundle_root, "policy/prompt_template.txt", label="policy/prompt_template.txt"
    )

    output_lines: list[str] = []
    trace_lines: list[str] = []
    decision_counts = {"ACCEPT": 0, "REJECT": 0, "ABSTAIN": 0}
    parse_status_counts: dict[str, int] = {}

    for record in records:
        # Read the item content from the bundle
        item_path = f"dataset/{record.item_path}"
        item_bytes = _read_bundle_member(prepared.bundle_root, item_path, label=item_path)
        if _sha256_bytes(item_bytes) != record.item_hash:
            raise E3V2DevelopmentExecutionError(f"development item hash mismatch for {record.record_id}")

        prompt_bytes = template + item_bytes
        prompt_sha256 = _sha256_bytes(prompt_bytes)
        raw_output = adapter.generate(prompt_bytes.decode("utf-8"))
        decision, support_fraction, calibrated_confidence, parse_status = parse_model_output(
            raw_output,
            require_structured=adapter.name == TRANSFORMERS_ADAPTER_NAME,
        )
        raw_output_sha256 = _sha256_bytes(raw_output.encode("utf-8"))
        expected = record.expected_decision.value

        output_lines.append(
            _canonical_json_bytes(
                {
                    "record_id": record.record_id,
                    "expected_decision": expected,
                    "item_hash": record.item_hash,
                    "prompt_sha256": prompt_sha256,
                    "raw_output": raw_output,
                    "raw_output_sha256": raw_output_sha256,
                    "decision": decision,
                    "support_fraction": support_fraction,
                    "calibrated_confidence": calibrated_confidence,
                    "parse_status": parse_status,
                    "adapter": adapter.name,
                    "evidence_origin": adapter.evidence_origin,
                }
            ).decode("utf-8")
        )
        trace_lines.append(
            _canonical_json_bytes(
                {
                    "record_id": record.record_id,
                    "prompt_sha256": prompt_sha256,
                    "seed": decode_policy.seed,
                    "max_new_tokens": decode_policy.max_new_tokens,
                    "adapter": adapter.name,
                    "raw_output_sha256": raw_output_sha256,
                }
            ).decode("utf-8")
        )
        decision_counts[decision] += 1
        parse_status_counts[parse_status] = parse_status_counts.get(parse_status, 0) + 1

    staging_dir = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=resolved_output_root))
    try:
        _write_atomic(staging_dir / "outputs.jsonl", ("\n".join(output_lines) + "\n").encode("utf-8"))
        _write_atomic(staging_dir / "trace.jsonl", ("\n".join(trace_lines) + "\n").encode("utf-8"))

        summary_payload: dict[str, Any] = {
            "schema_version": EXECUTION_SUMMARY_SCHEMA_VERSION,
            "run_id": run_id,
            "adapter": adapter.name,
            "evidence_origin": adapter.evidence_origin,
            "item_count": len(records),
            "decision_counts": decision_counts,
            "parse_status_counts": parse_status_counts,
            "development_bundle_manifest_sha256": grant.development_bundle_manifest_sha256,
            "development_dataset_manifest_hash": grant.development_dataset_manifest_hash,
            "development_model_manifest_hash": grant.development_model_manifest_hash,
            "development_decode_policy_hash": grant.development_decode_policy_hash,
        }
        _write_atomic(staging_dir / "summary.json", _canonical_json_bytes(summary_payload))

        execution_manifest_payload: dict[str, Any] = {
            "schema_version": EXECUTION_MANIFEST_SCHEMA_VERSION,
            "run_id": run_id,
            "adapter": adapter.name,
            "evidence_origin": adapter.evidence_origin,
            "development_bundle_manifest_sha256": grant.development_bundle_manifest_sha256,
            "development_dataset_manifest_hash": grant.development_dataset_manifest_hash,
            "development_model_manifest_hash": grant.development_model_manifest_hash,
            "development_decode_policy_hash": grant.development_decode_policy_hash,
            "development_environment_manifest_hash": grant.development_environment_manifest_hash,
            "development_policy_inputs_digest": grant.development_policy_inputs_digest,
            "deterministic_seed": decode_policy.seed,
            "max_new_tokens": decode_policy.max_new_tokens,
            "authority": {
                "authority_identity": grant.authority_identity,
                "authority_record_sha256": grant.authority_record_sha256,
                "decision": grant.decision,
                "metric_scope": list(grant.metric_scope),
                "artifact_scope": list(grant.artifact_scope),
                "request_manifest_sha256": grant.request_manifest_sha256,
                "request_manifest_self_digest": grant.request_manifest_self_digest,
                "allowed_signers_sha256": grant.allowed_signers_sha256,
                "signature_sha256": grant.signature_sha256,
            },
            "output_files": {
                "outputs": _sha256_bytes((staging_dir / "outputs.jsonl").read_bytes()),
                "trace": _sha256_bytes((staging_dir / "trace.jsonl").read_bytes()),
                "summary": _sha256_bytes((staging_dir / "summary.json").read_bytes()),
            },
        }
        execution_manifest_payload["self_digest"] = _sha256_bytes(
            _canonical_json_bytes(execution_manifest_payload)
        )
        _write_atomic(
            staging_dir / "execution_manifest.json",
            _canonical_json_bytes(execution_manifest_payload),
        )
        os.replace(staging_dir, run_dir)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True, help="Sealed E3-v2 development bundle root")
    parser.add_argument("--request-manifest", type=Path, required=True, help="Unsigned development authority request manifest")
    parser.add_argument("--authority-record", type=Path, required=True, help="Signed development authority record")
    parser.add_argument("--allowed-signers", type=Path, required=True, help="External allowed-signers file")
    parser.add_argument("--signature", type=Path, required=True, help="Detached signature of the authority record")
    parser.add_argument("--output-root", type=Path, required=True, help="External output root for execution evidence")
    parser.add_argument("--run-id", type=str, required=True, help="Run identifier (lowercase alnum + hyphens)")
    parser.add_argument("--adapter", choices=["stub", "transformers"], default="stub", help="Model adapter to use")
    args = parser.parse_args()
    try:
        result = run_development_execution(
            bundle_root=args.bundle_root,
            request_manifest_path=args.request_manifest,
            authority_record_path=args.authority_record,
            allowed_signers_path=args.allowed_signers,
            signature_path=args.signature,
            output_root=args.output_root,
            run_id=args.run_id,
            adapter_name=args.adapter,
        )
    except (E3V2DevelopmentExecutionError, FileNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Development execution complete: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
