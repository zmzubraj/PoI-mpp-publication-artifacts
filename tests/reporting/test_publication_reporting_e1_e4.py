from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from poi_mpp.reporting.load import PublicationEligibilityError, ReportBuildSpec, load_publication_inputs


REPO_ROOT = Path(
    "/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts"
)
RESULTS_ROOT = REPO_ROOT / "results" / "publication"
CONFIRMATORY_ROOT = REPO_ROOT / "configs" / "confirmatory"


def _copy_fixture(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _artifact_spec(tmp_path: Path, *, sources: dict[str, dict[str, str]]) -> ReportBuildSpec:
    artifact_root = tmp_path / "inputs"
    artifact_root.mkdir(parents=True, exist_ok=True)
    return ReportBuildSpec.model_validate(
        {
            "artifact_root": str(artifact_root.resolve()),
            "output_root": str((tmp_path / "out").resolve()),
            "sources": sources,
        }
    )


def _valid_spec(tmp_path: Path) -> ReportBuildSpec:
    artifact_root = tmp_path / "inputs"
    artifact_root.mkdir(parents=True, exist_ok=True)
    e1_rows = _copy_fixture(
        RESULTS_ROOT / "e1-real-11de165" / "e1_cost_rows.parquet",
        artifact_root / "e1_cost_rows.parquet",
    )
    e2_rows = _copy_fixture(
        RESULTS_ROOT / "e2-real-eb866c2" / "e2_receipt_rows.json",
        artifact_root / "e2_receipt_rows.json",
    )
    e2_summary = _copy_fixture(
        RESULTS_ROOT / "e2-real-eb866c2" / "e2_summary.json",
        artifact_root / "e2_summary.json",
    )
    e4_rows = _copy_fixture(
        RESULTS_ROOT / "e4-11de165" / "e4_rows.json",
        artifact_root / "e4_rows.json",
    )
    e4_summary = _copy_fixture(
        RESULTS_ROOT / "e4-11de165" / "e4_summary.json",
        artifact_root / "e4_summary.json",
    )
    e4_metadata = _copy_fixture(
        RESULTS_ROOT / "e4-11de165" / "e4_metadata.json",
        artifact_root / "e4_metadata.json",
    )
    e5_rows = _copy_fixture(
        RESULTS_ROOT / "e5-11de165" / "e5_rows.json",
        artifact_root / "e5_rows.json",
    )
    e5_contract = _copy_fixture(
        CONFIRMATORY_ROOT / "e5.yaml",
        artifact_root / "e5.yaml",
    )
    e6_rows = _copy_fixture(
        RESULTS_ROOT / "e6-11de165" / "e6_rows.json",
        artifact_root / "e6_rows.json",
    )
    e6_contract = _copy_fixture(
        CONFIRMATORY_ROOT / "e6.yaml",
        artifact_root / "e6.yaml",
    )
    return _artifact_spec(
        tmp_path,
        sources={
            "E1": {"rows_path": e1_rows.name},
            "E2": {"rows_path": e2_rows.name, "summary_path": e2_summary.name},
            "E4": {
                "rows_path": e4_rows.name,
                "summary_path": e4_summary.name,
                "metadata_path": e4_metadata.name,
            },
            "E5": {"rows_path": e5_rows.name, "contract_path": e5_contract.name},
            "E6": {"rows_path": e6_rows.name, "contract_path": e6_contract.name},
        },
    )


def _experiment_map(spec: ReportBuildSpec) -> dict[str, object]:
    return {
        experiment.experiment_id: experiment
        for experiment in load_publication_inputs(spec).experiments
    }


def test_loader_accepts_authoritative_e1_e2_e4_inputs_and_preserves_e5_e6_figure_ownership(tmp_path: Path):
    experiments = _experiment_map(_valid_spec(tmp_path))

    assert experiments["E1"].disposition == "INCONCLUSIVE"
    assert experiments["E1"].scope == "E1_REAL_MODEL_PUBLICATION_V1"
    assert experiments["E1"].summary["measurement_design"] == "FIXED_ORDER_PILOT"
    assert len(experiments["E1"].table_rows) == 6
    assert all(row["is_warmup"] is False for row in experiments["E1"].table_rows)
    assert any(row["is_warmup"] for row in experiments["E1"].figure_points)

    assert experiments["E2"].disposition == "INCONCLUSIVE"
    assert experiments["E2"].scope == "E2_REAL_MODEL_PUBLICATION_V1"
    assert experiments["E2"].summary["measurement_design"] == "NARROW_SCOPE_PILOT"
    assert experiments["E2"].summary["claim_disposition"] == "INCONCLUSIVE"

    assert experiments["E3"].disposition == "WAITING_EXTERNAL"
    assert experiments["E3"].omission_reason == "WAITING_EXTERNAL_EVALUATOR_AUTHORITY"

    assert experiments["E4"].disposition == "INCONCLUSIVE"
    assert experiments["E4"].scope == "E4_CONFIRMATORY_PUBLICATION_V1"
    assert experiments["E4"].summary["claim_disposition"] == "INCONCLUSIVE"
    assert experiments["E4"].summary["claim_target"] == "ATTACK_DETECTION"
    assert experiments["E4"].config_hash == "1639574c9328a6c2afb01c0b57807a28dcf9e5639d144664e31a6cc56c8ed2be"

    assert experiments["E5"].table_ids == ("T10",)
    assert experiments["E5"].figure_ids == ()
    assert experiments["E6"].table_ids == ("T11",)
    assert experiments["E6"].figure_ids == ("F9", "F10")


def test_loader_rejects_tampered_e2_summary_method_boundary(tmp_path: Path):
    spec = _valid_spec(tmp_path)
    summary_path = Path(spec.artifact_root) / "e2_summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["measurement_design"] = "COUNTERBALANCED_PAIRED"
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicationEligibilityError, match="NARROW_SCOPE_PILOT"):
        load_publication_inputs(spec)


