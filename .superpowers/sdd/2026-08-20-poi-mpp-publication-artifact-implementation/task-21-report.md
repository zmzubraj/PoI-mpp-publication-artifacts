# Task 21 — Local end-to-end task-to-committee orchestration

**Status:** DONE_WITH_CONCERNS

## Scope

- Added typed local orchestration in `src/poi_mpp/orchestration/run_mpp.py`.
- Added orchestration exports in `src/poi_mpp/orchestration/__init__.py`.
- Added CLI wrapper `scripts/run_mpp.py`.
- Replaced `scripts/run_all.sh` with a defensive Task 21 wrapper.
- Added local Task 21 config at `configs/e2e/local.yaml`.
- Added focused e2e coverage in:
  - `tests/e2e/test_happy_path.py`
  - `tests/e2e/test_failure_paths.py`

## RED evidence

```text
$ ./.venv/bin/python -m pytest -o addopts='' tests/e2e -q
E   ModuleNotFoundError: No module named 'poi_mpp.orchestration'
```

The initial Task 21 surface was absent, so the RED boundary correctly failed at collection before any orchestration code existed.

## Delivered behavior

- The real path is fail-closed and typed:
  - missing local model/tokenizer files -> `WAITING_LOCAL_MODEL_ARTIFACT`
  - once exact local files and hashes are present -> `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`
- No real model download, network fetch, GPU execution, fake semantic authority, or synthetic-to-real evidence promotion path was introduced.
- The synthetic mechanics path is explicit `SYNTHETIC_NON_EVIDENCE` / `NON_PUBLICATION_MECHANICS` and revalidates on reload/model-copy boundaries.
- Before mechanics execution, the orchestrator now:
  - reruns current Task 8 parity verification
  - starts/stops a local Anvil process with bounded readiness and cleanup
  - deploys the exact current local contracts
  - verifies source/compiler hashes plus normalized runtime-bytecode parity against the local artifacts
- The synthetic mechanics path now produces one deterministic task-to-committee chain plus required failure journeys:
  - registered model -> protocol-issued consensus task -> one deterministic inference bundle -> commitment -> finalized audit -> DA success -> pending receipt -> matured active receipt -> bounded next-epoch credit -> deterministic committee
  - execution rejection -> `REJECTED`
  - semantic abstention -> `ABSTAINED`
  - DA failure -> `DA_FAILED`
  - successful challenge/slashing -> `SLASHED`
  - service task -> zero credit
  - replayed credit allocation -> fail-closed `REPLAY_REJECTED`
- Synthetic DA failure fixtures are now contained under the configured output root, not the repo root.

## GREEN verification

Focused e2e:

```text
$ ./.venv/bin/python -m pytest -o addopts='' tests/e2e -q
3 passed in 42.02s
```

Relevant regression surfaces:

```text
$ ./.venv/bin/python -m pytest -o addopts='' tests/e2e tests/integration/test_python_solidity_parity.py tests/protocol tests/worker tests/auditor tests/semantic tests/experiments/test_e4_da.py -q
114 passed in 40.24s
```

Full Python:

```text
$ ./.venv/bin/python -m pytest -q
[100%] pass completed after a long-running full-suite check

$ ./.venv/bin/python -m pytest --collect-only -q | awk -F': ' '/: [0-9]+$/ {sum += $2} END {print sum}'
351
```

Foundry / parity / hygiene:

```text
$ cd contracts && forge test -q
PASS

$ ./.venv/bin/python -m compileall -q src tests scripts
PASS

$ bash -n scripts/run_all.sh
PASS

$ shellcheck scripts/run_all.sh
shellcheck not installed

$ git diff --check
PASS
```

## Exact mechanics that pass

- Fresh parity verification via `verify_current_e7_parity(...)` before synthetic evidence-bearing mechanics.
- Safe local Anvil startup on the configured host/port/chain id, with shutdown limited to the process group started by the run.
- Exact current contract deployment plus source/compiler/runtime verification for:
  - `PolicyRegistry`
  - `ModelRegistry`
  - `TaskManager`
  - `CommitmentHub`
  - `AuditManager`
  - `ReceiptManager`
  - `CreditEngine`
- Synthetic happy path:
  - one active receipt
  - bounded credit at `task_epoch + 1`
  - deterministic one-member next-epoch committee
- Synthetic service path:
  - receipt can activate mechanically
  - credit allocation remains zero because the task class is `SERVICE`
