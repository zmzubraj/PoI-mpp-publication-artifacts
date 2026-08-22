# Task 22 — Reproduce from a clean environment and freeze the publication bundle

**Status:** DONE

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
  - replays the production E8 publication artifact against the current frozen plan/contract/source closure instead of trusting copied status fields
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
- real-authority E7 replay is still required in full mode, and current E8 publication replay remains explicitly `REPRODUCIBLE_SIMULATION` with `C8=INCONCLUSIVE`

`C7` remains tied to the live local Foundry boundary; `C8` remains `INCONCLUSIVE`; no frozen sentinel is created.

Final committed-tree replay on Saturday, August 22, 2026:

- candidate root: `results/tmp/candidates/task22-741d9fb3f4e8d00f/`
- verification report: `results/tmp/candidates/task22-741d9fb3f4e8d00f/verification_report.json`
- verification report SHA-256: `80ae07314f4ba040a76bf3bf3b11d97ab06d5bfbd96c44a7b96356d191724672`
- completeness: `INCOMPLETE`
- direct verifier claims:
  - `C7=SUPPORTED`
  - `C8=INCONCLUSIVE`
- sentinel: absent

Final committed-tree blockers:

- `WAITING_LOCAL_MODEL_ARTIFACT: exact local model artifact is absent`
- `WAITING_EXTERNAL_EVALUATOR_AUTHORITY: external evaluator authority remains absent`
- `missing experiment evidence: E1`
- `missing experiment evidence: E2`
- `missing experiment evidence: E3`
- `missing experiment evidence: E4`
- `missing experiment evidence: E5`
- `missing experiment evidence: E6`
- `manual scientific review record is absent`
- `C1`-`C6` remain `INCOMPLETE` with their required artifacts missing

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
$ ./.venv/bin/python scripts/reproduce.py --mode candidate-only
INCOMPLETE by design; candidate written, no frozen bundle, no sentinel

$ ./.venv/bin/python scripts/reproduce.py
INCOMPLETE by design; candidate written, no frozen bundle, no sentinel

$ ./.venv/bin/python scripts/verify_bundle.py --bundle-root results/tmp/candidates/task22-741d9fb3f4e8d00f
INCOMPLETE by design; direct verifier agrees, `C7=SUPPORTED`, `C8=INCONCLUSIVE`, no sentinel

$ forge test -q
PASS
```

## Design notes

- The first implementation attempted to invoke the full Task 21 local deployment stack from Task 22. That surfaced unrelated local deployment failures and was removed from the Task 22 blocker source.
- Task 22 now records the authoritative Task 21 blocker chain directly from a sanitized staged config context:
  - `WAITING_LOCAL_MODEL_ARTIFACT`
  - `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`
- `reproduce.py` also sanitizes the checked-in Task 21 config copy before staging because the unquoted 64-digit hash fields in `configs/e2e/local.yaml` load as integers under YAML parsing.

## Residual concerns

- `results/tmp/candidates/` is intentionally ignored runtime evidence for the current incomplete replay and no longer poisons the Task 22 run id by itself.
- E8 is now a production-owned canonical simulation surface for Task 22 replay, but it still cannot upgrade the bundle beyond `INCOMPLETE` because the remaining blockers are evidence-authority and independent-review gaps, not E8 mechanics.
- A future complete freeze still requires an externally authenticated manual scientific review record; AI output, self-review, or user approval cannot satisfy that gate.
