# Task 22 — Reproduce from a clean environment and freeze the publication bundle

**Status:** DONE_WITH_CONCERNS

## Scope

- Added `scripts/reproduce.py` as the Task 22 candidate replay and freeze-stage entrypoint.
- Added `scripts/verify_bundle.py` as the typed bundle verifier/promoter.
- Added RED/GREEN coverage in `tests/reproducibility/test_clean_replay.py`.
- Updated current-facing reproducibility documentation:
  - `README.md`
  - `docs/REPRODUCIBILITY_CHECKLIST.md`
  - `docs/PAPER_ARTIFACT_MAP.md`
  - `docs/MAIN_RESULTS_TARGETS.md`

## RED evidence

```text
$ ./.venv/bin/python -m pytest tests/reproducibility/test_clean_replay.py -q
FAILED

Representative failures before implementation:
- JSON decode failure because `scripts/reproduce.py` did not exist
- `scripts/verify_bundle.py`: [Errno 2] No such file or directory
```

The Task 22 freeze surface was absent at the start of the task.

## Delivered behavior

- `make reproduce` now stages a typed candidate bundle under `results/tmp/candidates/<run_id>/`.
- The candidate bundle records:
  - typed freeze manifest
  - typed claim-support matrix
  - typed manual-review placeholder
  - verification report
  - publication report closure under `publication/`
  - authoritative-input pointers for report spec, Task 21 blocker chain, and any available E7/E8 replay inputs
  - Task 21 blocker-chain record under `task21/task21_blockers.json`
- The current Saturday, August 22, 2026 replay is intentionally fail-closed:
  - exits nonzero
  - records `INCOMPLETE`
  - does not create `results/frozen/<run_id>/`
  - does not create `MPP_ARTIFACT_COMPLETE`
- `scripts/verify_bundle.py` now:
  - rejects `TEST_ONLY_NON_EVIDENCE` fixtures in production verification/promotion
  - enforces exact bundle-file closure and anchored no-follow/hardlink-safe reads
  - re-runs Task 20 publication-manifest validation instead of trusting status strings
  - replays the live E7 authority boundary and compares the stored raw bundle/hash/closure
  - requires manual-review signature verification from an external allowed-signers file plus detached signature
  - preserves negative or inconclusive claim dispositions without upgrading completeness
- Promotion to `results/frozen/<run_id>/` is implemented but gated on:
  - no completeness blockers
  - complete externally authenticated manual review record
  - no synthetic/test-only substitution
  - no preexisting frozen target
  - successful atomic promotion path with reverified staging snapshot and sentinel written last

## Current candidate result

The final clean Saturday, August 22, 2026 candidate root and verification-report digest are recorded in the return contract for this task. The hardened replay remains intentionally `INCOMPLETE` with:

- `WAITING_LOCAL_MODEL_ARTIFACT`
- `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`
- missing accountable manual scientific review
- missing external review signature / trusted signers
- missing authorized publication evidence for `E1`-`E6`
- `NEEDS_CONTEXT` for a production-owned canonical E8 rows artifact/runner

`C7` remains `SUPPORTED`; `C8` remains `INCONCLUSIVE`; no frozen sentinel is created.

## Verification

Targeted post-implementation:

```text
$ ./.venv/bin/python -m pytest tests/reproducibility/test_clean_replay.py -q
PASS

$ ./.venv/bin/python -m compileall -q scripts tests/reproducibility
PASS
```

Broader verification after the hardening pass:

```text
$ ./.venv/bin/python -m pytest -q
PASS

$ ./.venv/bin/python -m compileall -q src tests experiments scripts
PASS

$ git diff --check
PASS
```

Live current-workspace replay after the hardening pass:

```text
$ make reproduce
INCOMPLETE by design; candidate written, no frozen bundle, no sentinel
```

## Design notes

- The first implementation attempted to invoke the full Task 21 local deployment stack from Task 22. That surfaced unrelated local deployment failures and was removed from the Task 22 blocker source.
- Task 22 now records the authoritative Task 21 blocker chain directly from a sanitized staged config context:
  - `WAITING_LOCAL_MODEL_ARTIFACT`
  - `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`
- `reproduce.py` also sanitizes the checked-in Task 21 config copy before staging because the unquoted 64-digit hash fields in `configs/e2e/local.yaml` load as integers under YAML parsing.

## Residual concerns

- `results/tmp/candidates/` is intentionally ignored runtime evidence for the current incomplete replay and no longer poisons the Task 22 run id by itself.
- E8 remains a documented canonical simulation surface, but the clean Task 22 candidate still records `NEEDS_CONTEXT` because no production-owned canonical rows artifact/runner is available outside test helpers today.
- A future complete freeze still requires an externally authenticated manual scientific review record; AI output, self-review, or user approval cannot satisfy that gate.
