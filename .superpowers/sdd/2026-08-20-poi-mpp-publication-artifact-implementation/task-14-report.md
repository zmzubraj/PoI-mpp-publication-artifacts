# Task 14 — E3 confirmatory semantic evaluation

## Scope

- Added typed E3 semantic-evaluation rows and confirmatory authority/config models in `src/poi_mpp/experiments/e3_semantic.py`.
- Added deterministic E3 reporting and frozen metric definitions in `src/poi_mpp/reporting/e3.py`.
- Replaced the prior random CSV generator with a fail-closed boundary CLI in `experiments/e3_semantic_eval.py`.
- Added pilot/configuration artifacts in `configs/pilot/e3.yaml` and `configs/confirmatory/e3.schema.yaml`.
- Added RED/GREEN coverage in `tests/experiments/test_e3_semantic.py`.

## Behavior

- `semantic_metrics()` now computes FAR, FRR, abstention, coverage, precision, recall, reference agreement, subgroup counts, confusion counts, and deterministic intervals.
- FAR denominator is frozen to all invalid cases; FRR denominator is frozen to all valid cases.
- Zero-denominator metrics remain explicit and never silently coerce to numeric rates.
- Calibration is reported as deterministic bootstrap Brier score over non-abstained decisions only.
- Confirmatory execution now fails closed unless publication scope, manifest split/isolation, non-synthetic provenance, verified evaluator identities, frozen development calibration, and verified provenance bundle are all present.
- The CLI does not run a real confirmatory evaluation without those authorities and assets.

## Task 11 boundary retained

- This task does not add a semantic-label minting path.
- Fixture rows are plumbing-only and synthetic.
- Real confirmatory execution remains blocked at the authority boundary until non-synthetic manifests, evaluator verification, and publication authorization are supplied.

## Verification

- `./.venv/bin/python -m pytest tests/experiments/test_e3_semantic.py -v`
- `./.venv/bin/python -m pytest tests/semantic tests/datasets tests/experiments/test_e3_semantic.py -v`
- `./.venv/bin/python -m pytest -q`
- `./.venv/bin/python -m compileall src/poi_mpp experiments`
- `git diff --check`

## Ledger candidate

- Task 14: complete (typed E3 confirmatory evaluation harness added; synthetic fixtures remain plumbing-only; confirmatory CLI stops at authority boundary; 5 targeted E3 tests PASS, 34 semantic/dataset+E3 tests PASS, full Python suite PASS, compileall PASS, git diff --check PASS).
