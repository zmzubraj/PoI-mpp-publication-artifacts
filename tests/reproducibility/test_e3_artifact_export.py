from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import zipfile
from xml.etree import ElementTree
import sys

import pytest

from poi_mpp.auditor.semantic.models import SemanticOutcome, VerificationDecision
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e3_semantic import (
    E3AnnotationProvenance,
    E3ConfirmatoryResult,
    E3SemanticRow,
)
from poi_mpp.reporting.e3 import semantic_metrics
from poi_mpp.reporting.e3_artifacts import (
    E3ArtifactExportError,
    E3ArtifactScope,
    E3ExecutionBindings,
    E3RawExecutionMembers,
    export_e3_artifacts,
)


RUN_ID = "e3-real-export-test"
ALL_METRICS = ("FAR", "FRR", "ABSTAIN", "coverage", "calibration")
ALL_ARTIFACTS = ("T4", "T8", "F7", "RAW_E3_EXECUTION")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _row(
    case_id: str,
    *,
    valid: bool,
    decision: VerificationDecision,
    confidence: float | None,
) -> E3SemanticRow:
    verifier_outcome = None if decision is VerificationDecision.ABSTAIN else (
        SemanticOutcome.SUPPORTED if decision is VerificationDecision.ACCEPT else SemanticOutcome.UNSUPPORTED
    )
    return E3SemanticRow(
        run_id=RUN_ID,
        experiment_id="E3",
        case_id=case_id,
        split="CONFIRMATORY",
        origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        frozen_reference_valid=valid,
        frozen_reference_outcome=(
            SemanticOutcome.SUPPORTED if valid else SemanticOutcome.UNSUPPORTED
        ),
        verifier_decision=decision,
        verifier_outcome=verifier_outcome,
        abstained=decision is VerificationDecision.ABSTAIN,
        subgroup="fixture",
        verifier_confidence=confidence,
        calibration_hash="a" * 64,
        source_record_id=f"source-{case_id}",
        source_content_hash="b" * 64,
        source_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        annotation_record_id=f"annotation-{case_id}",
        annotation_hash="c" * 64,
        annotation_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        evaluator_id="external-evaluator",
        evaluator_hash="d" * 64,
        evaluator_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        evaluator_independence_basis="External accountable semantic evaluation",
    )


def _result(*, only_valid: bool = False, all_abstain: bool = False) -> E3ConfirmatoryResult:
    if only_valid:
        rows = (
            _row("1", valid=True, decision=VerificationDecision.ACCEPT, confidence=0.9),
            _row("2", valid=True, decision=VerificationDecision.REJECT, confidence=0.2),
        )
    elif all_abstain:
        rows = (
            _row("1", valid=True, decision=VerificationDecision.ABSTAIN, confidence=None),
            _row("2", valid=False, decision=VerificationDecision.ABSTAIN, confidence=None),
        )
    else:
        rows = (
            _row("1", valid=True, decision=VerificationDecision.ACCEPT, confidence=0.9),
            _row("2", valid=True, decision=VerificationDecision.REJECT, confidence=0.2),
            _row("3", valid=True, decision=VerificationDecision.ABSTAIN, confidence=None),
            _row("4", valid=False, decision=VerificationDecision.ACCEPT, confidence=0.7),
            _row("5", valid=False, decision=VerificationDecision.REJECT, confidence=0.8),
            _row("6", valid=False, decision=VerificationDecision.ABSTAIN, confidence=None),
        )
    return E3ConfirmatoryResult(
        summary=semantic_metrics(rows),
        annotation_provenance=E3AnnotationProvenance(
            source_record_ids=tuple(row.source_record_id for row in rows),
            source_hashes=("b" * 64,),
            source_origins=(EvidenceOrigin.REAL_MODEL_EXECUTION,),
            annotation_record_ids=tuple(row.annotation_record_id for row in rows),
            annotation_hashes=("c" * 64,),
            annotation_origins=(EvidenceOrigin.REAL_MODEL_EXECUTION,),
            evaluator_ids=("external-evaluator",),
            evaluator_hashes=("d" * 64,),
            evaluator_origins=(EvidenceOrigin.REAL_MODEL_EXECUTION,),
            evaluator_independence_bases=("External accountable semantic evaluation",),
        ),
        error_ledger=(),
        evaluated_rows=rows,
    )


