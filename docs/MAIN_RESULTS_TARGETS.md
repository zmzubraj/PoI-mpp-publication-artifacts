# Main Results Targets

These are **targets, not achieved results**.

Current status on Sunday, August 23, 2026:

- Task 22 candidate replay is expected to end `INCOMPLETE`
- the current candidate state is expected to be `CANDIDATE_VERIFIED`
- no `results/frozen/<run_id>/MPP_ARTIFACT_COMPLETE` sentinel should exist
- `E1`-`E6` still lack authorized executed publication artifacts in this workspace
- `E8` is now rebuilt through the production publication replay and remains a canonical `REPRODUCIBLE_SIMULATION` surface with current `C8=INCONCLUSIVE`
- Task 21 real replay remains blocked by `WAITING_LOCAL_MODEL_ARTIFACT` and then `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`
- accountable manual review also remains incomplete until a trusted external reviewer signature and allowed-signers registry are supplied
- even with a reviewer record, only `review_basis=INDEPENDENT_DOMAIN_EXPERT_REVIEW` plus a valid detached external signature can satisfy the freeze gate
- any language stronger than the current evidence disposition must stay out of the paper map and candidate bundle

## Primary claims to support

### C1 — Single-pass cost advantage

Evidence target:

`E1 + F5 + T6`

### C2 — Execution audit detects corruption

Evidence target:

`E2 + F6 + T7`

### C3 — Semantic verifier is useful without reputation

Evidence target:

`E3 + F7 + T8`

### C4 — DA gates authority

Evidence target:

`E4 + F8 + T9`

### C5 — Optimistic disputes are economically viable

Evidence target:

`E5 + T10`

### C6 — Sybil splitting does not inflate task credit materially

Evidence target:

`E6 + F9 + T11`

### C7 — EVM normal path is bounded

Evidence target:

`E7 + F12 + T12`

### C8 — Verified work can drive next-epoch consensus weight

Evidence target:

`E8 + F11 + T13`

## Publication rule

If a claim has no generated artifact ID, it should be described as a design claim rather than an experimentally validated result.

If a claim has generated artifacts but the disposition is `NOT_SUPPORTED` or `INCONCLUSIVE`, the paper language must preserve that disposition rather than upgrading it to success, readiness, or production viability.

`MPP_ARTIFACT_COMPLETE` is only a future frozen-bundle marker. It is never valid for an August 23, 2026 `CANDIDATE_VERIFIED` run.