def test_loader_rejects_tampered_e4_metadata_method_boundary(tmp_path: Path):
    spec = _valid_spec(tmp_path)
    metadata_path = Path(spec.artifact_root) / "e4_metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["method_boundary"] = "EXECUTED_RECONSTRUCTION"
    metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicationEligibilityError, match="DECLARED_OUTCOME_PLAYBACK"):
        load_publication_inputs(spec)


def test_loader_rejects_tampered_e1_warmup_pair_contract(tmp_path: Path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    spec = _valid_spec(tmp_path)
    rows_path = Path(spec.artifact_root) / "e1_cost_rows.parquet"
    rows = pq.read_table(rows_path).to_pylist()
    warmup_rows = [row for row in rows if row["is_warmup"]]
    assert warmup_rows
    dropped_variant = warmup_rows[0]["variant"]
    rewritten_rows = [
        row
        for row in rows
        if not (
            row["is_warmup"]
            and row["pair_id"] == warmup_rows[0]["pair_id"]
            and row["variant"] == dropped_variant
        )
    ]
    pq.write_table(pa.Table.from_pylist(rewritten_rows), rows_path)

    with pytest.raises(PublicationEligibilityError, match="warmup pair"):
        load_publication_inputs(spec)


@pytest.mark.parametrize(
    ("experiment_id", "path_name", "mutator", "expected_message"),
    [
        (
            "E1",
            "e1_cost_rows.parquet",
            "wrong_experiment_id",
            "E1 rows.experiment_id must equal E1",
        ),
        (
            "E1",
            "e1_cost_rows.parquet",
            "mixed_run",
            "E1 rows.run_id must be singular",
        ),
        (
            "E2",
            "e2_receipt_rows.json",
            "wrong_experiment_id",
            "E2 rows.experiment_id must equal E2",
        ),
        (
            "E2",
            "e2_receipt_rows.json",
            "mixed_run",
            "E2 rows.run_id must be singular",
        ),
        (
            "E4",
            "e4_rows.json",
            "wrong_experiment_id",
            "E4 rows.experiment_id must equal E4",
        ),
        (
            "E4",
            "e4_rows.json",
            "mixed_run",
            "E4 rows.run_id must be singular",
        ),
    ],
)
def test_loader_rejects_identity_and_run_boundary_tamper(
    tmp_path: Path,
    experiment_id: str,
    path_name: str,
    mutator: str,
    expected_message: str,
):
    import pyarrow as pa
    import pyarrow.parquet as pq

    spec = _valid_spec(tmp_path)
    path = Path(spec.artifact_root) / path_name
    if path.suffix == ".parquet":
        rows = pq.read_table(path).to_pylist()
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["rows"] if isinstance(payload, dict) and "rows" in payload else payload
    assert rows
    if mutator == "wrong_experiment_id":
        rows[0]["experiment_id"] = "WRONG"
    elif mutator == "mixed_run":
        rows[0]["run_id"] = "run-mismatch"
    else:
        raise AssertionError(f"unknown mutator: {mutator}")
    if path.suffix == ".parquet":
        pq.write_table(pa.Table.from_pylist(rows), path)
    else:
        path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicationEligibilityError, match=expected_message):
        load_publication_inputs(spec)


def test_loader_marks_e2_missing_when_summary_path_is_unconfigured(tmp_path: Path):
    artifact_root = tmp_path / "inputs"
    artifact_root.mkdir(parents=True, exist_ok=True)
    e2_rows = _copy_fixture(
        RESULTS_ROOT / "e2-real-eb866c2" / "e2_receipt_rows.json",
        artifact_root / "e2_receipt_rows.json",
    )
    spec = _artifact_spec(
        tmp_path,
        sources={
            "E2": {"rows_path": e2_rows.name},
        },
    )

    experiment = _experiment_map(spec)["E2"]

    assert experiment.disposition == "MISSING"
    assert experiment.omission_reason == "missing E2 rows_path or summary_path"
