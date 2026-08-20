# PoI MPP Publication-Artifact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a test-driven 1B-8B open-weight, local-EVM Proof of Intelligence MPP that produces hash-bound, reproducible E1-E8 publication artifacts without promoting synthetic or incomplete outputs into scientific evidence.

**Architecture:** New behavior is built test-first under `src/poi_mpp/`; the current flat files remain historical scaffolds until parity is proven. A fail-closed evidence kernel governs canonical hashing, provenance, artifact lifecycle, and publication eligibility. Python and Solidity implement one protocol contract, while E1-E8 vertical slices convert validated receipt-level records into deterministic tables, figures, and claim-support dispositions.

**Tech Stack:** CPython 3.11, pytest, Hypothesis, Pydantic, JSON Schema, NumPy, Pandas/Parquet, SciPy, statsmodels, Matplotlib, PyTorch/Transformers/Safetensors for authorized model runs, Solidity 0.8.24, Foundry, and Anvil.

**Spec:** `docs/superpowers/specs/2026-08-20-poi-mpp-publication-artifact-design.md`

## Global Constraints

- First-publication scope is 1B-3B primary model, optional 7B-8B scaling model, objective and grounded tasks, local EVM, and E1-E8 artifacts.
- 70B/MoE, TEE, production dispute VM, production DA, production BFT, and full per-response zkML are excluded.
- New production code follows RED-GREEN-REFACTOR; a test must fail for the expected missing behavior before implementation.
- `SYNTHETIC_NON_EVIDENCE` may validate plumbing but may never become `FROZEN` or `PUBLICATION_ELIGIBLE`.
- Experiment completeness and scientific claim support are separate decisions.
- Negative and inconclusive results are retained.
- No `|| true`, silent experiment skip, empty-success CSV, auto-corrected invalid config, or manually entered measured result.
- Every frozen output binds schema, config, model, dataset, environment, code revision, parent hashes, and evidence origin.
- Every task ends with targeted tests plus the affected integrated suite.
- Do not run model downloads, GPU jobs, external datasets, or other networked evidence acquisition without explicit authorization and a frozen run specification.
- Before any execution, repeat the codebase security preflight and inspect changed entrypoints, dependency locks, scripts, and Foundry configuration.

---

## File and ownership map

| Surface | Responsibility |
|---|---|
| `src/poi_mpp/evidence/` | Schemas, canonical hashes, frozen runs, validation, registry, publication gates |
| `src/poi_mpp/protocol/` | Python reference state machine, audit compilation, DA, challenge, receipt, credit, committee |
| `src/poi_mpp/worker/` | Pinned model execution, deterministic decode, trace capture, Merkle roots, IEC |
| `src/poi_mpp/auditor/` | Exact checks, finite-field and floating-point audits, semantic and DA verification |
| `contracts/src/` | Local EVM policy, model, task, commitment, audit, receipt, and credit contracts |
| `contracts/test/` | Foundry unit, fuzz, invariant, gas, and parity tests |
| `experiments/` | Thin E1-E8 CLI adapters calling library APIs |
| `src/poi_mpp/experiments/` | Typed experiment logic and receipt-level writers |
| `src/poi_mpp/reporting/` | Aggregation, statistical analysis, tables, figures, manifests |
| `tests/` | Python unit, property, integration, artifact, statistical, and end-to-end tests |
| `configs/` | Frozen schemas, development profiles, pilot profiles, confirmatory profiles |
| `results/` | Run-scoped raw, derived, manifest, logs, and frozen bundles |

---

### Task 1: Establish the reproducible repository baseline

**Files:**
- Create: `.gitignore`
- Modify: `pyproject.toml`
- Create: `requirements.lock`
- Create: `src/poi_mpp/__init__.py`
- Create: `tests/meta/test_repository_contract.py`
- Modify: `Makefile`

**Interfaces:**
- Produces the Python package root and deterministic command surface consumed by every later task.
- Produces commands `make test-unit`, `make test-integration`, `make test-contracts`, `make test-all`, and `make reproduce`.

- [ ] **Step 1: Write the failing repository-contract test**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_reproducibility_files_exist():
    assert (ROOT / "requirements.lock").is_file()
    assert (ROOT / "src/poi_mpp/__init__.py").is_file()
    makefile = (ROOT / "Makefile").read_text()
    for target in ("test-unit:", "test-integration:", "test-contracts:", "test-all:", "reproduce:"):
        assert target in makefile
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/meta/test_repository_contract.py -v`  
Expected: FAIL because the package, lock, and required Make targets do not exist.

- [ ] **Step 3: Create the minimal package, lock, ignore rules, and Make targets**

Pin Python dependencies in `requirements.lock`; configure `pyproject.toml` with `package-dir = {"" = "src"}` and Python `==3.11.*`; ignore `.venv`, caches, model caches, temporary results, secrets, and local chain state while retaining frozen manifests and declared publication bundles.

- [ ] **Step 4: Verify GREEN and static import safety**

Run: `python -m pytest tests/meta/test_repository_contract.py -v`  
Expected: PASS.  
Run: `python -m compileall -q src tests`  
Expected: exit 0.

- [ ] **Step 5: Commit the reproducible baseline and initialize revision control**

Run: `git init && git add .gitignore pyproject.toml requirements.lock Makefile src/poi_mpp/__init__.py tests/meta/test_repository_contract.py && git commit -m "build: establish reproducible MPP baseline"`

---

### Task 2: Implement canonical evidence models and domain-separated hashing

**Files:**
- Create: `src/poi_mpp/evidence/models.py`
- Create: `src/poi_mpp/evidence/canonical.py`
- Create: `src/poi_mpp/evidence/__init__.py`
- Create: `tests/evidence/test_models.py`
- Create: `tests/evidence/test_canonical.py`
- Create: `tests/fixtures/hash_vectors.json`

**Interfaces:**
- Produces `EvidenceOrigin`, `ArtifactStage`, `ArtifactRecord`, `RunManifest`, `canonical_bytes(domain, value)`, and `digest(domain, value)`.
- All later schemas and Solidity parity vectors consume these names exactly.

- [ ] **Step 1: Write failing enum and lifecycle tests**

```python
import pytest
from poi_mpp.evidence.models import ArtifactRecord, ArtifactStage, EvidenceOrigin

