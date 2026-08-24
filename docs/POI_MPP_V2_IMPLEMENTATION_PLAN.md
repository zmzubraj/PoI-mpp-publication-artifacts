# PoI MPP V2 Implementation Plan

## Scientific Strengthening, Registry-Backed Semantic Assurance, and Repeatable E1-E8 Evidence

**Document role:** Canonical V2 implementation plan
**Repository scope:** First-publication PoI Minimum Publishable Prototype
**Implementation method:** Evidence-gated, test-driven, RED-GREEN-REFACTOR
**Primary architectural decision:** Preserve the Solidity and protocol core; bind semantic authority, policy, dataset, claim, model, and runtime state through a canonical `taskRoot` envelope.
**Scientific rule:** This plan makes each claim eligible for prospective support. It does not pre-assign `SUPPORTED`; measured results and frozen decision rules determine the disposition.

---

## 1. Objective

Strengthen the existing PoI MPP so that:

1. C1-C8 are expressed as versioned, falsifiable, scope-bounded claims;
2. every claim is tested by a sufficiently informative, reproducible experiment;
3. C3-v2 uses registry-backed, calibrated, grounded semantic assurance;
4. development and confirmatory evidence remain strictly separated;
5. real execution, Foundry measurement, reproducible simulation, and synthetic plumbing are never conflated;
6. every result can be regenerated deterministically from raw artifacts;
7. external authority, execution, attestation, and independent reproduction remain hash-bound and fail closed; and
8. negative and inconclusive results are preserved rather than rewritten as support.

The intended outcome is a stronger first-publication MPP, not a production consensus system.

---

## 2. Frozen publication boundary

### Included

- 1B-8B open-weight models;
- one primary 1B-3B model and an optional separately reported 7B-8B scaling model;
- local Python execution environment;
- local EVM using Foundry/Anvil;
- evidence kernel and protocol lifecycle;
- E1-E8 reproducible experiment artifacts;
- external authority and result-attestation contracts;
- deterministic raw-to-table/figure/manuscript replay.

### Deferred

- 70B or larger models;
- MoE/distributed serving;
- confidential GPU/TEE execution;
- production-grade dispute VM;
- production data-availability network;
- production consensus client;
- mainnet performance or security claims.

---

## 3. Current evidence baseline

The existing evidence remains immutable history.

| Claim | Experiment | Current disposition | V2 action |
|---|---|---|---|
| C1 | E1 single-pass cost | `INCONCLUSIVE` | Run counterbalanced paired C1-v2 experiment |
| C2 | E2 execution audit | `INCONCLUSIVE` | Expand attack families and confirmatory trials |
| C3 | E3 semantic assurance | `NOT_SUPPORTED` | Preserve C3-v1; build and test C3-v2 prospectively |
| C4 | E4 data availability | `INCONCLUSIVE` | Add executable withholding/reconstruction evidence |
| C5 | E5 watcher economics | scoped `SUPPORTED` simulation | Preserve through sensitivity and clean replay |
| C6 | E6 Sybil/task-budget safety | scoped `SUPPORTED` simulation | Preserve through additional scenarios and replay |
| C7 | E7 local EVM boundedness | scoped `SUPPORTED` local measurement | Preserve through fresh Foundry/parity evidence |
| C8 | E8 next-epoch dynamics | `INCONCLUSIVE` simulation | Run frozen multi-epoch C8-v2 scenario suite |

The historical C3-v1 result remains:

- FAR `0.500 (1/2)`;
- FRR `0.167 (1/6)`;
- ABSTAIN `0.125 (1/8)`;
- coverage `0.875 (7/8)`;
- Brier calibration `0.178`;
- frozen `alpha_sem = 0.25`;
- C3-v1 disposition `NOT_SUPPORTED`.

No V2 result may overwrite or silently replace this record.

---

## 4. Architectural decision

### 4.1 Stable core

The following components remain conceptually stable:

- response commitment;
- post-commit audit compilation;
- challenge and data-availability gates;
- receipt lifecycle;
- task-budgeted credit;
- next-epoch weight calculation;
- existing EVM role and dependency boundaries.

### 4.2 Canonical `taskRoot` envelope

Create a canonical off-chain `TaskEnvelopeV2` whose digest becomes the existing `taskRoot`:

