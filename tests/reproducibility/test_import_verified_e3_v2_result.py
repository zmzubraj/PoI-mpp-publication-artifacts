from __future__ import annotations

import csv
import json
from decimal import Decimal, localcontext
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.experiments.e3_v2_bundle_fixtures import canonical_json_bytes, sha256_bytes
from tests.reproducibility.test_build_e3_v2_attestation_draft import (
    _promote_to_authorized,
    _run_draft_builder,
)
from tests.reproducibility.test_e3_v2_authority_contract import IDENTITY
from tests.reproducibility.test_run_e3_v2_real_model import (
    RUN_ID,
    _run_runner,
    _write_execution_inputs,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
IMPORT_SCRIPT = REPO_ROOT / "scripts" / "import_verified_e3_v2_result.py"
FROZEN_Z = Decimal("1.959963984540054")


def _canonical_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    return sha256_bytes(canonical_json_bytes(unsigned))


def _sign_files(tmp_path: Path, paths: list[Path], identity: str) -> Path:
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required for detached signature verification")
    private_key = tmp_path / "attestation_key"
    public_key = tmp_path / "attestation_key.pub"
    allowed_signers = tmp_path / "attestation_allowed_signers"
    if not private_key.exists():
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
            check=True,
            capture_output=True,
        )
        pubkey = public_key.read_text(encoding="utf-8").strip()
        allowed_signers.write_text(f'{identity} namespaces="file" {pubkey}\n', encoding="utf-8")
    for path in paths:
        # ssh-keygen interactively refuses to overwrite an existing .sig file.
        Path(f"{path}.sig").unlink(missing_ok=True)
        subprocess.run(
            ["ssh-keygen", "-Y", "sign", "-f", str(private_key), "-n", "file", str(path)],
            check=True,
            capture_output=True,
        )
    return allowed_signers


def _rewrite_outputs(run_dir: Path, *, false_accepts: int = 0) -> None:
    """Rewrite a stub run so every decision equals gold except forced false accepts."""

    outputs_path = run_dir / "outputs.jsonl"
    lines = [json.loads(line) for line in outputs_path.read_text(encoding="utf-8").splitlines()]
    forced = 0
    for record in lines:
        decision = record["expected_decision"]
        if record["expected_decision"] == "REJECT" and forced < false_accepts:
            decision = "ACCEPT"
            forced += 1
        record["decision"] = decision
        record["parse_status"] = "OK"
        record["raw_output"] = f"SYNTHETIC_DECISION:{decision}"
        record["raw_output_sha256"] = sha256_bytes(record["raw_output"].encode("utf-8"))
    outputs_bytes = b"".join(canonical_json_bytes(record) + b"\n" for record in lines)
    outputs_path.write_bytes(outputs_bytes)

    trace_path = run_dir / "trace.jsonl"
    trace_lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    by_record = {record["record_id"]: record for record in lines}
    for entry in trace_lines:
        entry["raw_output_sha256"] = by_record[entry["record_id"]]["raw_output_sha256"]
    trace_bytes = b"".join(canonical_json_bytes(entry) + b"\n" for entry in trace_lines)
    trace_path.write_bytes(trace_bytes)

    decision_counts = {"ACCEPT": 0, "ABSTAIN": 0, "REJECT": 0}
    false_accept_count = 0
    false_reject_count = 0
    decisive_count = 0
    for record in lines:
        decision_counts[record["decision"]] += 1
        if record["decision"] != "ABSTAIN":
            decisive_count += 1
        if record["expected_decision"] == "REJECT" and record["decision"] == "ACCEPT":
            false_accept_count += 1
        if record["expected_decision"] == "ACCEPT" and record["decision"] == "REJECT":
            false_reject_count += 1
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["model_decision_counts"] = {key: decision_counts[key] for key in sorted(decision_counts)}
    summary["comparison"] = {
        "false_accept_count": false_accept_count,
        "false_reject_count": false_reject_count,
        "decisive_count": decisive_count,
        "parse_status_counts": {"OK": len(lines)},
    }
    summary.pop("self_digest", None)
    summary["self_digest"] = _canonical_digest(summary)
    summary_bytes = canonical_json_bytes(summary)
    summary_path.write_bytes(summary_bytes)

    manifest_path = run_dir / "execution_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs_sha256"] = sha256_bytes(outputs_bytes)
    manifest["trace_sha256"] = sha256_bytes(trace_bytes)
    manifest["summary_sha256"] = sha256_bytes(summary_bytes)
    manifest.pop("self_digest", None)
    manifest["self_digest"] = _canonical_digest(manifest)
    manifest_path.write_bytes(canonical_json_bytes(manifest))