def test_synthetic_record_cannot_be_frozen():
    with pytest.raises(ValueError, match="synthetic evidence cannot be frozen"):
        ArtifactRecord.minimal(
            origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
            stage=ArtifactStage.FROZEN,
        )
```

- [ ] **Step 2: Write failing canonical-hash tests**

```python
from poi_mpp.evidence.canonical import digest

def test_hash_is_key_order_independent_and_domain_separated():
    assert digest("TASK", {"b": 2, "a": 1}) == digest("TASK", {"a": 1, "b": 2})
    assert digest("TASK", {"a": 1}) != digest("MODEL", {"a": 1})
```

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/evidence/test_models.py tests/evidence/test_canonical.py -v`  
Expected: collection FAIL because the evidence package is missing.

- [ ] **Step 4: Implement minimal immutable Pydantic models and hashing**

Use sorted UTF-8 JSON with compact separators, reject NaN/Infinity, prefix `POI_MPP_V1|<DOMAIN>|`, and hash with SHA-256. Make records frozen and validate allowed lifecycle transitions.

- [ ] **Step 5: Verify GREEN and generate fixed cross-language vectors**

Run: `python -m pytest tests/evidence -v`  
Expected: PASS with stable digests recorded in `tests/fixtures/hash_vectors.json`.

- [ ] **Step 6: Commit**

Run: `git add src/poi_mpp/evidence tests/evidence tests/fixtures/hash_vectors.json && git commit -m "feat: add canonical evidence records and hashing"`

---

### Task 3: Freeze configuration, environment, and run provenance

**Files:**
- Create: `src/poi_mpp/evidence/config.py`
- Create: `src/poi_mpp/evidence/provenance.py`
- Create: `configs/schema/run-config-v1.json`
- Create: `configs/development.yaml`
- Create: `tests/evidence/test_config_freeze.py`
- Create: `tests/evidence/test_provenance.py`

**Interfaces:**
- Produces `RunConfig`, `EnvironmentManifest`, and `freeze_run(config, environment) -> RunManifest`.
- Consumes canonical hashing from Task 2.

- [ ] **Step 1: Write failing immutability and missing-provenance tests**

```python
import pytest
from poi_mpp.evidence.config import load_run_config

def test_invalid_da_sample_count_is_rejected(tmp_path):
    p = tmp_path / "run.yaml"
    p.write_text("data_availability:\n  total_shards: 16\n  samples: 32\n  replacement: false\n")
    with pytest.raises(ValueError, match="samples cannot exceed total_shards"):
        load_run_config(p)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/evidence/test_config_freeze.py tests/evidence/test_provenance.py -v`  
Expected: FAIL because loaders and manifests are absent.

- [ ] **Step 3: Implement strict schema loading and frozen manifests**

Reject unknown fields; capture Python, OS, CPU/GPU when available, package lock hash, model/dataset/config hashes, code revision or explicit `UNVERSIONED_BLOCKED`, and authorization scope.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/evidence/test_config_freeze.py tests/evidence/test_provenance.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/poi_mpp/evidence configs/schema configs/development.yaml tests/evidence && git commit -m "feat: freeze run configuration and provenance"`

---

### Task 4: Build atomic artifact validation and publication gates

**Files:**
- Create: `src/poi_mpp/evidence/validation.py`
- Create: `src/poi_mpp/evidence/registry.py`
- Create: `src/poi_mpp/evidence/publication_gate.py`
- Create: `tests/evidence/test_validation.py`
- Create: `tests/evidence/test_registry.py`
- Create: `tests/evidence/test_publication_gate.py`

**Interfaces:**
- Produces `validate_artifact`, `ArtifactRegistry.write_atomic`, and `evaluate_publication_gate`.
- Produces decisions `COMPLETE`, `INCOMPLETE`, `SUPPORTED`, `NOT_SUPPORTED`, and `INCONCLUSIVE`.

- [ ] **Step 1: Write failing fail-closed tests**

```python
def test_publication_gate_rejects_synthetic_parent(synthetic_record):
    decision = evaluate_publication_gate("C3", [synthetic_record])
    assert decision.completeness == "INCOMPLETE"
    assert "synthetic" in decision.reasons[0].lower()

