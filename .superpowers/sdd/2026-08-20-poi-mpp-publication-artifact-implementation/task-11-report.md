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

## Fix Round 2 — non-forgeable trust boundary and Unicode source-family normalization

**Status:** DONE_WITH_CONCERNS

### Delivered

- Public `EvidenceRecord` construction, `model_validate`, and `model_copy` no longer self-authorize trusted semantic labels. Any caller-supplied trust fields are stripped unless a module-private issuance context is active.
- Added a module-private trusted issuance path that requires:
  - a terminal `ArtifactRecord`;
  - matching `RunManifest` identity and origin;
  - non-synthetic publication evidence origin;
  - evidence content-hash equality; and
  - trusted label-payload hash membership in `artifact.parent_hashes`.
- Public reload of a previously trusted semantic record now downgrades to `UNTRUSTED_CALLER`.
- `verify_grounded()` now treats untrusted annotations or numeric facts as a fail-closed `ABSTAIN` surface instead of accepting caller-asserted trust.
- `source_family` now uses `NFKC` + `strip()` + `casefold()` before storage, hashing, and split-isolation comparison.

### Focused verification

```text
$ ./.venv/bin/python -m pytest tests/semantic tests/datasets/test_split_isolation.py -v
28 passed in 0.10s

$ ./.venv/bin/python -m pytest tests -v
217 passed in 2.94s

$ PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests
$ git diff --check
```

### Additional regressions covered

- Self-asserted `TRUSTED_GROUNDED_ANNOTATOR` via constructor, `model_validate`, and `model_copy` remains blocked and yields `ABSTAIN`.
- Public reload of a trusted record downgrades to untrusted and yields `ABSTAIN`.
- Legitimate test-only trusted issuance from a verified artifact/provenance path still yields `ACCEPT`.
- Unicode-composed/decomposed and case-variant `source_family` aliases collide during confirmatory-isolation checks.

### Residual concerns

- The trusted issuance helper is intentionally module-private because the current evidence kernel does not yet expose an independently verified public semantic-label artifact surface. A later task may replace this with a stronger first-class verified issuer.
- The trusted binding currently uses `artifact.parent_hashes` for label-payload commitment because Task 11 does not yet own a dedicated semantic-label artifact schema in the evidence kernel.

## Fix Round 3 — fail-closed fallback for semantic authority

**Status:** DONE_WITH_CONCERNS

### Delivered

- Removed the Task 11 accepting trust path entirely. `verify_grounded()` no longer accepts annotation-driven `SUPPORTED`, `PARTIAL`, `CONTRADICTORY`, or numeric outcomes as authoritative in this task.
- `EvidenceRecord` now strips all caller-supplied trust fields during validation and disables `model_construct()` so unchecked instantiation cannot mint trusted authority.
- Public/serialized trust bindings, stale artifact references, synthetic origins, and raw forged terminal-record metadata now all degrade to the same fail-closed behavior: `ABSTAIN` when semantic assertions are present.
- Kept Unicode `source_family` normalization from round 2.

### Focused verification

```text
$ ./.venv/bin/python -m pytest tests/semantic tests/datasets/test_split_isolation.py -v
29 passed in 0.11s

$ ./.venv/bin/python -m pytest tests -v
218 passed in 4.47s

$ PYTHONPATH=src ./.venv/bin/python -m compileall -q src tests
$ git diff --check
```

### Additional regressions covered

- `EvidenceRecord.model_construct(...)` is disabled.
- The private `_issue_trusted_evidence` helper is absent from the models module.
- Constructor / `model_validate` / `model_copy` self-asserted trust is stripped and still yields `ABSTAIN`.
- Serialized/reloaded trust bindings cannot be revived into authority.
- Stale registry-reference fields are ignored and still yield `ABSTAIN`.
- Synthetic annotated records cannot become trusted publication evidence.

### Residual concerns

- This round intentionally chooses the explicit Task 11 fallback because the current evidence kernel does not yet provide a defensible non-serializable, registry-backed semantic authority capability for acceptance.
- `ACCEPT` for annotation-driven grounded support is therefore deferred to a later task that can prove registry lookup, graph validation, canonical artifact identity, provenance validation, and publication-gate freshness at verification time.