def _attested_run(tmp_path: Path, *, false_accepts: int | None = None) -> dict[str, Path]:
    paths = _write_execution_inputs(tmp_path)
    output_root = tmp_path / "E3V2_RUN_OUTPUT"
    completed = _run_runner(paths, output_root)
    assert completed.returncode == 0, completed.stderr
    run_dir = output_root / RUN_ID
    if false_accepts is not None:
        _rewrite_outputs(run_dir, false_accepts=false_accepts)
    _promote_to_authorized(run_dir)
    draft_path = tmp_path / "e3_v2_result_attestation_draft.json"
    completed = _run_draft_builder(paths, run_dir, draft_path)
    assert completed.returncode == 0, completed.stderr
    attestation_allowed_signers = _sign_files(tmp_path, [draft_path], IDENTITY)
    return {
        **paths,
        "run_dir": run_dir,
        "attestation_record": draft_path,
        "attestation_signature": Path(f"{draft_path}.sig"),
        "attestation_allowed_signers": attestation_allowed_signers,
    }


def _run_importer(
    paths: dict[str, Path],
    publication_root: Path,
    *,
    attestation_signature: Path | None = None,
    run_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    signature = (
        paths["attestation_signature"] if attestation_signature is None else attestation_signature
    )
    command = [
        sys.executable,
        str(IMPORT_SCRIPT),
        "--request-manifest",
        str(paths["request_manifest"]),
        "--authority-record",
        str(paths["authority_record"]),
        "--authority-allowed-signers",
        str(paths["allowed_signers"]),
        "--authority-signature",
        str(paths["signature"]),
        "--attestation-record",
        str(paths["attestation_record"]),
        "--attestation-allowed-signers",
        str(paths["attestation_allowed_signers"]),
        "--attestation-signature",
        str(signature),
        "--run-dir",
        str(paths["run_dir"] if run_dir is None else run_dir),
        "--publication-root",
        str(publication_root),
    ]
    return subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)


def _wilson_upper_bound(successes: int, trials: int) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        z = FROZEN_Z
        n = Decimal(trials)
        p = Decimal(successes) / n
        center = p + z * z / (2 * n)
        margin = z * (p * (1 - p) / n + z * z / (4 * n * n)).sqrt()
        return (center + margin) / (1 + z * z / n)


def _expected_verdict(outputs_path: Path) -> tuple[str, dict[str, int]]:
    lines = [json.loads(line) for line in outputs_path.read_text(encoding="utf-8").splitlines()]
    counts = {
        "false_accept": sum(
            1 for r in lines if r["expected_decision"] == "REJECT" and r["decision"] == "ACCEPT"
        ),
        "false_reject": sum(
            1 for r in lines if r["expected_decision"] == "ACCEPT" and r["decision"] == "REJECT"
        ),
        "decisive": sum(1 for r in lines if r["decision"] != "ABSTAIN"),
        "total": len(lines),
    }
    far_ub = _wilson_upper_bound(counts["false_accept"], 200)
    frr_ub = _wilson_upper_bound(counts["false_reject"], 200)
    coverage = Decimal(counts["decisive"]) / Decimal(counts["total"])
    supported = (
        far_ub <= Decimal("0.25")
        and frr_ub <= Decimal("0.25")
        and coverage >= Decimal("0.50")
    )
    return ("SUPPORTED" if supported else "NOT_SUPPORTED"), counts