def test_atomic_writer_does_not_leave_frozen_partial_file(tmp_path, invalid_record):
    registry = ArtifactRegistry(tmp_path)
    with pytest.raises(ArtifactValidationError):
        registry.write_atomic(invalid_record)
    assert not list(tmp_path.glob("*.frozen.json"))
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/evidence/test_validation.py tests/evidence/test_registry.py tests/evidence/test_publication_gate.py -v`  
Expected: FAIL because validation and registry APIs are absent.

- [ ] **Step 3: Implement validation, parent closure, and temporary-write/rename**

Validate finite numbers, denominators, stages, parent hashes, required provenance, and evidence origin before atomic rename. Keep completeness independent of claim support.

- [ ] **Step 4: Verify GREEN and interruption behavior**

Run: `python -m pytest tests/evidence -v`  
Expected: PASS with interrupted runs remaining `INCOMPLETE`.

- [ ] **Step 5: Commit**

Run: `git add src/poi_mpp/evidence tests/evidence && git commit -m "feat: enforce atomic artifact and publication gates"`

---

### Task 5: Implement the Python protocol reference machine

**Files:**
- Create: `src/poi_mpp/protocol/types.py`
- Create: `src/poi_mpp/protocol/commitment.py`
- Create: `src/poi_mpp/protocol/audit_compiler.py`
- Create: `src/poi_mpp/protocol/receipt.py`
- Create: `src/poi_mpp/protocol/reference_machine.py`
- Create: `tests/protocol/test_commitment.py`
- Create: `tests/protocol/test_audit_compiler.py`
- Create: `tests/protocol/test_receipt_state_machine.py`
- Create: `tests/protocol/test_protocol_properties.py`

**Interfaces:**
- Produces `TaskSpec`, `ModelManifest`, `ResponseCommitment`, `AuditPlan`, `Receipt`, `ProtocolEvent`, `commit_response`, `compile_audit`, and `transition`.

- [ ] **Step 1: Write failing commitment and post-finality seed tests**

```python
def test_audit_cannot_compile_before_commitment_finality(task, commitment, policy):
    commitment = commitment.model_copy(update={"finalized_height": None})
    with pytest.raises(InvalidTransition, match="not finalized"):
        compile_audit(policy, task, commitment, b"beacon", 0)
```

- [ ] **Step 2: Write failing state-machine tests**

```python
def test_receipt_cannot_activate_before_audit_da_and_window(receipt):
    with pytest.raises(InvalidTransition):
        transition(receipt, ActivateReceipt(), context_without_gates())
```

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/protocol -v`  
Expected: FAIL because protocol APIs are absent.

- [ ] **Step 4: Implement minimal state and domain rules**

Implement only declared states and events. Bind all commitment fields. Derive audit samples from finalized commitment plus beacon and round. Reject invalid transitions rather than coercing state.

- [ ] **Step 5: Add Hypothesis state-machine properties**

Assert no event sequence activates a receipt without audit, DA, and elapsed challenge window; no slashed receipt returns active; repeated nullifiers reject.

- [ ] **Step 6: Verify GREEN**

Run: `python -m pytest tests/protocol -v`  
Expected: PASS.

- [ ] **Step 7: Commit**

Run: `git add src/poi_mpp/protocol tests/protocol && git commit -m "feat: implement reference PoI state machine"`

---

### Task 6: Implement credit conservation and committee selection

**Files:**
- Create: `src/poi_mpp/protocol/credit.py`
- Create: `src/poi_mpp/protocol/committee.py`
- Create: `tests/protocol/test_credit.py`
- Create: `tests/protocol/test_committee.py`

**Interfaces:**
- Produces `allocate_credit`, `derive_active_weight`, and `sample_committee`.

- [ ] **Step 1: Write failing invariant tests**

```python
def test_collateral_cannot_create_weight():
    assert derive_active_weight(credit=0, collateral=10**18, beta=10, concentration_cap=10**18) == 0

def test_task_credit_never_exceeds_budget(task, active_receipts):
    allocation = allocate_credit(task, active_receipts)
    assert sum(allocation.by_worker.values()) <= task.credit_budget
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/protocol/test_credit.py tests/protocol/test_committee.py -v`  
Expected: FAIL because credit and committee functions are absent.

- [ ] **Step 3: Implement integer-only allocation and seeded committee sampling**

Use deterministic tie rules, reject service tasks, accept only prior-epoch active receipts, and make probability sums exact within declared numerical representation.

- [ ] **Step 4: Verify GREEN with properties**

Run: `python -m pytest tests/protocol -v`  
Expected: PASS across random budgets, identities, collateral, caps, and seeds.

- [ ] **Step 5: Commit**

Run: `git add src/poi_mpp/protocol tests/protocol && git commit -m "feat: conserve credit and derive next-epoch committees"`

---

### Task 7: Replace permissive Solidity scaffolds with tested role and state contracts

**Files:**
- Create: `contracts/src/PolicyRegistry.sol`
- Modify: `contracts/src/ModelRegistry.sol`
- Modify: `contracts/src/TaskManager.sol`
- Modify: `contracts/src/CommitmentHub.sol`
- Modify: `contracts/src/AuditManager.sol`
- Modify: `contracts/src/ReceiptManager.sol`
- Modify: `contracts/src/CreditEngine.sol`
- Create: `contracts/test/ProtocolRoles.t.sol`
- Create: `contracts/test/ReceiptLifecycle.t.sol`
- Create: `contracts/test/CreditInvariant.t.sol`
- Create: `contracts/test/ReplayInvariant.t.sol`

**Interfaces:**
- Emits versioned events consumed by E7 and parity tooling.
- Implements the Task 5/6 state and credit contract.

- [ ] **Step 1: Write failing unauthorized-action tests**

```solidity
function testUnauthorizedCallerCannotAddCredit() public {
    vm.prank(attacker);
    vm.expectRevert();
    creditEngine.addCredit(1, worker, 10);
}

function testReceiptCannotActivateBeforeAuditDaAndWindow() public {
    vm.expectRevert();
    receiptManager.activate(receiptId);
}
```

- [ ] **Step 2: Verify RED**

Run: `cd contracts && forge test -vv`  
Expected: FAIL because current contracts permit unauthorized mutation and premature activation.

- [ ] **Step 3: Implement minimal roles, dependencies, and lifecycle checks**

Use explicit custom errors, immutable or policy-governed contract references, registered tasks/workers, finalized commitments, DA/audit disposition, challenge deadline, nullifier consumption, and integer credit conservation.

- [ ] **Step 4: Add Foundry fuzz and invariant tests**

Assert service tasks never increase raw credit, total task allocation never exceeds budget, zero credit yields zero weight, active receipts cannot be replayed, and invalid state transitions revert.

- [ ] **Step 5: Verify GREEN**