def _model_manifest() -> dict[str, object]:
    return {
        "schema_version": "POI_MPP_WORKER_MODEL_MANIFEST_V1",
        "model_id": "local-qwen-1.5b",
        "repository": "Qwen/Qwen2.5-1.5B-Instruct",
        "revision": "9" * 40,
        "tokenizer_id": "Qwen/Qwen2.5-1.5B-Instruct",
        "tokenizer_revision": "9" * 40,
        "license_id": "apache-2.0",
        "parameter_scale": "1.5B",
        "precision": "int4",
        "quantization": "q4_k_m",
        "runtime_name": "transformers",
        "runtime_version": "4.44.0",
        "model_file_hashes": {"model.safetensors": "1" * 64},
        "tokenizer_file_hashes": {"tokenizer.json": "2" * 64},
        "assurance_class": 1,
    }


def _jsonl(rows: tuple[dict[str, object], ...]) -> bytes:
    return b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )


def _raw_members(
    tmp_path: Path, result: E3ConfirmatoryResult | None = None
) -> E3RawExecutionMembers:
    tmp_path.mkdir(parents=True, exist_ok=True)
    result = result or _result()
    evaluated_rows = result.evaluated_rows
    closure_rows = tuple(
        {
            "case_id": row.case_id,
            "run_id": row.run_id,
            "experiment_id": row.experiment_id,
        }
        for row in evaluated_rows
    )
    values = {
        "model_manifest": (json.dumps(_model_manifest(), sort_keys=True) + "\n").encode(),
        "config": b'{"experiment_id":"E3","origin":"REAL_MODEL_EXECUTION","run_id":"e3-real-export-test"}\n',
        "inputs": _jsonl(closure_rows),
        "outputs": _jsonl(
            tuple(row.model_dump(mode="json") for row in evaluated_rows)
        ),
        "trace": _jsonl(closure_rows),
        "provenance": b'{"experiment_id":"E3","origin":"REAL_MODEL_EXECUTION","run_id":"e3-real-export-test","verified":true}\n',
    }
    paths: dict[str, Path] = {}
    for name, payload in values.items():
        suffix = ".jsonl" if name in {"inputs", "outputs", "trace"} else ".json"
        path = tmp_path / f"{name}{suffix}"
        path.write_bytes(payload)
        paths[name] = path
    return E3RawExecutionMembers(**paths)


def _bindings(raw: E3RawExecutionMembers, grant=None) -> E3ExecutionBindings:
    return E3ExecutionBindings(
        model_hash=_sha256(raw.model_manifest.read_bytes()),
        config_hash=_sha256(raw.config.read_bytes()),
        input_hash=_sha256(raw.inputs.read_bytes()),
        output_hash=_sha256(raw.outputs.read_bytes()),
        trace_hash=_sha256(raw.trace.read_bytes()),
        provenance_hash=_sha256(raw.provenance.read_bytes()),
        pre_execution_authority_record_sha256=(
            grant.authority_record_sha256 if grant is not None else "e" * 64
        ),
    )


