# Experiment Plan

## E1 — Single-pass cost advantage
Compare:
- B0: native single inference
- B1: two-run verification baseline
- MPP: single inference + trace/IEC + sampled audits
Metrics: latency, GPU/CPU time, retained trace bytes, audit time, expected dispute cost.

## E2 — Execution audit soundness
Inject model/trace/tensor corruption after commitment. Sweep audit sampling fractions and Freivalds rounds.
Metrics: detection rate, escape rate, false positive rate, audit cost.

## E3 — Grounded semantic assurance
Use grounded QA items with answer spans and evidence IDs. Inject unsupported/contradictory claims.
Metrics: FAR, FRR, ABSTAIN, evidence support precision/recall, calibration.

## E4 — Data availability gating
Withhold random and targeted shard fractions. Sample k_DA shards from post-commit randomness.
Metrics: empirical miss rate vs theoretical `(1-f)^k` bound; reconstruction success.

## E5 — Watcher/dispute economics
Simulate invalid receipt value, watcher cost, challenge reward, watcher count, and challenge probability.
Metric: P(invalid receipt matures), watcher expected utility.

## E6 — Sybil and task-budget safety
Split one operator into N identities under fixed per-task credit budgets and scheduler variants.
Metrics: expected credit advantage, concentration, cost to acquire 1/3 active weight.

## E7 — EVM boundedness
Measure gas/state for register model, create task, commit response, open challenge, finalize receipt, update credit.

## E8 — Next-epoch PoI consensus simulation
Convert matured receipts from epoch e into Q_i^(e+1), apply collateral cap, sample committees, and test Byzantine-weight scenarios.