Run: `cd contracts && forge test -vv`  
Expected: all unit, fuzz, and invariant tests PASS.

- [ ] **Step 6: Commit**

Run: `git add contracts/src contracts/test && git commit -m "feat: enforce EVM PoI roles and receipt lifecycle"`

---

### Task 8: Prove Python-Solidity commitment and state parity

**Files:**
- Create: `contracts/test/HashVectors.t.sol`
- Create: `scripts/export_solidity_vectors.py`
- Create: `tests/integration/test_python_solidity_parity.py`
- Create: `tests/fixtures/protocol_vectors.json`

**Interfaces:**
- Consumes Task 2 hash vectors and Task 5/6 protocol outputs.
- Produces a parity report required by E7 and publication freeze.

- [ ] **Step 1: Write a failing cross-language vector test**

```python
def test_python_commitment_matches_foundry_export(foundry_vector):
    assert commit_response(**foundry_vector.inputs).digest == foundry_vector.digest
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/integration/test_python_solidity_parity.py -v`  
Expected: FAIL because exported vectors and parity adapter are absent.

- [ ] **Step 3: Implement vector export with explicit ABI types and widths**

Export domain, bytes32 fields, enum values, uint widths, state transitions, credit allocations, and expected reverts. Do not serialize Solidity integers through floating point.

- [ ] **Step 4: Verify GREEN**

Run: `cd contracts && forge test --match-contract HashVectors -vv`  
Run: `python scripts/export_solidity_vectors.py`  
Run: `python -m pytest tests/integration/test_python_solidity_parity.py -v`  
Expected: all PASS with byte-identical digests and matching state/credit outputs.

- [ ] **Step 5: Commit**

Run: `git add contracts/test scripts/export_solidity_vectors.py tests/integration tests/fixtures/protocol_vectors.json && git commit -m "test: bind Python and Solidity protocol parity"`

---

### Task 9: Implement pinned worker execution, trace roots, and IEC

**Files:**
- Create: `src/poi_mpp/worker/model_manifest.py`
- Create: `src/poi_mpp/worker/deterministic_decode.py`
- Create: `src/poi_mpp/worker/trace_schema.py`
- Create: `src/poi_mpp/worker/trace_capture.py`
- Create: `src/poi_mpp/worker/trace_tree.py`
- Create: `src/poi_mpp/worker/iec_schema.py`
- Create: `src/poi_mpp/worker/iec_builder.py`
- Create: `src/poi_mpp/worker/inference.py`
- Create: `tests/worker/`

**Interfaces:**
- Produces `ExecutionBundle` and `execute_once(task, model_manifest, policy)`.

- [ ] **Step 1: Write failing deterministic fixture tests**

```python
def test_trace_root_changes_when_one_event_changes(trace_events):
    original = trace_root(trace_events)
    trace_events[0] = trace_events[0].model_copy(update={"output_hash": "00" * 32})
    assert trace_root(trace_events) != original

def test_iec_does_not_contain_private_reasoning(iec):
    assert "chain_of_thought" not in iec.model_dump()
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/worker -v`  
Expected: FAIL because worker package is absent.

- [ ] **Step 3: Implement deterministic CPU fixture path first**

Pin manifest fields, separate warm-up timing, capture declared trace events, create Merkle roots, map response claims to evidence IDs, and return immutable `ExecutionBundle`.

- [ ] **Step 4: Add optional authorized Transformers adapter behind dependency injection**

Adapter must require an exact local model revision/hash and refuse implicit network download during an evidence run.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/worker -v`  
Expected: PASS without network or GPU.

- [ ] **Step 6: Commit**

Run: `git add src/poi_mpp/worker tests/worker && git commit -m "feat: execute once with committed trace and IEC"`

---

### Task 10: Implement exact, finite-field, and floating-point auditors

**Files:**
- Create: `src/poi_mpp/auditor/exact/checks.py`
- Create: `src/poi_mpp/auditor/algebraic/finite_field.py`
- Create: `src/poi_mpp/auditor/algebraic/floating_point.py`
- Create: `src/poi_mpp/auditor/reports.py`
- Create: `tests/auditor/test_exact.py`
- Create: `tests/auditor/test_finite_field.py`
- Create: `tests/auditor/test_floating_point.py`

**Interfaces:**
- Produces `verify_exact`, `verify_freivalds_field`, `verify_freivalds_float`, and typed `AuditResult`.

- [ ] **Step 1: Write failing separation and corruption tests**

```python
def test_float_audit_cannot_claim_exact_soundness(float_result):
    assert float_result.assurance_class != "EXACT_FIELD_SOUNDNESS"

def test_field_audit_rejects_wrong_product():
    assert not verify_freivalds_field(A, B, wrong_C, rounds=8, seed=7, modulus=2147483647).accepted
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/auditor/test_exact.py tests/auditor/test_finite_field.py tests/auditor/test_floating_point.py -v`  
Expected: FAIL because auditors are absent.

- [ ] **Step 3: Implement exact-field and empirical-float paths independently**

Record challenge vectors, rounds, modulus or tolerance, honest/corrupt disposition, residual risks, and assurance class.

- [ ] **Step 4: Verify GREEN with property tests**

Run: `python -m pytest tests/auditor -v`  
Expected: PASS across dimension, seed, corruption, tolerance, NaN, and shape errors.

- [ ] **Step 5: Commit**

Run: `git add src/poi_mpp/auditor tests/auditor && git commit -m "feat: separate exact and approximate execution audits"`

---

### Task 11: Implement grounded semantic verification and dataset isolation

**Files:**
- Create: `src/poi_mpp/auditor/semantic/models.py`
- Create: `src/poi_mpp/auditor/semantic/verifier.py`
- Create: `src/poi_mpp/auditor/semantic/calibration.py`
- Create: `src/poi_mpp/datasets/manifests.py`
- Create: `tests/semantic/`
- Create: `tests/datasets/test_split_isolation.py`

**Interfaces:**
- Produces `verify_grounded`, `fit_development_calibration`, and `assert_confirmatory_isolation`.

- [ ] **Step 1: Write failing semantic boundary tests**

```python
def test_ambiguous_evidence_abstains(verifier):
    result = verifier.verify(response="A", evidence=[ambiguous_evidence])
    assert result.decision == "ABSTAIN"

