# Algorithm A3 — VerifySPAIEvent / VerifyIntelligence

## Inputs

`Task, C_P, C_T, C_M, C_R, R_X, R_E, AuditRoot, DA_Cert, Nullifier, ReceiptState`

## Output

`ACCEPT | ABSTAIN | REJECT`

## Algorithm

```text
1. require ActivePolicy(C_P)
2. require ValidTask(C_T)
3. require Finalized(C_R) before audit seed reveal
4. recompute (S_X, S_S) = AuditCompiler(...)
5. verify model/runtime binding
6. verify required execution audit openings or mature dispute result
7. verify IEC semantic obligations
8. compute LCB score and disagreement
9. if undefined semantics OR invalid calibration OR disagreement > gamma:
       return ABSTAIN
10. verify DA certificate, nullifier, deadlines, retention state
11. if any hard predicate fails:
       return REJECT
12. return ACCEPT
```

## Scientific interpretation

The algorithm verifies **task-conditioned operational competence**. It does not prove universal semantic truth.