```text
TaskEnvelopeV2
├── schema_version
├── claim_spec_hash
├── task_payload_hash
├── semantic_policy_hash
├── dataset_manifest_hash
├── authority_registry_snapshot_hash
├── model_manifest_hash
├── runtime_environment_hash
├── evidence_origin_policy_hash
├── experiment_protocol_hash
└── expiry / epoch / scope bindings
          ↓ canonical serialization
          ↓ domain-separated hash
        taskRoot
```

This design:

- binds the complete scientific and semantic contract before execution;
- preserves the existing Solidity `bytes32 taskRoot` interface;
- avoids a first-publication contract migration;
- allows Python and Solidity to verify the same root;
- makes threshold, dataset, authority, or model substitution detectable.

An explicit on-chain semantic registry is deferred unless the V2 threat model proves that the hash-bound snapshot is insufficient for the first-publication claim.

### 4.3 Receipt semantics

The protocol must enforce:

| Semantic decision | Receipt effect | Credit effect |
|---|---|---|
| `ACCEPT` | May proceed if all other gates pass | Eligible only after maturity |
| `REJECT` | Receipt rejected | No credit |
| `ABSTAIN` | Receipt enters abstained state | No credit |
| Authority/policy/hash mismatch | Fail closed | No credit |

Collateral, signature possession, or execution completion may never compensate for a failed semantic or evidence gate.

---

## 5. Evidence kernel V2

### 5.1 Canonical objects

Implement the following immutable, extra-forbid schemas.

#### `ClaimSpecV2`

- claim ID and revision;
- exact admissible wording;
- model, task, environment, and experiment scope;
- evidence-maturity ceiling;
- primary metrics and denominators;
- thresholds and confidence-interval method;
- `SUPPORTED`, `INCONCLUSIVE`, and `NOT_SUPPORTED` rules;
- required artifacts;
- prohibited generalizations.

#### `DatasetManifestV2`

- stable record ID;
- source and content hashes;
- license and privacy status;
- development or confirmatory split;
- expected `ACCEPT`, `REJECT`, or `ABSTAIN` decision;
- expected semantic outcome;
- error/attack family;
- subgroup and difficulty;
- annotation provenance and agreement;
- deterministic deduplication group;
- evidence-origin label.

#### `SemanticAuthorityRecordV1`

- authority and key identifiers;
- accountable identity-binding reference;
- capability and dataset scope;
- claim and metric scope;
- valid-from, valid-until, and revocation state;
- registry revision and snapshot hash;
- detached signature and signature namespace;
- independence basis and unresolved out-of-band checks.

#### `ExecutionEnvironmentManifestV1`

- model and tokenizer hashes;
- runtime and dependency lock hashes;
- hardware and driver inventory;
- generation parameters;
- random seeds;
- script and configuration hashes;
- environment/SBOM digest;
- network and external-service declaration.

### 5.2 Evidence-origin policy

Allowed publication evidence:

- `REAL_MODEL_EXECUTION`;
- `FOUNDRY_MEASUREMENT`;
- `REPRODUCIBLE_SIMULATION`.

Allowed only for plumbing:

- `SYNTHETIC_NON_EVIDENCE`.

Synthetic data must never satisfy a publication claim, populate a measured paper result, or be promoted by a missing label.

### 5.3 Proposed implementation surfaces

New files:

- `src/poi_mpp/evidence/claim_spec.py`
- `src/poi_mpp/evidence/dataset_manifest_v2.py`
- `src/poi_mpp/evidence/environment_manifest.py`
- `src/poi_mpp/auditor/semantic/authority.py`
- `src/poi_mpp/auditor/semantic/policy_v2.py`
- `src/poi_mpp/protocol/task_envelope.py`

Existing files to extend:

- `src/poi_mpp/evidence/registry.py`
- `src/poi_mpp/evidence/validation.py`
- `src/poi_mpp/auditor/semantic/models.py`
- `src/poi_mpp/auditor/semantic/verifier.py`
- `src/poi_mpp/protocol/types.py`
- `src/poi_mpp/protocol/commitment.py`

The implementation must reuse the canonical evidence and hashing utilities rather than creating parallel trust logic.

---

## 6. Semantic assurance kernel V2

### 6.1 Three-stage decision pipeline