def test_confirmation_ids_cannot_overlap_development_ids():
    with pytest.raises(DatasetLeakageError):
        assert_confirmatory_isolation({"x"}, {"x"})
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/semantic tests/datasets/test_split_isolation.py -v`  
Expected: FAIL because semantic and manifest APIs are absent.

- [ ] **Step 3: Implement explicit supported, unsupported, contradictory, partial, ambiguous, numerical, and citation outcomes**

Return structured reasons and `ABSTAIN`; keep development calibration separate from confirmation; tag generated datasets synthetic.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/semantic tests/datasets -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/poi_mpp/auditor/semantic src/poi_mpp/datasets tests/semantic tests/datasets && git commit -m "feat: verify grounded claims with fail-closed abstention"`

---

### Task 12: Implement E1 real single-pass cost experiment

**Files:**
- Create: `src/poi_mpp/experiments/e1_cost.py`
- Replace: `experiments/e1_single_pass_cost.py`
- Create: `tests/experiments/test_e1_cost.py`
- Create: `configs/pilot/e1.yaml`
- Create: `src/poi_mpp/reporting/e1.py`

**Interfaces:**
- Produces paired receipt rows and T6/F5 inputs.

- [ ] **Step 1: Write failing baseline-integrity tests**

```python
def test_two_run_baseline_invokes_inference_twice(counting_runner, task):
    run_two_run_baseline(counting_runner, task)
    assert counting_runner.calls == 2

def test_warmups_are_excluded_from_measured_rows(result):
    assert all(not row.is_warmup for row in result.measured_rows)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/experiments/test_e1_cost.py -v`  
Expected: FAIL because E1 library API is absent.

- [ ] **Step 3: Implement paired single, two-run, and SPAI measurement**

Write receipt-level Parquet through the evidence registry; calculate paired bootstrap interval and claim disposition; never substitute configured or synthetic time for measured time.

- [ ] **Step 4: Verify GREEN on CPU fixture**

Run: `python -m pytest tests/experiments/test_e1_cost.py -v`  
Expected: PASS with `SYNTHETIC_NON_EVIDENCE` fixture rows blocked from publication.

- [ ] **Step 5: Run authorized pilot only after config/model freeze**

Run: `python experiments/e1_single_pass_cost.py --config configs/pilot/e1.yaml`  
Expected: a run-scoped raw bundle; it remains pilot evidence and cannot be pooled into confirmation.

- [ ] **Step 6: Commit**

Run: `git add src/poi_mpp/experiments src/poi_mpp/reporting experiments/e1_single_pass_cost.py tests/experiments/test_e1_cost.py configs/pilot/e1.yaml && git commit -m "feat: measure real single-pass cost baselines"`

---

### Task 13: Implement E2 attack manifests and detection curves

**Files:**
- Create: `src/poi_mpp/experiments/e2_tamper.py`
- Create: `src/poi_mpp/attacks/execution.py`
- Replace: `experiments/e2_tamper_detection.py`
- Create: `tests/experiments/test_e2_tamper.py`
- Create: `configs/pilot/e2.yaml`
- Create: `src/poi_mpp/reporting/e2.py`

**Interfaces:**
- Produces attack-manifest-bound receipts, T7, F6, and residual-surface ledger.

- [ ] **Step 1: Write failing attack-binding tests**

```python
def test_attack_changes_target_but_not_original_commitment(honest_bundle):
    attacked, manifest = corrupt_trace_node(honest_bundle, index=0)
    assert attacked.trace_root != honest_bundle.trace_root
    assert manifest.original_commitment == honest_bundle.commitment

def test_missing_attack_manifest_is_rejected(attacked_row):
    with pytest.raises(ArtifactValidationError):
        validate_artifact(attacked_row.model_copy(update={"attack_manifest": None}))
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/experiments/test_e2_tamper.py -v`  
Expected: FAIL because attack APIs are absent.

- [ ] **Step 3: Implement the frozen attack matrix and separate exact/float analyses**

Include model root, weights, trace, tensor, response binding, indices, decode policy, cross-request splice, replay, and unsupported-kernel attacks.

- [ ] **Step 4: Verify GREEN and deterministic attack replay**

Run: `python -m pytest tests/experiments/test_e2_tamper.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/poi_mpp/attacks src/poi_mpp/experiments/e2_tamper.py src/poi_mpp/reporting/e2.py experiments/e2_tamper_detection.py tests/experiments/test_e2_tamper.py configs/pilot/e2.yaml && git commit -m "feat: measure post-commit tamper detection"`

---

### Task 14: Implement E3 confirmatory semantic evaluation

**Files:**
- Create: `src/poi_mpp/experiments/e3_semantic.py`
- Replace: `experiments/e3_semantic_eval.py`
- Create: `tests/experiments/test_e3_semantic.py`
- Create: `configs/pilot/e3.yaml`
- Create: `configs/confirmatory/e3.schema.yaml`
- Create: `src/poi_mpp/reporting/e3.py`

**Interfaces:**
- Produces T4, T8, F7, annotation provenance, calibration report, and error ledger.

- [ ] **Step 1: Write failing leakage and metric tests**

