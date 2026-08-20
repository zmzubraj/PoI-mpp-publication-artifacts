# Algorithm A2 — Post-Commit Audit Compiler

## Purpose

Generate concrete execution and semantic audits only after the response commitment is fixed.

## Inputs

`C_P, C_T, C_R, epoch_beacon, audit_round, task_family`

## Algorithm

```text
1. Verify ActivePolicy(C_P).
2. Verify Finalized(C_R).
3. eta = H(domain || epoch_beacon || C_T || C_R || audit_round)
4. derive computational sample set S_X from task-family audit policy and eta
5. derive semantic obligations S_S from task-family utility policy and eta
6. bind every selected obligation to C_R
7. publish audit identifiers without revealing unopened witness data
8. return S_X, S_S
```

## Security property

The concrete sample is unavailable before `C_R` finalization under the assumed randomness model.

## Complexity target

Audit compilation should be small relative to model inference. Concrete complexity depends on the trace layout and sample generator implementation.