def _canonical_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _verified_grant(tmp_path: Path, *, limited: bool = False):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from build_e3_authority_request import build_manifest
        from verify_e3_authority import verify_authority
    finally:
        sys.path.remove(str(scripts))
    request = build_manifest()
    assert request["self_digest"] == _canonical_digest(request)
    request_path = tmp_path / "E3_AUTHORITY_REQUEST_MANIFEST.json"
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    requested = request["requested_scope"]
    record = {
        "schema_version": "POI_MPP_E3_AUTHORITY_RECORD_V2",
        "record_type": "PRE_EXECUTION_SCOPE_AUTHORIZATION",
        "authority_identity": "external-e3-export-test@example.org",
        "authority_basis": "Test-only external authority fixture",
        "expertise_scope": "Grounded semantic evaluation test fixture",
        "authorized_scope": {
            "experiment_id": "E3",
            "claim_id": "C3",
            "task_class": requested["task_class"],
            "evidence_origin": requested["evidence_origin"],
            "metric_scope": ["FAR"] if limited else requested["metric_scope"],
            "artifact_scope": ["RAW_E3_EXECUTION", "T8"] if limited else requested["artifact_scope"],
            "privacy_scope": "Test-only hash-closed records",
            "request_scope_digest": request["requested_scope_digest"],
        },
        "reviewed_request_manifest": {
            "path": request_path.name,
            "sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
            "self_digest": request["self_digest"],
        },
        "decision": "LIMITED_SCOPE" if limited else "APPROVED",
        "decision_notes": "Test-only signed authority fixture.",
        "authorization_date": "2026-08-24",
        "result_attestation_status": "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION",
        "external_signature_required": True,
        "signature_reference": "external://test-e3-authority.sig",
        "allowed_signers_reference": "external://test-e3-allowed-signers",
    }
    record_path = tmp_path / "authority.json"
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen is required for verified authority fixtures")
    key = tmp_path / "authority-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
        capture_output=True,
    )
    allowed_signers = tmp_path / "allowed_signers"
    allowed_signers.write_text(
        f'{record["authority_identity"]} namespaces="file" {Path(f"{key}.pub").read_text().strip()}\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "file", str(record_path)],
        check=True,
        capture_output=True,
    )
    return verify_authority(
        request_path,
        record_path,
        allowed_signers_path=allowed_signers,
        signature_path=Path(f"{record_path}.sig"),
    )


@pytest.fixture(scope="module")
def approved_grant(tmp_path_factory: pytest.TempPathFactory):
    return _verified_grant(tmp_path_factory.mktemp("approved-grant"))


@pytest.fixture(scope="module")
def limited_grant(tmp_path_factory: pytest.TempPathFactory):
    return _verified_grant(tmp_path_factory.mktemp("limited-grant"), limited=True)


def test_export_writes_deterministic_typed_artifact_set(tmp_path: Path, approved_grant) -> None:
    raw = _raw_members(tmp_path / "raw")
    first = tmp_path / "first"
    second = tmp_path / "second"

    export_e3_artifacts(
        result=_result(), authority_grant=approved_grant, bindings=_bindings(raw, approved_grant), raw_members=raw, artifact_root=first
    )
    export_e3_artifacts(
        result=_result(), authority_grant=approved_grant, bindings=_bindings(raw, approved_grant), raw_members=raw, artifact_root=second
    )

    relative_paths = (
        "publication/tables/T4_dataset_composition.json",
        "publication/tables/T8_semantic_verification.csv",
        "publication/figures/F7_semantic_verification_quality.svg",
        f"results/publication/{RUN_ID}/raw_e3_execution.zip",
    )
    for relative in relative_paths:
        assert (first / relative).read_bytes() == (second / relative).read_bytes()

    t4 = json.loads((first / relative_paths[0]).read_text(encoding="utf-8"))
    assert t4["class_counts"] == {"invalid": 3, "valid": 3}
    assert t4["record_count"] == 6
    assert t4["execution_bindings"] == _bindings(raw, approved_grant).model_dump(mode="json")

    t8_payload = (first / relative_paths[1]).read_bytes()
    t8_rows = list(csv.DictReader(io.StringIO(t8_payload.decode("utf-8"), newline="")))
    assert [row["metric"] for row in t8_rows] == list(ALL_METRICS)
    assert {row["metric"]: int(row["sample_count"]) for row in t8_rows} == {
        "FAR": 3,
        "FRR": 3,
        "ABSTAIN": 6,
        "coverage": 6,
        "calibration": 4,
    }

    svg = ElementTree.fromstring((first / relative_paths[2]).read_bytes())
    metadata_nodes = [
        node for node in svg.iter()
        if node.tag.rsplit("}", 1)[-1] == "metadata" and node.attrib.get("id") == "poi-e3-attestation"
    ]
    assert len(metadata_nodes) == 1
    metadata = json.loads(metadata_nodes[0].text or "")
    assert metadata["source_t8_sha256"] == _sha256(t8_payload)
    assert metadata["execution_bindings"] == _bindings(raw, approved_grant).model_dump(mode="json")

    with zipfile.ZipFile(first / relative_paths[3]) as archive:
        assert archive.namelist() == [
            "model_manifest.json",
            "config.json",
            "inputs.jsonl",
            "outputs.jsonl",
            "trace.jsonl",
            "provenance.json",
            "run_manifest.json",
        ]
        manifest = json.loads(archive.read("run_manifest.json"))
        assert manifest["execution_bindings"] == _bindings(raw, approved_grant).model_dump(mode="json")


