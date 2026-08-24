from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
REPRODUCE = REPO_ROOT / "scripts" / "reproduce.py"
VERIFY_BUNDLE = REPO_ROOT / "scripts" / "verify_bundle.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))
import verify_bundle as verify_module  # noqa: E402
import reproduce as reproduce_module  # noqa: E402
from poi_mpp.experiments.e7_evm import e7_publication_dataset_hash, e7_publication_model_hash  # noqa: E402
from poi_mpp.reporting import manifest as reporting_manifest  # noqa: E402


def _run_python(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON), *argv],
        cwd=str(cwd or REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def _run_candidate_only_reproduce() -> tuple[dict[str, object], Path]:
    completed = _run_python(str(REPRODUCE), "--mode", "candidate-only")
    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    candidate_root = REPO_ROOT / str(payload["candidate_relative_path"])
    assert candidate_root.is_dir()
    return payload, candidate_root


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_full_replay_spec_uses_canonical_e7_input_bindings(tmp_path: Path) -> None:
    context = reproduce_module.RunContext(
        mode="full",
        run_id="test-full-replay",
        head_revision="a" * 40,
        effective_code_revision="a" * 40,
        git_status_fingerprint="b" * 64,
        tracked_dirty_paths=(),
        package_lock_hash=None,
    )

    spec = reproduce_module._report_spec(
        tmp_path,
        context,
        full_mode=True,
        e8_rows_relative_path=None,
        e8_contract_relative_path=None,
    )

    assert spec["sources"]["E1"]["rows_path"] == "results/publication/e1-real-11de165/e1_cost_rows.parquet"
    assert spec["sources"]["E2"]["summary_path"] == "results/publication/e2-real-eb866c2/e2_summary.json"
    config = yaml.safe_load((tmp_path / "inputs" / "e7_run_config.yaml").read_text(encoding="utf-8"))
    assert config["model_hash"] == e7_publication_model_hash()
    assert config["dataset_hash"] == e7_publication_dataset_hash(repo_root=REPO_ROOT)


def _make_publication_manifest(candidate_root: Path, output_paths: list[tuple[str, str, str]]) -> None:
    publication_root = candidate_root / "publication"
    artifact_root = candidate_root / "inputs"
    inputs = []
    outputs = []
    for relative_path, artifact_id, experiment_id in output_paths:
        output_path = publication_root / relative_path
        _write_bytes(output_path, f"{artifact_id}:{experiment_id}\n".encode("utf-8"))
        outputs.append(
            {
                "output_id": relative_path.replace("/", ":"),
                "artifact_id": artifact_id,
                "relative_path": relative_path,
                "sha256": _digest(output_path),
                "kind": relative_path.split("/", 1)[0],
                "experiment_id": experiment_id,
                "origin": "REPRODUCIBLE_SIMULATION" if experiment_id == "E8" else "REAL_MODEL_EXECUTION",
                "disposition": "SUPPORTED",
                "derivation_edge": f"{experiment_id}->{artifact_id}:{relative_path.rsplit('.', 1)[-1]}",
                "omission_reason": None,
                "schema_version": None,
                "run_id": None,
                "config_hash": None,
                "source_closure_hash": None,
                "source_hashes": [],
                "derived_from_input_paths": [],
                "derives_to_artifact_ids": [],
            }
        )
    payload = {
        "schema_version": "POI_MPP_PUBLICATION_REPORT_MANIFEST_V4",
        "artifact_root_relative_path": "../inputs",
        "generator_source_closure_hash": reporting_manifest._current_generator_source_closure_hash(),
        "build_environment_hash": reporting_manifest._current_build_environment_hash(),
        "inputs": inputs,
        "outputs": outputs,
        "omissions": [],
        "self_digest": "",
    }
    payload["self_digest"] = reporting_manifest._manifest_self_digest(payload)
    _write_json(publication_root / "artifact_manifest.json", payload)


def _signature_paths(base: Path) -> tuple[Path, Path, Path]:
    private_key = base / "reviewer_key"
    public_key = base / "reviewer_key.pub"
    allowed_signers = base / "allowed_signers"
    return private_key, public_key, allowed_signers


def _generate_signature_bundle(
    candidate_root: Path,
    *,
    review_payload: dict[str, object],
) -> tuple[Path, Path]:
    sign_root = candidate_root.parent / "external-review"
    sign_root.mkdir(parents=True, exist_ok=True)
    private_key, public_key, allowed_signers = _signature_paths(sign_root)
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
        capture_output=True,
        text=True,
    )
    pubkey = public_key.read_text(encoding="utf-8").strip()
    reviewer_identity = str(review_payload["reviewer_identity"])
    allowed_signers.write_text(f'{reviewer_identity} namespaces="file" {pubkey}\n', encoding="utf-8")
    _write_json(candidate_root / "manual_review.json", review_payload)
    subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(private_key),
            "-n",
            "file",
            str(candidate_root / "manual_review.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    generated_signature = candidate_root / "manual_review.json.sig"
    signature_path = sign_root / "manual_review.json.sig"
    shutil.move(str(generated_signature), str(signature_path))
    return allowed_signers, signature_path


def _signed_review_payload(
    candidate_root: Path,
    *,
    review_basis: str = "INDEPENDENT_DOMAIN_EXPERT_REVIEW",
    review_date: str = "2026-08-23",
    expertise_scope: str | None = "consensus-protocols",
    independence_basis: str | None = "separate-review-chain",
) -> dict[str, object]:
    claim_matrix_path = candidate_root / "claim_support_matrix.json"
    publication_manifest_path = candidate_root / "publication" / "artifact_manifest.json"
    review_handoff_path = candidate_root / "review_handoff" / "EXTERNAL_REVIEW_HANDOFF_MANIFEST.json"
    manifest = _read_json(candidate_root / "manifest.json")
    return {
        "schema_version": "POI_MPP_MANUAL_REVIEW_V1",
        "status": "COMPLETE",
        "reviewer_identity": "independent-reviewer@example.com",
        "review_basis": review_basis,
        "review_date": review_date,
        "expertise_scope": expertise_scope,
        "independence_basis": independence_basis,
        "reviewed_run_id": manifest["run_id"],
        "reviewed_artifact_hashes": {
            "claim_support_matrix.json": _digest(claim_matrix_path),
            "publication/artifact_manifest.json": _digest(publication_manifest_path),
            "review_handoff/EXTERNAL_REVIEW_HANDOFF_MANIFEST.json": _digest(review_handoff_path),
        },
        "checks": {
            "denominator": True,
            "interval": True,
            "negative_results": True,
            "simulation_labeling": True,
            "editability": True,
            "accessibility": True,
            "claim_language": True,
        },
        "conflicts_of_interest": {
            "has_conflict": False,
            "conflict_details": "",
        },
        "required_questions_answered": [f"Q{index}" for index in range(1, 13)],
        "verdict_summary": "The evidence boundary and negative results are preserved.",
    }


def _write_review_handoff_fixture(candidate_root: Path) -> None:
    inputs = (
        "claim_support_matrix.json",
        "publication/artifact_manifest.json",
    )
    entries = []
    for relative_path in inputs:
        source = candidate_root / relative_path
        copy_path = candidate_root / "review_handoff" / "inputs" / relative_path
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        copy_path.write_bytes(source.read_bytes())
        entries.append(
            {
                "path": relative_path,
                "role": "TEST_ONLY_REVIEW_INPUT",
                "sha256": _digest(source),
                "size_bytes": source.stat().st_size,
            }
        )
    payload = {
        "schema_version": "POI_MPP_EXTERNAL_REVIEW_HANDOFF_V1",
        "status": "UNSIGNED_REVIEW_INPUT_ONLY",
        "canonical_publication_manifest_sha256": _digest(candidate_root / "publication" / "artifact_manifest.json"),
        "review_input_count": len(entries),
        "review_inputs": entries,
        "external_gates": {
            "e3_semantic_evaluator_authority": "WAITING_EXTERNAL",
            "independent_domain_expert_review": "WAITING_EXTERNAL",
            "publication_freeze_sentinel": "BLOCKED_UNTIL_EXTERNAL_GATES_CLOSE",
        },
        "authority_boundary": "TEST_ONLY_NON_EVIDENCE",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["self_digest"] = hashlib.sha256(encoded).hexdigest()
    _write_json(candidate_root / "review_handoff" / "EXTERNAL_REVIEW_HANDOFF_MANIFEST.json", payload)


def _build_production_like_complete_candidate(candidate_root: Path) -> tuple[Path, Path, Path]:
    _write_json(candidate_root / "inputs" / "report_spec.json", {"schema_version": "POI_MPP_TEST_FIXTURE_INPUT_V1"})
    _write_json(candidate_root / "inputs" / "task21_local_config.json", {"schema_version": "POI_MPP_TEST_FIXTURE_INPUT_V1"})
    _write_json(candidate_root / "task21" / "task21_blockers.json", {"schema_version": "POI_MPP_TASK21_BLOCKER_CHAIN_V1", "blocker_chain": []})
    _write_json(
        candidate_root / "claim_support_matrix.json",
        {
            "schema_version": "POI_MPP_CLAIM_SUPPORT_MATRIX_V1",
            "claims": _complete_structural_claims(),
        },
    )
    output_paths = [
        ("tables/T6_single_pass_cost.csv", "T6", "E1"),
        ("figures/F5_single_pass_cost.svg", "F5", "E1"),
        ("tables/T7_execution_audit_security.csv", "T7", "E2"),
        ("figures/F6_audit_soundness.svg", "F6", "E2"),
        ("tables/T4_dataset_composition.json", "T4", "E3"),
        ("tables/T8_semantic_verification.csv", "T8", "E3"),
        ("figures/F7_semantic_verification_quality.svg", "F7", "E3"),
        ("tables/T9_data_availability.csv", "T9", "E4"),
        ("figures/F8_da_withholding.svg", "F8", "E4"),
        ("tables/T10_watcher_dispute_economics.csv", "T10", "E5"),
        ("tables/T11_sybil_economics.csv", "T11", "E6"),
        ("figures/F9_sybil_advantage.svg", "F9", "E6"),
        ("figures/F10_economic_security.svg", "F10", "E6"),
        ("tables/T12_evm_boundedness.csv", "T12", "E7"),
        ("figures/F12_evm_gas_state_scaling.svg", "F12", "E7"),
        ("tables/T13_consensus_safety.csv", "T13", "E8"),
        ("figures/F11_consensus_dynamics.svg", "F11", "E8"),
    ]
    _make_publication_manifest(candidate_root, output_paths)
    _write_review_handoff_fixture(candidate_root)
    _write_json(
        candidate_root / "manifest.json",
        {
            "schema_version": "POI_MPP_FREEZE_BUNDLE_V1",
            "bundle_kind": "candidate",
            "bundle_state": "CANDIDATE_VERIFIED",
            "run_id": "fixture-run",
            "repo_root": str(REPO_ROOT),
            "report_relative_path": "verification_report.json",
            "claim_matrix_relative_path": "claim_support_matrix.json",
            "publication_report_relative_path": "publication/artifact_manifest.json",
            "manual_review_relative_path": "manual_review.json",
            "authoritative_inputs": {
                "report_spec_relative_path": "inputs/report_spec.json",
                "task21_config_relative_path": "inputs/task21_local_config.json",
                "task21_blocker_relative_path": "task21/task21_blockers.json",
                "review_handoff_manifest_relative_path": "review_handoff/EXTERNAL_REVIEW_HANDOFF_MANIFEST.json",
            },
            "completeness": "COMPLETE",
            "claim_support_overall": "INCONCLUSIVE",
            "blockers": [],
            "required_experiments": [f"E{index}" for index in range(1, 9)],
            "experiments": _complete_structural_experiments(),
            "manual_review": {
                "status": "COMPLETE",
                "reviewer_identity": "independent-reviewer@example.com",
                "review_date": "2026-08-23",
            },
            "sentinel_present": False,
            "frozen_manifest_relative_path": None,
            "tool_versions": {"python": sys.version.split()[0]},
            "argv_contract": {
                "report_all_build": [str(PYTHON), "scripts/report_all.py", "build", "--spec", "<SPEC>"],
            },
        },
    )
    complete_report = verify_module.VerificationSummary(
        run_id="fixture-run",
        completeness="COMPLETE",
        blockers=(),
        claims={row["claim_id"]: str(row["disposition"]) for row in _complete_structural_claims()},
        sentinel_present=False,
        manual_review_authenticated=True,
        bundle_state="CANDIDATE_VERIFIED",
    )
    _write_json(candidate_root / "verification_report.json", complete_report.model_dump(mode="json"))
    review_payload = _signed_review_payload(candidate_root)
    allowed_signers, signature_path = _generate_signature_bundle(candidate_root, review_payload=review_payload)
    return candidate_root, allowed_signers, signature_path


def _complete_structural_experiments() -> dict[str, dict[str, object]]:
    mapping = {
        "E1": ("T6", "F5"),
        "E2": ("T7", "F6"),
        "E3": ("T4", "T8", "F7"),
        "E4": ("T9", "F8"),
        "E5": ("T10",),
        "E6": ("T11", "F9", "F10"),
        "E7": ("T12", "F12"),
        "E8": ("T13", "F11"),
    }
    origins = {
        "E3": "REAL_MODEL_EXECUTION",
        "E7": "FOUNDRY_MEASUREMENT",
        "E8": "REPRODUCIBLE_SIMULATION",
    }
    return {
        experiment_id: {
            "status": "COMPLETE",
            "required_artifacts": list(required_artifacts),
            "present_artifacts": list(required_artifacts),
            "origin": origins.get(experiment_id, "REAL_MODEL_EXECUTION"),
        }
        for experiment_id, required_artifacts in mapping.items()
    }


def _complete_structural_claims(*, first_disposition: str = "SUPPORTED") -> list[dict[str, object]]:
    mapping = {
        "C1": ("T6", "F5"),
        "C2": ("T7", "F6"),
        "C3": ("T4", "T8", "F7"),
        "C4": ("T9", "F8"),
        "C5": ("T10",),
        "C6": ("T11", "F9", "F10"),
        "C7": ("T12", "F12"),
        "C8": ("T13", "F11"),
    }
    claims: list[dict[str, object]] = []
    for index, (claim_id, required_artifacts) in enumerate(mapping.items()):
        claims.append(
            {
                "claim_id": claim_id,
                "completeness": "COMPLETE",
                "disposition": first_disposition if index == 0 else "SUPPORTED",
                "required_artifacts": list(required_artifacts),
                "present_artifacts": list(required_artifacts),
                "paper_language_status": "MATCHES_EVIDENCE",
                "maturity": "REAL_MODEL_EXECUTION" if claim_id != "C8" else "REPRODUCIBLE_SIMULATION",
            }
        )
    return claims


def _write_structural_report(candidate_root: Path) -> None:
    summary = verify_module.verify_bundle_structure(candidate_root)
    _write_json(candidate_root / "verification_report.json", summary.model_dump(mode="json"))
    summary = verify_module.verify_bundle_structure(candidate_root)
    _write_json(candidate_root / "verification_report.json", summary.model_dump(mode="json"))


def _build_test_only_structural_candidate(
    candidate_root: Path,
    *,
    first_disposition: str = "SUPPORTED",
    include_extra_file: bool = False,
) -> Path:
    _write_json(candidate_root / "inputs" / "report_spec.json", {"schema_version": "TEST_ONLY_NON_EVIDENCE"})
    _write_json(candidate_root / "inputs" / "task21_local_config.json", {"schema_version": "TEST_ONLY_NON_EVIDENCE"})
    _write_json(candidate_root / "task21" / "task21_blockers.json", {"schema_version": "TEST_ONLY_NON_EVIDENCE"})
    _write_json(
        candidate_root / "manual_review.json",
        {
            "schema_version": "POI_MPP_MANUAL_REVIEW_V1",
            "status": "COMPLETE",
            "reviewer_identity": "independent-reviewer@example.com",
            "review_basis": "INDEPENDENT_DOMAIN_EXPERT_REVIEW",
            "review_date": "2026-08-23",
            "expertise_scope": "consensus-protocols",
            "independence_basis": "separate-review-chain",
            "reviewed_run_id": "fixture-run",
            "reviewed_artifact_hashes": {},
            "checks": {
                "denominator": True,
                "interval": True,
                "negative_results": True,
                "simulation_labeling": True,
                "editability": True,
                "accessibility": True,
                "claim_language": True,
            },
            "conflicts_of_interest": {
                "has_conflict": False,
                "conflict_details": "",
            },
        },
    )
    _write_json(
        candidate_root / "claim_support_matrix.json",
        {
            "schema_version": "POI_MPP_CLAIM_SUPPORT_MATRIX_V1",
            "claims": _complete_structural_claims(first_disposition=first_disposition),
        },
    )
    _write_json(candidate_root / "publication" / "artifact_manifest.json", {"schema_version": "TEST_ONLY_NON_EVIDENCE"})
    _write_review_handoff_fixture(candidate_root)
    _write_json(
        candidate_root / "manifest.json",
        {
            "schema_version": "POI_MPP_FREEZE_BUNDLE_V1",
            "bundle_kind": "candidate",
            "bundle_state": "CANDIDATE_VERIFIED",
            "run_id": "fixture-run",
            "repo_root": str(REPO_ROOT),
            "report_relative_path": "verification_report.json",
            "claim_matrix_relative_path": "claim_support_matrix.json",
            "publication_report_relative_path": "publication/artifact_manifest.json",
            "manual_review_relative_path": "manual_review.json",
            "authoritative_inputs": {
                "report_spec_relative_path": "inputs/report_spec.json",
                "task21_config_relative_path": "inputs/task21_local_config.json",
                "task21_blocker_relative_path": "task21/task21_blockers.json",
                "review_handoff_manifest_relative_path": "review_handoff/EXTERNAL_REVIEW_HANDOFF_MANIFEST.json",
            },
            "completeness": "COMPLETE",
            "claim_support_overall": "INCONCLUSIVE",
            "blockers": [],
            "required_experiments": [f"E{index}" for index in range(1, 9)],
            "experiments": _complete_structural_experiments(),
            "manual_review": {
                "status": "COMPLETE",
                "reviewer_identity": "independent-reviewer@example.com",
                "review_date": "2026-08-23",
            },
            "sentinel_present": False,
            "frozen_manifest_relative_path": None,
            "tool_versions": {"python": sys.version.split()[0]},
            "argv_contract": {
                "report_all_build": [str(PYTHON), "scripts/report_all.py", "build", "--spec", "<SPEC>"],
            },
        },
    )
    _write_json(candidate_root / "verification_report.json", verify_module.VerificationSummary(
        run_id="fixture-run",
        completeness="INCOMPLETE",
        blockers=(),
        claims={},
        sentinel_present=False,
        manual_review_authenticated=False,
        bundle_state="CANDIDATE_VERIFIED",
    ).model_dump(mode="json"))
    _write_structural_report(candidate_root)
    if include_extra_file:
        (candidate_root / "reviewer-extra.txt").write_text("extra\n", encoding="utf-8")
    return candidate_root


def test_reproduce_current_workspace_is_incomplete_and_writes_no_frozen_sentinel() -> None:
    payload, candidate_root = _run_candidate_only_reproduce()
    assert payload["status"] == "INCOMPLETE"
    manifest = _read_json(candidate_root / "manifest.json")
    assert manifest["completeness"] == "INCOMPLETE"
    blockers = "\n".join(str(item) for item in payload["blockers"])
    assert "WAITING_EXTERNAL_EVALUATOR_AUTHORITY" in blockers
    assert "WAITING_LOCAL_MODEL_ARTIFACT" not in blockers
    assert "manual scientific review record is absent" in blockers
    assert "results/tmp/candidates" in payload["candidate_relative_path"]
    assert not any((REPO_ROOT / "results" / "frozen").glob("*/MPP_ARTIFACT_COMPLETE"))


def test_structural_checker_preserves_negative_claims_when_complete(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate", first_disposition="NOT_SUPPORTED")
    summary = verify_module.verify_bundle_structure(candidate_root)
    assert summary.completeness == "COMPLETE"
    assert summary.claims["C1"] == "NOT_SUPPORTED"


def test_production_verifier_rejects_test_only_promotion_and_forged_complete(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    frozen_root = tmp_path / "frozen"
    completed = _run_python(
        str(VERIFY_BUNDLE),
        "--bundle-root",
        str(candidate_root),
        "--promote-to-frozen",
        "--frozen-root",
        str(frozen_root),
    )
    assert completed.returncode != 0
    assert "TEST_ONLY_NON_EVIDENCE" in completed.stdout
    assert not any(frozen_root.glob("*/MPP_ARTIFACT_COMPLETE"))


def test_structural_checker_rejects_extra_file(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate", include_extra_file=True)
    summary = verify_module.verify_bundle_structure(candidate_root)
    assert summary.completeness == "INCOMPLETE"
    assert "unexpected files" in "\n".join(summary.blockers)


def test_production_verifier_rejects_unsigned_manual_review(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    loader = verify_module._load_bundle(candidate_root, allow_test_only=True)
    reasons, authenticated = verify_module._validate_manual_review(
        loader,
        allowed_signers_path=None,
        signature_path=None,
    )
    assert not authenticated
    assert "manual scientific review signature is absent" in "\n".join(reasons)


def test_manual_review_runtime_accepts_published_schema_fields(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    payload = _signed_review_payload(candidate_root)
    record = verify_module.ManualReviewRecord.model_validate(payload)
    assert record.conflicts_of_interest is not None
    assert record.conflicts_of_interest.has_conflict is False
    assert record.required_questions_answered == tuple(f"Q{index}" for index in range(1, 13))


def test_qualifying_manual_review_rejects_declared_conflict(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    review_payload = _signed_review_payload(candidate_root)
    review_payload["conflicts_of_interest"] = {
        "has_conflict": True,
        "conflict_details": "Producer-chain financial relationship",
    }
    allowed_signers, signature_path = _generate_signature_bundle(candidate_root, review_payload=review_payload)
    bundle = verify_module._load_bundle(candidate_root, allow_test_only=True)
    reasons, authenticated = verify_module._validate_manual_review(
        bundle,
        allowed_signers_path=allowed_signers,
        signature_path=signature_path,
    )
    assert not authenticated
    assert "no conflict of interest" in "\n".join(reasons)


def test_manual_review_requires_hash_bound_review_handoff(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    review_payload = _signed_review_payload(candidate_root)
    review_payload["reviewed_artifact_hashes"].pop(
        "review_handoff/EXTERNAL_REVIEW_HANDOFF_MANIFEST.json"
    )
    allowed_signers, signature_path = _generate_signature_bundle(candidate_root, review_payload=review_payload)
    bundle = verify_module._load_bundle(candidate_root, allow_test_only=True)
    reasons, authenticated = verify_module._validate_manual_review(
        bundle,
        allowed_signers_path=allowed_signers,
        signature_path=signature_path,
    )
    assert not authenticated
    assert "review_handoff/EXTERNAL_REVIEW_HANDOFF_MANIFEST.json" in "\n".join(reasons)


def test_structural_checker_rejects_tampered_review_handoff_input(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    staged_input = candidate_root / "review_handoff" / "inputs" / "claim_support_matrix.json"
    staged_input.write_text("{}\n", encoding="utf-8")
    with pytest.raises(verify_module.BundleVerificationError, match="handoff (size|hash) mismatch"):
        verify_module.verify_bundle_structure(candidate_root)


@pytest.mark.parametrize(
    ("review_basis", "review_date", "expertise_scope", "independence_basis", "expected_fragment"),
    (
        ("INDEPENDENT_DOMAIN_EXPERT_REVIEW", "2026/08/23", "consensus-protocols", "separate-review-chain", "strict ISO"),
        ("INDEPENDENT_DOMAIN_EXPERT_REVIEW", "2026-08-24", "consensus-protocols", "separate-review-chain", "must not be in the future"),
        ("self-review", "2026-08-23", "consensus-protocols", "separate-review-chain", "review_basis must be one of"),
        ("AI_REVIEW", "2026-08-23", "consensus-protocols", "separate-review-chain", "review_basis must be one of"),
        ("INDEPENDENT_DOMAIN_EXPERT_REVIEW", "2026-08-23", None, "separate-review-chain", "expertise_scope"),
        ("INDEPENDENT_DOMAIN_EXPERT_REVIEW", "2026-08-23", "consensus-protocols", None, "independence_basis"),
    ),
)
def test_manual_review_real_signature_regressions(
    tmp_path: Path,
    review_basis: str,
    review_date: str,
    expertise_scope: str | None,
    independence_basis: str | None,
    expected_fragment: str,
) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    review_payload = _signed_review_payload(
        candidate_root,
        review_basis=review_basis,
        review_date=review_date,
        expertise_scope=expertise_scope,
        independence_basis=independence_basis,
    )
    allowed_signers, signature_path = _generate_signature_bundle(candidate_root, review_payload=review_payload)
    bundle = verify_module._load_bundle(candidate_root, allow_test_only=True)
    reasons, authenticated = verify_module._validate_manual_review(
        bundle,
        allowed_signers_path=allowed_signers,
        signature_path=signature_path,
    )
    assert not authenticated
    assert expected_fragment in "\n".join(reasons)


def test_production_verifier_rejects_task20_invalid_manifest(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    publication_manifest_path = candidate_root / "publication" / "artifact_manifest.json"
    _write_json(publication_manifest_path, {"schema_version": "POI_MPP_PUBLICATION_REPORT_MANIFEST_V4", "self_digest": "0" * 64})
    completed = _run_python(str(VERIFY_BUNDLE), "--bundle-root", str(candidate_root))
    assert completed.returncode != 0
    assert "artifact manifest" in completed.stdout.lower() or "schema_version" in completed.stdout.lower()


def test_verify_bundle_rejects_symlink_root_on_promotion(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    escaped_root = tmp_path / "escaped"
    escaped_root.symlink_to(candidate_root, target_is_directory=True)
    completed = _run_python(
        str(VERIFY_BUNDLE),
        "--bundle-root",
        str(escaped_root),
        "--promote-to-frozen",
        "--frozen-root",
        str(tmp_path / "frozen"),
    )
    assert completed.returncode != 0
    assert "symlink" in completed.stdout.lower() or "bundle root" in completed.stdout.lower()


def test_reproduce_candidate_report_is_deterministic_and_run_path_matches_returned_run_id() -> None:
    first = _run_python(str(REPRODUCE), "--mode", "candidate-only")
    second = _run_python(str(REPRODUCE), "--mode", "candidate-only")
    assert first.returncode == second.returncode
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload == second_payload
    run_id = first_payload["run_id"]
    assert first_payload["candidate_relative_path"] == f"results/tmp/candidates/{run_id}"
    candidate_root = REPO_ROOT / first_payload["candidate_relative_path"]
    assert candidate_root.is_dir()
    completed = _run_python(str(VERIFY_BUNDLE), "--bundle-root", str(candidate_root))
    assert "report_spec artifact_root is missing" not in completed.stdout


def test_reproduce_candidate_only_integrates_production_e8_as_inconclusive() -> None:
    payload, candidate_root = _run_candidate_only_reproduce()
    manifest = _read_json(candidate_root / "manifest.json")
    claims = _read_json(candidate_root / "claim_support_matrix.json")["claims"]
    assert manifest["authoritative_inputs"]["e8_rows_relative_path"] == "inputs/e8_publication_artifact.json"
    assert manifest["authoritative_inputs"]["e8_contract_relative_path"] == "inputs/configs/confirmatory/e8.yaml"
    assert manifest["experiments"]["E8"]["status"] == "COMPLETE"
    assert manifest["experiments"]["E8"]["present_artifacts"] == ["T13", "F11"]
    c8 = next(row for row in claims if row["claim_id"] == "C8")
    assert c8["completeness"] == "COMPLETE"
    assert c8["disposition"] == "INCONCLUSIVE"
    assert c8["present_artifacts"] == ["T13", "F11"]
    assert "missing experiment evidence: E8" not in "\n".join(str(item) for item in payload["blockers"])
    assert not any((REPO_ROOT / "results" / "frozen").glob("*/MPP_ARTIFACT_COMPLETE"))


@pytest.mark.parametrize(
    ("mutation", "expected_fragment"),
    (
        (("claim_disposition", "SUPPORTED"), "deterministic plan replay"),
        (("plan_hash", "0" * 64), "plan_hash does not match the supplied plan_path"),
        (("origin", "SYNTHETIC_NON_EVIDENCE"), "origin must equal REPRODUCIBLE_SIMULATION"),
    ),
)
def test_production_verifier_rejects_tampered_e8_publication_artifact(
    mutation: tuple[str, object], expected_fragment: str
) -> None:
    _, candidate_root = _run_candidate_only_reproduce()
    bundle = verify_module._load_bundle(candidate_root, allow_test_only=False)
    artifact_path = candidate_root / "inputs" / "e8_publication_artifact.json"
    artifact = _read_json(artifact_path)
    key, value = mutation
    artifact[key] = value
    _write_json(artifact_path, artifact)
    with pytest.raises(verify_module.BundleVerificationError, match=expected_fragment):
        verify_module._revalidate_e8(bundle)
    assert not any((REPO_ROOT / "results" / "frozen").glob("*/MPP_ARTIFACT_COMPLETE"))


def test_production_verifier_rejects_missing_e8_authoritative_artifact() -> None:
    _, candidate_root = _run_candidate_only_reproduce()
    (candidate_root / "inputs" / "e8_publication_artifact.json").unlink()
    completed = _run_python(str(VERIFY_BUNDLE), "--bundle-root", str(candidate_root))
    assert completed.returncode != 0
    assert "unable to open file without following symlinks" in completed.stdout
    assert not any((REPO_ROOT / "results" / "frozen").glob("*/MPP_ARTIFACT_COMPLETE"))


def test_structural_checker_rejects_candidate_sentinel_and_state_contradiction(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    (candidate_root / verify_module.SENTINEL).write_text("sentinel\n", encoding="utf-8")
    summary = verify_module.verify_bundle_structure(candidate_root)
    blockers = "\n".join(summary.blockers)
    assert summary.completeness == "INCOMPLETE"
    assert "unexpected files" in blockers or "sentinel" in blockers


def test_structural_checker_rejects_frozen_state_without_sentinel(tmp_path: Path) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    manifest = _read_json(candidate_root / "manifest.json")
    manifest["bundle_kind"] = "frozen"
    manifest["bundle_state"] = "FROZEN_VERIFIED"
    manifest["sentinel_present"] = True
    _write_json(candidate_root / "manifest.json", manifest)
    report = _read_json(candidate_root / "verification_report.json")
    report["bundle_state"] = "FROZEN_VERIFIED"
    report["sentinel_present"] = True
    _write_json(candidate_root / "verification_report.json", report)
    summary = verify_module.verify_bundle_structure(candidate_root)
    assert summary.completeness == "INCOMPLETE"
    assert "sentinel" in "\n".join(summary.blockers).lower()


def test_promote_bundle_post_reverify_and_sentinel_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate_root, allowed_signers, signature_path = _build_production_like_complete_candidate(tmp_path / "candidate")
    monkeypatch.setattr(verify_module, "_revalidate_e7", lambda bundle: ())
    monkeypatch.setattr(verify_module, "_revalidate_e8", lambda bundle: ())
    frozen_root = tmp_path / "frozen"
    target_root = verify_module.promote_bundle(
        candidate_root,
        frozen_root,
        manual_review_allowed_signers=allowed_signers,
        manual_review_signature=signature_path,
    )
    summary = verify_module.verify_bundle(
        target_root,
        manual_review_allowed_signers=allowed_signers,
        manual_review_signature=signature_path,
    )
    assert summary.completeness == "COMPLETE"
    assert summary.sentinel_present is True
    manifest = _read_json(target_root / "manifest.json")
    report = _read_json(target_root / "verification_report.json")
    assert manifest["bundle_state"] == "FROZEN_VERIFIED"
    assert manifest["sentinel_present"] is True
    assert report["bundle_state"] == "FROZEN_VERIFIED"
    assert report["sentinel_present"] is True

    sentinel_path = target_root / verify_module.SENTINEL
    sentinel_payload = _read_json(sentinel_path)
    sentinel_payload["manifest_sha256"] = "0" * 64
    _write_json(sentinel_path, sentinel_payload)
    tampered = verify_module.verify_bundle(
        target_root,
        manual_review_allowed_signers=allowed_signers,
        manual_review_signature=signature_path,
    )
    assert tampered.completeness == "INCOMPLETE"
    assert "sentinel" in "\n".join(tampered.blockers).lower()


def test_promote_bundle_refuses_existing_target_and_cleans_up_simulated_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate_root = _build_test_only_structural_candidate(tmp_path / "candidate")
    frozen_root = tmp_path / "frozen"
    target_root = frozen_root / "fixture-run"
    target_root.mkdir(parents=True)

    complete_summary = verify_module.VerificationSummary(
        run_id="fixture-run",
        completeness="COMPLETE",
        blockers=(),
        claims={"C1": "NOT_SUPPORTED"},
        sentinel_present=False,
        manual_review_authenticated=True,
        bundle_state="CANDIDATE_VERIFIED",
    )

    monkeypatch.setattr(verify_module, "verify_bundle", lambda *args, **kwargs: complete_summary)

    with pytest.raises(verify_module.BundleVerificationError, match="already exists"):
        verify_module.promote_bundle(candidate_root, frozen_root)

    shutil.rmtree(target_root)
    with pytest.raises(verify_module.BundleVerificationError, match="simulated promotion failure"):
        verify_module.promote_bundle(candidate_root, frozen_root, simulate_failure=True)
    assert not target_root.exists()
