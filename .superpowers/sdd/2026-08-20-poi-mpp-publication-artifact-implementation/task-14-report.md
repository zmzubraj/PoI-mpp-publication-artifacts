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
- Synthetic plumbing evaluation is now a separate explicit path with synthetic-only evaluator declarations, strict case/source/annotation manifest closure, and guaranteed nonterminal `SEMANTICALLY_VALID` outputs.
- Confirmatory execution no longer treats caller-authored `verified=True` as authority. After config/schema/closure validation it stops at the explicit `WAITING_EXTERNAL_EVALUATOR_AUTHORITY` boundary.
- Source manifest closure and annotation manifest closure are both exact: row IDs, hashes, origins, evaluator bindings, run IDs, experiment IDs, and case IDs must close exactly before metrics run.
- The CLI now loads and validates the typed `configs/confirmatory/e3.schema.yaml` contract before it stops at the external-authority boundary.

## Task 11 boundary retained

- This task does not add a semantic-label minting path.
- Fixture rows are plumbing-only and synthetic.
- Real confirmatory execution remains blocked at the authority boundary until a real external registry-backed evaluator authority artifact exists.

## Fix Round 1

- Removed the public `verified=True` evaluator path entirely from confirmatory authority decisions.
- Added a separate `E3SyntheticPlumbingEvaluator` / `run_synthetic_plumbing_semantic()` path for non-evidence metrics plumbing.
- Added exact source-manifest and annotation-manifest closure checks before metrics.
- Added typed confirmatory-schema loading and CLI validation with corruption/mismatch coverage.

## Verification

- `./.venv/bin/python -m pytest tests/experiments/test_e3_semantic.py -v`
- `./.venv/bin/python -m pytest tests/semantic tests/datasets tests/experiments/test_e3_semantic.py -v`
- `./.venv/bin/python -m pytest -q`
- `./.venv/bin/python -m compileall src/poi_mpp experiments`
- `git diff --check`

## Ledger candidate

- Task 14: fix round 1 complete (removed caller-authored evaluator verification, added explicit `WAITING_EXTERNAL_EVALUATOR_AUTHORITY` boundary, enforced exact source/annotation manifest closure, validated typed confirmatory schema in CLI; 10 targeted E3 tests PASS, 39 semantic/dataset+E3 tests PASS, full Python suite PASS, compileall PASS, git diff --check PASS).