def test_exported_bytes_pass_existing_typed_artifact_verifiers(tmp_path: Path, approved_grant) -> None:
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from verify_e3_result_attestation import (
            ResultScope,
            _validate_f7,
            _validate_t4,
            _validate_t8,
            _validate_zip_bundle,
        )
    finally:
        sys.path.remove(str(scripts))

    raw = _raw_members(tmp_path / "raw")
    output = tmp_path / "artifacts"
    bindings = _bindings(raw, approved_grant)
    export_e3_artifacts(
        result=_result(), authority_grant=approved_grant, bindings=bindings, raw_members=raw, artifact_root=output
    )
    verifier_scope = ResultScope(
        experiment_id="E3",
        claim_id="C3",
        task_class="GROUNDED_SEMANTIC_ASSURANCE",
        run_id=RUN_ID,
        evidence_origin="REAL_MODEL_EXECUTION",
        metric_scope=ALL_METRICS,
        artifact_scope=ALL_ARTIFACTS,
        execution_bindings=bindings.model_dump(mode="json"),
    )
    t4 = (output / "publication/tables/T4_dataset_composition.json").read_bytes()
    t8 = (output / "publication/tables/T8_semantic_verification.csv").read_bytes()
    f7 = (output / "publication/figures/F7_semantic_verification_quality.svg").read_bytes()
    raw_zip = output / f"results/publication/{RUN_ID}/raw_e3_execution.zip"
    _validate_t4(t4, scope=verifier_scope)
    _validate_t8(t8, scope=verifier_scope)
    _validate_f7(f7, scope=verifier_scope, t8_sha256=_sha256(t8))
    _validate_zip_bundle(raw_zip, scope=verifier_scope)


@pytest.mark.parametrize(
    ("result", "match"),
    [
        (lambda: _result(only_valid=True), "FAR.*undefined"),
        (lambda: _result(all_abstain=True), "calibration.*undefined"),
    ],
)
def test_export_rejects_undefined_authorized_metric_without_partial_outputs(
    tmp_path: Path, result, match: str, approved_grant
) -> None:
    evaluated = result()
    raw = _raw_members(tmp_path / "raw", evaluated)
    output = tmp_path / "artifacts"
    with pytest.raises(E3ArtifactExportError, match=match):
        export_e3_artifacts(
            result=evaluated, authority_grant=approved_grant, bindings=_bindings(raw, approved_grant), raw_members=raw, artifact_root=output
        )
    assert not output.exists()


def test_limited_scope_exports_only_exact_incomplete_subset(tmp_path: Path, limited_grant) -> None:
    raw = _raw_members(tmp_path / "raw")
    output = tmp_path / "artifacts"
    receipt = export_e3_artifacts(
        result=_result(), authority_grant=limited_grant, bindings=_bindings(raw, limited_grant), raw_members=raw, artifact_root=output
    )

    assert receipt.completeness == "INCOMPLETE_NONPUBLICATION"
    assert (output / "publication/tables/T8_semantic_verification.csv").is_file()
    assert (output / f"results/publication/{RUN_ID}/raw_e3_execution.zip").is_file()
    assert not (output / "publication/tables/T4_dataset_composition.json").exists()
    assert not (output / "publication/figures/F7_semantic_verification_quality.svg").exists()


