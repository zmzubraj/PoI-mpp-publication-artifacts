from __future__ import annotations

from pathlib import Path
import subprocess

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


def _write_contract(tmp_path: Path, rows):
    from poi_mpp.experiments.e8_consensus import E8_SIMULATION_MODEL_VERSION, load_e8_confirmatory_contract

    lines = [
        "schema_version: POI_MPP_E8_CONFIRMATORY_CONTRACT_V1",
        "publication_scope: E8_CONFIRMATORY_PUBLICATION_V1",
        "required_run_origin: REPRODUCIBLE_SIMULATION",
        "required_run_authorization_scope: PUBLICATION_EVIDENCE_AUTHORIZED",
        f"required_simulations: {rows[0].simulations}",
        "maximum_replay_simulations: 2048",
        f"required_model_version: {E8_SIMULATION_MODEL_VERSION}",
        f"required_committee_size: {rows[0].committee_size}",
        "required_algorithm_version: POI_MPP_COMMITTEE_SAMPLER_SHA256_NO_REPLACEMENT_V1",
        "required_target_epoch_delta: 1",
        f"minimum_scenario_breadth: {len(rows)}",
        "minimum_negative_controls: 1",
        "minimum_boundary_rows: 1",
        "seed_policy: FIXED_PER_SCENARIO",
        "allowed_scenarios:",
    ]
    for row in rows:
        lines.extend(
            [
                f"  - scenario_id: {row.scenario_id}",
                f"    scenario_contract_hash: {row.scenario_contract_hash}",
                f"    required_role: {row.role.value}",
                f"    required_ablation: {row.ablation.value}",
                f"    required_seed: {row.seed}",
            ]
        )
    lines.extend(["notes:", "  - test contract"])
    path = tmp_path / "e8.contract.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return load_e8_confirmatory_contract(path)


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
    from poi_mpp.reporting.e8 import publication_precheck_reasons, summarize_e8_rows

    baseline = _run_row(scenario=_scenario())
    sybil_split = _run_row(
        scenario=_scenario(
            scenario_id="support-sybil-split",
            ablation="SYBIL_SPLIT",
            worker_bindings=(
                *_scenario().worker_bindings,
                _scenario().worker_bindings[0].model_copy(
                    update={"worker_id": "0x0000000000000000000000000000000000003102"}
                ),
            ),
            task_batches=(
                _scenario().task_batches[0],
                _scenario().task_batches[0].model_copy(
                    update={
                        "task": _task(
                            task_id=4,
                            worker_id="0x0000000000000000000000000000000000003102",
                            credit_budget=90,
                        ),
                        "receipts": (
                            _receipt(
                                receipt_id=4,
                                task_id=4,
                                worker_id="0x0000000000000000000000000000000000003102",
                            ),
                        ),
                    }
                ),
                *_scenario().task_batches[1:],
            ),
        ),
        seed=19,
    )
    uncapped = _run_row(
        scenario=_scenario(
            scenario_id="negative-cap-removed",
            role="NEGATIVE_CONTROL",
            ablation="CONCENTRATION_CAP_REMOVED",
            concentration_cap_micros=10_000,
        ),
        seed=23,
    )
    zero_weight = _run_row(
        scenario=_scenario(
            scenario_id="boundary-zero-total-weight",
            role="BOUNDARY",
            ablation="MISSING_RECEIPTS",
            task_batches=(
                _scenario().task_batches[0].model_copy(
                    update={
                        "receipts": (
                            _receipt(
                                receipt_id=71,
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
        ),
        seed=29,
    )
    rows = [baseline, sybil_split, uncapped, zero_weight]

    assert "confirmatory contract" in publication_precheck_reasons(rows)[0].lower()
    contract = _write_contract(tmp_path, rows)
    assert summarize_e8_rows(rows, contract=contract).claim_disposition == "SUPPORTED"


def test_forged_output_is_rejected_by_publication_replay(tmp_path: Path):
    from poi_mpp.reporting.e8 import summarize_e8_rows

    baseline = _run_row(scenario=_scenario())
    uncapped = _run_row(
        scenario=_scenario(
            scenario_id="negative-cap-removed",
            role="NEGATIVE_CONTROL",
            ablation="CONCENTRATION_CAP_REMOVED",
            concentration_cap_micros=10_000,
        ),
        seed=23,
    )
    zero_weight = _run_row(
        scenario=_scenario(
            scenario_id="boundary-zero-total-weight",
            role="BOUNDARY",
            ablation="MISSING_RECEIPTS",
            task_batches=(
                _scenario().task_batches[0].model_copy(
                    update={
                        "receipts": (
                            _receipt(
                                receipt_id=81,
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
        ),
        seed=29,
    )
    contract = _write_contract(tmp_path, [baseline, uncapped, zero_weight])
    forged = uncapped.model_copy(
        update={
            "attacker_weight_threshold_probability_ge_one_third": 0.999,
            "result_contract_hash": uncapped.result_contract_hash,
        }
    )

    with pytest.raises(ValueError, match="canonical simulator replay"):
        summarize_e8_rows([baseline, forged, zero_weight], contract=contract)


def test_duplicate_scenarios_do_not_inflate_confirmatory_breadth():
    from poi_mpp.reporting.e8 import summarize_e8_rows

    baseline = _run_row(scenario=_scenario())
    duplicate = baseline.model_copy()

    with pytest.raises(ValueError, match="unique scenario_id"):
        summarize_e8_rows([baseline, duplicate])


def test_cli_stops_at_publication_authority_boundary(tmp_path: Path):
    run_config_path = tmp_path / "run.yaml"
    run_config_path.write_text(
        "\n".join(
            [
                "schema_version: POI_MPP_RUN_CONFIG_V1",
                f"schema_hash: \"{approved_schema_hash()}\"",
                "run_id: run-e8-cli",
                "experiment_id: E8",
                "origin: REPRODUCIBLE_SIMULATION",
                "authorization_scope: PUBLICATION_EVIDENCE_AUTHORIZED",
                f"model_hash: \"{'7' * 64}\"",
                f"dataset_hash: \"{'8' * 64}\"",
                "parent_hashes: []",
                "data_availability:",
                "  total_shards: 16",
                "  samples: 8",
                "  replacement: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "./.venv/bin/python",
            "experiments/e8_consensus_weight_sim.py",
            "--run-config",
            str(run_config_path),
            "--confirmatory-contract",
            "configs/confirmatory/e8.yaml",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "publication" in result.stderr.lower()
