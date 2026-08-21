from __future__ import annotations

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

    assert "INCONCLUSIVE" in claim_matrix
    assert "REPRODUCIBLE_SIMULATION" in t13
    assert "REPRODUCIBLE_SIMULATION" in f11
    assert any(entry.artifact_id == "T13" for entry in manifest.outputs)


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
