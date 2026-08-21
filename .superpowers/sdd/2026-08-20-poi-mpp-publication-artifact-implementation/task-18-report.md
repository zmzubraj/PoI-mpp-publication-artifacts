# Task 18 — E7 Foundry gas/state collection

## Scope

- Added the dedicated Foundry gas/state harness and witness writer in `contracts/test/GasSnapshots.t.sol`.
- Added strict E7 raw-report parsing, manifest binding, controlled `forge` collection, parity attachment loading, and bundle models in `src/poi_mpp/experiments/e7_evm.py`.
- Added fail-closed T12/F12/publication-summary helpers in `src/poi_mpp/reporting/e7.py`.
- Replaced the placeholder collector with an argv-only wrapper in `scripts/collect_gas.py`.
- Replaced the E7 scaffold wrapper with a bundle-plus-summary entrypoint in `experiments/e7_evm_boundedness.py`.
- Added RED/GREEN coverage in `tests/experiments/test_e7_evm.py`.

## Fix round 1

- Invalidated the earlier raw witness hash `039e790367dfb2f1606c0c15c23d520fda721d04834906a82a36028e21184639`. It is not authoritative after the provenance/gas/storage review findings and must not be cited as E7 evidence.
- Tightened publication authority to the exact canonical collector path `contracts/out/e7_foundry_measurements.json`.
- Rejected symlinked raw reports and non-canonical paths for publication support. Off-repo reports still parse for plumbing tests, but they remain `PLUMBING_FIXTURE` and cannot reach `SUPPORTED`.
- Bound canonical raw-report hash into the recomputed manifest and added an explicit collector-capability record (`CANONICAL_COLLECTOR_REPORT` vs `PLUMBING_FIXTURE`).
- Changed the storage metric from exact-byte language to:
  - `changed_storage_slot_count`
  - `storage_change_upper_bound_bytes`
  - `storage_unit=bytes_upper_bound`
- Removed pre-measurement `vm.load`/snapshot reads from measured paths. Gas is now recorded immediately around the protocol call, and slot diffs are derived after the call against a fresh baseline fixture.
- Added explicit packed-write and repeated-surface tests in Solidity, plus a Python regression that scans the witness functions to prevent pre-measurement `vm.load`.
- Made bundle and summary writes atomic with write/fsync/replace/read-back verification.

## Fix round 2

- Demoted ordinary stored-bundle summary/review to metadata-only: `summarize_e7_bundle(...)` is now always `INCONCLUSIVE`, even if a caller forges `E7CollectorCapability` or replays JSON via `model_copy`/`model_construct`.
- Added one live publication boundary, `collect_and_summarize_e7_publication(...)`, and routed `experiments/e7_evm_boundedness.py` through it.
- The live publication boundary now performs fresh Task 8 parity verification in the same call before local E7 support is emitted:
  - `./.venv/bin/python scripts/export_solidity_vectors.py`
  - `cd contracts && forge test --match-contract HashVectors -q`
  - `./.venv/bin/python -m pytest tests/integration/test_python_solidity_parity.py -q`
- Bound a current parity source-closure hash over the Python protocol/hashing modules, Solidity protocol contracts, `contracts/test/HashVectors.t.sol`, `contracts/script/ProtocolVectorWitness.s.sol`, `scripts/export_solidity_vectors.py`, the parity pytest, and the current vectors fixture.
- Bound transcript hashes for the exporter, direct HashVectors test, and Python parity pytest into the live publication result.
- Current source drift without a fresh live parity rerun no longer has any path to `SUPPORTED`, because serialized `E7ParityAttachment` is treated as metadata only.

## RED evidence

- Initial RED run: `./.venv/bin/python -m pytest tests/experiments/test_e7_evm.py -q`
- Observed failure: `ModuleNotFoundError: No module named 'poi_mpp.experiments.e7_evm'`, confirming the E7 measurement surface was absent before implementation.

## Behavior

- The E7 slice now uses one explicit local measurement contract:
  - `MODEL_REGISTER`
  - `TASK_CREATE`
  - `COMMIT_RESPONSE`
  - `AUDIT_OPEN`
  - `AUDIT_RECORD_RESULT`
  - `AUDIT_RECORD_DA`
  - `OPEN_CHALLENGE`
  - `RECEIPT_MINT_PENDING`
  - `RECEIPT_ACTIVATE`
  - `RECEIPT_MARK_CHALLENGED`
  - `RECEIPT_SLASH`
  - `CREDIT_ALLOCATE` at batch sizes `1, 2, 4, 8`
- The human-facing gas command is `forge test --match-contract GasSnapshots --gas-report -vv`, while the machine-readable artifact is emitted by `forge script test/GasSnapshots.t.sol:GasSnapshotWitness --via-ir -q`.
- The two gas surfaces are intentionally distinct:
  - the gas report covers full Foundry test-function execution
  - the raw witness JSON records `CALL_BODY_GASLEFT_DELTA_EXCLUDES_TEST_HARNESS`
- The raw Foundry report is strict JSON and fail-closed:
  - exact schema version
  - no empty reports
  - unique `(operation, batch_size)` keys
  - plain bounded integer gas/storage fields
  - `changed_storage_slot_count`
  - `storage_change_upper_bound_bytes = changed_storage_slot_count * 32`
  - explicit `gas` and `bytes_upper_bound` units only
