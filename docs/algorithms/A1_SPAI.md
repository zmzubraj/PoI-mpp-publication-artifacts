# Algorithm A1 — Single-Pass Auditable Intelligence (SPAI)

## Purpose

Define the atomic PoI production event.

## Inputs

- task contract `C_T`
- registered model commitment `C_M`
- model/runtime `M`
- policy root `C_P`
- artifact/DA policy

## Steps

```text
1. y, trace, IEC = ExecuteOnce(C_T, C_M, M)
2. R_X = MerkleRoot(trace)
3. R_E = MerkleRoot(IEC)
4. C_A = CommitArtifactBundle(y, IEC, trace openings)
5. C_R = H(C_T || C_M || H(y) || R_X || R_E || C_A || nonce)
6. Publish C_R and required worker bond
7. Finalize C_R
8. eta = H(EpochBeacon || C_T || C_R || audit_round)
9. (S_X, S_S) = AuditCompiler(C_P, C_T, C_R, eta)
10. Open required trace/evidence regions
11. Run execution and semantic audits
12. If invalid evidence is found, enter dispute path
13. If hard gates + semantic threshold + DA + freshness pass, create candidate receipt
14. After challenge/retention window, mature the receipt
15. Convert matured receipt into next-epoch PoI credit
```

## Critical invariant

`C_R` must be irreversible before `eta` can be known to the worker.

## Failure states

- `REJECT` — cryptographic or hard-gate failure.
- `ABSTAIN` — semantic uncertainty/calibration failure.
- `SLASHED` — proven invalid receipt or protocol fault.
- `EXPIRED` — challenge/retention deadline passes without activation.
