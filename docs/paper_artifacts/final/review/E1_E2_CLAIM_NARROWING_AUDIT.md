# E1 and E2 permanent claim-narrowing audit

Status: `CLAIM_NARROWED`

Audit date: 2026-08-24

No new E1 or E2 execution was authorized by a frozen confirmatory design with a
prespecified precision rationale, broader model/task/attack coverage, and an
independent-reproduction contract. The smallest scientifically defensible action
is therefore permanent claim narrowing at the current evidence revision.

## E1 boundary

- Evidence: one 1.5B open-weight model, two paired observations, six measurement
  rows, fixed monotonic order, `REAL_MODEL_EXECUTION`.
- Disposition: `INCONCLUSIVE`.
- Admissible statement: the observed two-run baseline took approximately twice
  the single-execution paths in both recorded pairs.
- Inadmissible statements: general efficiency advantage, model-family advantage,
  hardware-independent speedup, production throughput, or causal savings.
- Reopening condition: a separately frozen counterbalanced paired design,
  prespecified precision/sample rationale, real provenance, and external
  reproduction.

## E2 boundary

- Evidence: one model/task/layer/token surface, one 4x4 tensor product, four
  attacked observations, one honest control, three exact/field checks and one
  empirical floating-point check, `REAL_MODEL_EXECUTION` plus controlled attacks.
- Disposition: `INCONCLUSIVE`.
- Admissible statement: all four tested corruptions were rejected on the frozen
  narrow surface, with the reported wide Wilson interval and no false positive
  in the single control.
- Inadmissible statements: broad soundness, robustness across attacks or models,
  exact floating-point soundness, production detection probability, or general
  adversarial security.
- Reopening condition: a predeclared multi-task/multi-model attack-family design,
  independent replication, explicit exact-versus-empirical semantics, and real
  provenance.

## Reconciled surfaces

The manuscript abstract/results/limitations, T4, T6/F5, T7/F6, claim matrix,
scorecard, submission-readiness audit, limitations/nonclaims table, and external
review packet all retain the same ceiling. Artifact presence, observed ratios,
or 4/4 detection may not promote C1 or C2.

This audit can be superseded only by a later, versioned evidence package that
meets the reopening conditions. Prose edits alone cannot upgrade either claim.
