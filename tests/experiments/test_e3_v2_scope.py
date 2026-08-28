from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.experiments.e3_v2_bundle_fixtures import (
    canonical_json_bytes,
    confirmatory_lineage_payload,
    development_report_payload,
    sha256_bytes,
    write_confirmatory_bundle,
    write_development_bundle,
    write_external_calibration_freeze,
    write_external_development_manifest,
)
from poi_mpp.experiments.e3_development import validate_e3_phase3_development_bundle_materials
from poi_mpp.experiments.e3_v2_scope import (
    E3V2ScopeError,
    E3_V2_REQUEST_SCHEMA_VERSION,
    REQUEST_INPUTS,
    build_manifest,
    build_requested_scope,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _canonical_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("self_digest", None)
    return sha256_bytes(canonical_json_bytes(unsigned))


def _write_authority_inputs(tmp_path: Path) -> dict[str, Path]:
    development_bundle = write_development_bundle(tmp_path / "POI_E3_V2_DEVELOPMENT")
    confirmatory_bundle = write_confirmatory_bundle(tmp_path / "POI_E3_V2_CONFIRMATORY")
    development_manifest = write_external_development_manifest(
        tmp_path / "development_dataset_manifest_v2.json"
    )
    materials = validate_e3_phase3_development_bundle_materials(bundle_root=development_bundle)

    report_path = tmp_path / "development_bundle_report.json"
    report_path.write_bytes(canonical_json_bytes(development_report_payload(development_bundle)))
    lineage_path = tmp_path / "confirmatory_freeze_lineage.json"
    lineage_path.write_bytes(
        canonical_json_bytes(confirmatory_lineage_payload(confirmatory_bundle, development_manifest))
    )
    freeze_path = write_external_calibration_freeze(
        tmp_path / "semantic_calibration_freeze.json",
        development_dataset_manifest_hash=materials.dataset_manifest.dataset_manifest_hash(),
        runtime_environment_hash=materials.policy_input_file_hashes["runtime_environment_hash"],
    )
    return {
        "development_report": report_path,
        "confirmatory_lineage": lineage_path,
        "calibration_freeze": freeze_path,
    }


def test_requested_scope_is_the_frozen_c3_v2_contract() -> None:
    scope = build_requested_scope()
    assert scope == {
        "experiment_id": "E3",
        "experiment_generation": "E3_V2",
        "claim_id": "C3",
        "claim_generation": "C3_V2",
        "task_class": "GROUNDED_SEMANTIC_ASSURANCE",
        "metric_scope": ["ABSTAIN", "FAR", "FRR", "calibration", "coverage"],
        "artifact_scope": ["F7", "RAW_E3_EXECUTION", "T4", "T8"],
        "evidence_origin": "REAL_MODEL_EXECUTION",
        "support_rule": {
            "rule_id": "C3_V2_WILSON_SUPPORT_V1",
            "wilson_z_value": "1.959963984540054",
            "far_wilson_upper_bound_max": "0.25",
            "frr_wilson_upper_bound_max": "0.25",
            "coverage_min": "0.50",
            "confirmatory_composition": {"ACCEPT": 200, "REJECT": 200, "ABSTAIN": 100, "total": 500},
        },
    }


def test_build_manifest_binds_material_reports_and_repo_inputs(tmp_path: Path) -> None:
    inputs = _write_authority_inputs(tmp_path)
    development_report = json.loads(inputs["development_report"].read_text(encoding="utf-8"))
    lineage = json.loads(inputs["confirmatory_lineage"].read_text(encoding="utf-8"))

    manifest = build_manifest(
        development_report_path=inputs["development_report"],
        confirmatory_lineage_path=inputs["confirmatory_lineage"],
        calibration_freeze_path=inputs["calibration_freeze"],
    )

    assert manifest["schema_version"] == E3_V2_REQUEST_SCHEMA_VERSION
    assert manifest["status"] == "UNSIGNED_PRE_EXECUTION_SCOPE_REQUEST"
    assert manifest["requested_scope"] == build_requested_scope()
    assert manifest["requested_scope_digest"] == sha256_bytes(
        canonical_json_bytes(build_requested_scope())
    )
    assert manifest["bound_materials"] == {
        "development_bundle_manifest_sha256": development_report["development_bundle_manifest_sha256"],
        "development_dataset_manifest_hash": development_report["development_dataset_manifest_hash"],
        "development_model_manifest_hash": development_report["development_model_manifest_hash"],
        "development_decode_policy_hash": development_report["development_decode_policy_hash"],
        "development_environment_manifest_hash": development_report[
            "development_environment_manifest_hash"
        ],
        "development_policy_inputs_digest": development_report["development_policy_inputs_digest"],
        "confirmatory_freeze_material_lineage_hash": lineage["material_lineage_hash"],
        "confirmatory_dataset_manifest_hash": lineage["lineage"]["dataset_manifest_hash"],
        "confirmatory_development_manifest_hash": lineage["lineage"]["development_manifest_hash"],
        "calibration_freeze_content_hash": json.loads(
            inputs["calibration_freeze"].read_text(encoding="utf-8")
        )["content_hash"],
    }
    assert manifest["bound_materials_digest"] == sha256_bytes(
        canonical_json_bytes(manifest["bound_materials"])
    )
    assert manifest["bound_documents"] == {
        "development_report": inputs["development_report"].resolve().as_posix(),
        "confirmatory_lineage": inputs["confirmatory_lineage"].resolve().as_posix(),
        "calibration_freeze": inputs["calibration_freeze"].resolve().as_posix(),
    }
    assert manifest["result_attestation_status"] == "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION"
    assert manifest["self_digest"] == _canonical_digest(manifest)

    assert manifest["request_input_count"] == len(manifest["request_inputs"])
    assert manifest["request_input_count"] == len(REQUEST_INPUTS)
    for entry in manifest["request_inputs"]:
        artifact = REPO_ROOT / entry["path"]
        assert entry["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert entry["size_bytes"] == artifact.stat().st_size

    second = build_manifest(
        development_report_path=inputs["development_report"],
        confirmatory_lineage_path=inputs["confirmatory_lineage"],
        calibration_freeze_path=inputs["calibration_freeze"],
    )
    assert canonical_json_bytes(second) == canonical_json_bytes(manifest)


def test_build_manifest_rejects_input_documents_that_fail_their_own_contracts(tmp_path: Path) -> None:
    inputs = _write_authority_inputs(tmp_path)

    stale_report = json.loads(inputs["development_report"].read_text(encoding="utf-8"))
    stale_report["development_bundle_manifest_sha256"] = "0" * 64
    inputs["development_report"].write_bytes(canonical_json_bytes(stale_report))
    with pytest.raises(E3V2ScopeError, match="self_digest"):
        build_manifest(
            development_report_path=inputs["development_report"],
            confirmatory_lineage_path=inputs["confirmatory_lineage"],
            calibration_freeze_path=inputs["calibration_freeze"],
        )


def test_build_manifest_rejects_wrong_schema_versions(tmp_path: Path) -> None:
    inputs = _write_authority_inputs(tmp_path)
    report = json.loads(inputs["development_report"].read_text(encoding="utf-8"))
    report["schema_version"] = "POI_MPP_E3_V2_DEVELOPMENT_BUNDLE_REPORT_V0"
    report["self_digest"] = _canonical_digest(report)
    inputs["development_report"].write_bytes(canonical_json_bytes(report))
    with pytest.raises(E3V2ScopeError, match="schema_version"):
        build_manifest(
            development_report_path=inputs["development_report"],
            confirmatory_lineage_path=inputs["confirmatory_lineage"],
            calibration_freeze_path=inputs["calibration_freeze"],
        )


def test_build_manifest_rejects_calibration_freeze_not_bound_to_development_dataset(
    tmp_path: Path,
) -> None:
    inputs = _write_authority_inputs(tmp_path)
    from tests.experiments.e3_v2_bundle_fixtures import calibration_freeze_payload

    unbound = calibration_freeze_payload(
        development_dataset_manifest_hash="f" * 64,
        runtime_environment_hash="e" * 64,
    )
    inputs["calibration_freeze"].write_bytes(canonical_json_bytes(unbound))
    with pytest.raises(E3V2ScopeError, match="calibration freeze is not bound to the development bundle"):
        build_manifest(
            development_report_path=inputs["development_report"],
            confirmatory_lineage_path=inputs["confirmatory_lineage"],
            calibration_freeze_path=inputs["calibration_freeze"],
        )


def test_build_manifest_rejects_unfrozen_calibration_status(tmp_path: Path) -> None:
    inputs = _write_authority_inputs(tmp_path)
    materials = validate_e3_phase3_development_bundle_materials(
        bundle_root=tmp_path / "POI_E3_V2_DEVELOPMENT"
    )
    from tests.experiments.e3_v2_bundle_fixtures import calibration_freeze_payload

    unfrozen = calibration_freeze_payload(
        development_dataset_manifest_hash=materials.dataset_manifest.dataset_manifest_hash(),
        runtime_environment_hash=materials.policy_input_file_hashes["runtime_environment_hash"],
        status="READY_FOR_DATA",
    )
    inputs["calibration_freeze"].write_bytes(canonical_json_bytes(unfrozen))
    with pytest.raises(E3V2ScopeError, match="FROZEN_DEVELOPMENT_ONLY"):
        build_manifest(
            development_report_path=inputs["development_report"],
            confirmatory_lineage_path=inputs["confirmatory_lineage"],
            calibration_freeze_path=inputs["calibration_freeze"],
        )


def test_build_manifest_requires_external_input_files(tmp_path: Path) -> None:
    inputs = _write_authority_inputs(tmp_path)
    inside_repo = REPO_ROOT / "tmp-e3-v2-scope-report-test-only.json"
    inside_repo.write_bytes(inputs["development_report"].read_bytes())
    try:
        with pytest.raises(E3V2ScopeError, match="must live outside the repository"):
            build_manifest(
                development_report_path=inside_repo,
                confirmatory_lineage_path=inputs["confirmatory_lineage"],
                calibration_freeze_path=inputs["calibration_freeze"],
            )
    finally:
        inside_repo.unlink(missing_ok=True)