```text
Stage 1: Evidence integrity
  - canonical schema and hashes
  - citation closure
  - active authority and capability scope
  - dataset, claim, model, runtime, and policy bindings
  - license/privacy/evidence-origin gates
                    ↓
Stage 2: Claim verification
  - explicit support
  - contradiction detection
  - numeric expectation checks
  - missing or irrelevant evidence
  - partial-support and dependency checks
                    ↓
Stage 3: Calibrated decision
  - ACCEPT
  - REJECT
  - ABSTAIN
```

### 6.2 Decision rules

- hard contradiction -> `REJECT`;
- required evidence missing -> `REJECT`;
- citation/hash/authority failure -> fail closed;
- insufficient confidence or unresolved disagreement -> `ABSTAIN`;
- `ACCEPT` only when every required claim-level obligation passes;
- calibration uses development data only;
- confirmatory execution cannot mutate thresholds, prompts, labels, or policy;
- response-level output and trace-level decision must agree exactly.

### 6.3 Error ledger

Every run must preserve:

- false accept;
- false reject;
- correct abstention;
- incorrect abstention;
- outcome mismatch;
- citation error;
- contradiction miss;
- numeric-check failure;
- authority or provenance failure;
- subgroup and attack-family attribution.

---

## 7. E3-v2 scientific design

### 7.1 Development set

Use 120-150 development items. These are not confirmatory publication evidence.

Suggested composition:

- 50 acceptable grounded responses;
- 50 invalid, unsupported, or contradicted responses;
- 20-50 ambiguous, underdetermined, and adversarial cases.

Use only this split to select:

- confidence thresholds;
- contradiction policy;
- prompts and output schema;
- abstention behavior;
- calibration mapping;
- error-recovery behavior.

### 7.2 Confirmatory set

Freeze 500 untouched confirmatory items:

| Reference class | Count | Expected decision |
|---|---:|---|
| Acceptable grounded | 200 | `ACCEPT` |
| Invalid/unsupported/contradicted | 200 | `REJECT` |
| Ambiguous/underdetermined | 100 | `ABSTAIN` |

Invalid cases must cover:

- factual contradiction;
- unsupported assertion;
- irrelevant or incorrect citation;
- numeric inconsistency;
- partial support presented as full support;
- missing evidence;
- evidence withholding;
- persuasive adversarial falsehood.

### 7.3 Annotation protocol

- two blinded independent annotators where feasible;
- adjudication for disagreement;
- annotators do not see verifier output;
- source licensing and privacy reviewed before inclusion;
- near-duplicates grouped and removed deterministically;
- development and confirmatory source separation checked;
- annotation agreement reported with denominators;
- accountable identity and independence verified out of band.

### 7.4 Frozen primary gate

Preserve:

- FAR 95% Wilson upper bound `<= 0.25`;
- FRR 95% Wilson upper bound `<= 0.25`;
- useful coverage `>= 0.50`;
- ABSTAIN and Brier calibration reported separately;
- predefined subgroup and attack-family reporting.

With 200 invalid and 200 acceptable cases, the design should target a safety margin near 10-15% FAR/FRR rather than merely reaching the 25% boundary.

### 7.5 Model scope

- primary result: one frozen 1B-3B open-weight model;
- optional scaling result: one separately frozen 7B-8B model;
- do not pool model strata into a general 1B-8B claim;
- report each model/configuration independently;
- cross-model generality requires an explicitly broader future claim.

### 7.6 External execution lifecycle

```text
Freeze claim + dataset + policy + environment
                 ↓
Build canonical request manifest/package
                 ↓
External pre-execution review and detached signature
                 ↓
Canonical authority verification
                 ↓
Authorized REAL_MODEL_EXECUTION
                 ↓
Deterministic T4/T8/F7/raw generation
                 ↓
External post-execution result attestation
                 ↓
Canonical attestation verification
                 ↓
Versioned import and independent reproduction
```

No external file may be overwritten in place. Every V2 authority, execution, and attestation must have a distinct run directory and immutable hashes.

---

## 8. E1-E8 strengthening matrix

### E1 / C1-v2 — Counterbalanced single-pass cost

Design:

- 1,000 paired receipts where feasible;
- randomized AB/BA execution order;
- block by prompt, model, hardware, and batch;
- freeze warm-up and exclusion rules;
- native single run, two-run baseline, and SPAI single-pass comparison.

Metrics:

- paired latency delta;
- compute time;
- trace/evidence bytes;
- audit time;
- expected dispute cost;
- uncertainty interval.

Allowed support scope: tested model, runtime, hardware, and task distribution only.

### E2 / C2-v2 — Execution-audit soundness

Design:

- at least 500 frozen tamper trials;
- honest negative controls;
- exact tensor, trace, commitment, serialization, and field-arithmetic attacks;
- multiple frozen sampling fractions and Freivalds rounds;
- held-out confirmatory attack families.

Metrics:

- detection and escape rates;
- false-positive rate;
- exact-field theoretical bound;
- floating-point empirical behavior reported separately;
- audit cost.

### E4 / C4-v2 — Executable data availability

Add a local executable harness for:

- deterministic sharding;
- shard retention;
- random and targeted withholding;
- post-commit sampling;
- reconstruction attempts;
- corrupted, missing, duplicated, and reordered shard cases.

Compare empirical miss/reconstruction behavior with the frozen theoretical model. The claim remains local and experimental, not production DA security.

### E5 / C5 — Watcher economics preservation

- at least 1,000 deterministic seeds;
- independent and correlated watcher failure;
- shared-infrastructure sensitivity;
- fraud-value and reward sweeps;
- negative controls;
- clean-room replay.

The disposition remains simulation-scoped.

### E6 / C6 — Sybil/task-budget preservation

- additional seeds and scheduler variants;
- identity-uniform and capacity-committed allocation;
- collusion and subsidized-compute scenarios;
- task-budget conservation;
- concentration sensitivity;
- negative controls and replay.

The disposition remains simulation-scoped.

### E7 / C7 — Local EVM boundedness and parity

- fresh Foundry/Anvil measurement;
- repeated gas snapshots and batch sizes;
- fuzz and invariant tests;
- state-growth measurements;
- Python-Solidity hash vectors;
- replay, duplicate receipt, lifecycle, and `Q=0 => W=0` probes;
- toolchain and environment manifest.

The disposition remains local-Foundry scoped.

### E8 / C8-v2 — Next-epoch dynamics

- 1,000 epochs and multiple deterministic seeds;
- committee-size sensitivity;
- honest, Sybil, collusion, subsidized-compute, churn, and missing-receipt modes;
- concentration-cap and beta ablations;
- `Q=0 => W=0` invariant;
- Byzantine-weight threshold analysis;
- frozen scenario matrix and negative controls.

The admissible claim is reproducible simulated dynamics, not production consensus security.

---

## 9. TDD implementation contract

Every implementation task follows RED-GREEN-REFACTOR and closes with a publication gate.

### RED: adversarial tests first

Required new test surfaces:

- `tests/evidence/test_claim_spec_v2.py`
- `tests/evidence/test_dataset_manifest_v2.py`
- `tests/evidence/test_environment_manifest.py`
- `tests/semantic/test_authority_registry.py`
- `tests/semantic/test_policy_v2.py`
- `tests/semantic/test_verifier_v2.py`
- `tests/protocol/test_task_envelope_v2.py`
- `tests/experiments/test_e3_v2_contract.py`
- `tests/reproducibility/test_e3_v2_authority.py`
- `tests/reproducibility/test_e3_v2_attestation.py`
- `tests/reproducibility/test_e3_v2_clean_replay.py`

Adversarial cases must include:

- forged, expired, and revoked authority;
- wrong key, capability, dataset, claim, metric, or artifact scope;
- stale registry snapshot;
- task/policy/model/runtime hash mismatch;
- development-confirmatory leakage;
- duplicate and near-duplicate records;
- missing license/privacy status;
- unsigned annotations;
- threshold or prompt mutation after freeze;
- output/trace decision disagreement;
- symlinked or repository-local trust material;
- artifact overwrite and path traversal;
- replayed authority or attestation;
- synthetic evidence promotion;
- receipt activation after `REJECT` or `ABSTAIN`.

### GREEN: minimum correct implementation

Implement only enough production behavior to satisfy the frozen contracts and adversarial tests. Do not weaken a test to accommodate an implementation shortcut.

### REFACTOR

- centralize canonical serialization and trust checks;
- remove duplicated authority logic;
- preserve deterministic ordering;
- normalize structured failure reasons;
- keep backward-compatible V1 readers where needed;
- prevent V1 history from being rewritten as V2 evidence.

### Publication gate