def test_export_rejects_missing_or_freely_constructed_scope_without_verified_grant(
    tmp_path: Path,
) -> None:
    raw = _raw_members(tmp_path / "raw")
    forged_scope = E3ArtifactScope(
        decision="APPROVED",
        run_id=RUN_ID,
        evidence_origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
        metric_scope=ALL_METRICS,
        artifact_scope=ALL_ARTIFACTS,
    )
    for index, candidate in enumerate((None, forged_scope)):
        output = tmp_path / f"artifacts-{index}"
        with pytest.raises(E3ArtifactExportError, match="verified authority grant"):
            export_e3_artifacts(
                result=_result(), authority_grant=candidate, bindings=_bindings(raw), raw_members=raw, artifact_root=output
            )
        assert not output.exists()


def test_export_rejects_authority_record_hash_mismatch(tmp_path: Path, approved_grant) -> None:
    raw = _raw_members(tmp_path / "raw")
    output = tmp_path / "artifacts"
    with pytest.raises(E3ArtifactExportError, match="authority_record_sha256"):
        export_e3_artifacts(
            result=_result(), authority_grant=approved_grant, bindings=_bindings(raw), raw_members=raw, artifact_root=output
        )
    assert not output.exists()


def test_export_rejects_binding_mismatch_symlink_and_existing_target(tmp_path: Path, approved_grant) -> None:
    raw = _raw_members(tmp_path / "raw")
    output = tmp_path / "artifacts"
    bad_bindings = _bindings(raw, approved_grant).model_copy(update={"output_hash": "f" * 64})
    with pytest.raises(E3ArtifactExportError, match="output_hash"):
        export_e3_artifacts(
            result=_result(), authority_grant=approved_grant, bindings=bad_bindings, raw_members=raw, artifact_root=output
        )
    assert not output.exists()

    link = tmp_path / "linked-output.jsonl"
    link.symlink_to(raw.outputs)
    linked_raw = E3RawExecutionMembers(
        model_manifest=raw.model_manifest,
        config=raw.config,
        inputs=raw.inputs,
        outputs=link,
        trace=raw.trace,
        provenance=raw.provenance,
    )
    with pytest.raises(E3ArtifactExportError, match="symlink"):
        export_e3_artifacts(
            result=_result(), authority_grant=approved_grant, bindings=_bindings(raw, approved_grant), raw_members=linked_raw, artifact_root=output
        )
    assert not output.exists()

    output.mkdir()
    with pytest.raises(E3ArtifactExportError, match="must not already exist"):
        export_e3_artifacts(
            result=_result(), authority_grant=approved_grant, bindings=_bindings(raw, approved_grant), raw_members=raw, artifact_root=output
        )


def test_export_enforces_raw_member_size_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approved_grant
) -> None:
    import poi_mpp.reporting.e3_artifacts as exporter

    raw = _raw_members(tmp_path / "raw")
    monkeypatch.setattr(exporter, "MAX_RAW_ZIP_UNCOMPRESSED_BYTES", 8)
    output = tmp_path / "artifacts"
    with pytest.raises(E3ArtifactExportError, match="uncompressed ceiling"):
        export_e3_artifacts(
            result=_result(), authority_grant=approved_grant, bindings=_bindings(raw, approved_grant), raw_members=raw, artifact_root=output
        )
    assert not output.exists()