```python
def test_far_denominator_is_all_invalid_cases(records):
    result = semantic_metrics(records)
    assert result.far_denominator == sum(not r.is_valid for r in records)

def test_synthetic_confirmation_is_rejected(config):
    config.dataset.origin = "SYNTHETIC_NON_EVIDENCE"
    with pytest.raises(PublicationEligibilityError):
        run_confirmatory_semantic(config)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/experiments/test_e3_semantic.py -v`  
Expected: FAIL because confirmatory evaluator is absent.

- [ ] **Step 3: Implement development/pilot/confirmation separation and intervals**

Compute FAR, FRR, abstention, coverage, precision/recall, calibration, confusion matrices, subgroup results, and reference agreement with frozen definitions.

- [ ] **Step 4: Verify GREEN using non-evidence fixtures**

Run: `python -m pytest tests/experiments/test_e3_semantic.py -v`  
Expected: PASS while publication eligibility remains blocked.

- [ ] **Step 5: Require explicit authorization before obtaining or labeling the confirmatory dataset**

The execution owner freezes dataset license, source, manifest, annotation protocol, evaluator identities/independence basis, and privacy status before running confirmation.

- [ ] **Step 6: Commit**

Run: `git add src/poi_mpp/experiments/e3_semantic.py src/poi_mpp/reporting/e3.py experiments/e3_semantic_eval.py tests/experiments/test_e3_semantic.py configs/pilot/e3.yaml configs/confirmatory/e3.schema.yaml && git commit -m "feat: evaluate grounded semantic assurance"`

---

### Task 15: Implement E4 DA sampling and reconstruction

**Files:**
- Create: `src/poi_mpp/protocol/availability.py`
- Create: `src/poi_mpp/auditor/availability/sampling.py`
- Create: `src/poi_mpp/experiments/e4_da.py`
- Replace: `experiments/e4_da_withholding.py`
- Create: `tests/experiments/test_e4_da.py`
- Create: `src/poi_mpp/reporting/e4.py`

**Interfaces:**
- Produces static-with/without-replacement, targeted, selective-serving, and correlated-loss records, T9, and F8.

- [ ] **Step 1: Write failing formula and lifecycle tests**

```python
def test_without_replacement_uses_hypergeometric_probability():
    assert miss_probability(total=16, withheld=4, samples=8, replacement=False) == Fraction(comb(12, 8), comb(16, 8))

def test_da_failed_receipt_cannot_activate(reference_machine, receipt):
    with pytest.raises(InvalidTransition):
        reference_machine.activate(receipt.with_da_failure())
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/experiments/test_e4_da.py -v`  
Expected: FAIL because DA APIs are absent.

- [ ] **Step 3: Implement sampling certificates, local shard storage, reconstruction, and attack models**

Reject impossible configurations and label each probability assumption explicitly.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/experiments/test_e4_da.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/poi_mpp/protocol/availability.py src/poi_mpp/auditor/availability src/poi_mpp/experiments/e4_da.py src/poi_mpp/reporting/e4.py experiments/e4_da_withholding.py tests/experiments/test_e4_da.py && git commit -m "feat: test DA withholding and receipt gating"`

---

### Task 16: Implement E5 watcher and dispute economics

**Files:**
- Create: `src/poi_mpp/experiments/e5_watcher.py`
- Replace: `experiments/e5_watcher_economics.py`
- Create: `tests/experiments/test_e5_watcher.py`
- Create: `configs/confirmatory/e5.yaml`
- Create: `src/poi_mpp/reporting/e5.py`

**Interfaces:**
- Produces T10, expected-utility surfaces, invalid-maturity sensitivity, and assumption ledger.

- [ ] **Step 1: Write failing model-boundary tests**

```python
def test_correlated_watchers_do_not_use_independent_closed_form():
    with pytest.raises(ModelAssumptionError):
        independent_no_challenge_probability(correlated_scenario)

def test_negative_bond_is_rejected():
    with pytest.raises(ValueError):
        WatcherScenario(challenge_bond=-1)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/experiments/test_e5_watcher.py -v`  
Expected: FAIL because watcher model is absent.

- [ ] **Step 3: Implement scenario-explicit Monte Carlo and analytic baseline**

Cover independent, correlated outage, shared infrastructure, heterogeneous cost, collusion, fraud value, bribery/subsidy, and bonded-auditor scenarios.

- [ ] **Step 4: Verify GREEN and reproducibility**

Run: `python -m pytest tests/experiments/test_e5_watcher.py -v`  
Expected: PASS with identical seeded results and model labels.

- [ ] **Step 5: Commit**

Run: `git add src/poi_mpp/experiments/e5_watcher.py src/poi_mpp/reporting/e5.py experiments/e5_watcher_economics.py tests/experiments/test_e5_watcher.py configs/confirmatory/e5.yaml && git commit -m "feat: simulate watcher and dispute economics"`

---

### Task 17: Implement E6 Sybil and task-budget analysis

**Files:**
- Create: `src/poi_mpp/experiments/e6_sybil.py`
- Replace: `experiments/e6_sybil_economics.py`
- Create: `tests/experiments/test_e6_sybil.py`
- Create: `configs/confirmatory/e6.yaml`
- Create: `src/poi_mpp/reporting/e6.py`

**Interfaces:**
- Produces T11, F9, F10, invariant report, and boundary ledger.

- [ ] **Step 1: Write failing scheduler and credit tests**

```python
@given(identity_count=st.integers(min_value=1, max_value=64))
def test_capacity_neutral_scheduler_preserves_operator_share(identity_count):
    assert expected_share("operator-A", identities=identity_count) == expected_share("operator-A", identities=1)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/experiments/test_e6_sybil.py -v`  
Expected: FAIL because schedulers and analysis are absent.

- [ ] **Step 3: Implement unsafe and safe comparators plus ablations**

Use predeclared `epsilon_sybil`, seeded trials, confidence bounds, and cost-to-one-third-weight scenarios. Preserve cases where the proposed scheduler fails.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/experiments/test_e6_sybil.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add src/poi_mpp/experiments/e6_sybil.py src/poi_mpp/reporting/e6.py experiments/e6_sybil_economics.py tests/experiments/test_e6_sybil.py configs/confirmatory/e6.yaml && git commit -m "feat: measure Sybil and credit-budget safety"`

