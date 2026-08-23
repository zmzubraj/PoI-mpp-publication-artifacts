# Final paper algorithms artifact

This file rewrites the existing A1-A5 drafts into manuscript-ready English pseudocode.
It does not add new execution evidence, measured performance, or publication-completion claims.

## Algorithm 1. Single-Pass Auditable Intelligence event

Purpose: define the one-response production event that can later mature into bounded next-epoch authority.

Inputs:

- active policy `C_P`
- task contract `C_T`
- model/runtime manifest `C_M`
- requested model/runtime `M`
- artifact retention and dispute policy

Pseudocode:

```text
1. Execute the requested model exactly once to obtain response y.
2. Build committed execution surface R_X from the trace sidecar.
3. Build committed semantic surface R_E from the Intelligence Evidence Capsule.
4. Build artifact commitment C_A for the retained off-chain bundle.
5. Form response commitment C_R = H(C_T || C_M || H(y) || R_X || R_E || C_A || nonce).
6. Publish C_R together with the required worker bond.
7. Wait until C_R is finalized under the active settlement rule.
8. Derive post-commit audit seed eta from the epoch beacon and C_R.
9. Use the audit compiler to derive execution obligations S_X and semantic obligations S_S.
10. Open only the trace and evidence regions required by S_X and S_S.
11. Run routine execution, semantic, data-availability, and policy checks.
12. If a watcher proves invalid execution or protocol fault, enter the dispute path and slash the losing party.
13. If all hard gates pass, create a candidate receipt in pending state.
14. Keep the receipt non-authoritative until its challenge and retention window closes.
15. If no successful challenge remains, mature the receipt and make it eligible for bounded next-epoch credit.
```

Invariant:

- The concrete audit sample must remain unknown to the worker until `C_R` is final.

Failure states:

- `REJECT` for hard cryptographic, policy, or data-availability failure.
- `ABSTAIN` for unresolved semantic uncertainty or invalid calibration.
- `SLASHED` for proven invalid execution or protocol fault.
- `EXPIRED` for a receipt that never reaches active status under the policy window.

## Algorithm 2. Post-commit audit compiler

Purpose: derive concrete audit obligations only after the response commitment is irreversible.

Inputs:

- active policy root `C_P`
- task contract `C_T`
- finalized response commitment `C_R`
- epoch randomness source
- audit round identifier
- task-family audit policy

Pseudocode:

```text
1. Verify that C_P is active for the current epoch and task family.
2. Verify that C_R is finalized before any concrete sample is derived.
3. Compute eta = H(domain || epoch_beacon || C_T || C_R || audit_round).
4. Derive execution sample set S_X from the task-family execution-audit policy and eta.
5. Derive semantic obligation set S_S from the task-family semantic policy and eta.
6. Bind every selected obligation to C_R so that openings cannot be replayed across tasks.
7. Publish audit identifiers and deadlines without revealing unopened witness data.
8. Return S_X and S_S.
```

Security property:

- The protocol assumes an epoch randomness source that the worker cannot bias after `C_R` is fixed.

## Algorithm 3. Verify one SPAI event

Purpose: decide whether one committed response is accepted, abstained, or rejected for task-conditioned competence.

Inputs:

- active policy `C_P`
- task contract `C_T`
- model/runtime manifest `C_M`
- response commitment `C_R`
- execution root `R_X`
- semantic root `R_E`
- data-availability certificate
- nullifier and receipt state

Output:

- `ACCEPT | ABSTAIN | REJECT`

Pseudocode:

```text
1. Require ActivePolicy(C_P).
2. Require that C_T is valid and belongs to an eligible task family.
3. Require that C_R was finalized before the audit seed was revealed.
4. Recompute S_X and S_S from the active audit compiler.
5. Verify exact model/runtime binding against C_M.
6. Verify the required execution openings or a mature dispute result for S_X.
7. Verify semantic obligations against the committed response and IEC root R_E.
8. Compute the lower-confidence-bound score and the verifier disagreement signal.
9. If semantics are undefined, calibration is invalid, or disagreement exceeds policy threshold gamma, return ABSTAIN.
10. Verify data availability, nullifier uniqueness, deadlines, and receipt-window predicates.
11. If any hard predicate fails, return REJECT.
12. Otherwise return ACCEPT.
```

Interpretation:

- This verifies operational, task-conditioned competence under the active policy. It does not prove universal semantic truth.

## Algorithm 4. Bounded PoI credit and next-epoch weight

Purpose: convert matured receipts into bounded epoch-local authority without allowing stake or identity splitting to mint work.

Inputs:

- matured receipts from epoch `e`
- task-level credit budgets `D_j`
- quality and assurance factors admitted by policy
- worker bonds and concentration caps

Pseudocode:

```text
1. For each matured task j, cap the total allocated credit so that sum_i c_ij <= D_j.
2. Compute each worker allocation c_ij from the precommitted task budget, task-relative quality score, and assurance factor.
3. Aggregate task allocations into epoch-local credit Q_i^(e+1) = sum_j c_ij.
4. Convert epoch-local credit into active weight W_i^(e+1) using bond and concentration caps.
5. Set committee sampling probability proportional to W_i^(e+1).
6. Enforce the invariant Q_i = 0 implies W_i = 0.
```

Boundary:

- Bond and collateral cap authority; they do not create PoI credit on their own.

## Algorithm 5. Optimistic dispute localization

Purpose: resolve a contested execution or protocol fault without making full zkML proof mandatory on the common path.

Preconditions:

- a candidate receipt is still pending
- a watcher has posted a challenge bond
- the disputed interval is committed under the response trace

Pseudocode:

```text
1. Watcher submits a challenge and names the disputed interval.
2. Worker responds with the corresponding interval commitment or opening.
3. Recursively bisect the disagreement until one bounded deterministic step remains.
4. Evaluate the final step in the settlement contract or a minimal dispute VM.
5. If that step is not economically expressible directly, allow a tiny proof for the disputed micro-step only.
6. Slash the losing party and pay the protocol-defined challenge reward to the winner.
7. Update the receipt state accordingly.
```

Boundary:

- This algorithm describes the optimistic dispute target. A minimal implementation may support a simplified dispute surface first and must not be described as full general transformer-kernel bisection unless the code and evidence support it.