def test_export_enforces_member_count_ceiling_and_duplicate_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approved_grant
) -> None:
    import poi_mpp.reporting.e3_artifacts as exporter

    raw = _raw_members(tmp_path / "raw")
    output = tmp_path / "artifacts"
    monkeypatch.setattr(exporter, "MAX_RAW_ZIP_MEMBERS", 6)
    with pytest.raises(E3ArtifactExportError, match="member-count ceiling"):
        export_e3_artifacts(
            result=_result(), authority_grant=approved_grant, bindings=_bindings(raw, approved_grant), raw_members=raw, artifact_root=output
        )
    assert not output.exists()

    monkeypatch.setattr(exporter, "MAX_RAW_ZIP_MEMBERS", 64)
    duplicated = raw.model_copy(update={"trace": raw.outputs})
    with pytest.raises(E3ArtifactExportError, match="distinct file paths"):
        export_e3_artifacts(
            result=_result(), authority_grant=approved_grant, bindings=_bindings(raw, approved_grant), raw_members=duplicated, artifact_root=output
        )
    assert not output.exists()


def test_export_rejects_non_evidence_raw_marker_and_cleans_failed_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approved_grant
) -> None:
    raw = _raw_members(tmp_path / "raw")
    raw.inputs.write_bytes(b'{"origin":"SYNTHETIC_NON_EVIDENCE"}\n')
    output = tmp_path / "artifacts"
    with pytest.raises(E3ArtifactExportError, match="non-evidence marker"):
        export_e3_artifacts(
            result=_result(), authority_grant=approved_grant, bindings=_bindings(raw, approved_grant), raw_members=raw, artifact_root=output
        )
    assert not output.exists()

    raw = _raw_members(tmp_path / "real-raw")
    original_write = Path.write_bytes
    calls = 0

    def fail_second_write(path: Path, payload: bytes) -> int:
        nonlocal calls
        if ".artifacts.staging-" in path.as_posix():
            calls += 1
            if calls == 2:
                raise OSError("injected staging failure")
        return original_write(path, payload)

    monkeypatch.setattr(Path, "write_bytes", fail_second_write)
    with pytest.raises(E3ArtifactExportError, match="atomically publish"):
        export_e3_artifacts(
            result=_result(), authority_grant=approved_grant, bindings=_bindings(raw, approved_grant), raw_members=raw, artifact_root=output
        )
    assert not output.exists()
    assert not tuple(tmp_path.glob(".artifacts.staging-*"))


