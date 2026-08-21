# Task 17 — E6 Sybil and task-budget economics

## Scope

- Added typed E6 Sybil/task-budget scenario, confirmatory-contract, simulation-config, replay, and result-row models in `src/poi_mpp/experiments/e6_sybil.py`.
- Added deterministic E6 reporting helpers for T11, F9, F10, publication precheck, and claim summary in `src/poi_mpp/reporting/e6.py`.
- Replaced the prior toy CSV generator with a fail-closed authority-boundary CLI in `experiments/e6_sybil_economics.py`.
- Added the frozen confirmatory contract in `configs/confirmatory/e6.yaml`.
- Added RED/GREEN coverage in `tests/experiments/test_e6_sybil.py`.

## RED evidence

- Initial RED run: `./.venv/bin/python -m pytest tests/experiments/test_e6_sybil.py -q`
- Observed failure: `ModuleNotFoundError` for `poi_mpp.experiments.e6_sybil` and `poi_mpp.reporting.e6`, confirming the E6 publication-artifact surface was absent before implementation.

## Behavior

- The E6 slice now distinguishes unsafe `IDENTITY_UNIFORM` scheduling from operator-level `CAPACITY_COMMITTED` and `OPERATOR_SLOT` scheduling, with explicit ablations for task-budget-only, collateral-cap, and concentration-cap economics.
- Rows are immutable and hash-bound: every E6 result binds the frozen `RunConfig`, simulation config, scenario material, publication scope, and deterministic result contract hash.
- Publication review is replay-authoritative: summaries revalidate every row, rerun the canonical simulator from the frozen scenario/config snapshot, and require exact closure against the confirmatory contract's allowed scenario ids, hashes, seeds, simulations, origin, scope, authorization scope, and model version.
- Stable operator aggregation preserves safe scheduler flatness under paired seeded runs, so splitting one operator into `1..64` identities does not mint extra safe credit or active weight.
- Unsafe negative controls are retained instead of hidden: identity-uniform scheduling and concentration-cap ablations can still show positive Sybil advantage and are reported as boundary evidence, not folded into support.
- Credit conservation remains exact at the task-budget layer, and collateral-rich zero-credit operators remain at `Q = 0 => W = 0`.
- Cost-to-one-third-weight outputs are explicitly labeled as reproducible simulation economics, not production economic security measurements.

## Authority boundary retained

- E6 publication evidence remains restricted to `REPRODUCIBLE_SIMULATION` under `PUBLICATION_EVIDENCE_AUTHORIZED`.
- `SYNTHETIC_NON_EVIDENCE` remains plumbing-only and cannot satisfy the confirmatory publication path.
- The CLI validates the frozen run config and confirmatory contract, then stops at the publication boundary instead of auto-running or freezing artifacts.

## Verification

- `./.venv/bin/python -m pytest tests/experiments/test_e6_sybil.py -q`
- `./.venv/bin/python -m pytest tests/experiments -q`
- `./.venv/bin/python -m pytest -q`
- `./.venv/bin/python -m compileall src tests experiments`
- `git diff --check`

## Ledger candidate

- Task 17: implementation complete (typed E6 Sybil/task-budget simulator and reporting added; paired-seed operator-level schedulers stay flat across `1..64` identities; publication support now requires canonical replay, confirmatory-contract closure, and exact run authorization binding; unsafe negative controls retained; focused E6 tests PASS, `tests/experiments` PASS, full Python suite PASS, compileall PASS, git diff --check PASS).

## Fix round 1

- Negative-control publication semantics are now evidence-bearing rather than presence-only: the confirmatory contract binds each allowed row's `required_role` and `required_capacity_model`, and publication support additionally requires the split negative-control lower bound to exceed the frozen `epsilon_sybil`.
- Flat safe rows can still exist as valid declared negative controls, but they now keep the summary `INCONCLUSIVE` instead of silently satisfying the negative-control count requirement.
- The old `exact_credit_conservation` flag has been replaced by separate exact accounting invariants:
  - `task_accounting_exact`
  - `credit_issuance_exact`
  - `budget_non_exceedance`
  - `credit_utilization_ratio`
- Result rows now expose allocated and unallocated task-count means and intervals so zero-success runs can satisfy accounting equalities without being misread as full task-budget utilization.

### Additional RED regressions

- Flat contract-bound negative controls with zero advantage remain `INCONCLUSIVE`.
- Zero-success runs preserve exact task accounting and issuance equality while reporting zero utilization.

### Fix-round verification

- `./.venv/bin/python -m pytest tests/experiments/test_e6_sybil.py -q`
- `./.venv/bin/python -m pytest tests/experiments -q`
- `./.venv/bin/python -m pytest -q`
- `./.venv/bin/python -m compileall src tests experiments`
- `git diff --check`
