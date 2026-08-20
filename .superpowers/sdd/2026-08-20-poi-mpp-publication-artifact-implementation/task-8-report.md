Task 8 blocked on protocol parity defects already present in the Python and Solidity kernels.

Scope inspected:
- `src/poi_mpp/protocol/commitment.py`
- `src/poi_mpp/protocol/types.py`
- `src/poi_mpp/protocol/credit.py`
- `contracts/src/CommitmentHub.sol`
- `contracts/src/CreditEngine.sol`
- `contracts/src/ReceiptManager.sol`
- `contracts/src/TaskManager.sol`
- existing protocol and Foundry tests

Commands run:
- `cd contracts && forge test --match-contract ReceiptLifecycleTest -q`
  - Result: pass
- `PYTHONPATH=src ./.venv/bin/python - <<'PY' ... commit_response(...) ... PY`
  - Result: Python commitment hash `09efe0730a02fdea986311584a04ba31c2c7e516e8c1bdbe99657c6f55e4db12`
- `cd contracts && cast abi-encode 'f(uint16,uint256,address,bytes32,bytes32,bytes32,bytes32,uint64,uint64)' 1 1 0x0000000000000000000000000000000000002001 0x1111111111111111111111111111111111111111111111111111111111111111 0x2222222222222222222222222222222222222222222222222222222222222222 0x3333333333333333333333333333333333333333333333333333333333333333 0x4444444444444444444444444444444444444444444444444444444444444444 1 3 | cast keccak`
  - Result: Solidity event-style commitment hash `0xfc0711d4015b9b326c2dc41b00437621a897c3cd0cb523fd557f7c8dbf520196`

Blocking defects:

1. Commitment hash material and hash function do not match.
   - Python binds SHA-256 canonical JSON over task/model metadata, response/trace/evidence/artifact roots, nonce, and finality depth.
   - Solidity binds `keccak256(abi.encode(...))` over `EVENT_VERSION`, numeric `taskId`, worker address, roots, and block heights.
   - Evidence:
     - `src/poi_mpp/protocol/commitment.py:23-46`
     - `src/poi_mpp/protocol/types.py:119-197`
     - `contracts/src/CommitmentHub.sol:77-91`
   - Consequence: byte-identical commitment vectors are impossible without changing one kernel or introducing a separate canonical Solidity commitment path.

2. Task identity and worker identity shapes do not match.
   - Python uses string `task_id` / `worker_id` plus hashed `TaskSpec` and hashed `ModelManifest`.
   - Solidity uses `uint256 taskId`, `address worker`, and does not include model manifest hash or task root digest inside commitment construction.
   - Evidence:
     - `src/poi_mpp/protocol/types.py:44-55`
     - `src/poi_mpp/protocol/types.py:119-197`
     - `contracts/src/TaskManager.sol:14-31`
     - `contracts/src/CommitmentHub.sol:19-30`
   - Consequence: even a vector exporter cannot preserve identical ABI types and payload semantics across both sides today.

3. Credit allocation semantics do not match.
   - Python automatically allocates the entire task credit budget across all eligible active receipts by deterministic equal-share logic.
   - Solidity exposes imperative `addCredit(taskId, receiptId, worker, credit)` that lets an operator choose any per-receipt credit amount, with only budget and replay checks enforced.
   - Evidence:
     - `src/poi_mpp/protocol/credit.py:67-91`
     - `contracts/src/CreditEngine.sol:61-99`
   - Consequence: there is no canonical cross-language vector for credit allocation semantics yet; only active-weight formula parity exists.

4. Receipt multiplicity differs.
   - Python credit allocation supports multiple eligible receipts and aggregates by `receipt.worker_id`.
   - Solidity tasks are single-worker, and `addCredit` requires `worker == task.worker == receipt.worker`.
   - Evidence:
     - `src/poi_mpp/protocol/credit.py:83-90`
     - `contracts/src/CreditEngine.sol:74-88`
   - Consequence: publication-grade parity vectors for receipt-to-credit semantics would be misleading.

Decision:
- I did not create `contracts/test/HashVectors.t.sol`, `scripts/export_solidity_vectors.py`, `tests/integration/test_python_solidity_parity.py`, or `tests/fixtures/protocol_vectors.json`.
- Doing so now would either hard-code divergent expectations or falsely imply parity that the kernels do not satisfy.

Nearest regression surface:
- Any future kernel alignment change must re-check:
  - `tests/protocol/test_commitment.py`
  - `tests/protocol/test_credit.py`
  - `contracts/test/ReceiptLifecycle.t.sol`
  - `contracts/test/CreditInvariant.t.sol`
  - eventual Task 8 parity fixtures

Residual risk:
- Task 5-7 tests can all remain green while the publication requirement "Python and Solidity implement one protocol contract" is still false for commitments and credit allocation.
- If later work proceeds without reconciling this, E7 parity artifacts will encode architecture drift instead of proof of equivalence.

---

Resolution on Thursday, August 20, 2026:

The blocker was resolved by aligning both kernels to one EVM-shaped protocol contract while keeping the evidence kernel unchanged.

