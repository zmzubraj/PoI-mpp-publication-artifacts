# Task 10 — Exact and approximate execution audits report

## Status

`IMPLEMENTATION_CANDIDATE_PENDING_REVIEW`

Task 10's owned auditor split is implemented under `src/poi_mpp/auditor/` with
fail-closed separation between exact equality, finite-field Freivalds, and
empirical floating-point Freivalds paths.

## Files changed

- `src/poi_mpp/auditor/__init__.py`
- `src/poi_mpp/auditor/reports.py`
- `src/poi_mpp/auditor/exact/__init__.py`
- `src/poi_mpp/auditor/exact/checks.py`
- `src/poi_mpp/auditor/algebraic/__init__.py`
- `src/poi_mpp/auditor/algebraic/finite_field.py`
- `src/poi_mpp/auditor/algebraic/floating_point.py`
- `tests/auditor/test_exact.py`
- `tests/auditor/test_finite_field.py`
- `tests/auditor/test_floating_point.py`
- `.superpowers/sdd/2026-08-20-poi-mpp-publication-artifact-implementation/task-10-report.md`
- `.superpowers/sdd/2026-08-20-poi-mpp-publication-artifact-implementation/progress.md`

## RED evidence

Command:

```text
.venv/bin/python -m pytest tests/auditor/test_exact.py tests/auditor/test_finite_field.py tests/auditor/test_floating_point.py -v
```

Output and exit status:

```text
collected 0 items / 3 errors
E   ModuleNotFoundError: No module named 'poi_mpp.auditor'
exit 2
```

The failure was expected: Task 10's package surface did not exist.

## GREEN and integrated verification

Focused Task 10 suite:

```text
.venv/bin/python -m pytest tests/auditor/test_exact.py tests/auditor/test_finite_field.py tests/auditor/test_floating_point.py -v
============================== 17 passed in 0.05s ==============================
exit 0
```

Owned auditor package suite:

```text
.venv/bin/python -m pytest tests/auditor -v
============================== 17 passed in 0.05s ==============================
exit 0
```

Full Python suite:

```text
.venv/bin/python -m pytest
184 passed in 1.75s
exit 0
```

Static and diff hygiene:

```text
.venv/bin/python -m compileall -q src tests
exit 0

git diff --check
exit 0
```

## Implemented APIs

- `verify_exact(expected, observed, *, evidence_origin=...) -> AuditResult`
- `verify_freivalds_field(A, B, C, *, rounds, seed, modulus, evidence_origin=..., declared_modulus_only=False) -> AuditResult`
- `verify_freivalds_float(A, B, C, *, rounds, seed, atol, rtol, evidence_origin=...) -> AuditResult`
- `AuditResult` with immutable evidence origin, assurance class, accepted flag,
  disposition, challenge vectors, rounds, seed, modulus or tolerances,
  dimensions, residual risk, and error-bound or residual metrics fields.

## Self-review

- Exact checks accept only canonical integer matrices, bytes, lowercase SHA-256
  digests, or integers; malformed hash or matrix inputs return
  `INVALID_INPUT` rather than coercing.
- The finite-field path is integer-only, records deterministic nonzero binary
  challenge vectors, validates matrix shapes, rejects negative, oversized, and
  noninteger entries, and exposes `2^-k` soundness only on the exact-prime
  assurance path.
- The declared-modulus path stays separate from exact-field soundness and
  records the conditional residual risk instead of silently upgrading it.
- The floating-point path rejects NaN, Inf, invalid tolerances, and non-finite
  intermediates; it reports only empirical approximation with residual metrics
  and never sets an exact soundness bound.

## Residual risks

- The declared-modulus path currently accepts any caller-declared modulus when
  `declared_modulus_only=True`; review should confirm whether later protocol
  consumers need a narrower allowlist or stronger semantic labeling.
- The floating-point implementation computes full reference products to emit
  residual metrics for small MPP fixtures; if later large-matrix experiments
  require a strictly projection-only path, the metric strategy may need a
  separate bounded mode.

## Fix Round 1 — finite float metrics, safe copy semantics, and modulus ceiling

### Changed files

- `src/poi_mpp/auditor/reports.py`
- `src/poi_mpp/auditor/algebraic/floating_point.py`
- `src/poi_mpp/auditor/algebraic/finite_field.py`
- `tests/auditor/test_floating_point.py`
- `tests/auditor/test_finite_field.py`

### RED evidence

```text
.venv/bin/python -m pytest tests/auditor/test_floating_point.py tests/auditor/test_finite_field.py -v
```

```text
3 failed, 10 passed in 0.08s

- zero-reference float metric case raised instead of returning an AuditResult
- AuditResult.model_copy accepted evidence-origin mutation without validation
- oversized modulus reached primality logic instead of failing on the MPP field ceiling

exit 1
```

Note: the first RED pass also exposed a malformed `1x2 @ 2x1` zero-product test
fixture; the fixture was corrected to a `1x1` result shape before fixing the
implementation defects above.

### GREEN and verification evidence

Focused regression suite:

```text
.venv/bin/python -m pytest tests/auditor/test_floating_point.py tests/auditor/test_finite_field.py -v
============================== 13 passed in 0.07s ==============================
exit 0
```

Owned auditor suite:

```text
.venv/bin/python -m pytest tests/auditor -v
============================== 19 passed in 0.05s ==============================
exit 0
```

Full Python suite:

```text
.venv/bin/python -m pytest
186 passed in 1.93s
exit 0
```

Static and diff hygiene:

```text
.venv/bin/python -m compileall -q src tests
exit 0

git diff --check
exit 0
```

### Fix summary

- Float error metrics now use a finite denominator floor:
  `max(abs(expected), abs(observed), sys.float_info.min)`, so finite inputs
  never produce `inf` or raise during zero-reference relative-error reporting.
- `AuditResult.model_copy(update=...)` now forbids changes to
  `evidence_origin` and `assurance_class`, and revalidates any allowed updates
  through normal model validation before returning a new instance.
- Finite-field audits now reject moduli above the exact MPP ceiling of `31`
  bits before primality testing or any stronger exactness implication.
