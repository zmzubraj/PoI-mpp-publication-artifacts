from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest

from poi_mpp.evidence.config import RunConfig, approved_schema_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.protocol.types import AuditDecision, Receipt, ReceiptState, TaskClass, TaskSpec


def _run_config(
    *,
    run_id: str = "run-e8",
    experiment_id: str = "E8",
    origin: EvidenceOrigin = EvidenceOrigin.REPRODUCIBLE_SIMULATION,
    authorization_scope: str = "PUBLICATION_EVIDENCE_AUTHORIZED",
) -> RunConfig:
    return RunConfig.model_validate(
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": run_id,
            "experiment_id": experiment_id,
            "origin": origin,
            "authorization_scope": authorization_scope,
            "model_hash": "7" * 64,
            "dataset_hash": "8" * 64,
            "parent_hashes": (),
            "data_availability": {
                "total_shards": 16,
                "samples": 8,
                "replacement": False,
            },
        }
    )


def _task(
    *,
    task_id: int,
    worker_id: str,
    epoch: int = 7,
    task_class: TaskClass = TaskClass.CONSENSUS,
    credit_budget: int = 90,
    active: bool = True,
    registered: bool = True,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        task_root=f"0x{task_id:064x}",
        worker_id=worker_id,
        task_class=task_class,
        active=active,
        registered=registered,
        credit_budget=credit_budget,
        epoch=epoch,
        deadline=500,
        commitment_height=120,
        commitment_finality_depth=5,
        challenge_window_blocks=9,
        audit_domain_size=16,
    )


def _receipt(
    *,
    receipt_id: int,
    task_id: int,
    worker_id: str,
    state: ReceiptState = ReceiptState.ACTIVE,
    epoch_issued: int = 7,
    activated_epoch: int | None = 8,
    audit_decision: AuditDecision | None = AuditDecision.ACCEPT,
    audit_accepted: bool = True,
    da_decision: bool | None = True,
    data_availability_passed: bool = True,
    nullifier_suffix: int | None = None,
    challenge_reason: str | None = None,
    slash_reason: str | None = None,
) -> Receipt:
    suffix = receipt_id if nullifier_suffix is None else nullifier_suffix
    return Receipt(
        receipt_id=receipt_id,
        task_id=task_id,
        worker_id=worker_id,
        commitment_hash=f"0x{(10_000 + receipt_id):064x}",
        audit_id=f"0x{(20_000 + receipt_id):064x}",
        state=state,
        epoch_issued=epoch_issued,
        challenge_deadline=640,
        nullifier=f"0x{(30_000 + suffix):064x}",
        audit_decision=audit_decision,
        audit_accepted=audit_accepted,
        da_decision=da_decision,
        data_availability_passed=data_availability_passed,
        activated_epoch=activated_epoch,
        challenge_reason=challenge_reason,
        slash_reason=slash_reason,
    )


def _scenario(**overrides):
    from poi_mpp.experiments.e8_consensus import (
        CommitteeAblation,
        CommitteeScenario,
        CommitteeScenarioRole,
        CommitteeTaskBatch,
        OperatorClass,
        OperatorProfile,
        WorkerBinding,
    )

    attacker_worker = "0x0000000000000000000000000000000000003101"
    honest_worker_one = "0x0000000000000000000000000000000000004101"
    honest_worker_two = "0x0000000000000000000000000000000000004201"
    payload = {
        "scenario_id": "support-honest-baseline",
        "role": CommitteeScenarioRole.SUPPORT,
        "ablation": CommitteeAblation.NONE,
        "committee_size": 2,
        "target_epoch": 8,
        "beta_micros": 10_000,
        "concentration_cap_micros": 120,
        "attacker_operator_ids": ("attacker-1",),
        "operator_profiles": (
            OperatorProfile(
                operator_id="attacker-1",
                operator_class=OperatorClass.ATTACKER,
                collateral_micros=1_200_000,
                compute_cost_micros=700_000,
                compute_subsidy_micros=0,
            ),
            OperatorProfile(
                operator_id="honest-1",
                operator_class=OperatorClass.HONEST,
                collateral_micros=3_000_000,
                compute_cost_micros=0,
                compute_subsidy_micros=0,
            ),
            OperatorProfile(
                operator_id="honest-2",
                operator_class=OperatorClass.HONEST,
                collateral_micros=3_000_000,
                compute_cost_micros=0,
                compute_subsidy_micros=0,
            ),
        ),
        "worker_bindings": (
            WorkerBinding(worker_id=attacker_worker, operator_id="attacker-1"),
            WorkerBinding(worker_id=honest_worker_one, operator_id="honest-1"),
            WorkerBinding(worker_id=honest_worker_two, operator_id="honest-2"),
        ),
        "task_batches": (
            CommitteeTaskBatch(
                task=_task(task_id=1, worker_id=attacker_worker, credit_budget=90),
                receipts=(
                    _receipt(receipt_id=1, task_id=1, worker_id=attacker_worker),
                ),
            ),
            CommitteeTaskBatch(
                task=_task(task_id=2, worker_id=honest_worker_one, credit_budget=90),
                receipts=(
                    _receipt(receipt_id=2, task_id=2, worker_id=honest_worker_one),
                ),
            ),
            CommitteeTaskBatch(
                task=_task(task_id=3, worker_id=honest_worker_two, credit_budget=90),
                receipts=(
                    _receipt(receipt_id=3, task_id=3, worker_id=honest_worker_two),
                ),
            ),
        ),
    }
    payload.update(overrides)
    return CommitteeScenario.model_validate(payload)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _publication_contract_path() -> Path:
    return _repo_root() / "configs/confirmatory/e8.yaml"