For each vertical slice:

- focused unit tests;
- integration tests;
- full Python suite;
- full Foundry suite where applicable;
- Python-Solidity parity;
- canonical artifact verification;
- deterministic replay;
- independent read-only engineering review;
- explicit scientific disposition.

---

## 10. Ordered implementation phases

### Phase 0 — Baseline reconciliation

Objective: establish a clean immutable starting point.

Tasks:

1. preserve the current C3-v1 negative result and verification receipt;
2. quarantine stale or mismatched external authority/attestation files;
3. verify the repository request manifest with the canonical authority builder;
4. create versioned external exchange paths for V2;
5. record current claim matrix and artifact-manifest hashes;
6. run focused and integrated baseline checks.

Gate: no unresolved overwrite, stale-signature, output/trace, or manifest-lineage ambiguity enters V2.

### Phase 1 — V2 evidence contracts

Objective: implement claim, dataset, authority, environment, and task-envelope schemas.

Gate: adversarial schema, hashing, provenance, and backward-compatibility tests pass.

### Phase 2 — Semantic kernel V2

Objective: implement registry-backed three-stage semantic verification.

Gate: forged trust and scope bypasses fail; tri-state decisions and receipt consequences are deterministic.

### Phase 3 — E3 development and calibration

Objective: build the development set and freeze policy/configuration.

Gate: calibration is justified, error taxonomy reviewed, and no confirmatory item has been inspected or reused.

### Phase 4 — E3 confirmatory dataset

Objective: construct, annotate, adjudicate, deduplicate, and freeze 500 items.

Gate: manifest closure, licensing/privacy, class balance, agreement, independence, and hash checks pass.

### Phase 5 — E3 external execution

Objective: obtain fresh pre-execution authority, execute the real model, attest results, and import deterministically.

Gate: both canonical external verifiers pass; metrics determine C3-v2 disposition without manual override.

### Phase 6 — E1/E2/E4/E8 strengthening

Objective: replace weak pilot/simulation surfaces with the frozen V2 designs described above.

Gate: each experiment has sufficient direct evidence for its exact scoped claim or remains honestly inconclusive/not supported.

### Phase 7 — E5/E6/E7 preservation

Objective: rerun and independently reproduce the existing supported scoped claims.

Gate: fresh reproducible artifacts agree with the frozen contracts and disclose scope limits.

### Phase 8 — Integrated publication replay

Objective: regenerate all tables, figures, claim matrices, limitations, and manuscript surfaces from canonical artifacts.

Gate:

- raw -> processed -> table/figure -> manuscript replay passes;
- negative and inconclusive evidence is preserved;
- no claim exceeds its measured scope;
- external reproduction package is complete;
- rendered DOCX/PDF and figure/table QA pass;
- accountable human approval remains separate.

---

## 11. Verification commands and evidence

The exact command set must be confirmed against the repository at execution time. The minimum evidence suite is:

```text
Focused V2 tests
Full pytest suite
Python compile/import checks
Full forge test suite
Gas snapshots
Python-Solidity parity vectors
Canonical authority verification
Canonical result-attestation verification
Artifact-manifest verification
Clean deterministic reproduction
DOCX/PDF render and visual inspection
Independent read-only engineering review
```

Passing tests prove implementation behavior only. They do not prove semantic reliability, evaluator independence, real-world validity, or publication readiness.

---

## 12. Timeline and critical dependencies

| Phase | Estimated effort | Critical dependency |
|---|---:|---|
| P0 baseline reconciliation | 2-3 days | stable repository and external exchange history |
| P1 evidence contracts | 5-8 days | frozen V2 schemas |
| P2 semantic kernel | 5-8 days | P1 contracts |
| P3 development/calibration | 1-2 weeks | model access and development annotations |
| P4 500-item confirmatory set | 2-4 weeks | sources, licensing, two annotators, adjudication |
| P5 external E3-v2 execution | 2-5 days plus waiting | evaluator availability and fresh signatures |
| P6 weak-claim strengthening | 2-4 weeks | compute and experiment-specific harnesses |
| P7 supported-claim preservation | 1-2 weeks | Foundry and clean replay environment |
| P8 publication replay/QA | 3-7 days | all upstream artifacts final |

Engineering-only work is expected to be smaller than the scientific evidence-acquisition work. External annotation, authority, and independent reproduction are calendar-dependent and cannot be completed by local code alone.

