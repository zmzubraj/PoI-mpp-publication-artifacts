# Task 11 — grounded semantic verification and dataset isolation

**Status:** DONE_WITH_CONCERNS

## Delivered

- Added explicit grounded-semantic verifier APIs under `src/poi_mpp/auditor/semantic/`.
- Added fail-closed outcome types: `SUPPORTED`, `UNSUPPORTED`, `CONTRADICTORY`, `PARTIAL`, `AMBIGUOUS`, `NUMERICAL_ERROR`, and `CITATION_ERROR`.
- Added deterministic citation binding, bounded decimal checking, and abstention on semantic ambiguity.
- Added development-only calibration fitting that emits a frozen hash-bound calibration artifact and tie-breaks toward stricter thresholds.
- Added dataset manifests plus confirmatory isolation checks for ID, content-hash, and source-family overlap.
- Preserved the synthetic-data boundary by allowing `SYNTHETIC_NON_EVIDENCE` only on `PLUMBING` fixtures.

## RED evidence

The task-prescribed RED target failed because the semantic and dataset APIs did not yet exist:

```text
$ ./.venv/bin/python -m pytest tests/semantic tests/datasets/test_split_isolation.py -v
ModuleNotFoundError: No module named 'poi_mpp.auditor.semantic'
ModuleNotFoundError: No module named 'poi_mpp.datasets'
3 errors during collection
```

## GREEN evidence

```text
$ ./.venv/bin/python -m pytest tests/semantic tests/datasets -v
17 passed in 0.06s

$ ./.venv/bin/python -m pytest tests -v
203 passed in 1.98s

$ PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests
$ git diff --check
```

## Files

- `src/poi_mpp/auditor/semantic/__init__.py`
- `src/poi_mpp/auditor/semantic/models.py`
- `src/poi_mpp/auditor/semantic/verifier.py`
- `src/poi_mpp/auditor/semantic/calibration.py`
- `src/poi_mpp/datasets/__init__.py`
- `src/poi_mpp/datasets/manifests.py`
- `src/poi_mpp/auditor/__init__.py`
- `tests/semantic/test_verifier.py`
- `tests/semantic/test_calibration.py`
- `tests/datasets/test_split_isolation.py`

## Ledger candidate

- Task 11 complete on branch `feature/poi-mpp-publication-artifacts`.
- New verifier is deterministic and does not call a model, network, or lexical entailment fallback.
- Confirmatory calibration tuning is not exposed; verification only consumes a frozen development artifact.
- Confirmatory isolation currently rejects any source-family overlap, which is conservative and may require narrower source-family normalization in a later task if the publication dataset design needs multiple non-overlapping excerpts from one broader venue family.

## Residual concerns

- The verifier is intentionally annotation-driven. It proves the contract for grounded claim adjudication, not a learned semantic model or real E3 measured performance.
- Numeric checking is bounded to strict decimal strings and comparator checks; richer unit algebra or interval semantics remain out of scope for this task.
- Verification used the repository-owned `./.venv/bin/python` interpreter because that is the configured project path.