Implemented contract:
- Evidence kernel remains SHA-256 canonical JSON and was not modified.
- Python and Solidity protocol commitments now use explicit static ABI fields plus `keccak256`.
- Parity-critical identities now use `uint256` task/receipt ids, `address` worker ids, and `bytes32` roots/nullifiers/nonces.
- Commitment heights/finality stay as validated envelope metadata and are excluded from `C_R`.
- `ModelRegistry` now binds `modelManifestHash` and exposes canonical `modelCommitment`.
- `TaskManager` now exposes canonical `taskCommitment`.
- `CommitmentHub` now binds `C_T`, `C_M`, `H(y)`, `R_X`, `R_E`, `C_A`, and `nonce`.
- `CreditEngine` now performs deterministic batch allocation over a strictly ascending active-receipt list and records per-receipt credit for parity inspection.
- `HashVectors.t.sol`, `export_solidity_vectors.py`, `test_python_solidity_parity.py`, and `tests/fixtures/protocol_vectors.json` were added as the parity harness.

Files changed:
- `src/poi_mpp/protocol/types.py`
- `src/poi_mpp/protocol/commitment.py`
- `src/poi_mpp/protocol/audit_compiler.py`
- `src/poi_mpp/protocol/receipt.py`
- `src/poi_mpp/protocol/reference_machine.py`
- `src/poi_mpp/protocol/credit.py`
- `src/poi_mpp/protocol/__init__.py`
- `tests/protocol/conftest.py`
- `tests/protocol/test_audit_compiler.py`
- `tests/protocol/test_commitment.py`
- `tests/protocol/test_credit.py`
- `tests/protocol/test_protocol_properties.py`
- `tests/protocol/test_receipt_state_machine.py`
- `contracts/src/ProtocolHashing.sol`
- `contracts/src/ModelRegistry.sol`
- `contracts/src/TaskManager.sol`
- `contracts/src/CommitmentHub.sol`
- `contracts/src/CreditEngine.sol`
- `contracts/test/ProtocolRoles.t.sol`
- `contracts/test/CreditInvariant.t.sol`
- `contracts/test/HashVectors.t.sol`
- `scripts/export_solidity_vectors.py`
- `tests/integration/test_python_solidity_parity.py`
- `tests/fixtures/protocol_vectors.json`

Verification commands and results:
- RED:
  - `PYTHONPATH=src ./.venv/bin/python -m pytest tests/protocol/test_commitment.py tests/protocol/test_credit.py tests/integration/test_python_solidity_parity.py -q`
  - Result: failed on height-sensitive commitment hashing, missing per-receipt credit surface, and absent parity fixture.
- GREEN protocol Python suite:
  - `PYTHONPATH=src ./.venv/bin/python -m pytest tests/protocol -q`
  - Result: `36` protocol tests passed.
- GREEN parity integration:
  - `PYTHONPATH=src ./.venv/bin/python -m pytest tests/integration/test_python_solidity_parity.py -q`
  - Result: `4` integration tests passed.
- GREEN full Python suite:
  - `PYTHONPATH=src ./.venv/bin/python -m pytest`
  - Result: `148 passed in 1.72s`
- GREEN Solidity parity suite:
  - `cd contracts && forge test --match-contract HashVectors -vv`
  - Result: `8` tests passed.
- GREEN full Foundry suite:
  - `cd contracts && forge test -vv`
  - Result: `31` tests passed across `5` suites.
- Formatting:
  - `cd contracts && forge fmt`
  - Result: formatted touched Solidity sources.
- Deterministic exporter:
  - `PYTHONPATH=src ./.venv/bin/python scripts/export_solidity_vectors.py`
  - Run twice with identical output hash:
    - `dcfd1e264c947168736c8de5f271fa5ecf775970afc69d5e79b5de2040f18364`
    - `dcfd1e264c947168736c8de5f271fa5ecf775970afc69d5e79b5de2040f18364`

Migration notes:
- Python protocol fixtures now use EVM-typed ids and `bytes32` words with `0x` prefixes.
- The protocol kernel no longer binds commitment height/finality into `C_R`; only `taskCommitment`, `modelCommitment`, roots, and nonce are hashed.
- Credit allocation is no longer operator-amount driven. It requires the full active receipt batch for the task and deterministically splits budget by canonical receipt-id order.
- The vector fixture is labeled as non-evidence test data via `artifact_origin=TEST_VECTOR_NON_EVIDENCE` and `evidence_origin=SYNTHETIC_NON_EVIDENCE`.

Residual risks:
- Foundry invariant suites still emit harmless `target*` warning probes before execution; tests still pass and no behavior regressions were observed from them.
- Credit parity is exact only for the current single-worker-per-task MPP; any future multi-worker task model will require a new canonical batch contract and fresh vectors.
- The audit compiler remains a Python reference path and is not yet mirrored by a Solidity audit-seed implementation; Task 8 parity covers commitments, receipt state, and credit allocation exactly, not on-chain audit-plan derivation.