- Python never trusts caller-supplied manifest data. It re-derives:
  - Foundry version
  - compiler version
  - optimizer settings
  - chain id
  - block gas limit
  - source hashes
  - creation/deployed bytecode hashes
  - git revision and dirty flag
- Each E7 row binds the frozen `RunConfig`, exact raw report hash, manifest identity, and canonical row hash.
- Publication review is raw-report authoritative rather than row-authoritative: stored bundles are re-parsed against the canonical raw Foundry report, but they remain metadata-only and cannot mint `SUPPORTED`.
- Local `SUPPORTED` now exists only through the live publication boundary. In that call it:
  - reruns current parity/export verification
  - collects the canonical raw Foundry report
  - immediately re-reads and hashes the canonical raw file with anchored no-follow checks
  - parses that exact report into the returned bundle
  - verifies the exact operation/batch matrix and local block boundedness

## Authority boundary retained

- E7 publication evidence remains restricted to `FOUNDRY_MEASUREMENT` under `PUBLICATION_EVIDENCE_AUTHORIZED`.
- Local Foundry measurements are explicitly local-EVM artifacts and are not labeled as Ethereum-mainnet or production dispute-VM costs.
- The wrappers collect and summarize evidence only; they do not auto-freeze publication artifacts or widen authority beyond the frozen run config.

## Verification

- `./.venv/bin/python -m pytest tests/experiments/test_e7_evm.py -q`
- `cd contracts && forge test --match-contract GasSnapshots --gas-report -vv`
- `cd contracts && forge script test/GasSnapshots.t.sol:GasSnapshotWitness --via-ir -q`
- `./.venv/bin/python scripts/collect_gas.py --run-config <temp E7 config> --contracts-root contracts --out <temp bundle>`
- `./.venv/bin/python experiments/e7_evm_boundedness.py --run-config <temp E7 config> --contracts-root contracts --bundle-out <temp bundle> --summary-out <temp summary>`
- `./.venv/bin/python scripts/export_solidity_vectors.py`
- `cd contracts && forge test --match-contract HashVectors -q`
- `./.venv/bin/python -m pytest tests/integration/test_python_solidity_parity.py -q`
- `./.venv/bin/python -m pytest tests/experiments -q`
- `./.venv/bin/python -m pytest -q`
- `cd contracts && forge test -vv`
- `./.venv/bin/python -m compileall src tests experiments scripts`
- `git diff --check`

## Collected measurement artifact

- Raw witness path: `contracts/out/e7_foundry_measurements.json`
- Invalidated raw witness SHA-256: `039e790367dfb2f1606c0c15c23d520fda721d04834906a82a36028e21184639`
- Current raw witness SHA-256: `c5e7fe21f4d786a789a356fd13992444216d2de451734be72ee5e1cacec7dda4`
- Current bundle SHA-256 (temp collector run): `993657a008f17fadf3784e9ca382bcaad82519ab54f5f64dc14e63f203c869bd`
- Current summary SHA-256 (temp boundedness run): `07d2f7e0b00676497824043247fb8e1df1c5b33b1a13a8464ee2d6a75d6bc338`
- Current parity source-closure SHA-256: `4fdf9b927fffe04c2a4931328638706beb22cada2ea0730e35e7e80de8300f9f`
- Current boundedness summary:
  - `measurement_count=15`
  - `max_gas_used=467937`
  - `claim_disposition=SUPPORTED`

## Ledger candidate

- Task 18: implementation complete (typed E7 Foundry measurement contract/bundle/reporting added; raw-report authority now re-parses canonical Foundry JSON and rejects forged rows; local block-limit boundedness is measured over the exact E7 operation/batch matrix and bound to Task 8 parity attachment; focused E7 tests PASS, parity integration PASS, `tests/experiments` PASS, full Python suite PASS, GasSnapshots Foundry suite PASS, full Foundry suite PASS, compileall PASS, git diff --check PASS; local Foundry evidence only, no publication freeze executed).
- Task 18: fix round 1 complete (invalidated raw hash `039e...`; publication support now requires collector-owned canonical `contracts/out/e7_foundry_measurements.json` with anchored no-follow/symlink-free provenance; off-repo and symlink repros fail closed; gas timing no longer pre-warms measured storage; storage reporting now uses `changed_storage_slot_count` plus `storage_change_upper_bound_bytes`; atomic bundle/summary writes verified; regenerated raw hash `c5e7fe21...` and temp collector bundle/summary hashes `86aa2040...` / `34d016f7...`; no broader publication claim).
- Task 18: fix round 2 complete (stored bundle/attachment/capability metadata can no longer mint `SUPPORTED`; only the live `collect_and_summarize_e7_publication(...)` boundary may emit local support, and it now reruns exporter + HashVectors + Python parity in-call, binds current source-closure/transcript hashes, then recollects and summarizes the canonical raw Foundry report; temp live-publication bundle/summary hashes updated to `993657a0...` / `07d2f7e0...`; parity source-closure hash `4fdf9b92...`; no broader publication claim).

## Residual risk

- The machine-readable witness path relies on `forge script ... --via-ir`, matching the existing Task 8 witness strategy; if Foundry’s script JSON-writing behavior changes, collection should fail closed rather than silently degrade.
- The measured block gas limit is the local Foundry limit (`1073741824` in the current witness), so the summary supports only local boundedness for the frozen matrix, not any mainnet gas claim.