def test_import_verified_e3_v2_result_installs_adjudicated_package(tmp_path: Path) -> None:
    paths = _attested_run(tmp_path)
    publication_root = tmp_path / "PUBLICATION"

    completed = _run_importer(paths, publication_root)
    assert completed.returncode == 0, completed.stderr

    run_root = publication_root / RUN_ID
    source_dir = run_root / "source"
    receipt_path = run_root / "verification_receipt.json"
    adjudication_path = run_root / "c3_v2_adjudication.json"
    assert receipt_path.is_file() and adjudication_path.is_file()

    # Raw attested execution evidence is installed verbatim.
    for name in ("execution_manifest.json", "outputs.jsonl", "summary.json", "trace.jsonl"):
        installed = source_dir / name
        assert installed.is_file()
        assert installed.read_bytes() == (paths["run_dir"] / name).read_bytes()

    expected_verdict, counts = _expected_verdict(paths["run_dir"] / "outputs.jsonl")
    adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
    assert adjudication["schema_version"] == "POI_MPP_E3_V2_C3_ADJUDICATION_V1"
    assert adjudication["claim_id"] == "C3"
    assert adjudication["claim_generation"] == "C3_V2"
    assert adjudication["run_id"] == RUN_ID
    assert adjudication["support_rule"] == {
        "rule_id": "C3_V2_WILSON_SUPPORT_V1",
        "wilson_z_value": "1.959963984540054",
        "far_wilson_upper_bound_max": "0.25",
        "frr_wilson_upper_bound_max": "0.25",
        "coverage_min": "0.50",
        "confirmatory_composition": {"ACCEPT": 200, "REJECT": 200, "ABSTAIN": 100, "total": 500},
    }
    assert adjudication["counts"]["false_accept_count"] == counts["false_accept"]
    assert adjudication["counts"]["false_reject_count"] == counts["false_reject"]
    assert adjudication["counts"]["decisive_count"] == counts["decisive"]
    assert adjudication["counts"]["record_count"] == 500
    assert adjudication["verdict"] == expected_verdict
    assert adjudication["calibration_status"] == "NOT_APPLICABLE_DECISION_ONLY_OUTPUT"
    assert adjudication["self_digest"] == _canonical_digest(adjudication)

    # T4 composition is derived from the signed scope, not hardcoded.
    t4 = json.loads((source_dir / "T4_dataset_composition.json").read_text(encoding="utf-8"))
    assert t4["schema_version"] == "POI_MPP_E3_V2_DATASET_COMPOSITION_V1"
    assert t4["evidence_origin"] == "REAL_MODEL_EXECUTION"
    assert t4["record_count"] == 500
    assert t4["gold_decision_counts"] == {"ACCEPT": 200, "ABSTAIN": 100, "REJECT": 200}

    # T8 carries one row per frozen confirmatory record.
    t8_text = (source_dir / "T8_semantic_verification.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(t8_text.splitlines()))
    assert len(rows) == 500
    assert rows[0].keys() == {"record_id", "expected_decision", "decision", "parse_status", "outcome"}
    false_accept_rows = sum(1 for row in rows if row["outcome"] == "FALSE_ACCEPT")
    assert false_accept_rows == counts["false_accept"]

    assert (source_dir / "F7_semantic_verification_quality.svg").read_text(encoding="utf-8").startswith(
        "<svg"
    )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "POI_MPP_E3_V2_VERIFIED_IMPORT_RECEIPT_V1"
    assert receipt["status"] == "VERIFIED_E3_V2_IMPORTED"
    assert receipt["run_id"] == RUN_ID
    assert receipt["authority_verification"]["status"] == "VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY"
    assert receipt["authority_verification"]["decision"] == "APPROVED"
    assert receipt["attestation"]["sha256"] == sha256_bytes(
        paths["attestation_record"].read_bytes()
    )
    assert receipt["adjudication"]["verdict"] == expected_verdict

    # Re-importing identical evidence is idempotent.
    repeat = _run_importer(paths, publication_root)
    assert repeat.returncode == 0, repeat.stderr
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt


def test_importer_adjudicates_supported_at_37_false_accepts(tmp_path: Path) -> None:
    paths = _attested_run(tmp_path, false_accepts=37)
    publication_root = tmp_path / "PUBLICATION"

    completed = _run_importer(paths, publication_root)
    assert completed.returncode == 0, completed.stderr

    adjudication = json.loads(
        (publication_root / RUN_ID / "c3_v2_adjudication.json").read_text(encoding="utf-8")
    )
    assert adjudication["counts"]["false_accept_count"] == 37
    assert Decimal(adjudication["metrics"]["far_wilson_upper_bound"]) <= Decimal("0.25")
    assert adjudication["verdict"] == "SUPPORTED"


def test_importer_adjudicates_not_supported_at_38_false_accepts(tmp_path: Path) -> None:
    paths = _attested_run(tmp_path, false_accepts=38)
    publication_root = tmp_path / "PUBLICATION"

    completed = _run_importer(paths, publication_root)
    assert completed.returncode == 0, completed.stderr

    adjudication = json.loads(
        (publication_root / RUN_ID / "c3_v2_adjudication.json").read_text(encoding="utf-8")
    )
    assert adjudication["counts"]["false_accept_count"] == 38
    assert Decimal(adjudication["metrics"]["far_wilson_upper_bound"]) > Decimal("0.25")
    assert adjudication["verdict"] == "NOT_SUPPORTED"


def test_importer_refuses_invalid_attestation_signature(tmp_path: Path) -> None:
    paths = _attested_run(tmp_path)
    publication_root = tmp_path / "PUBLICATION"
    forged_signature = tmp_path / "forged.sig"
    forged_signature.write_text("-----BEGIN SSH SIGNATURE-----\nnot a signature\n-----END SSH SIGNATURE-----\n")

    completed = _run_importer(paths, publication_root, attestation_signature=forged_signature)
    assert completed.returncode != 0
    assert "signature" in completed.stderr
    assert not (publication_root / RUN_ID).exists()


def test_importer_refuses_tampered_outputs_after_attestation(tmp_path: Path) -> None:
    paths = _attested_run(tmp_path)
    outputs_path = paths["run_dir"] / "outputs.jsonl"
    outputs_path.write_bytes(outputs_path.read_bytes() + b" ")
    publication_root = tmp_path / "PUBLICATION"

    completed = _run_importer(paths, publication_root)
    assert completed.returncode != 0
    assert "outputs" in completed.stderr
    assert not (publication_root / RUN_ID).exists()


def test_importer_refuses_self_test_execution(tmp_path: Path) -> None:
    paths = _attested_run(tmp_path)
    run_dir = paths["run_dir"]

    # Demote the execution back to a pipeline self-test and re-bind the attestation.
    manifest_path = run_dir / "execution_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evidence_origin"] = "PIPELINE_SELF_TEST"
    manifest["adapter"] = "stub-self-test-v1"
    manifest.pop("self_digest", None)
    manifest["self_digest"] = _canonical_digest(manifest)
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)

    draft_path = paths["attestation_record"]
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    for artifact in draft["artifacts"]:
        if artifact["path"] == "execution_manifest.json":
            artifact["sha256"] = sha256_bytes(manifest_bytes)
            artifact["size_bytes"] = len(manifest_bytes)
    draft["result_scope"]["execution_bindings"]["execution_manifest_sha256"] = sha256_bytes(
        manifest_bytes
    )
    draft.pop("self_digest", None)
    draft["self_digest"] = _canonical_digest(draft)
    draft_path.write_bytes(canonical_json_bytes(draft))
    _sign_files(tmp_path, [draft_path], IDENTITY)

    publication_root = tmp_path / "PUBLICATION"
    completed = _run_importer(paths, publication_root)
    assert completed.returncode != 0
    assert "self-test" in completed.stderr
    assert not (publication_root / RUN_ID).exists()


