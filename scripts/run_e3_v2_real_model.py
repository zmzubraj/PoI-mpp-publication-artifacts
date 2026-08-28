#!/usr/bin/env python3
"""Execute the frozen E3-v2 confirmatory dataset under verified authority.

Runs the pinned model over all 500 frozen confirmatory items in manifest
order after fail-closed verification of the external authority grant, the
development bundle bindings, the confirmatory freeze lineage, and a separate
accountable freeze approval. Until the approval verifier is implemented, real
model execution remains blocked; the stub adapter is plumbing-only. Emits raw
hash-bound execution evidence (outputs.jsonl, trace.jsonl, summary.json,
execution_manifest.json) under an external output root.  This script never
decides C3-v2 support: the disposition is computed only by the importer under
the frozen Wilson-bound rule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from poi_mpp.experiments.e3_confirmatory_freeze import (  # noqa: E402
    E3ConfirmatoryFreezeError,
    prepare_e3_phase4_confirmatory_freeze,
    validate_e3_phase4_confirmatory_freeze_materials,
)
from poi_mpp.experiments.e3_development import (  # noqa: E402
    E3DevelopmentBundleError,
    E3DevelopmentBundleStatus,
    prepare_e3_phase3_development_bundle,
)


EXECUTION_MANIFEST_SCHEMA_VERSION = "POI_MPP_E3_V2_EXECUTION_MANIFEST_V1"
EXECUTION_SUMMARY_SCHEMA_VERSION = "POI_MPP_E3_V2_EXECUTION_SUMMARY_V1"
STUB_ADAPTER_NAME = "stub-self-test-v1"
TRANSFORMERS_ADAPTER_NAME = "transformers-pinned-v1"
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_DECISION_TOKEN_RE = re.compile(r"\b(ACCEPT|REJECT|ABSTAIN)\b")
_BINDING_FIELDS = (
    "development_bundle_manifest_sha256",
    "development_dataset_manifest_hash",
    "development_model_manifest_hash",
    "development_decode_policy_hash",
    "development_environment_manifest_hash",
    "development_policy_inputs_digest",
    "confirmatory_freeze_material_lineage_hash",
    "confirmatory_dataset_manifest_hash",
    "confirmatory_development_manifest_hash",
    "calibration_freeze_content_hash",
)


class E3V2ExecutionError(ValueError):
    """Raised when the E3-v2 execution gate or run fails closed."""


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
            raise E3V2ExecutionError(f"{label} may not be a symlink")


def _require_external(path: Path, *, label: str, is_dir: bool) -> Path:
    _assert_no_symlink_components(path, label=label)
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise E3V2ExecutionError(f"{label} must live outside the repository")
    if is_dir and resolved.exists() and not resolved.is_dir():
        raise E3V2ExecutionError(f"{label} must be a directory")
    return resolved


def _read_bundle_member(bundle_root: Path, relative_path: str, *, label: str) -> bytes:
    _assert_no_symlink_components(bundle_root / relative_path, label=label)
    resolved = (bundle_root / relative_path).resolve(strict=True)
    resolved.relative_to(bundle_root)
    return resolved.read_bytes()


def parse_decision(raw_output: str) -> tuple[str, str]:
    """Fail-closed tri-state parse of a raw model transcript."""

    distinct = set(_DECISION_TOKEN_RE.findall(raw_output))
    if len(distinct) == 1:
        return distinct.pop(), "OK"
    if len(distinct) > 1:
        return "ABSTAIN", "CONTRADICTION_FAIL_CLOSED"
    return "ABSTAIN", "UNPARSEABLE_FAIL_CLOSED"


class StubAdapter:
    """Deterministic self-test adapter; its evidence is never publication evidence."""

    name = STUB_ADAPTER_NAME
    evidence_origin = "PIPELINE_SELF_TEST"

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
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as error:  # pragma: no cover - environment dependent
            raise E3V2ExecutionError(
                f"transformers runtime is unavailable for authorized execution: {error}"
            ) from error
        precision = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "float32": torch.float32,
        }.get(model_manifest.precision)
        if precision is None:  # pragma: no cover - manifest validation owns precision
            raise E3V2ExecutionError("pinned model manifest precision is unsupported")
        self._torch = torch
        torch.manual_seed(decode_policy.seed)
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_manifest.tokenizer_id,
            revision=model_manifest.tokenizer_revision,
            local_files_only=True,
        )
        self._model = AutoModelForCausalLM.from_pretrained(
            model_manifest.repository,
            revision=model_manifest.revision,
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
        new_tokens = generated[0][inputs["input_ids"].shape[1] :]
        return self._tokenizer.decode(new_tokens, skip_special_tokens=True)


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


def run_execution(
    *,
    development_bundle_root: Path,
    confirmatory_bundle_root: Path,
    development_manifest_path: Path,
    request_manifest_path: Path,
    authority_record_path: Path,
    allowed_signers_path: Path,
    signature_path: Path,
    output_root: Path,
    run_id: str,
    adapter_name: str,
) -> Path:
    if not _RUN_ID_RE.match(run_id):
        raise E3V2ExecutionError("invalid run-id: must match ^[a-z0-9][a-z0-9-]{2,63}$")
    resolved_output_root = _require_external(output_root, label="output root", is_dir=True)
    run_dir = resolved_output_root / run_id
    if run_dir.exists():
        raise E3V2ExecutionError(f"run directory already exists: {run_dir}")

    prepared = prepare_e3_phase3_development_bundle(
        bundle_root=development_bundle_root,
        request_manifest_path=request_manifest_path,
        authority_record_path=authority_record_path,
        allowed_signers_path=allowed_signers_path,
        signature_path=signature_path,
    )
    if prepared.status is not E3DevelopmentBundleStatus.READY_FOR_EXECUTION:
        missing = ", ".join(prepared.missing_inputs) if prepared.missing_inputs else "none"
        raise E3V2ExecutionError(
            f"E3-v2 execution is not authorized: {prepared.reason} (missing: {missing})"
        )
    grant = prepared.authority_grant

    confirmatory = validate_e3_phase4_confirmatory_freeze_materials(
        bundle_root=confirmatory_bundle_root,
        development_manifest_path=development_manifest_path,
    )
    if grant.confirmatory_freeze_material_lineage_hash != confirmatory.material_lineage_hash:
        raise E3V2ExecutionError(
            "authority grant does not bind the confirmatory bundle material lineage"
        )
    if grant.confirmatory_dataset_manifest_hash != confirmatory.dataset_manifest_hash:
        raise E3V2ExecutionError("authority grant does not bind the confirmatory dataset manifest")
    if grant.confirmatory_development_manifest_hash != confirmatory.development_manifest_hash:
        raise E3V2ExecutionError(
            "authority grant does not bind the confirmatory development manifest"
        )
    composition = grant.confirmatory_composition
    counts = confirmatory.decision_counts
    records = confirmatory.dataset_manifest.records
    if (
        len(records) != composition.get("total")
        or counts.get("ACCEPT") != composition.get("ACCEPT")
        or counts.get("REJECT") != composition.get("REJECT")
        or counts.get("ABSTAIN") != composition.get("ABSTAIN")
    ):
        raise E3V2ExecutionError(
            "confirmatory composition does not match the frozen C3-v2 support rule"
        )

    if adapter_name != "stub":
        freeze_gate = prepare_e3_phase4_confirmatory_freeze(
            bundle_root=confirmatory_bundle_root,
            development_manifest_path=development_manifest_path,
        )
        raise E3V2ExecutionError(
            "E3-v2 real execution is WAITING_EXTERNAL: "
            f"{freeze_gate.reason}; missing: {', '.join(freeze_gate.missing_inputs)}"
        )

    if adapter_name == "stub":
        adapter: StubAdapter | TransformersAdapter = StubAdapter()
    else:
        adapter = TransformersAdapter(
            model_manifest=prepared.model_manifest,
            decode_policy=prepared.decode_policy,
        )

    template = _read_bundle_member(
        prepared.bundle_root, "policy/prompt_template.txt", label="policy/prompt_template.txt"
    )
    decode_policy = prepared.decode_policy

    output_lines: list[str] = []
    trace_lines: list[str] = []
    decision_counts = {"ACCEPT": 0, "REJECT": 0, "ABSTAIN": 0}
    parse_status_counts: dict[str, int] = {}
    false_accept_count = 0
    false_reject_count = 0
    decisive_count = 0

    for record in records:
        item_bytes = _read_bundle_member(
            confirmatory.bundle_root, record.item_path, label=record.item_path
        )
        if _sha256_bytes(item_bytes) != record.item_hash:
            raise E3V2ExecutionError(f"confirmatory item hash mismatch for {record.record_id}")
        prompt_bytes = template + item_bytes
        prompt_sha256 = _sha256_bytes(prompt_bytes)
        raw_output = adapter.generate(prompt_bytes.decode("utf-8"))
        decision, parse_status = parse_decision(raw_output)
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
                    "parse_status": parse_status,
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
        if decision != "ABSTAIN":
            decisive_count += 1
        if expected == "REJECT" and decision == "ACCEPT":
            false_accept_count += 1
        if expected == "ACCEPT" and decision == "REJECT":
            false_reject_count += 1

    outputs_bytes = ("\n".join(output_lines) + "\n").encode("utf-8")
    trace_bytes = ("\n".join(trace_lines) + "\n").encode("utf-8")

    summary: dict[str, Any] = {
        "schema_version": EXECUTION_SUMMARY_SCHEMA_VERSION,
        "run_id": run_id,
        "record_count": len(records),
        "model_decision_counts": {key: decision_counts[key] for key in sorted(decision_counts)},
        "comparison": {
            "false_accept_count": false_accept_count,
            "false_reject_count": false_reject_count,
            "decisive_count": decisive_count,
            "parse_status_counts": {
                key: parse_status_counts[key] for key in sorted(parse_status_counts)
            },
        },
    }
    summary["self_digest"] = _sha256_bytes(_canonical_json_bytes(summary))
    summary_bytes = _canonical_json_bytes(summary)

    model_manifest = prepared.model_manifest
    request_manifest_sha256 = _sha256_bytes(
        _require_external(request_manifest_path, label="request manifest", is_dir=False).read_bytes()
    )
    execution_manifest: dict[str, Any] = {
        "schema_version": EXECUTION_MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "evidence_origin": adapter.evidence_origin,
        "adapter": adapter.name,
        "authority": {
            "authority_record_sha256": grant.authority_record_sha256,
            "request_manifest_sha256": request_manifest_sha256,
            "decision": grant.decision,
            "authority_identity": grant.authority_identity,
        },
        "bindings": {field: getattr(grant, field) for field in _BINDING_FIELDS},
        "model": {
            "model_id": model_manifest.model_id,
            "repository": model_manifest.repository,
            "revision": model_manifest.revision,
            "tokenizer_id": model_manifest.tokenizer_id,
            "tokenizer_revision": model_manifest.tokenizer_revision,
            "parameter_scale": model_manifest.parameter_scale,
            "runtime_name": model_manifest.runtime_name,
            "runtime_version": model_manifest.runtime_version,
        },
        "decode_policy": {
            "seed": decode_policy.seed,
            "max_new_tokens": decode_policy.max_new_tokens,
        },
        "prompt_template_sha256": _sha256_bytes(template),
        "record_count": len(records),
        "outputs_sha256": _sha256_bytes(outputs_bytes),
        "trace_sha256": _sha256_bytes(trace_bytes),
        "summary_sha256": _sha256_bytes(summary_bytes),
        "execution_boundary": (
            "This manifest records hash-bound E3-v2 execution evidence only. It decides no "
            "claim: the C3-v2 disposition is computed solely by the importer under the frozen "
            "Wilson-bound support rule, and publication binding requires a separate external "
            "post-execution attestation."
        ),
    }
    execution_manifest["self_digest"] = _sha256_bytes(_canonical_json_bytes(execution_manifest))

    run_dir.mkdir(parents=True)
    _write_atomic(run_dir / "outputs.jsonl", outputs_bytes)
    _write_atomic(run_dir / "trace.jsonl", trace_bytes)
    _write_atomic(run_dir / "summary.json", summary_bytes)
    _write_atomic(run_dir / "execution_manifest.json", _canonical_json_bytes(execution_manifest))
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-bundle-root", type=Path, required=True)
    parser.add_argument("--confirmatory-bundle-root", type=Path, required=True)
    parser.add_argument("--development-manifest", type=Path, required=True)
    parser.add_argument("--request-manifest", type=Path, required=True)
    parser.add_argument("--authority-record", type=Path, required=True)
    parser.add_argument("--allowed-signers", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", type=str, required=True)
    parser.add_argument("--adapter", choices=("stub", "transformers"), required=True)
    args = parser.parse_args()
    try:
        run_dir = run_execution(
            development_bundle_root=args.development_bundle_root,
            confirmatory_bundle_root=args.confirmatory_bundle_root,
            development_manifest_path=args.development_manifest,
            request_manifest_path=args.request_manifest,
            authority_record_path=args.authority_record,
            allowed_signers_path=args.allowed_signers,
            signature_path=args.signature,
            output_root=args.output_root,
            run_id=args.run_id,
            adapter_name=args.adapter,
        )
    except E3V2ExecutionError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (E3DevelopmentBundleError, E3ConfirmatoryFreezeError, FileNotFoundError, OSError) as error:
        print(f"E3-v2 execution failed: {error}", file=sys.stderr)
        return 1
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
