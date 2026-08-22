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

- `make reproduce` now stages a typed candidate bundle under `results/candidates/<run_id>/`.
- The candidate bundle records:
  - typed freeze manifest
  - typed claim-support matrix
  - typed manual-review placeholder
  - verification report
  - publication report closure under `publication/`
  - Task 21 blocker-chain record under `task21/task21_blockers.json`
- The current Saturday, August 22, 2026 replay is intentionally fail-closed:
  - exits nonzero
  - records `INCOMPLETE`
  - does not create `results/frozen/<run_id>/`
  - does not create `MPP_ARTIFACT_COMPLETE`
- `scripts/verify_bundle.py` revalidates bundle structure from filesystem contents and preserves negative or inconclusive claim dispositions.
- Promotion to `results/frozen/<run_id>/` is implemented but gated on:
  - no completeness blockers
  - complete manual review record
  - no synthetic substitution
  - no preexisting frozen target
  - successful atomic promotion path

## Current candidate result

- Candidate root: `results/candidates/task22-4906a347c25fc3b9`
- Verification report SHA-256: `a4b18f30fb01edd561caeb81e9e869f8eb6be63c4ab286e2c9050af631888911`
- `scripts/verify_bundle.py --bundle-root results/candidates/task22-4906a347c25fc3b9`
  - completeness: `INCOMPLETE`
  - sentinel present: `false`
  - claims:
    - `C1`: `INCONCLUSIVE`
    - `C2`: `INCONCLUSIVE`
    - `C3`: `INCONCLUSIVE`
    - `C4`: `INCONCLUSIVE`
    - `C5`: `INCONCLUSIVE`
    - `C6`: `INCONCLUSIVE`
    - `C7`: `SUPPORTED`
    - `C8`: `INCONCLUSIVE`
- Recorded blockers:
  - `WAITING_LOCAL_MODEL_ARTIFACT`
  - `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`
  - missing accountable manual scientific review
  - `UNVERSIONED_BLOCKED` code revision / dirty evidence
  - missing authorized publication evidence for `E1`, `E2`, `E3`, `E4`, `E5`, `E6`, `E8`

## Verification

Targeted post-implementation:

```text
$ ./.venv/bin/python -m pytest tests/reproducibility/test_clean_replay.py -q
PASS

$ ./.venv/bin/python -m pytest tests/reproducibility -q
PASS

$ ./.venv/bin/python -m compileall -q scripts tests/reproducibility
PASS

$ ./.venv/bin/python scripts/verify_bundle.py --bundle-root results/candidates/task22-4906a347c25fc3b9
INCOMPLETE, expected blockers recorded, no sentinel
```

Broader verification before the final Task 22 script-only blocker-chain adjustment:

```text
$ make test-all
PASS

$ ./.venv/bin/python -m pytest -q
PASS

$ cd contracts && forge test -q
PASS

$ ./.venv/bin/python -m compileall -q src tests experiments scripts
PASS

$ git diff --check
PASS
```

Live current-workspace replay after the final Task 22 blocker-chain adjustment:

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

- The final script-only blocker-chain adjustment was revalidated with the full Task 22 targeted suite and live replay, but the entire repository-wide Python/Foundry wave was not rerun after that last narrow adjustment.
- `results/candidates/` is intentionally left untracked as runtime evidence for the current incomplete replay.
- E8 remains a documented canonical simulation surface, but the clean Task 22 candidate still records `E8` as missing publication evidence because no authoritative clean-workspace E8 artifact bundle is checked in here today.