def test_importer_refuses_broken_authority_chain(tmp_path: Path) -> None:
    paths = _attested_run(tmp_path)
    draft_path = paths["attestation_record"]
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    draft["pre_execution_authority_record"]["sha256"] = "f" * 64
    draft.pop("self_digest", None)
    draft["self_digest"] = _canonical_digest(draft)
    draft_path.write_bytes(canonical_json_bytes(draft))
    _sign_files(tmp_path, [draft_path], IDENTITY)

    publication_root = tmp_path / "PUBLICATION"
    completed = _run_importer(paths, publication_root)
    assert completed.returncode != 0
    assert "authority" in completed.stderr
    assert not (publication_root / RUN_ID).exists()


def test_importer_refuses_repository_local_run_dir(tmp_path: Path) -> None:
    paths = _attested_run(tmp_path)
    inside_repo = REPO_ROOT / "tmp-e3-v2-import-run-test-only"
    try:
        shutil.copytree(paths["run_dir"], inside_repo)
        completed = _run_importer(paths, tmp_path / "PUBLICATION", run_dir=inside_repo)
        assert completed.returncode != 0
        assert "must live outside the repository" in completed.stderr
    finally:
        shutil.rmtree(inside_repo, ignore_errors=True)


def test_importer_refuses_divergent_existing_target(tmp_path: Path) -> None:
    paths = _attested_run(tmp_path)
    publication_root = tmp_path / "PUBLICATION"
    divergent = publication_root / RUN_ID / "source"
    divergent.mkdir(parents=True)
    (divergent / "outputs.jsonl").write_text("divergent", encoding="utf-8")

    completed = _run_importer(paths, publication_root)
    assert completed.returncode != 0
    assert "divergent" in completed.stderr
