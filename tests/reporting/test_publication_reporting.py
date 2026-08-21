from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.experiments.e7_evm import (
    default_measurement_contract,
    load_default_parity_attachment,
    parse_foundry_measurement_report,
)
from poi_mpp.reporting.load import PublicationEligibilityError, ReportBuildSpec
from poi_mpp.reporting.manifest import build_publication_report, validate_existing_manifest
from tests.experiments.test_e7_evm import _contracts_root, _measurement, _run_config, _write_report
from tests.experiments.test_e8_consensus import _publication_rows, _write_contract


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _read_manifest(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    from poi_mpp.reporting.manifest import _manifest_self_digest

    payload["self_digest"] = ""
    payload["self_digest"] = _manifest_self_digest(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _base_spec(tmp_path: Path, *, artifact_root: Path | None = None, output_root: Path | None = None) -> ReportBuildSpec:
    return ReportBuildSpec.model_validate(
        {
            "artifact_root": str((artifact_root or (tmp_path / "inputs")).resolve()),
            "output_root": str((output_root or (tmp_path / "out")).resolve()),
            "sources": {},
        }
    )


def _valid_e8_spec(tmp_path: Path) -> ReportBuildSpec:
    artifact_root = tmp_path / "inputs"
    artifact_root.mkdir(parents=True)
    rows = _publication_rows()
    rows_path = _write_json(
        artifact_root / "e8_rows.json",
        {"rows": [row.model_dump(mode="json") for row in rows]},
    )
    contract = _write_contract(tmp_path, rows)
    contract_path = artifact_root / "e8_contract.yaml"
    contract_path.write_text((tmp_path / "e8.contract.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return ReportBuildSpec.model_validate(
        {
            "artifact_root": str(artifact_root.resolve()),
            "output_root": str((tmp_path / "out").resolve()),
            "sources": {
                "E8": {
                    "rows_path": str(rows_path.resolve()),
                    "contract_path": str(contract_path.resolve()),
                }
            },
        }
    )


def _valid_live_e7_spec(tmp_path: Path) -> ReportBuildSpec:
    artifact_root = tmp_path / "inputs"
    artifact_root.mkdir(parents=True)
    run_config_path = _write_json(
        artifact_root / "e7_run_config.json",
        _run_config(run_id="run-e7-live-reporting").model_dump(mode="json"),
    )
    return ReportBuildSpec.model_validate(
        {
            "artifact_root": str(artifact_root.resolve()),
            "output_root": str((tmp_path / "out").resolve()),
            "sources": {
                "E7": {
                    "run_config_path": str(run_config_path.resolve()),
                    "contracts_root": str(_contracts_root().resolve()),
                }
            },
        }
    )


def test_report_rejects_manual_or_synthetic_measurement(tmp_path: Path):
    artifact_root = tmp_path / "inputs"
    artifact_root.mkdir()
    rows = [row.model_copy(update={"origin": EvidenceOrigin.SYNTHETIC_NON_EVIDENCE}) for row in _publication_rows()]
    rows_path = _write_json(
        artifact_root / "e8_rows.json",
        {"rows": [row.model_dump(mode="json") for row in rows]},
    )
    _write_contract(tmp_path, rows)
    contract_path = artifact_root / "e8_contract.yaml"
    contract_path.write_text((tmp_path / "e8.contract.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    spec = ReportBuildSpec.model_validate(
        {
            "artifact_root": str(artifact_root.resolve()),
            "output_root": str((tmp_path / "out").resolve()),
            "sources": {
                "E8": {
                    "rows_path": str(rows_path.resolve()),
                    "contract_path": str(contract_path.resolve()),
                }
            },
        }
    )

    with pytest.raises(PublicationEligibilityError):
        build_publication_report(spec)


def test_same_inputs_produce_identical_outputs(tmp_path: Path):
    spec_a = _valid_e8_spec(tmp_path / "a")
    spec_b = _valid_e8_spec(tmp_path / "b")

    manifest_a = build_publication_report(spec_a)
    manifest_b = build_publication_report(spec_b)

    files_a = sorted(Path(spec_a.output_root).rglob("*"))
    files_b = sorted(Path(spec_b.output_root).rglob("*"))
    rel_a = [path.relative_to(spec_a.output_root) for path in files_a if path.is_file()]
    rel_b = [path.relative_to(spec_b.output_root) for path in files_b if path.is_file()]
    assert rel_a == rel_b
    for relative_path in rel_a:
        assert (Path(spec_a.output_root) / relative_path).read_bytes() == (
            Path(spec_b.output_root) / relative_path
        ).read_bytes()
    assert manifest_a.generator_source_closure_hash == manifest_b.generator_source_closure_hash


def test_symlink_and_path_escape_are_rejected(tmp_path: Path):
    artifact_root = tmp_path / "inputs"
    artifact_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (artifact_root / "link.json").symlink_to(outside)
    spec = ReportBuildSpec.model_validate(
        {
            "artifact_root": str(artifact_root.resolve()),
            "output_root": str((tmp_path / "out").resolve()),
            "sources": {"E8": {"rows_path": str(artifact_root / "link.json"), "contract_path": str(outside)}},
        }
    )
    with pytest.raises(PublicationEligibilityError):
        build_publication_report(spec)


def test_e7_stored_bundle_remains_nonauthoritative(tmp_path: Path):
    artifact_root = tmp_path / "inputs"
    artifact_root.mkdir()
    report = _write_report(
        artifact_root / "e7_report.json",
        measurements=[
            _measurement(item.operation, item.batch_size, 21000 + index, index + 1)
            for index, item in enumerate(default_measurement_contract().expected_measurements)
        ],
    )
    bundle = parse_foundry_measurement_report(
        report_path=report,
        contracts_root=_contracts_root(),
        run_config=_run_config(),
    )
    bundle_path = _write_json(artifact_root / "e7_bundle.json", bundle.model_dump(mode="json"))
    parity = load_default_parity_attachment(Path(__file__).resolve().parents[2])
    _write_json(artifact_root / "e7_parity.json", parity.model_dump(mode="json"))
    spec = ReportBuildSpec.model_validate(
        {
            "artifact_root": str(artifact_root.resolve()),
            "output_root": str((tmp_path / "out").resolve()),
            "sources": {
                "E7": {
                    "bundle_path": str(bundle_path.resolve()),
                    "parity_attachment_path": str((artifact_root / "e7_parity.json").resolve()),
                }
            },
        }
    )

    manifest = build_publication_report(spec)
    claim_matrix = (Path(spec.output_root) / "tables" / "claim_matrix.csv").read_text(encoding="utf-8")
    assert "E7_LOCAL_EVM_BOUNDEDNESS_AND_PARITY" in claim_matrix
    assert "INCONCLUSIVE" in claim_matrix
    assert any(row.artifact_id == "F12" and row.omission_reason for row in manifest.omissions)


def test_e8_inconclusive_is_preserved_and_labeled(tmp_path: Path):
    spec = _valid_e8_spec(tmp_path)
    manifest = build_publication_report(spec)

    t13 = (Path(spec.output_root) / "tables" / "T13_consensus_safety.csv").read_text(encoding="utf-8")
    f11 = (Path(spec.output_root) / "figures" / "F11_consensus_dynamics.svg").read_text(encoding="utf-8")
    claim_matrix = (Path(spec.output_root) / "tables" / "claim_matrix.csv").read_text(encoding="utf-8")
    t4_status = json.loads((Path(spec.output_root) / "tables" / "T4_status.json").read_text(encoding="utf-8"))

    assert "INCONCLUSIVE" in claim_matrix
    assert "REPRODUCIBLE_SIMULATION" in t13
    assert "REPRODUCIBLE_SIMULATION" in f11
    assert any(entry.artifact_id == "T13" for entry in manifest.outputs)
    assert t4_status["artifact_id"] == "T4"
    assert t4_status["disposition"] == "MISSING"


def test_generated_svg_includes_source_hash_caption(tmp_path: Path):
    spec = _valid_e8_spec(tmp_path)
    build_publication_report(spec)
    figure = (Path(spec.output_root) / "figures" / "F11_consensus_dynamics.svg").read_text(encoding="utf-8")
    assert "source_hashes:" in figure


def test_manifest_detects_tamper_and_extra_files(tmp_path: Path):
    spec = _valid_e8_spec(tmp_path)
    build_publication_report(spec)
    table_path = Path(spec.output_root) / "tables" / "T13_consensus_safety.csv"
    table_path.write_text(table_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(PublicationEligibilityError):
        validate_existing_manifest(Path(spec.output_root))

    build_publication_report(spec)
    extra_path = Path(spec.output_root) / "tables" / "unexpected.txt"
    extra_path.write_text("unexpected", encoding="utf-8")
    with pytest.raises(PublicationEligibilityError):
        validate_existing_manifest(Path(spec.output_root))


def test_manifest_detects_input_and_generator_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = _valid_e8_spec(tmp_path)
    build_publication_report(spec)
    rows_path = Path(spec.artifact_root) / "e8_rows.json"
    rows_payload = json.loads(rows_path.read_text(encoding="utf-8"))
    rows_payload["rows"][0]["scenario_id"] = "mutated-scenario"
    rows_path.write_text(json.dumps(rows_payload, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(PublicationEligibilityError, match="input hash mismatch"):
        validate_existing_manifest(Path(spec.output_root))

    spec = _valid_e8_spec(tmp_path / "drift")
    build_publication_report(spec)
    import poi_mpp.reporting.manifest as reporting_manifest

    monkeypatch.setattr(reporting_manifest, "_current_generator_source_closure_hash", lambda: "0" * 64)
    with pytest.raises(PublicationEligibilityError, match="generator source closure drift"):
        validate_existing_manifest(Path(spec.output_root))


def test_manifest_rejects_duplicate_outputs_and_unknown_keys(tmp_path: Path):
    spec = _valid_e8_spec(tmp_path)
    build_publication_report(spec)
    manifest_path = Path(spec.output_root) / "artifact_manifest.json"
    payload = _read_manifest(manifest_path)
    assert isinstance(payload["outputs"], list)
    payload["outputs"].append(dict(payload["outputs"][0]))
    payload["outputs"][-1]["output_id"] = payload["outputs"][0]["output_id"]
    payload["outputs"][-1]["relative_path"] = "tables/duplicate.csv"
    _write_manifest(manifest_path, payload)
    with pytest.raises(PublicationEligibilityError, match="duplicate output ids"):
        validate_existing_manifest(Path(spec.output_root))

    spec = _valid_e8_spec(tmp_path / "unknown")
    build_publication_report(spec)
    manifest_path = Path(spec.output_root) / "artifact_manifest.json"
    payload = _read_manifest(manifest_path)
    payload["unknown_field"] = True
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(Exception):
        validate_existing_manifest(Path(spec.output_root))


def test_output_symlink_root_and_leaf_are_rejected(tmp_path: Path):
    spec = _valid_e8_spec(tmp_path)
    build_publication_report(spec)

    symlink_root = tmp_path / "out-link"
    symlink_root.symlink_to(Path(spec.output_root))
    with pytest.raises(PublicationEligibilityError):
        validate_existing_manifest(symlink_root)

    spec = _valid_e8_spec(tmp_path / "leaf")
    build_publication_report(spec)
    output_root = Path(spec.output_root)
    target = output_root / "figures" / "F11_consensus_dynamics.svg"
    replacement = output_root / "figures" / "replacement.svg"
    replacement.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    target.unlink()
    target.symlink_to(replacement.name)
    with pytest.raises(PublicationEligibilityError):
        validate_existing_manifest(output_root)


def test_manifest_rejects_noncanonical_relative_paths(tmp_path: Path):
    spec = _valid_e8_spec(tmp_path)
    build_publication_report(spec)
    manifest_path = Path(spec.output_root) / "artifact_manifest.json"
    payload = _read_manifest(manifest_path)

    outside = tmp_path / "escape.json"
    outside.write_text('{"rows":[]}', encoding="utf-8")
    payload["inputs"][0]["relative_path"] = "../escape.json"
    payload["inputs"][0]["sha256"] = hashlib.sha256(outside.read_bytes()).hexdigest()
    _write_manifest(manifest_path, payload)
    with pytest.raises(PublicationEligibilityError, match="relative_path"):
        validate_existing_manifest(Path(spec.output_root))

    spec = _valid_e8_spec(tmp_path / "output-escape")
    build_publication_report(spec)
    manifest_path = Path(spec.output_root) / "artifact_manifest.json"
    payload = _read_manifest(manifest_path)
    payload["outputs"][0]["relative_path"] = "../escape.json"
    payload["outputs"][0]["sha256"] = "0" * 64
    _write_manifest(manifest_path, payload)
    with pytest.raises(PublicationEligibilityError):
        validate_existing_manifest(Path(spec.output_root))


@pytest.mark.skipif(not (_contracts_root() / "foundry.toml").is_file(), reason="contracts workspace unavailable")
def test_live_e7_raw_bundle_is_manifested_and_validated(tmp_path: Path):
    spec = _valid_live_e7_spec(tmp_path)
    manifest = build_publication_report(spec)
    validated = validate_existing_manifest(Path(spec.output_root))
    manifest_path = Path(spec.output_root) / "artifact_manifest.json"
    payload = _read_manifest(manifest_path)

    raw_outputs = [item for item in payload["outputs"] if item["artifact_id"] == "RAW_E7_LIVE_BUNDLE"]
    assert len(raw_outputs) == 1
    raw_output = raw_outputs[0]
    assert raw_output["kind"] == "raw"
    assert raw_output["relative_path"] == "raw/E7_live_bundle.json"
    assert raw_output["experiment_id"] == "E7"
    assert raw_output["schema_version"] == "POI_MPP_E7_BUNDLE_V1"
    assert raw_output["run_id"] == "run-e7-live-reporting"
    assert raw_output["config_hash"]
    assert raw_output["source_closure_hash"]
    assert raw_output["derives_to_artifact_ids"] == ["T12", "F12"]
    assert raw_output["derived_from_input_paths"] == ["e7_run_config.json"]
    assert any(entry.artifact_id == "RAW_E7_LIVE_BUNDLE" for entry in manifest.outputs)
    assert any(entry.artifact_id == "RAW_E7_LIVE_BUNDLE" for entry in validated.outputs)


@pytest.mark.skipif(not (_contracts_root() / "foundry.toml").is_file(), reason="contracts workspace unavailable")
def test_live_e7_raw_bundle_tamper_or_removal_invalidates_manifest(tmp_path: Path):
    spec = _valid_live_e7_spec(tmp_path)
    build_publication_report(spec)
    raw_bundle_path = Path(spec.output_root) / "raw" / "E7_live_bundle.json"
    raw_bundle_path.write_text(raw_bundle_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(PublicationEligibilityError):
        validate_existing_manifest(Path(spec.output_root))

    spec = _valid_live_e7_spec(tmp_path / "missing")
    build_publication_report(spec)
    raw_bundle_path = Path(spec.output_root) / "raw" / "E7_live_bundle.json"
    raw_bundle_path.unlink()
    with pytest.raises(PublicationEligibilityError):
        validate_existing_manifest(Path(spec.output_root))


def test_artifact_mapping_covers_t4_t6_t13_and_f5_f12():
    from poi_mpp.reporting.load import ARTIFACT_PLAN, experiment_artifact_ids

    all_artifacts = sorted({artifact_id for experiment_id in ARTIFACT_PLAN for artifact_id in experiment_artifact_ids(experiment_id)})
    assert all_artifacts == ["F10", "F11", "F12", "F5", "F6", "F7", "F8", "F9", "T10", "T11", "T12", "T13", "T4", "T6", "T7", "T8", "T9"]
    assert ARTIFACT_PLAN["E3"]["tables"] == ("T4", "T8")


def test_atomic_write_failure_leaves_no_partial_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = _valid_e8_spec(tmp_path)

    import poi_mpp.reporting.manifest as reporting_manifest

    original = reporting_manifest._atomic_write_bytes

    def failing_atomic_write(path: Path, data: bytes) -> str:
        if path.name == "claim_matrix.csv":
            raise OSError("forced failure")
        return original(path, data)

    monkeypatch.setattr(reporting_manifest, "_atomic_write_bytes", failing_atomic_write)
    with pytest.raises(OSError):
        build_publication_report(spec)
    assert not (Path(spec.output_root) / "tables" / "claim_matrix.csv").exists()
