# Task 18 — E7 Foundry gas/state collection

## Scope

- Added the dedicated Foundry gas/state harness and witness writer in `contracts/test/GasSnapshots.t.sol`.
- Added strict E7 raw-report parsing, manifest binding, controlled `forge` collection, parity attachment loading, and bundle models in `src/poi_mpp/experiments/e7_evm.py`.
- Added fail-closed T12/F12/publication-summary helpers in `src/poi_mpp/reporting/e7.py`.
- Replaced the placeholder collector with an argv-only wrapper in `scripts/collect_gas.py`.
- Replaced the E7 scaffold wrapper with a bundle-plus-summary entrypoint in `experiments/e7_evm_boundedness.py`.
- Added RED/GREEN coverage in `tests/experiments/test_e7_evm.py`.

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
- The raw Foundry report is strict JSON and fail-closed:
  - exact schema version
  - no empty reports
  - unique `(operation, batch_size)` keys
  - plain bounded integer gas/storage fields
  - explicit `gas` and `bytes` units only
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
- Publication review is raw-report authoritative rather than row-authoritative: support re-parses the raw Foundry report from disk and rejects any caller-mutated/reloaded bundle that does not match the canonical replay.
- Publication support is deliberately narrow: the summary only reaches `SUPPORTED` when:
  - the exact operation/batch matrix closes against the frozen E7 measurement contract
  - the run config remains `FOUNDRY_MEASUREMENT` under `PUBLICATION_EVIDENCE_AUTHORIZED`
  - all measured operations remain within the measured local block gas limit
  - the Task 8 parity attachment stays hash-bound and structurally valid

## Authority boundary retained

- E7 publication evidence remains restricted to `FOUNDRY_MEASUREMENT` under `PUBLICATION_EVIDENCE_AUTHORIZED`.
- Local Foundry measurements are explicitly local-EVM artifacts and are not labeled as Ethereum-mainnet or production dispute-VM costs.
- The wrappers collect and summarize evidence only; they do not auto-freeze publication artifacts or widen authority beyond the frozen run config.

## Verification

- `./.venv/bin/python -m pytest tests/experiments/test_e7_evm.py -q`
- `cd contracts && forge test --match-contract GasSnapshots --gas-report -vv`
- `./.venv/bin/python -m pytest tests/integration/test_python_solidity_parity.py -q`
- `./.venv/bin/python -m pytest tests/experiments -q`
- `./.venv/bin/python -m pytest -q`
- `cd contracts && forge test -vv`
- `./.venv/bin/python -m compileall src tests experiments scripts`
- `git diff --check`

## Collected measurement artifact

- Raw witness path: `contracts/out/e7_foundry_measurements.json`
- Raw witness SHA-256: `039e790367dfb2f1606c0c15c23d520fda721d04834906a82a36028e21184639`

## Ledger candidate

- Task 18: implementation complete (typed E7 Foundry measurement contract/bundle/reporting added; raw-report authority now re-parses canonical Foundry JSON and rejects forged rows; local block-limit boundedness is measured over the exact E7 operation/batch matrix and bound to Task 8 parity attachment; focused E7 tests PASS, parity integration PASS, `tests/experiments` PASS, full Python suite PASS, GasSnapshots Foundry suite PASS, full Foundry suite PASS, compileall PASS, git diff --check PASS; local Foundry evidence only, no publication freeze executed).

## Residual risk

- The machine-readable witness path relies on `forge script ... --via-ir`, matching the existing Task 8 witness strategy; if Foundry’s script JSON-writing behavior changes, collection should fail closed rather than silently degrade.
- The measured block gas limit is the local Foundry limit (`1073741824` in the current witness), so the summary supports only local boundedness for the frozen matrix, not any mainnet gas claim.