- Synthetic replay path:
  - second credit allocation on the same receipt fails closed

## Exact real-path external blockers

- No approved local Qwen model artifact exists in this workspace today, so the real path remains blocked first at `WAITING_LOCAL_MODEL_ARTIFACT`.
- When a valid local artifact is supplied, the next blocker is intentionally `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`.
- Task 11 / Task 14 semantic acceptance remains unavailable by design; this Task 21 delivery does not widen that authority boundary.

## Self-review

- Runtime-bytecode verification needed immutable-reference normalization for deployed artifacts; this was fixed inside the owned orchestration wrapper without touching Solidity kernels.
- The initial `cast send` boolean serialization was invalid (`True`/`False`); the wrapper now emits lowercase ABI booleans.
- The initial DA failure fixture wrote under a fixed repo-root path; it now writes under the configured output root to preserve containment.

## Residual concerns

- The real publication-bearing path is still externally blocked and intentionally not claimed complete.
- `shellcheck` is not installed on this machine, so shell lint evidence is limited to `bash -n`.
- The full Python suite is slow because it now includes multiple Anvil/Foundry-backed e2e mechanics checks; it eventually completed cleanly but is materially heavier than the earlier task waves.

## Spec fix round 1 — 2026-08-22

### RED evidence

```text
$ ./.venv/bin/python -m pytest -o addopts='' tests/e2e/test_happy_path.py tests/e2e/test_failure_paths.py -q
8 failed, 5 passed in 61.74s

Representative failures:
- module had no `_resolve_output_relative_path`
- serialized artifact/result path assertions exposed absolute host paths
- `./` path inputs were still accepted
- `_safe_env()` did not force offline variables
- non-loopback host / model URI rejection was absent
- authoritative receipt helpers were absent, so monkeypatch mismatch checks could not fail closed
- `scripts/run_all.sh` did not declare offline localhost-only posture
```

### Additional hardening delivered

- Artifact/result path containment:
  - `MechanicsArtifact.relative_path` and serialized happy-path artifact references are now canonical output-root-relative POSIX paths only.
  - Safe reads now resolve relative paths against the configured output root through a validating no-symlink resolver.
  - Serialized real-path blocker reasons were stripped of absolute host-path leakage.
  - E2E reload now verifies canonical path serialization plus parent/hash closure from disk.
- Authoritative receipt/epoch sourcing:
  - Happy-path `receipt_state` and `credit_epoch` now come from `ReceiptManager.getReceipt(...)` readback, not synthesized local values.
  - The readback is cross-checked against `AuditManager.getAudit(...)` plus expected task/worker/commitment/audit/nullifier fields before any kernel `Receipt` is built.
  - Monkeypatched expected epoch/readback mismatches now fail closed with an authoritative-readback error instead of mutating the returned summary.
- Process/offline hardening:
  - Anvil stdout is now drained through a bounded in-memory capture with `_ANVIL_LOG_LIMIT`, final capped file write, truncation flag, and full/captured SHA-256 metadata in the serialized deployment summary.
  - Subprocess environment now forces offline Hugging Face / Transformers / dataset posture, disables pip index fallback, and drops inherited proxy variables.
  - Chain host validation is now loopback-only, and configured model/tokenizer roots reject URI-style remote locations.
  - `scripts/run_all.sh` now exports the same offline posture and documents the localhost-only Anvil exception.

### GREEN verification after spec fix

Focused e2e:

```text
$ ./.venv/bin/python -m pytest -o addopts='' tests/e2e/test_happy_path.py tests/e2e/test_failure_paths.py -q
13 passed in 103.65s (0:01:43)
```

Relevant regression surfaces:

```text
$ ./.venv/bin/python -m pytest -o addopts='' tests/e2e tests/integration/test_python_solidity_parity.py tests/protocol tests/worker tests/auditor tests/semantic tests/experiments/test_e4_da.py -q
124 passed in 102.64s (0:01:42)
```

Full Python:

```text
$ ./.venv/bin/python -m pytest -q
[100%] full suite PASS
```

Foundry / hygiene:

```text
$ cd contracts && forge test -q
PASS

$ ./.venv/bin/python -m compileall -q src tests scripts
PASS

$ bash -n scripts/run_all.sh
PASS

$ git diff --check
PASS

$ shellcheck scripts/run_all.sh
shellcheck not installed
```
