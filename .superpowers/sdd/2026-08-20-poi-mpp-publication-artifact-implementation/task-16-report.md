# Task 16 — E5 watcher and dispute economics

## Scope

- Added typed E5 watcher/dispute scenario, confirmatory-contract, simulation-config, replay, and result-row models in `src/poi_mpp/experiments/e5_watcher.py`.
- Added deterministic E5 reporting helpers for T10 and invalid-maturity sensitivity in `src/poi_mpp/reporting/e5.py`.
- Replaced the prior toy CSV generator with a fail-closed authority-boundary CLI in `experiments/e5_watcher_economics.py`.
- Added the frozen confirmatory contract in `configs/confirmatory/e5.yaml`.
- Added RED/GREEN coverage in `tests/experiments/test_e5_watcher.py`.

## Behavior

- Exact independent closed forms are available only for fully independent watcher scenarios; correlated outage, shared infrastructure, collusion, bribery/backstop variants, and heterogeneous-cost variants are modeled explicitly and fail closed if callers request the independent formula.
- All probabilities are bounded to `[0, 1]`, all money values use non-negative integer micros, and all scenario counts reject negative, non-finite, or structurally inconsistent inputs.
- Monte Carlo outputs now include `P(no challenge)`, `P(challenge)`, `P(successful challenge)`, `P(challenge failure)`, `P(invalid maturity)`, Wilson intervals, watcher expected utility, bonded-auditor expected utility, and convergence metadata.
- Currency-valued expectations are reported in decimal micros with explicit `MICROS_DECIMAL` labeling rather than lossy floating-point dollars.
- Scenario ledgers retain the declared correlation/failure/bribery/backstop assumptions so the E5 slice stays model-bounded rather than pretending to be a general incentive theorem.
- Publication support is now contract-bound and replay-authoritative: summaries revalidate each row, replay the seeded simulator from the frozen scenario/config snapshot, and require exact closure against the confirmatory contract's allowed scenario ids, scenario hashes, simulations, seeds, origin, scope, and model version.
- Each E5 row now carries a typed frozen `RunConfig` snapshot plus canonical `run_config_hash`, so publication review is bound to the exact authorization scope rather than only to scenario/config hashes.
- Publication precheck now fail-closes before replay when row simulation counts exceed the hard E5 maximum or the active confirmatory-contract replay cap, preventing oversized caller rows from reaching the simulator.
- The CLI validates both the frozen run config and the E5 confirmatory contract, then stops at the explicit publication boundary instead of auto-running or freezing publication artifacts.

## Authority boundary retained

- E5 publication evidence remains restricted to `REPRODUCIBLE_SIMULATION` under `PUBLICATION_EVIDENCE_AUTHORIZED`.
- `SYNTHETIC_NON_EVIDENCE` remains plumbing-only and cannot satisfy the confirmatory publication path.
- The wrapper explicitly refuses to treat the MPP dispute simulator as a production dispute VM or as real execution evidence.

## Verification

- `./.venv/bin/python -m pytest tests/experiments/test_e5_watcher.py -v`
- `./.venv/bin/python -m pytest tests/experiments -q`
- `./.venv/bin/python -m compileall src tests experiments`
- `git diff --check`

## Ledger candidate

- Task 16: fix round 1 complete (added typed watcher/dispute simulation and reporting, enforced independent closed-form boundaries, accounted for failed-challenge bond loss, added bonded-auditor backstop modeling, validated confirmatory scope/CLI authority stop; 7 targeted E5 tests PASS, full `tests/experiments` suite PASS, compileall PASS, git diff --check PASS).
- Task 16: fix round 2 complete (publication support now requires canonical E5 confirmatory scope on every row, homogeneous reproducible-simulation origin, canonical config/scenario contract hashes, and unique scenario identifiers; bribery/subsidy now requires declared colluding recipients when attacker bribes are modeled and preserves subsidy-only noncolluder effects; 10 targeted E5 tests PASS, full `tests/experiments` suite PASS, compileall PASS, git diff --check PASS).
- Task 16: fix round 3 complete (summary authority now replays every row from its frozen `WatcherScenario` and `E5SimulationConfig` snapshot, rows carry canonical result hashes plus full replay inputs, support requires explicit `E5ConfirmatoryContract` closure with exact allowed scenario ids/hashes and fixed seeds, and forged caller outputs fail against canonical replay; 12 targeted E5 tests PASS, full `tests/experiments` suite PASS, compileall PASS, git diff --check PASS).
- Task 16: fix round 4 complete (rows now bind a typed frozen `RunConfig` snapshot and canonical authorization hash, publication support requires exact `PUBLICATION_EVIDENCE_AUTHORIZED` scope on the bound run config, and precheck rejects oversized rows against the hard/global and contract replay caps before any simulator replay; 14 targeted E5 tests PASS, full `tests/experiments` suite PASS, compileall PASS, git diff --check PASS).