@pytest.mark.parametrize(
    ("member", "mutator", "match"),
    [
        ("inputs", lambda rows: rows[:-1], "case-id set"),
        ("outputs", lambda rows: rows[:-1], "case-id set"),
        ("trace", lambda rows: rows[:-1], "case-id set"),
        ("inputs", lambda rows: (*rows, rows[0]), "duplicate case_id"),
        (
            "trace",
            lambda rows: ({**rows[0], "case_id": "wrong-case"}, *rows[1:]),
            "case-id set",
        ),
        (
            "inputs",
            lambda rows: ({**rows[0], "run_id": "wrong-run"}, *rows[1:]),
            "run_id",
        ),
    ],
)
def test_export_rejects_raw_jsonl_omissions_duplicates_and_scope_drift(
    tmp_path: Path, approved_grant, member: str, mutator, match: str
) -> None:
    result = _result()
    raw = _raw_members(tmp_path / "raw", result)
    path = getattr(raw, member)
    rows = tuple(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    path.write_bytes(_jsonl(tuple(mutator(rows))))
    output = tmp_path / "artifacts"
    with pytest.raises(E3ArtifactExportError, match=match):
        export_e3_artifacts(
            result=result,
            authority_grant=approved_grant,
            bindings=_bindings(raw, approved_grant),
            raw_members=raw,
            artifact_root=output,
        )
    assert not output.exists()


def test_export_rejects_output_row_or_summary_not_closed_to_evaluated_rows(
    tmp_path: Path, approved_grant
) -> None:
    result = _result()
    raw = _raw_members(tmp_path / "raw", result)
    output_rows = [json.loads(line) for line in raw.outputs.read_text().splitlines()]
    output_rows[0]["frozen_reference_valid"] = False
    raw.outputs.write_bytes(_jsonl(tuple(output_rows)))
    with pytest.raises(E3ArtifactExportError, match="evaluated row"):
        export_e3_artifacts(
            result=result,
            authority_grant=approved_grant,
            bindings=_bindings(raw, approved_grant),
            raw_members=raw,
            artifact_root=tmp_path / "row-drift",
        )

    forged = result.model_copy(
        update={"summary": result.summary.model_copy(update={"denominator": 999})}
    )
    raw = _raw_members(tmp_path / "second-raw", result)
    with pytest.raises(E3ArtifactExportError, match="summary"):
        export_e3_artifacts(
            result=forged,
            authority_grant=approved_grant,
            bindings=_bindings(raw, approved_grant),
            raw_members=raw,
            artifact_root=tmp_path / "summary-drift",
        )


@pytest.mark.parametrize("member", ["config", "provenance"])
def test_export_rejects_raw_config_or_provenance_scope_drift(
    tmp_path: Path, approved_grant, member: str
) -> None:
    raw = _raw_members(tmp_path / "raw")
    getattr(raw, member).write_text(
        '{"experiment_id":"E2","origin":"REAL_MODEL_EXECUTION","run_id":"wrong"}\n',
        encoding="utf-8",
    )
    with pytest.raises(E3ArtifactExportError, match=f"raw {member}.*run_id|raw {member}.*experiment_id"):
        export_e3_artifacts(
            result=_result(),
            authority_grant=approved_grant,
            bindings=_bindings(raw, approved_grant),
            raw_members=raw,
            artifact_root=tmp_path / "artifacts",
        )


def test_export_rejects_invalid_or_out_of_range_model_manifest(
    tmp_path: Path, approved_grant
) -> None:
    raw = _raw_members(tmp_path / "raw")
    manifest = _model_manifest()
    manifest["parameter_scale"] = "70B"
    raw.model_manifest.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    with pytest.raises(E3ArtifactExportError, match="PinnedModelManifest"):
        export_e3_artifacts(
            result=_result(),
            authority_grant=approved_grant,
            bindings=_bindings(raw, approved_grant),
            raw_members=raw,
            artifact_root=tmp_path / "artifacts",
        )


def test_oversized_raw_file_is_rejected_from_stat_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approved_grant
) -> None:
    import poi_mpp.reporting.e3_artifacts as exporter

    raw = _raw_members(tmp_path / "raw")
    bindings = _bindings(raw, approved_grant)
    monkeypatch.setattr(exporter, "MAX_RAW_MEMBER_BYTES", 32)
    original_read = Path.read_bytes

    def reject_if_oversized_read(path: Path) -> bytes:
        if path == raw.outputs:
            raise AssertionError("oversized member was read before stat rejection")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", reject_if_oversized_read)
    with pytest.raises(E3ArtifactExportError, match="per-file size ceiling"):
        export_e3_artifacts(
            result=_result(),
            authority_grant=approved_grant,
            bindings=bindings,
            raw_members=raw,
            artifact_root=tmp_path / "artifacts",
        )


def test_atomic_publish_race_preserves_concurrent_destination_and_removes_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approved_grant
) -> None:
    import poi_mpp.reporting.e3_artifacts as exporter

    raw = _raw_members(tmp_path / "raw")
    output = tmp_path / "artifacts"
    original_rename = exporter._rename_noreplace

    def race(staging: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "concurrent-owner.txt").write_text("preserve me", encoding="utf-8")
        original_rename(staging, destination)

    monkeypatch.setattr(exporter, "_rename_noreplace", race)
    with pytest.raises(E3ArtifactExportError, match="already exists|no-replace"):
        export_e3_artifacts(
            result=_result(),
            authority_grant=approved_grant,
            bindings=_bindings(raw, approved_grant),
            raw_members=raw,
            artifact_root=output,
        )
    assert (output / "concurrent-owner.txt").read_text() == "preserve me"
    assert not tuple(tmp_path.glob(".artifacts.staging-*"))