---

## 13. Gate table

| Gate | Required disposition to advance |
|---|---|
| Current external E3 lineage | `VERIFIED` historical baseline or quarantined mismatch |
| V2 schemas and hashing | `COMPLETE` |
| Registry-backed semantic authority | `COMPLETE` engineering + external identity binding |
| Development calibration | `COMPLETE`, non-confirmatory |
| 500-item dataset | `COMPLETE` and frozen |
| Pre-execution authority | `VERIFIED` external |
| E3-v2 execution | `REAL_MODEL_EXECUTION` |
| Result attestation | `VERIFIED` external |
| C3-v2 disposition | Computed from frozen rule |
| C1/C2/C4/C8 | `SUPPORTED`, `INCONCLUSIVE`, or `NOT_SUPPORTED` without override |
| C5/C6/C7 replay | scoped support preserved or downgraded honestly |
| Independent reproduction | `WAITING_EXTERNAL` until authenticated evidence arrives |
| Final PDF/portal approval | `WAITING_USER` until accountable review |

---

## 14. Definition of done

The V2 implementation is complete only when:

1. the task envelope binds claim, policy, dataset, authority, model, runtime, and protocol hashes;
2. semantic authority is registry-backed, scoped, signed, versioned, and revocable;
3. the verifier implements evidence integrity, claim checks, and calibrated tri-state decisions;
4. development and confirmatory data are demonstrably separate;
5. E3-v2 has 500 frozen items and an externally authorized real execution;
6. every E1-E8 result has raw provenance and deterministic paper artifacts;
7. Python-Solidity parity and Foundry measurements are fresh;
8. all synthetic inputs remain `SYNTHETIC_NON_EVIDENCE`;
9. current and historical negative results remain visible;
10. independent reproduction and accountable human approval are not impersonated by AI or local tests.

The manuscript may state that a claim is `SUPPORTED` only when its own frozen gate passes. It may never claim that all PoI architecture, semantic reliability, or production consensus security is universally supported.

---

## 15. Immediate first implementation batch

After explicit execution approval, begin with one bounded RED-GREEN-REFACTOR batch:

1. add failing tests for `ClaimSpecV2` and `TaskEnvelopeV2`;
2. implement canonical domain-separated serialization and hashing;
3. add Python-Solidity parity vectors using the existing `taskRoot` interface;
4. add forged/mutated-field adversarial tests;
5. run focused Python and Foundry checks;
6. obtain an independent read-only engineering review;
7. freeze the schema revision before starting the authority registry.

This batch establishes the root binding on which all later semantic and experiment evidence depends.

---

## 16. Implementation checkpoint — Phase 1

**Checkpoint date:** 2026-08-25
**Engineering gate:** `COMPLETE`
**Scientific claim effect:** none; C3-v1 remains `NOT_SUPPORTED` and C3-v2 remains prospective.

Implemented and hash-bound:

- `ClaimSpecV2` with exact wording, scope, maturity, metric, artifact, and disjoint decision-rule contracts;
- `DatasetManifestV2` with split/origin boundaries, annotation provenance, deterministic ordering, and rooted path/symlink rejection;
- `ExecutionEnvironmentManifestV1` with pinned open-weight 1B-8B model/tokenizer state, runtime/SBOM, deterministic generation, local-only execution, and mandatory runner/exporter/protocol/config hashes;
- `SemanticAuthorityRecordV1` with revocation/time/scope bindings, canonical signature metadata, separate identity/independence/key-custody gates, canonical-verifier input, and exact `LIMITED_SCOPE` metric/artifact equality;
- `TaskEnvelopeV2` with domain-separated canonical hashing, complete scientific bindings, and `expiry > epoch`;
- Python-Solidity task-root parity using the existing `bytes32 taskRoot` interface.

Verification evidence:

- focused Phase-1 Python suite: `88 passed`;
- authority/rule/environment/expiry remediation suite: `51 passed`;
- Foundry `HashVectors`: passed;
- `git diff --check`: passed;
- independent read-only static review: initial four findings remediated; final authority-decision follow-up passed.

This checkpoint closes only the Phase-1 engineering contract. It does not establish semantic reliability, external evaluator identity or independence, a 500-item confirmatory dataset, authorized C3-v2 execution, independent reproduction, or submission readiness.