---

### Task 18: Implement E7 Foundry gas/state collection

**Files:**
- Create: `contracts/test/GasSnapshots.t.sol`
- Replace: `scripts/collect_gas.py`
- Create: `src/poi_mpp/experiments/e7_evm.py`
- Replace: `experiments/e7_evm_boundedness.py`
- Create: `tests/experiments/test_e7_evm.py`
- Create: `src/poi_mpp/reporting/e7.py`

**Interfaces:**
- Parses Foundry JSON output into validated `FOUNDRY_MEASUREMENT` rows; produces T12, F12, compiler/bytecode manifest, and parity report.

- [ ] **Step 1: Write failing empty-report and unit tests**

```python
def test_empty_foundry_report_is_not_success(tmp_path):
    with pytest.raises(ArtifactValidationError):
        parse_foundry_gas_report(tmp_path / "empty.json")

def test_gas_and_storage_units_are_explicit(parsed_rows):
    assert all(r.gas_unit == "gas" and r.storage_unit == "bytes" for r in parsed_rows)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/experiments/test_e7_evm.py -v`  
Expected: FAIL because collector is a placeholder.

- [ ] **Step 3: Implement representative calls, batches, state deltas, and JSON parsing**

Measure registration, task, commitment, audit, challenge, receipt, credit, and multiple batch sizes. Capture compiler, optimizer, bytecode, chain, block-gas configuration, and Foundry version.

- [ ] **Step 4: Verify GREEN**

Run: `cd contracts && forge test --match-contract GasSnapshots --gas-report -vv`  
Run: `python -m pytest tests/experiments/test_e7_evm.py -v`  
Expected: PASS and non-empty measured rows.

- [ ] **Step 5: Commit**

Run: `git add contracts/test/GasSnapshots.t.sol scripts/collect_gas.py src/poi_mpp/experiments/e7_evm.py src/poi_mpp/reporting/e7.py experiments/e7_evm_boundedness.py tests/experiments/test_e7_evm.py && git commit -m "feat: collect bounded EVM gas and state evidence"`

---

### Task 19: Implement E8 next-epoch committee simulation

**Files:**
- Create: `src/poi_mpp/experiments/e8_consensus.py`
- Replace: `experiments/e8_consensus_weight_sim.py`
- Create: `tests/experiments/test_e8_consensus.py`
- Create: `configs/confirmatory/e8.yaml`
- Create: `src/poi_mpp/reporting/e8.py`

**Interfaces:**
- Produces T13, F11, committee histories, threshold probabilities, and assumption ledger.

- [ ] **Step 1: Write failing maturity, epoch, and probability tests**

```python
def test_pending_receipt_contributes_no_weight(simulator, pending_receipt):
    assert simulator.weight_from([pending_receipt]) == 0

def test_same_seed_produces_same_committee(simulator):
    assert simulator.sample(seed=9) == simulator.sample(seed=9)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/experiments/test_e8_consensus.py -v`  
Expected: FAIL because simulator is absent.

- [ ] **Step 3: Implement honest/adversarial scenarios and cap ablations**

Include high-compute, Sybil, collateral-rich no-credit, subsidized compute, collusion, missing receipts, churn, and concentration-cap ablation. Reject zero-total-weight epochs with a typed disposition.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/experiments/test_e8_consensus.py -v`  
Expected: PASS with deterministic histories and valid probabilities.

- [ ] **Step 5: Commit**

Run: `git add src/poi_mpp/experiments/e8_consensus.py src/poi_mpp/reporting/e8.py experiments/e8_consensus_weight_sim.py tests/experiments/test_e8_consensus.py configs/confirmatory/e8.yaml && git commit -m "feat: simulate bounded next-epoch PoI weight"`

---

### Task 20: Generate deterministic tables, figures, and manifests

**Files:**
- Create: `src/poi_mpp/reporting/load.py`
- Create: `src/poi_mpp/reporting/statistics.py`
- Create: `src/poi_mpp/reporting/tables.py`
- Create: `src/poi_mpp/reporting/figures.py`
- Create: `src/poi_mpp/reporting/manifest.py`
- Replace: `scripts/generate_figures.py`
- Replace: `scripts/report_all.py`
- Modify: `scripts/build_artifact_manifest.py`
- Create: `tests/reporting/`

**Interfaces:**
- Consumes only validated raw artifacts and produces T4/T6-T13, F5-F12, claim matrix, and hash manifest.

- [ ] **Step 1: Write failing provenance and determinism tests**

```python
def test_report_rejects_manual_or_synthetic_measurement(raw_bundle):
    raw_bundle.rows[0].origin = "SYNTHETIC_NON_EVIDENCE"
    with pytest.raises(PublicationEligibilityError):
        build_publication_report(raw_bundle)

