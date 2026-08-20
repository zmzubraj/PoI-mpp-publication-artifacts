# Task 13 — E2 attack manifests and detection curves

## Status

`IMPLEMENTATION_CANDIDATE_PENDING_REVIEW`

Task 13 now implements a frozen post-commit attack matrix for E2 with
manifest-bound corruption records, deterministic replay, exact-vs-empirical
reporting separation, unsupported-surface abstention, and publication-record
blocking for synthetic fixtures.

## Files changed

- `src/poi_mpp/attacks/__init__.py`
- `src/poi_mpp/attacks/execution.py`
- `src/poi_mpp/experiments/e2_tamper.py`
- `src/poi_mpp/reporting/e2.py`
- `experiments/e2_tamper_detection.py`
- `tests/experiments/test_e2_tamper.py`
- `configs/pilot/e2.yaml`
- `src/poi_mpp/experiments/__init__.py`
- `src/poi_mpp/reporting/__init__.py`
- `.superpowers/sdd/2026-08-20-poi-mpp-publication-artifact-implementation/task-13-report.md`

## Attack matrix delivered

- `MODEL_ROOT_SUBSTITUTION`
- `WEIGHT_CORRUPTION`
- `TRACE_NODE_MUTATION`
- `TENSOR_PRODUCT_CORRUPTION`
  - exact-field path via finite-field Freivalds
  - empirical-float path via floating-point Freivalds
- `RESPONSE_BINDING_MISMATCH`
- `IEC_EVIDENCE_INDEX_MUTATION`
- `DECODE_POLICY_MUTATION`
- `CROSS_REQUEST_SPLICE`
- `REPLAY_NULLIFIER`
- `UNSUPPORTED_KERNEL`

Every attacked receipt row now binds:

- original immutable commitment hash
- original target hash
- attacked target hash
- attack family
- attack location
- seed
- typed parameters
- evidence origin

Missing or mismatched manifests fail closed through `validate_attack_receipt()`.

## RED evidence

Command:

```text
./.venv/bin/python -m pytest tests/experiments/test_e2_tamper.py -v
```

Expected RED outcome before implementation:

```text
9 failed
- ModuleNotFoundError: no module named poi_mpp.attacks
- ModuleNotFoundError: no module named poi_mpp.experiments.e2_tamper
- legacy e2_tamper_detection.py CLI rejected --config and failed the new pilot boundary contract
```

## GREEN and integrated verification

Focused Task 13 suite:

```text
./.venv/bin/python -m pytest tests/experiments/test_e2_tamper.py -v
9 passed in 0.27s
```

Adjacent regression slice:

```text
./.venv/bin/python -m pytest tests/experiments/test_e2_tamper.py tests/experiments/test_e1_cost.py tests/auditor/test_exact.py tests/auditor/test_floating_point.py tests/auditor/test_finite_field.py -q
40 passed
```

Full Python suite:

```text
./.venv/bin/python -m pytest -q
236 passed
```

Static and diff hygiene:

```text
./.venv/bin/python -m compileall src experiments tests/experiments/test_e2_tamper.py
exit 0

git diff --check -- src/poi_mpp/attacks src/poi_mpp/experiments/e2_tamper.py src/poi_mpp/reporting/e2.py experiments/e2_tamper_detection.py tests/experiments/test_e2_tamper.py configs/pilot/e2.yaml src/poi_mpp/experiments/__init__.py src/poi_mpp/reporting/__init__.py
exit 0
```

## Implemented APIs

- `build_fixture_bundle(...) -> ExecutionAuditBundle`
- `apply_attack(bundle, family, *, seed, peer_bundle=None, analysis_surface=None) -> (bundle, manifest)`
- `corrupt_trace_node(...) -> (bundle, manifest)`
- `evaluate_receipt(bundle, *, attack_manifest=None, audit_rate, freivalds_rounds, prior_nullifiers=()) -> E2ReceiptRow`
- `validate_attack_receipt(row) -> E2ReceiptRow`
- `summarize_e2_rows(rows, *, claim_id="C2") -> E2Summary`
- `build_publication_record(summary, rows, run_config) -> dict`

## Self-review

- Attack transforms mutate only the targeted observed surface while preserving
  the original commitment object and commitment hash.
- `ExecutionAuditBundle.model_copy()` revalidates updates instead of trusting
  unchecked `model_copy(update=...)` mutation.
- Exact-match, exact-field, empirical-float, and unsupported surfaces are
  reported separately; unsupported surfaces abstain and are excluded from the
  supported-attack denominator.
- Replay/nullifier checks incorporate prior-nullifier state so the experiment
  can distinguish replay reuse from clean first observation.
- Synthetic fixtures intentionally stop at `SEMANTICALLY_VALID`; publication
  gate evaluation remains incomplete for `SYNTHETIC_NON_EVIDENCE`.

## Residual risks

- The current E2 implementation is fixture-driven and publication-oriented; it
  does not execute an authorized real pilot or produce T7/F6 evidence from live
  model runs in this task.
- `run_config` and `commitment` are preserved as trusted in-memory objects
  inside `ExecutionAuditBundle` so post-commit mutation testing can keep the
  original commitment instance intact; reviewer scrutiny should confirm this is
  acceptable for the local experiment harness boundary.
- The current summary emits rates without confidence intervals. That matches the
  present test contract, but confirmatory publication reporting may later need
  interval estimation before a real T7/F6 artifact is frozen.