def _publication_plan_path() -> Path:
    return _repo_root() / "configs/confirmatory/e8.publication.yaml"


def _copy_publication_bundle(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    plan_path = root / "e8.publication.yaml"
    contract_path = root / "e8.yaml"
    plan_path.write_bytes(_publication_plan_path().read_bytes())
    contract_path.write_bytes(_publication_contract_path().read_bytes())
    return plan_path, contract_path


def _managed_alias_variant(path: Path) -> Path | None:
    text = path.as_posix()
    for canonical_prefix, alias_prefix in (("/private/var", "/var"), ("/private/tmp", "/tmp")):
        alias_root = Path(alias_prefix)
        canonical_root = Path(canonical_prefix)
        try:
            if not os.path.islink(alias_root):
                continue
            if alias_root.resolve(strict=True) != canonical_root.resolve(strict=True):
                continue
        except FileNotFoundError:
            continue
        if text == canonical_prefix:
            return alias_root
        prefix = f"{canonical_prefix}/"
        if text.startswith(prefix):
            return Path(f"{alias_prefix}{text[len(canonical_prefix):]}")
    return None


def _require_managed_alias_path(path: Path) -> Path:
    alias_path = _managed_alias_variant(path)
    if alias_path is None:
        pytest.skip("managed /var or /tmp alias is not present for this tempfile root")
    return alias_path


def _publication_artifact(tmp_path: Path, *, output_name: str = "e8_rows.json"):
    from poi_mpp.experiments.e8_consensus import load_and_run_e8_publication

    return load_and_run_e8_publication(_publication_plan_path(), output_path=tmp_path / output_name)


def _publication_rows(tmp_path: Path | None = None):
    if tmp_path is None:
        tmp_path = Path(tempfile.mkdtemp(prefix="poi-mpp-e8-publication-"))
    return _publication_artifact(tmp_path).rows


def _write_contract(tmp_path: Path, rows):
    from poi_mpp.experiments.e8_consensus import load_e8_confirmatory_contract

    contract_path = tmp_path / "e8.contract.yaml"
    contract_path.write_text(_publication_contract_path().read_text(encoding="utf-8"), encoding="utf-8")
    return load_e8_confirmatory_contract(contract_path)


def _run_row(*, scenario, seed: int = 17, simulations: int = 256, run_config: RunConfig | None = None):
    from poi_mpp.experiments.e8_consensus import E8SimulationConfig, run_committee_scenario

    resolved_run_config = _run_config() if run_config is None else run_config
    return run_committee_scenario(
        run_id=resolved_run_config.run_id,
        experiment_id="E8",
        run_config=resolved_run_config,
        scenario=scenario,
        config=E8SimulationConfig(
            simulations=simulations,
            seed=seed,
            origin=resolved_run_config.origin,
            publication_scope="E8_CONFIRMATORY_PUBLICATION_V1",
        ),
    )


def test_pending_receipt_contributes_no_weight():
    from poi_mpp.experiments.e8_consensus import SamplingDisposition, derive_operator_weights

    scenario = _scenario(
        scenario_id="boundary-pending-only",
        role="BOUNDARY",
        ablation="MISSING_RECEIPTS",
        task_batches=(
            _scenario().task_batches[0].model_copy(
                update={
                    "receipts": (
                        _receipt(
                            receipt_id=41,
                            task_id=1,
                            worker_id="0x0000000000000000000000000000000000003101",
                            state=ReceiptState.PENDING,
                            activated_epoch=None,
                            audit_decision=None,
                            audit_accepted=False,
                            da_decision=None,
                            data_availability_passed=False,
                        ),
                    )
                }
            ),
        ),
    )

    state = derive_operator_weights(scenario)
    assert state.total_active_weight_micros == 0
    assert state.sampling_disposition is SamplingDisposition.ZERO_TOTAL_WEIGHT


def test_same_seed_produces_same_committee_histories():
    first = _run_row(scenario=_scenario())
    second = _run_row(scenario=_scenario())

    assert first.committee_histories == second.committee_histories
    assert first.attacker_weight_threshold_probability_ge_one_third == second.attacker_weight_threshold_probability_ge_one_third


def test_same_epoch_and_service_receipts_do_not_mint_next_epoch_weight():
    from poi_mpp.experiments.e8_consensus import derive_operator_weights

    attacker_worker = "0x0000000000000000000000000000000000003101"
    scenario = _scenario(
        scenario_id="boundary-service-and-same-epoch",
        role="BOUNDARY",
        ablation="CHURN",
        task_batches=(
            _scenario().task_batches[0].model_copy(
                update={
                    "task": _task(
                        task_id=10,
                        worker_id=attacker_worker,
                        task_class=TaskClass.SERVICE,
                        credit_budget=200,
                    ),
                    "receipts": (_receipt(receipt_id=10, task_id=10, worker_id=attacker_worker),),
                }
            ),
            _scenario().task_batches[0].model_copy(
                update={
                    "task": _task(task_id=11, worker_id=attacker_worker, credit_budget=200),
                    "receipts": (
                        _receipt(
                            receipt_id=11,
                            task_id=11,
                            worker_id=attacker_worker,
                            activated_epoch=7,
                        ),
                    ),
                }
            ),
        ),
    )

    state = derive_operator_weights(scenario)
    assert state.total_active_weight_micros == 0


def test_collateral_rich_zero_credit_operator_stays_at_zero_weight():
    row = _run_row(
        scenario=_scenario(
            scenario_id="boundary-zero-credit-rich",
            role="BOUNDARY",
            ablation="COLLATERAL_RICH_ZERO_CREDIT",
            operator_profiles=(
                _scenario().operator_profiles[0].model_copy(update={"collateral_micros": 9_000_000_000}),
                *_scenario().operator_profiles[1:],
            ),
            task_batches=(
                _scenario().task_batches[0].model_copy(
                    update={
                        "receipts": (
                            _receipt(
                                receipt_id=51,
                                task_id=1,
                                worker_id="0x0000000000000000000000000000000000003101",
                                state=ReceiptState.PENDING,
                                activated_epoch=None,
                                audit_decision=None,
                                audit_accepted=False,
                                da_decision=None,
                                data_availability_passed=False,
                            ),
                        )
                    }
                ),
                *_scenario().task_batches[1:],
            ),
        )
    )

    assert row.attacker_active_weight_micros == 0
    assert row.attacker_active_weight_share == 0.0
    assert row.zero_credit_implies_zero_weight


def test_concentration_cap_ablation_preserves_adverse_result():
    high_collateral_profiles = (
        _scenario().operator_profiles[0].model_copy(update={"collateral_micros": 9_000_000}),
        *_scenario().operator_profiles[1:],
    )
    capped = _run_row(
        scenario=_scenario(
            scenario_id="support-high-compute-capped",
            ablation="HIGH_COMPUTE",
            operator_profiles=high_collateral_profiles,
            task_batches=(
                _scenario().task_batches[0].model_copy(
                    update={
                        "task": _task(
                            task_id=1,
                            worker_id="0x0000000000000000000000000000000000003101",
                            credit_budget=300,
                        )
                    }
                ),
                *_scenario().task_batches[1:],
            ),
        )
    )
    uncapped = _run_row(
        scenario=_scenario(
            scenario_id="negative-high-compute-uncapped",
            role="NEGATIVE_CONTROL",
            ablation="CONCENTRATION_CAP_REMOVED",
            concentration_cap_micros=10_000,
            operator_profiles=high_collateral_profiles,
            task_batches=(
                _scenario().task_batches[0].model_copy(
                    update={
                        "task": _task(
                            task_id=1,
                            worker_id="0x0000000000000000000000000000000000003101",
                            credit_budget=300,
                        )
                    }
                ),
                *_scenario().task_batches[1:],
            ),
        )
    )

    assert uncapped.attacker_weight_threshold_probability_ge_one_third >= capped.attacker_weight_threshold_probability_ge_one_third
    assert uncapped.attacker_active_weight_micros > capped.attacker_active_weight_micros


def test_zero_total_weight_yields_typed_nonterminal_disposition():
    from poi_mpp.experiments.e8_consensus import SamplingDisposition

    row = _run_row(
        scenario=_scenario(
            scenario_id="boundary-zero-total-weight",
            role="BOUNDARY",
            ablation="MISSING_RECEIPTS",
            task_batches=(
                _scenario().task_batches[0].model_copy(
                    update={
                        "receipts": (
                            _receipt(
                                receipt_id=61,
                                task_id=1,
                                worker_id="0x0000000000000000000000000000000000003101",
                                state=ReceiptState.PENDING,
                                activated_epoch=None,
                                audit_decision=None,
                                audit_accepted=False,
                                da_decision=None,
                                data_availability_passed=False,
                            ),
                        )
                    }
                ),
            ),
        )
    )

    assert row.sampling_disposition is SamplingDisposition.ZERO_TOTAL_WEIGHT
    assert row.committee_histories == ()
    assert row.attacker_weight_threshold_probability_ge_one_third is None
    assert row.attacker_weight_threshold_probability_ge_two_thirds is None


def test_publication_support_requires_confirmatory_contract_and_replay_authority(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_confirmatory_contract
    from poi_mpp.reporting.e8 import publication_precheck_reasons, summarize_e8_rows

    rows = _publication_rows(tmp_path)

    assert "confirmatory contract" in publication_precheck_reasons(rows)[0].lower()
    contract = load_e8_confirmatory_contract(_publication_contract_path())
    assert summarize_e8_rows(rows, contract=contract).claim_disposition == "INCONCLUSIVE"


def test_forged_output_is_rejected_by_publication_replay(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_confirmatory_contract
    from poi_mpp.reporting.e8 import summarize_e8_rows

    rows = _publication_rows(tmp_path)
    contract = load_e8_confirmatory_contract(_publication_contract_path())
    negative = next(row for row in rows if row.scenario_id == "negative-cap-removed")
    forged = negative.model_copy(
        update={
            "attacker_weight_threshold_probability_ge_one_third": 0.999,
            "result_contract_hash": negative.result_contract_hash,
        }
    )

    with pytest.raises(ValueError, match="canonical simulator replay"):
        summarize_e8_rows(
            [row if row.scenario_id != "negative-cap-removed" else forged for row in rows],
            contract=contract,
        )


def test_duplicate_scenarios_do_not_inflate_confirmatory_breadth(tmp_path: Path):
    from poi_mpp.reporting.e8 import summarize_e8_rows

    baseline = _publication_rows(tmp_path)[0]
    duplicate = baseline.model_copy()

    with pytest.raises(ValueError, match="unique scenario_id"):
        summarize_e8_rows([baseline, duplicate])


def test_attacker_dominant_support_row_cannot_mint_supported(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_confirmatory_contract
    from poi_mpp.reporting.e8 import summarize_e8_rows

    rows = _publication_rows(tmp_path)
    dominant = _run_row(
        scenario=_scenario(
            scenario_id="support-honest-baseline",
            ablation="NONE",
            concentration_cap_micros=10_000,
            operator_profiles=(
                _scenario().operator_profiles[0].model_copy(update={"collateral_micros": 90_000_000}),
                *_scenario().operator_profiles[1:],
            ),
            task_batches=(
                _scenario().task_batches[0].model_copy(
                    update={"task": _task(task_id=1, worker_id="0x0000000000000000000000000000000000003101", credit_budget=5_000)}
                ),
                _scenario().task_batches[1].model_copy(
                    update={"task": _task(task_id=2, worker_id="0x0000000000000000000000000000000000004101", credit_budget=1)}
                ),
                _scenario().task_batches[2].model_copy(
                    update={"task": _task(task_id=3, worker_id="0x0000000000000000000000000000000000004201", credit_budget=1)}
                ),
            ),
        ),
        seed=17,
    )
    contract = load_e8_confirmatory_contract(_publication_contract_path())
    summary = summarize_e8_rows(
        [dominant if row.scenario_id == "support-honest-baseline" else row for row in rows],
        contract=contract,
    )

    assert dominant.attacker_active_weight_share > 0.9
    assert dominant.attacker_weight_threshold_probability_ge_one_third == 1.0
    assert summary.claim_disposition == "INCONCLUSIVE"


def test_negative_control_requires_paired_support_exogenous_closure(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_confirmatory_contract
    from poi_mpp.reporting.e8 import summarize_e8_rows

    rows = _publication_rows(tmp_path)
    drifted_negative = _run_row(
        scenario=_scenario(
            scenario_id="negative-cap-removed",
            role="NEGATIVE_CONTROL",
            ablation="CONCENTRATION_CAP_REMOVED",
            concentration_cap_micros=10_000,
            operator_profiles=(
                _scenario().operator_profiles[0].model_copy(update={"collateral_micros": 9_000_000}),
                *_scenario().operator_profiles[1:],
            ),
            task_batches=(
                _scenario().task_batches[0].model_copy(
                    update={"task": _task(task_id=1, worker_id="0x0000000000000000000000000000000000003101", credit_budget=600)}
                ),
                *_scenario().task_batches[1:],
            ),
        ),
        seed=19,
    )
    contract = load_e8_confirmatory_contract(_publication_contract_path())
    summary = summarize_e8_rows(
        [drifted_negative if row.scenario_id == "negative-cap-removed" else row for row in rows],
        contract=contract,
    )

    assert summary.claim_disposition == "INCONCLUSIVE"


def test_loader_rejects_placeholder_hashes_and_incomplete_family_closure(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_confirmatory_contract

    placeholder = tmp_path / "placeholder.yaml"
    placeholder.write_text(
        "\n".join(
            [
                "schema_version: POI_MPP_E8_CONFIRMATORY_CONTRACT_V1",
                "publication_scope: E8_CONFIRMATORY_PUBLICATION_V1",
                "required_run_origin: REPRODUCIBLE_SIMULATION",
                "required_run_authorization_scope: PUBLICATION_EVIDENCE_AUTHORIZED",
                "required_simulations: 256",
                "maximum_replay_simulations: 2048",
                "required_model_version: POI_MPP_E8_SIMULATOR_V1",
                "required_committee_size: 2",
                "required_algorithm_version: POI_MPP_COMMITTEE_SAMPLER_SHA256_NO_REPLACEMENT_V1",
                "required_target_epoch_delta: 1",
                "minimum_scenario_breadth: 10",
                "minimum_negative_controls: 1",
                "minimum_boundary_rows: 3",
                "seed_policy: FIXED_PER_SCENARIO",
                "allowed_scenarios:",
                "  - scenario_id: support-honest-baseline",
                "    scenario_contract_hash: \"1111111111111111111111111111111111111111111111111111111111111111\"",
                "    required_role: SUPPORT",
                "    required_ablation: NONE",
                "    required_seed: 17",
                "    support_assertions:",
                "      max_attacker_active_weight_share: 0.5",
                "      max_attacker_weight_probability_ge_one_third: 0.8",
                "      max_attacker_weight_probability_ge_one_third_upper_bound: 0.85",
                "      max_attacker_weight_probability_ge_two_thirds: 0.1",
                "      max_attacker_weight_probability_ge_two_thirds_upper_bound: 0.15",
                "      max_attacker_seat_probability_ge_one_third: 0.8",
                "      max_attacker_seat_probability_ge_one_third_upper_bound: 0.85",
                "      max_attacker_seat_probability_ge_two_thirds: 0.1",
                "      max_attacker_seat_probability_ge_two_thirds_upper_bound: 0.15",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="placeholder|closure"):
        load_e8_confirmatory_contract(placeholder)


def test_support_assertions_reject_contradictory_caps():
    from poi_mpp.experiments.e8_consensus import E8SupportAssertions

    with pytest.raises(ValueError, match="upper-bound cap must be >=|>=2/3 point cap must be <="):
        E8SupportAssertions(
            max_attacker_active_weight_share=0.45,
            max_attacker_weight_probability_ge_one_third=0.40,
            max_attacker_weight_probability_ge_one_third_upper_bound=0.35,
            max_attacker_weight_probability_ge_two_thirds=0.50,
            max_attacker_weight_probability_ge_two_thirds_upper_bound=0.30,
            max_attacker_seat_probability_ge_one_third=0.40,
            max_attacker_seat_probability_ge_one_third_upper_bound=0.35,
            max_attacker_seat_probability_ge_two_thirds=0.50,
            max_attacker_seat_probability_ge_two_thirds_upper_bound=0.30,
        )


def test_support_assertions_reject_vacuous_caps():
    from poi_mpp.experiments.e8_consensus import E8SupportAssertions

    with pytest.raises(ValueError, match="strictly less than 1.0"):
        E8SupportAssertions(
            max_attacker_active_weight_share=1.0,
            max_attacker_weight_probability_ge_one_third=0.8,
            max_attacker_weight_probability_ge_one_third_upper_bound=0.85,
            max_attacker_weight_probability_ge_two_thirds=0.1,
            max_attacker_weight_probability_ge_two_thirds_upper_bound=0.15,
            max_attacker_seat_probability_ge_one_third=0.8,
            max_attacker_seat_probability_ge_one_third_upper_bound=0.85,
            max_attacker_seat_probability_ge_two_thirds=0.1,
            max_attacker_seat_probability_ge_two_thirds_upper_bound=0.15,
        )


def test_negative_assertions_reject_vacuous_deltas():
    from poi_mpp.experiments.e8_consensus import E8NegativeAssertions

    with pytest.raises(ValueError, match="nonzero|strictly positive"):
        E8NegativeAssertions(
            pair_id="pair",
            paired_support_scenario_id="support-high-compute-capped",
            paired_support_scenario_hash="6a4867c03fe528ddf8f351194ba232afada4a9176be8208f150c7b0f1d3e748c",
            required_pair_exogenous_hash="f7e8c2de1f31e3896dee3293e94461d23260fdbeb1a591c90a883fe85185d0e1",
            min_attacker_active_weight_share_delta=0.0,
            min_attacker_weight_probability_ge_one_third_lower_advantage=0.0,
        )


def test_checked_in_confirmatory_contract_is_nonvacuous_and_current_rows_are_inconclusive(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_confirmatory_contract
    from poi_mpp.reporting.e8 import summarize_e8_rows

    contract = load_e8_confirmatory_contract(_publication_contract_path())
    summary = summarize_e8_rows(_publication_rows(tmp_path), contract=contract)

    assert summary.claim_disposition == "INCONCLUSIVE"


def test_cli_writes_publication_artifact_via_plan_only(tmp_path: Path):
    output_path = tmp_path / "e8_rows.json"

    result = subprocess.run(
        [
            "./.venv/bin/python",
            "experiments/e8_consensus_weight_sim.py",
            "--plan",
            "configs/confirmatory/e8.publication.yaml",
            "--output",
            str(output_path),
        ],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert output_path.is_file()


def test_plan_loader_rejects_scenario_hash_tamper(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_publication_plan

    contract_copy = tmp_path / "e8.yaml"
    plan_copy = tmp_path / "e8.publication.yaml"
    contract_copy.write_text(_publication_contract_path().read_text(encoding="utf-8"), encoding="utf-8")
    payload = _publication_plan_path().read_text(encoding="utf-8").replace(
        "credit_budget: 300",
        "credit_budget: 301",
        1,
    )
    plan_copy.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match="scenario_contract_hash mismatch"):
        load_e8_publication_plan(plan_copy)


def test_plan_loader_rejects_incomplete_family_closure(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_publication_plan

    contract_copy = tmp_path / "e8.yaml"
    plan_copy = tmp_path / "e8.publication.yaml"
    contract_copy.write_text(_publication_contract_path().read_text(encoding="utf-8"), encoding="utf-8")
    lines = _publication_plan_path().read_text(encoding="utf-8").splitlines()
    trimmed = "\n".join(line for line in lines if "boundary-zero-total-weight" not in line) + "\n"
    plan_copy.write_text(trimmed, encoding="utf-8")

    with pytest.raises(ValueError, match="publication scenario closure|close against|Field required"):
        load_e8_publication_plan(plan_copy)


def test_plan_loader_rejects_duplicate_scenario_ids(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_publication_plan

    contract_copy = tmp_path / "e8.yaml"
    plan_copy = tmp_path / "e8.publication.yaml"
    contract_copy.write_text(_publication_contract_path().read_text(encoding="utf-8"), encoding="utf-8")
    payload = _publication_plan_path().read_text(encoding="utf-8").replace(
        "scenario_id: support-sybil-split",
        "scenario_id: support-high-compute-capped",
        1,
    )
    plan_copy.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match="unique scenario_id|publication scenario closure"):
        load_e8_publication_plan(plan_copy)


def test_publication_artifact_loader_replays_instead_of_trusting_status(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_publication_artifact

    output_path = tmp_path / "e8_rows.json"
    artifact = _publication_artifact(tmp_path, output_name=output_path.name)
    payload = artifact.model_dump(mode="json")
    payload["claim_disposition"] = "SUPPORTED"
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="deterministic plan replay"):
        load_e8_publication_artifact(output_path)


def test_publication_artifact_loader_rejects_forged_rows(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_publication_artifact

    output_path = tmp_path / "e8_rows.json"
    artifact = _publication_artifact(tmp_path, output_name=output_path.name)
    payload = artifact.model_dump(mode="json")
    payload["rows"][0]["attacker_active_weight_share"] = 0.99
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="deterministic plan replay|canonical E8 scenario row|result_contract_hash"):
        load_e8_publication_artifact(output_path)


def test_publication_artifact_loader_replays_current_rows(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_publication_artifact

    output_path = tmp_path / "e8_rows.json"
    written = _publication_artifact(tmp_path, output_name=output_path.name)
    loaded = load_e8_publication_artifact(output_path)

    assert loaded.claim_disposition == "INCONCLUSIVE"
    assert loaded.model_dump(mode="json") == written.model_dump(mode="json")


def test_publication_runner_is_byte_identical_across_two_runs(tmp_path: Path):
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    _publication_artifact(tmp_path, output_name=first_path.name)
    _publication_artifact(tmp_path, output_name=second_path.name)

    assert first_path.read_bytes() == second_path.read_bytes()


def test_publication_runner_is_byte_identical_across_two_directories(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_and_run_e8_publication

    left_plan, _ = _copy_publication_bundle(tmp_path / "left")
    right_plan, _ = _copy_publication_bundle(tmp_path / "right")
    left_output = tmp_path / "left" / "rows.json"
    right_output = tmp_path / "right" / "rows.json"

    load_and_run_e8_publication(left_plan, output_path=left_output)
    load_and_run_e8_publication(right_plan, output_path=right_output)

    left_bytes = left_output.read_bytes()
    right_bytes = right_output.read_bytes()
    assert left_bytes == right_bytes
    artifact_text = left_bytes.decode("utf-8")
    assert str((tmp_path / "left").resolve()) not in artifact_text
    assert str((tmp_path / "right").resolve()) not in artifact_text


def test_publication_artifact_loader_replays_from_embedded_snapshots(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_and_run_e8_publication, load_e8_publication_artifact

    plan_path, contract_path = _copy_publication_bundle(tmp_path / "embedded")
    output_path = tmp_path / "embedded" / "rows.json"
    written = load_and_run_e8_publication(plan_path, output_path=output_path)
    plan_path.unlink()
    contract_path.unlink()

    loaded = load_e8_publication_artifact(output_path)

    assert loaded.model_dump(mode="json") == written.model_dump(mode="json")


def test_publication_plan_loader_rejects_symlinked_plan(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_publication_plan

    symlink_path = tmp_path / "linked-plan.yaml"
    symlink_path.symlink_to(_publication_plan_path())

    with pytest.raises(ValueError, match="cannot be symlinked") as excinfo:
        load_e8_publication_plan(symlink_path)
    assert str(symlink_path) not in str(excinfo.value)


def test_publication_runner_rejects_symlinked_output(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_and_run_e8_publication

    real_output = tmp_path / "real.json"
    real_output.write_text("{}", encoding="utf-8")
    symlink_path = tmp_path / "linked-output.json"
    symlink_path.symlink_to(real_output)

    with pytest.raises(ValueError, match="cannot be symlinked"):
        load_and_run_e8_publication(_publication_plan_path(), output_path=symlink_path)


def test_publication_plan_loader_preserves_duplicate_key_reason_without_paths(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_publication_plan

    _, contract_copy = _copy_publication_bundle(tmp_path / "duplicate-key")
    plan_copy = tmp_path / "duplicate-key" / "e8.publication.yaml"
    lines = _publication_plan_path().read_text(encoding="utf-8").splitlines()
    duplicate_index = next(index for index, line in enumerate(lines) if line.startswith("contract_path:"))
    lines.insert(duplicate_index + 1, lines[duplicate_index])
    plan_copy.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        load_e8_publication_plan(plan_copy)

    message = str(excinfo.value)
    assert "E8 publication plan" in message
    assert "duplicate key" in message
    assert str(plan_copy) not in message
    assert str(contract_copy) not in message


def test_publication_artifact_loader_rejects_mismatched_supplied_plan_path(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_and_run_e8_publication, load_e8_publication_artifact

    plan_path, _ = _copy_publication_bundle(tmp_path / "primary")
    output_path = tmp_path / "primary" / "rows.json"
    load_and_run_e8_publication(plan_path, output_path=output_path)

    mismatched_plan_path, _ = _copy_publication_bundle(tmp_path / "secondary")
    plan_lines = mismatched_plan_path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(plan_lines):
        if line.strip().startswith("run_id:"):
            plan_lines[index] = "  run_id: run-e8-publication-v2"
            break
    mismatched_plan_path.write_text("\n".join(plan_lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="does not match the supplied plan_path"):
        load_e8_publication_artifact(output_path, plan_path=mismatched_plan_path)


def test_publication_source_closure_allowlist_covers_runtime_dependencies():
    from poi_mpp.experiments.e8_consensus import (
        _E8_PUBLICATION_SOURCE_RELATIVE_PATHS,
        _e8_publication_source_closure_manifest,
    )

    expected = {
        "src/poi_mpp/evidence/canonical.py",
        "src/poi_mpp/evidence/config.py",
        "src/poi_mpp/evidence/models.py",
        "src/poi_mpp/experiments/e8_consensus.py",
        "src/poi_mpp/protocol/committee.py",
        "src/poi_mpp/protocol/credit.py",
        "src/poi_mpp/protocol/types.py",
        "src/poi_mpp/reporting/e8.py",
        "experiments/e8_consensus_weight_sim.py",
    }
    actual = {path.as_posix() for path in _E8_PUBLICATION_SOURCE_RELATIVE_PATHS}

    assert expected <= actual
    assert set(_e8_publication_source_closure_manifest()) == actual


def test_publication_source_closure_hash_changes_when_dependency_changes(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import (
        _E8_PUBLICATION_SOURCE_RELATIVE_PATHS,
        _e8_publication_source_closure_hash,
    )

    closure_root = tmp_path / "closure-copy"
    for relative_path in _E8_PUBLICATION_SOURCE_RELATIVE_PATHS:
        destination = closure_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((_repo_root() / relative_path).read_bytes())

    before = _e8_publication_source_closure_hash(closure_root)
    target = closure_root / "src/poi_mpp/reporting/e8.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# temporary closure drift\n", encoding="utf-8")
    after = _e8_publication_source_closure_hash(closure_root)

    assert before != after


def test_managed_var_alias_write_and_reload_succeeds(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import (
        load_and_run_e8_publication,
        load_e8_publication_artifact,
    )

    canonical_root = tmp_path / "managed-alias"
    canonical_root.mkdir()
    alias_root = _require_managed_alias_path(canonical_root)
    canonical_plan = canonical_root / "e8.publication.yaml"
    canonical_contract = canonical_root / "e8.yaml"
    canonical_output = canonical_root / "rows.json"
    canonical_plan.write_text(_publication_plan_path().read_text(encoding="utf-8"), encoding="utf-8")
    canonical_contract.write_text(_publication_contract_path().read_text(encoding="utf-8"), encoding="utf-8")

    alias_plan = alias_root / canonical_plan.name
    alias_output = alias_root / canonical_output.name
    written = load_and_run_e8_publication(alias_plan, output_path=alias_output)
    loaded = load_e8_publication_artifact(alias_output)

    assert alias_output.read_bytes() == canonical_output.read_bytes()
    assert loaded.model_dump(mode="json") == written.model_dump(mode="json")
    assert loaded.claim_disposition == "INCONCLUSIVE"


def test_managed_var_alias_rejects_deeper_user_symlink_component(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_publication_plan

    canonical_root = tmp_path / "managed-symlink-component"
    canonical_root.mkdir()
    alias_root = _require_managed_alias_path(canonical_root)
    real_dir = canonical_root / "real"
    real_dir.mkdir()
    canonical_plan = real_dir / "e8.publication.yaml"
    canonical_contract = real_dir / "e8.yaml"
    canonical_plan.write_text(_publication_plan_path().read_text(encoding="utf-8"), encoding="utf-8")
    canonical_contract.write_text(_publication_contract_path().read_text(encoding="utf-8"), encoding="utf-8")
    (canonical_root / "jump").symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(ValueError, match="cannot be symlinked"):
        load_e8_publication_plan(alias_root / "jump" / canonical_plan.name)


def test_managed_var_alias_rejects_symlink_leaf(tmp_path: Path):
    from poi_mpp.experiments.e8_consensus import load_e8_publication_artifact, load_and_run_e8_publication

    canonical_root = tmp_path / "managed-symlink-leaf"
    canonical_root.mkdir()
    alias_root = _require_managed_alias_path(canonical_root)
    canonical_target = canonical_root / "real.json"
    canonical_target.write_text("{}", encoding="utf-8")
    alias_leaf = alias_root / "linked.json"
    (canonical_root / "linked.json").symlink_to(canonical_target)

    with pytest.raises(ValueError, match="cannot be symlinked"):
        load_and_run_e8_publication(_publication_plan_path(), output_path=alias_leaf)
    with pytest.raises(ValueError, match="cannot be symlinked"):
        load_e8_publication_artifact(alias_leaf)