def test_same_inputs_produce_identical_table_bytes(valid_bundle):
    assert render_tables(valid_bundle) == render_tables(valid_bundle)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/reporting -v`  
Expected: FAIL because reporting implementation is absent.

- [ ] **Step 3: Implement schema-aware load, statistics, editable tables, vector figures, and manifest**

Every table row includes denominator and uncertainty where applicable. Every figure stores source artifact hashes. Use stable sort order, fixed fonts, deterministic metadata, and explicit simulation labels.

- [ ] **Step 4: Verify GREEN and regeneration hashes**

Run: `python -m pytest tests/reporting -v`  
Expected: PASS with identical outputs from identical inputs.

- [ ] **Step 5: Commit**

Run: `git add src/poi_mpp/reporting scripts tests/reporting && git commit -m "feat: generate deterministic publication artifacts"`

---

### Task 21: Implement the real end-to-end MPP and failure journeys

**Files:**
- Create: `src/poi_mpp/orchestration/run_mpp.py`
- Create: `scripts/run_mpp.py`
- Replace: `scripts/run_all.sh`
- Create: `tests/e2e/test_happy_path.py`
- Create: `tests/e2e/test_failure_paths.py`
- Create: `configs/e2e/local.yaml`

**Interfaces:**
- Produces one real task-to-committee artifact chain and required rejected/abstained/slashed paths.

- [ ] **Step 1: Write failing happy-path acceptance test**

```python
def test_task_to_next_epoch_committee(local_stack):
    result = local_stack.run_grounded_task()
    assert result.receipt.state == "ACTIVE"
    assert result.next_epoch_weight > 0
    assert result.artifact_chain.is_closed()
```

- [ ] **Step 2: Write failing failure-path tests**

Cover execution rejection, semantic abstention, DA failure, successful challenge/slashing, service-task no-credit, and replay rejection.

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/e2e -v`  
Expected: FAIL because orchestrator and integrated stack are absent.

- [ ] **Step 4: Implement the smallest integrated orchestration**

Start and stop Anvil safely, deploy contracts, run the pinned local model, capture trace/IEC, commit, derive audit, submit dispositions, mature or reject receipt, allocate prior-epoch credit, sample committee, and write artifacts atomically.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/e2e -v`  
Expected: PASS for the happy path and all six failure journeys.

- [ ] **Step 6: Commit**

Run: `git add src/poi_mpp/orchestration scripts/run_mpp.py scripts/run_all.sh tests/e2e configs/e2e/local.yaml && git commit -m "feat: complete local task-to-committee MPP"`

---

### Task 22: Reproduce from a clean environment and freeze the publication bundle

**Files:**
- Create: `scripts/reproduce.py`
- Create: `scripts/verify_bundle.py`
- Create: `tests/reproducibility/test_clean_replay.py`
- Modify: `docs/REPRODUCIBILITY_CHECKLIST.md`
- Modify: `docs/PAPER_ARTIFACT_MAP.md`
- Modify: `docs/MAIN_RESULTS_TARGETS.md`
- Modify: `README.md`

**Interfaces:**
- Produces `results/frozen/<run_id>/manifest.json`, claim-support matrix, verification report, and `MPP_ARTIFACT_COMPLETE` only when every completeness gate passes.

- [ ] **Step 1: Write failing bundle-verification tests**

```python
def test_bundle_fails_when_one_required_experiment_is_missing(valid_bundle):
    valid_bundle.remove_experiment("E7")
    assert verify_bundle(valid_bundle).status == "INCOMPLETE"

def test_bundle_preserves_not_supported_claim(valid_negative_bundle):
    report = verify_bundle(valid_negative_bundle)
    assert report.completeness == "COMPLETE"
    assert report.claims["C1"] == "NOT_SUPPORTED"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/reproducibility/test_clean_replay.py -v`  
Expected: FAIL because reproduction and bundle verification are absent.

- [ ] **Step 3: Implement argv-only reproduction and fail-closed bundle verification**

Record commands, tool versions, environment lock, configs, model/dataset manifests, raw/derived hashes, logs, warnings, and claim dispositions. Never source untrusted shell text or execute commands from an artifact.

- [ ] **Step 4: Verify GREEN with the complete suite and reproduction workflow**

Run: `make test-all`  
Expected: all Python and Foundry tests PASS.  
Run: `make reproduce`  
Expected: frozen bundle created only from authorized evidence.  
Run: `python scripts/verify_bundle.py results/frozen/<run_id>`  
Expected: `MPP_ARTIFACT_COMPLETE` with per-claim `SUPPORTED`, `NOT_SUPPORTED`, or `INCONCLUSIVE`.

- [ ] **Step 5: Perform manual scientific and rendered-artifact review**

Verify denominators, intervals, negative findings, simulation labels, table editability, figure accessibility, manuscript claim alignment, and absence of production-readiness language. Record accountable reviewer and date; do not convert this review into independent scientific validation unless the reviewer satisfies the declared independence and expertise criteria.

- [ ] **Step 6: Commit the reproducibility implementation and reviewed documentation**

Run: `git add scripts/reproduce.py scripts/verify_bundle.py tests/reproducibility README.md docs/REPRODUCIBILITY_CHECKLIST.md docs/PAPER_ARTIFACT_MAP.md docs/MAIN_RESULTS_TARGETS.md && git commit -m "feat: freeze reproducible PoI MPP artifact bundle"`

---

## Execution order and phase gates

| Phase | Tasks | Gate before advancing |
|---|---|---|
| Foundation | 1-4 | Evidence records, hashes, provenance, and publication gates pass |
| Protocol | 5-8 | Python properties, Foundry invariants, and parity vectors pass |
| Worker/auditor | 9-11 | Deterministic CPU fixtures, trace/IEC, exact/float separation, semantic isolation pass |
| Empirical slices | 12-15 | E1-E4 completeness gates pass; pilots remain separate |
| Economic/EVM/consensus slices | 16-19 | E5-E8 completeness gates pass with correct simulation/measurement labels |
| Reporting | 20 | Deterministic tables, figures, and manifests regenerate |
| Integration | 21 | Happy path plus all six failure journeys pass |
| Freeze | 22 | Clean replay and publication bundle verification pass |

Do not begin a confirmatory evidence run merely because its software task is green. Confirmation additionally requires a frozen protocol, approved evidence-acquisition authority, dataset/model/license review, sample-size and analysis specification, and a clean pilot-to-confirmation separation.
