from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import zipfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_REQUEST_SCRIPT = REPO_ROOT / "scripts" / "build_e3_authority_request.py"
VERIFY_RESULT_SCRIPT = REPO_ROOT / "scripts" / "verify_e3_result_attestation.py"
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "paper_artifacts"
    / "final"
    / "external_review"
    / "e3_result_attestation_record.schema.json"
)

IDENTITY = "external-evaluator@example.org"
RUN_ID = "e3-unit-test-fixture"
METRICS = ["ABSTAIN", "FAR", "FRR", "calibration", "coverage"]
ARTIFACT_IDS = ["F7", "RAW_E3_EXECUTION", "T4", "T8"]
ARTIFACT_ROLES = {
    "T4": "DATASET_COMPOSITION",
    "T8": "SEMANTIC_METRICS",
    "F7": "SEMANTIC_QUALITY_FIGURE",
    "RAW_E3_EXECUTION": "RAW_EXECUTION_BUNDLE",
}
RAW_MEMBER_INPUTS = {
    "model_hash": ("model_manifest.json", b'{"model_id":"unit-test-open-weight-model"}\n'),
    "config_hash": ("config.json", b'{"temperature":0,"seed":7}\n'),
    "input_hash": ("inputs.jsonl", b'{"sample_id":"fixture-1"}\n'),
    "output_hash": ("outputs.jsonl", b'{"sample_id":"fixture-1","prediction":"allow"}\n'),
    "trace_hash": ("trace.jsonl", b'{"sample_id":"fixture-1","step":1}\n'),
    "provenance_hash": ("provenance.json", b'{"fixture":"test-only"}\n'),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_request(path: Path) -> dict[str, object]:
    subprocess.run(
        [sys.executable, str(BUILD_REQUEST_SCRIPT), "--output", str(path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _authority_record(request_path: Path, request: dict[str, object]) -> dict[str, object]:
    requested_scope = request["requested_scope"]
    assert isinstance(requested_scope, dict)
    return {
        "schema_version": "POI_MPP_E3_AUTHORITY_RECORD_V2",
        "record_type": "PRE_EXECUTION_SCOPE_AUTHORIZATION",
        "authority_identity": IDENTITY,
        "authority_basis": "Accountable external semantic-evaluation lead",
        "expertise_scope": "Grounded semantic evaluation, calibration, and privacy review",
        "authorized_scope": {
            "experiment_id": "E3",
            "claim_id": "C3",
            "task_class": requested_scope["task_class"],
            "evidence_origin": requested_scope["evidence_origin"],
            "metric_scope": requested_scope["metric_scope"],
            "artifact_scope": requested_scope["artifact_scope"],
            "privacy_scope": "No prompt text may leave the approved evaluator environment",
            "request_scope_digest": request["requested_scope_digest"],
        },
        "reviewed_request_manifest": {
            "path": request_path.name,
            "sha256": _sha256(request_path),
            "self_digest": request["self_digest"],
        },
        "decision": "APPROVED",
        "decision_notes": "Authorization is limited to the hash-bound E3 pre-execution scope.",
        "authorization_date": "2026-08-24",
        "result_attestation_status": "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION",
        "external_signature_required": True,
        "signature_reference": "external://e3-authority-record.sig",
        "allowed_signers_reference": "external://e3-authority-allowed-signers",
    }


def _write_artifacts(
    root: Path,
    *,
    authority_sha256: str,
    metric_scope: list[str] | None = None,
    placeholder: bool = False,
    token_only: bool = False,
) -> tuple[dict[str, Path], dict[str, str]]:
    metrics = metric_scope or METRICS
    paths = {
        "T4": root / "publication/tables/T4_dataset_composition.json",
        "T8": root / "publication/tables/T8_semantic_verification.csv",
        "F7": root / "publication/figures/F7_semantic_verification_quality.svg",
        "RAW_E3_EXECUTION": root / "results/publication/e3-unit-test-fixture/raw_e3_execution.zip",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    bindings = {
        name: hashlib.sha256(payload).hexdigest()
        for name, (_, payload) in RAW_MEMBER_INPUTS.items()
    }
    bindings["pre_execution_authority_record_sha256"] = authority_sha256
    if token_only:
        paths["T4"].write_text(
            f'E3 C3 {RUN_ID} REAL_MODEL_EXECUTION {" ".join(bindings.values())}\n',
            encoding="utf-8",
        )
        paths["T8"].write_text(
            f'E3,C3,{RUN_ID},REAL_MODEL_EXECUTION,{",".join(bindings.values())}\n',
            encoding="utf-8",
        )
        paths["F7"].write_text(
            "<svg xmlns='http://www.w3.org/2000/svg'><metadata>"
            f'E3 C3 {RUN_ID} REAL_MODEL_EXECUTION {" ".join(bindings.values())}'
            "</metadata></svg>\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(paths["RAW_E3_EXECUTION"], "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "run_manifest.json",
                f'E3 C3 {RUN_ID} REAL_MODEL_EXECUTION {" ".join(bindings.values())}',
            )
        return paths, bindings

    t4 = {
        "schema_version": "POI_MPP_E3_T4_V1",
        "artifact_role": "DATASET_COMPOSITION",
        "experiment_id": "E3",
        "claim_id": "C3",
        "run_id": RUN_ID,
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "record_count": 2,
        "class_counts": {"attack": 1, "genuine": 1},
        "execution_bindings": bindings,
    }
    paths["T4"].write_text(json.dumps(t4, sort_keys=True) + "\n", encoding="utf-8")
    if placeholder:
        t4["disposition"] = "WAITING_EXTERNAL"
        paths["T4"].write_text(json.dumps(t4, sort_keys=True) + "\n", encoding="utf-8")

    fieldnames = [
        "schema_version",
        "artifact_role",
        "experiment_id",
        "claim_id",
        "run_id",
        "evidence_origin",
        "metric",
        "value",
        "sample_count",
        *bindings.keys(),
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for index, metric in enumerate(metrics, start=1):
        writer.writerow(
            {
                "schema_version": "POI_MPP_E3_T8_V1",
                "artifact_role": "SEMANTIC_METRICS",
                "experiment_id": "E3",
                "claim_id": "C3",
                "run_id": RUN_ID,
                "evidence_origin": "REAL_MODEL_EXECUTION",
                "metric": metric,
                "value": f"0.{index}",
                "sample_count": "2",
                **bindings,
            }
        )
    paths["T8"].write_text(stream.getvalue(), encoding="utf-8")

    f7_metadata = {
        "schema_version": "POI_MPP_E3_F7_METADATA_V1",
        "artifact_role": "SEMANTIC_QUALITY_FIGURE",
        "experiment_id": "E3",
        "claim_id": "C3",
        "run_id": RUN_ID,
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "metric_scope": metrics,
        "source_t8_sha256": _sha256(paths["T8"]),
        "execution_bindings": bindings,
    }
    paths["F7"].write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'>"
        f"<metadata id='poi-e3-attestation'>{json.dumps(f7_metadata, sort_keys=True)}</metadata>"
        "<rect width='10' height='10'/></svg>\n",
        encoding="utf-8",
    )

    raw_files = {
        logical_name: {
            "path": member_path,
            "sha256": bindings[logical_name],
            "size_bytes": len(payload),
        }
        for logical_name, (member_path, payload) in RAW_MEMBER_INPUTS.items()
    }
    raw_manifest = {
        "schema_version": "POI_MPP_E3_RAW_EXECUTION_V1",
        "artifact_role": "RAW_EXECUTION_BUNDLE",
        "experiment_id": "E3",
        "claim_id": "C3",
        "run_id": RUN_ID,
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "metric_scope": metrics,
        "execution_bindings": bindings,
        "files": raw_files,
    }
    with zipfile.ZipFile(paths["RAW_E3_EXECUTION"], "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for _, (member_path, payload) in RAW_MEMBER_INPUTS.items():
            archive.writestr(member_path, payload)
        archive.writestr("run_manifest.json", json.dumps(raw_manifest, sort_keys=True))
    return paths, bindings


def _attestation_record(
    root: Path,
    request_path: Path,
    request: dict[str, object],
    authority_path: Path,
    artifacts: dict[str, Path],
    execution_bindings: dict[str, str],
    *,
    metric_scope: list[str] | None = None,
    artifact_scope: list[str] | None = None,
) -> dict[str, object]:
    metrics = metric_scope or METRICS
    artifact_ids = artifact_scope or ARTIFACT_IDS
    entries: list[dict[str, object]] = []
    for artifact_id in artifact_ids:
        path = artifacts[artifact_id]
        entries.append(
            {
                "artifact_id": artifact_id,
                "artifact_role": ARTIFACT_ROLES[artifact_id],
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
                "experiment_id": "E3",
                "claim_id": "C3",
                "run_id": RUN_ID,
                "evidence_origin": "REAL_MODEL_EXECUTION",
            }
        )
    return {
        "schema_version": "POI_MPP_E3_RESULT_ATTESTATION_V1",
        "record_type": "POST_EXECUTION_RESULT_ATTESTATION",
        "authority_identity": IDENTITY,
        "authority_basis": "Accountable external semantic-evaluation lead",
        "expertise_scope": "Grounded semantic evaluation, calibration, and privacy review",
        "pre_execution_authority_record": {
            "path": authority_path.name,
            "sha256": _sha256(authority_path),
        },
        "reviewed_request_manifest": {
            "path": request_path.name,
            "sha256": _sha256(request_path),
            "self_digest": request["self_digest"],
        },
        "result_scope": {
            "experiment_id": "E3",
            "claim_id": "C3",
            "task_class": "GROUNDED_SEMANTIC_ASSURANCE",
            "run_id": RUN_ID,
            "evidence_origin": "REAL_MODEL_EXECUTION",
            "metric_scope": metrics,
            "artifact_scope": artifact_ids,
            "execution_bindings": execution_bindings,
        },
        "artifacts": entries,
        "results_disposition": "ATTESTED_AS_REPORTED",
        "attestation_notes": "The signature authenticates the exact artifacts and declared scope only.",
        "attestation_date": "2026-08-24",
        "publication_support_decision_status": "NOT_EVALUATED_BY_THIS_ATTESTATION",
        "external_signature_required": True,
        "signature_namespace": "file",
        "signature_reference": "external://e3-result-attestation.sig",
        "allowed_signers_reference": "external://e3-authority-allowed-signers",
    }


def _key_material(tmp_path: Path) -> tuple[Path, Path]:
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required for detached signature verification")
    private_key = tmp_path / "e3_attestor_key"
    public_key = tmp_path / "e3_attestor_key.pub"
    allowed_signers = tmp_path / "allowed_signers"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
        capture_output=True,
    )
    allowed_signers.write_text(
        f'{IDENTITY} namespaces="file" {public_key.read_text(encoding="utf-8").strip()}\n',
        encoding="utf-8",
    )
    return private_key, allowed_signers


def _sign(private_key: Path, record_path: Path) -> Path:
    subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(private_key), "-n", "file", str(record_path)],
        check=True,
        capture_output=True,
    )
    return Path(f"{record_path}.sig")


def _fixture(
    tmp_path: Path,
    *,
    metric_scope: list[str] | None = None,
    artifact_scope: list[str] | None = None,
    placeholder: bool = False,
    token_only: bool = False,
    force_authority_decision: str | None = None,
) -> dict[str, Path | dict[str, object]]:
    metrics = metric_scope or METRICS
    artifact_ids = artifact_scope or ARTIFACT_IDS
    artifact_root = tmp_path / "artifact-root"
    request_path = tmp_path / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    request = _build_request(request_path)
    authority = _authority_record(request_path, request)
    authority["decision"] = force_authority_decision or (
        "APPROVED"
        if set(metrics) == set(METRICS) and set(artifact_ids) == set(ARTIFACT_IDS)
        else "LIMITED_SCOPE"
    )
    authority["authorized_scope"]["metric_scope"] = metrics
    authority["authorized_scope"]["artifact_scope"] = artifact_ids
    authority_path = tmp_path / "authority_record.json"
    authority_path.write_text(json.dumps(authority, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    artifacts, execution_bindings = _write_artifacts(
        artifact_root,
        authority_sha256=_sha256(authority_path),
        metric_scope=metrics,
        placeholder=placeholder,
        token_only=token_only,
    )
    attestation = _attestation_record(
        artifact_root,
        request_path,
        request,
        authority_path,
        artifacts,
        execution_bindings,
        metric_scope=metrics,
        artifact_scope=artifact_ids,
    )
    attestation_path = tmp_path / "result_attestation.json"
    attestation_path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    private_key, allowed_signers = _key_material(tmp_path)
    authority_signature = _sign(private_key, authority_path)
    attestation_signature = _sign(private_key, attestation_path)
    return {
        "artifact_root": artifact_root,
        "request_path": request_path,
        "request": request,
        "authority_path": authority_path,
        "authority_signature": authority_signature,
        "attestation_path": attestation_path,
        "attestation": attestation,
        "attestation_signature": attestation_signature,
        "allowed_signers": allowed_signers,
        "artifacts": artifacts,
        "execution_bindings": execution_bindings,
    }


def _run_verifier(fixture: dict[str, Path | dict[str, object]]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFY_RESULT_SCRIPT),
            "--request-manifest",
            str(fixture["request_path"]),
            "--authority-record",
            str(fixture["authority_path"]),
            "--authority-signature",
            str(fixture["authority_signature"]),
            "--attestation-record",
            str(fixture["attestation_path"]),
            "--attestation-signature",
            str(fixture["attestation_signature"]),
            "--allowed-signers",
            str(fixture["allowed_signers"]),
            "--artifact-root",
            str(fixture["artifact_root"]),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )


def _rewrite_and_resign(fixture: dict[str, Path | dict[str, object]], tmp_path: Path) -> None:
    attestation_path = fixture["attestation_path"]
    assert isinstance(attestation_path, Path)
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    attestation_path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    signature = fixture["attestation_signature"]
    assert isinstance(signature, Path)
    signature.unlink()
    fixture["attestation_signature"] = _sign(tmp_path / "e3_attestor_key", attestation_path)


def test_result_attestation_schema_requires_post_execution_hash_and_signature_closure() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == "POI_MPP_E3_RESULT_ATTESTATION_V1"
    assert schema["properties"]["record_type"]["const"] == "POST_EXECUTION_RESULT_ATTESTATION"
    assert schema["properties"]["publication_support_decision_status"]["const"] == (
        "NOT_EVALUATED_BY_THIS_ATTESTATION"
    )
    assert {
        "pre_execution_authority_record",
        "reviewed_request_manifest",
        "result_scope",
        "artifacts",
        "results_disposition",
        "external_signature_required",
    }.issubset(schema["required"])
    result_scope = schema["$defs"]["resultScope"]
    assert "execution_bindings" in result_scope["required"]
    result_artifact = schema["$defs"]["resultArtifact"]
    assert "artifact_role" in result_artifact["required"]
    assert len(result_artifact["allOf"]) == 4


def test_result_attestation_accepts_external_signatures_and_exact_real_artifacts(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    completed = _run_verifier(fixture)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION"
    assert result["experiment_id"] == "E3"
    assert result["claim_id"] == "C3"
    assert result["run_id"] == RUN_ID
    assert result["evidence_origin"] == "REAL_MODEL_EXECUTION"
    assert result["publication_support_decision_status"] == "NOT_EVALUATED_BY_THIS_ATTESTATION"
    assert "claim_support" not in result


def test_result_attestation_rejects_current_waiting_external_placeholder(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, placeholder=True)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "placeholder or non-evidence marker" in completed.stderr


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("authority_hash", "pre-execution authority record sha256 mismatch"),
        ("request_self_digest", "request manifest self_digest mismatch"),
        ("artifact_hash", "artifact T8 sha256 mismatch"),
        ("artifact_size", "artifact F7 size mismatch"),
        ("claim_scope", "result scope must close exactly over E3/C3"),
        ("synthetic_origin", "evidence_origin"),
        ("run_mismatch", "artifact T4 run_id does not match result scope"),
        ("missing_artifact", "artifact set must be exactly"),
    ),
)
def test_result_attestation_fails_closed_on_broken_scope_or_provenance(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    fixture = _fixture(tmp_path)
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    if mutation == "authority_hash":
        attestation["pre_execution_authority_record"]["sha256"] = "0" * 64
    elif mutation == "request_self_digest":
        attestation["reviewed_request_manifest"]["self_digest"] = "0" * 64
    elif mutation == "artifact_hash":
        next(item for item in attestation["artifacts"] if item["artifact_id"] == "T8")["sha256"] = "0" * 64
    elif mutation == "artifact_size":
        next(item for item in attestation["artifacts"] if item["artifact_id"] == "F7")["size_bytes"] += 1
    elif mutation == "claim_scope":
        attestation["result_scope"]["claim_id"] = "C4"
    elif mutation == "synthetic_origin":
        attestation["result_scope"]["evidence_origin"] = "SYNTHETIC_NON_EVIDENCE"
    elif mutation == "run_mismatch":
        next(item for item in attestation["artifacts"] if item["artifact_id"] == "T4")["run_id"] = "other-run"
    elif mutation == "missing_artifact":
        attestation["artifacts"] = [item for item in attestation["artifacts"] if item["artifact_id"] != "F7"]
    _rewrite_and_resign(fixture, tmp_path)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert expected in completed.stderr


@pytest.mark.parametrize("unsafe_path", ("../outside.csv", "/absolute/T8.csv"))
def test_result_attestation_rejects_unsafe_artifact_paths(tmp_path: Path, unsafe_path: str) -> None:
    fixture = _fixture(tmp_path)
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    next(item for item in attestation["artifacts"] if item["artifact_id"] == "T8")["path"] = unsafe_path
    _rewrite_and_resign(fixture, tmp_path)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "path" in completed.stderr


def test_result_attestation_rejects_symlinked_artifact(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    artifacts = fixture["artifacts"]
    assert isinstance(artifacts, dict)
    target = artifacts["F7"]
    assert isinstance(target, Path)
    original = target.with_name("actual-f7.svg")
    target.rename(original)
    target.symlink_to(original)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "artifact F7 may not be a symlink" in completed.stderr


def test_result_attestation_rejects_record_changed_after_signature(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    attestation["attestation_notes"] = "Changed after signing"
    attestation_path = fixture["attestation_path"]
    assert isinstance(attestation_path, Path)
    attestation_path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "result attestation signature verification failed" in completed.stderr


def test_result_attestation_requires_strict_iso_attestation_date(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    attestation["attestation_date"] = "2026-8-24"
    _rewrite_and_resign(fixture, tmp_path)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "strict ISO" in completed.stderr


def test_result_attestation_rejects_symlink_member_in_raw_bundle(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    artifacts = fixture["artifacts"]
    assert isinstance(artifacts, dict)
    raw_bundle = artifacts["RAW_E3_EXECUTION"]
    assert isinstance(raw_bundle, Path)
    link = zipfile.ZipInfo("unsafe-link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(raw_bundle, "a") as archive:
        archive.writestr(link, "run_manifest.json")
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    raw_entry = next(item for item in attestation["artifacts"] if item["artifact_id"] == "RAW_E3_EXECUTION")
    raw_entry["sha256"] = _sha256(raw_bundle)
    raw_entry["size_bytes"] = raw_bundle.stat().st_size
    _rewrite_and_resign(fixture, tmp_path)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "RAW_E3_EXECUTION may not contain symlinks" in completed.stderr


def test_result_attestation_rejects_duplicate_normalized_artifact_paths(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    t8 = next(item for item in attestation["artifacts"] if item["artifact_id"] == "T8")
    f7 = next(item for item in attestation["artifacts"] if item["artifact_id"] == "F7")
    f7["path"] = t8["path"]
    _rewrite_and_resign(fixture, tmp_path)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "artifact paths must be unique after normalization" in completed.stderr


@pytest.mark.parametrize(
    ("artifact_id", "field", "value"),
    (
        ("T4", "artifact_role", "SEMANTIC_METRICS"),
        ("T8", "path", "publication/tables/not-the-canonical-t8.csv"),
        ("F7", "path", "publication/figures/not-the-canonical-f7.svg"),
        ("RAW_E3_EXECUTION", "path", "results/publication/wrong/raw.zip"),
    ),
)
def test_result_attestation_binds_each_artifact_id_to_role_and_path(
    tmp_path: Path, artifact_id: str, field: str, value: str
) -> None:
    fixture = _fixture(tmp_path)
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    entry = next(item for item in attestation["artifacts"] if item["artifact_id"] == artifact_id)
    entry[field] = value
    _rewrite_and_resign(fixture, tmp_path)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert f"artifact {artifact_id} role/path contract mismatch" in completed.stderr


def test_result_attestation_rejects_token_only_artifacts_without_typed_contracts(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, token_only=True)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "T4 typed JSON contract" in completed.stderr


def test_result_attestation_rejects_raw_member_not_matching_bound_actual_hash(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    artifacts = fixture["artifacts"]
    assert isinstance(artifacts, dict)
    raw_bundle = artifacts["RAW_E3_EXECUTION"]
    assert isinstance(raw_bundle, Path)
    replacement = raw_bundle.with_name("replacement.zip")
    with zipfile.ZipFile(raw_bundle) as source, zipfile.ZipFile(
        replacement, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            payload = source.read(info)
            if info.filename == "outputs.jsonl":
                payload = b"X" * len(payload)
            target.writestr(info, payload)
    replacement.replace(raw_bundle)
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    raw_entry = next(item for item in attestation["artifacts"] if item["artifact_id"] == "RAW_E3_EXECUTION")
    raw_entry["sha256"] = _sha256(raw_bundle)
    raw_entry["size_bytes"] = raw_bundle.stat().st_size
    _rewrite_and_resign(fixture, tmp_path)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "RAW output_hash does not match actual archive member" in completed.stderr


def test_limited_scope_attestation_authenticates_as_incomplete_nonpublication(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        metric_scope=["ABSTAIN", "FAR"],
        artifact_scope=["RAW_E3_EXECUTION", "T8"],
    )

    completed = _run_verifier(fixture)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION_INCOMPLETE"
    assert result["publication_eligibility_status"] == "INCOMPLETE_NONPUBLICATION"
    assert result["authority_decision"] == "LIMITED_SCOPE"
    assert result["publication_support_decision_status"] == "NOT_EVALUATED_BY_THIS_ATTESTATION"
    assert {item["artifact_id"] for item in result["verified_artifacts"]} == {"RAW_E3_EXECUTION", "T8"}


def test_limited_scope_attestation_must_exactly_match_signed_authorized_subsets(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        metric_scope=["ABSTAIN", "FAR"],
        artifact_scope=["RAW_E3_EXECUTION", "T8"],
    )
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    attestation["result_scope"]["metric_scope"] = ["ABSTAIN"]
    _rewrite_and_resign(fixture, tmp_path)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "result scope must exactly match signed pre-execution authority subsets" in completed.stderr


def test_limited_scope_decision_never_returns_complete_publication_set_status(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, force_authority_decision="LIMITED_SCOPE")

    completed = _run_verifier(fixture)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION_INCOMPLETE"
    assert result["publication_eligibility_status"] == "INCOMPLETE_NONPUBLICATION"


def test_raw_bundle_enforces_member_count_ceiling(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    artifacts = fixture["artifacts"]
    assert isinstance(artifacts, dict)
    raw_bundle = artifacts["RAW_E3_EXECUTION"]
    assert isinstance(raw_bundle, Path)
    with zipfile.ZipFile(raw_bundle, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        for index in range(64):
            archive.writestr(f"extra/{index}.txt", "x")
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    raw_entry = next(item for item in attestation["artifacts"] if item["artifact_id"] == "RAW_E3_EXECUTION")
    raw_entry["sha256"] = _sha256(raw_bundle)
    raw_entry["size_bytes"] = raw_bundle.stat().st_size
    _rewrite_and_resign(fixture, tmp_path)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "RAW_E3_EXECUTION exceeds 64-member ceiling" in completed.stderr


def test_raw_bundle_enforces_uncompressed_size_ceiling(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    artifacts = fixture["artifacts"]
    assert isinstance(artifacts, dict)
    raw_bundle = artifacts["RAW_E3_EXECUTION"]
    assert isinstance(raw_bundle, Path)
    payload_size = 64 * 1024 * 1024 + 1
    with zipfile.ZipFile(raw_bundle, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        with archive.open("oversize.bin", "w") as member:
            chunk = b"0" * (1024 * 1024)
            for _ in range(payload_size // len(chunk)):
                member.write(chunk)
            member.write(b"0" * (payload_size % len(chunk)))
    attestation = fixture["attestation"]
    assert isinstance(attestation, dict)
    raw_entry = next(item for item in attestation["artifacts"] if item["artifact_id"] == "RAW_E3_EXECUTION")
    raw_entry["sha256"] = _sha256(raw_bundle)
    raw_entry["size_bytes"] = raw_bundle.stat().st_size
    _rewrite_and_resign(fixture, tmp_path)

    completed = _run_verifier(fixture)

    assert completed.returncode != 0
    assert "RAW_E3_EXECUTION exceeds 67108864-byte uncompressed ceiling" in completed.stderr
