# PoI Minimum Publishable Prototype Publication-Artifact Design

**Status:** Approved design specification  
**Design date:** 2026-08-20  
**Workspace:** `/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace`  
**Primary objective:** Build the smallest test-driven, end-to-end Proof of Intelligence implementation that produces reproducible research artifacts for E1-E8 without overstating unexecuted, synthetic, or simulated evidence.

## 1. Scope

The first publication MPP is limited to:

- one 1B-3B open-weight primary model;
- one optional 7B-8B open-weight scaling model;
- objective (`O`) and grounded (`G`) task classes;
- a local EVM using Foundry and Anvil;
- one real task-to-receipt vertical slice;
- E1-E8 reproducible experiments;
- deterministic publication tables, figures, and manifests;
- explicit negative, inconclusive, and residual-risk reporting.

The following are post-MPP work and cannot block the first publication artifact package:

- 70B or larger model evaluation;
- distributed or mixture-of-experts execution;
- confidential GPU or TEE execution;
- production-grade interactive dispute VM;
- production decentralized data availability;
- production HotStuff or custom-L1 deployment;
- universal open-semantic Proof of Intelligence;
- mandatory full per-response zkML.

## 2. Experience and evidence thesis

The MPP must demonstrate the following bounded path:

```text
Task
-> one model execution
-> trace and IEC
-> finalized commitment
-> post-commit audit
-> challenge and DA gates
-> matured receipt
-> bounded next-epoch PoI weight
-> reproducible E1-E8 artifacts
```

No component may convert its own output into publication evidence. Evidence becomes publication-eligible only through the shared evidence kernel and independent validation rules.

## 3. Approved architecture

The implementation uses an artifact-first vertical-slice architecture with three foundational layers.

### 3.1 Evidence kernel

The evidence kernel owns canonical schemas, hashing, configuration freeze, provenance, artifact validation, lifecycle state, and publication eligibility.

Canonical evidence origins are:

```text
REAL_MODEL_EXECUTION
FOUNDRY_MEASUREMENT
REPRODUCIBLE_SIMULATION
SYNTHETIC_NON_EVIDENCE
```

Every run and receipt record must contain:

- schema version;
- run ID and experiment ID;
- model, dataset, configuration, and environment identifiers and hashes;
- Git commit when the workspace becomes Git-controlled;
- input, response, trace, evidence, and artifact roots;
- seed and audit parameters;
- evidence origin;
- hardware and software environment;
- authorization scope;
- validation disposition;
- parent artifact hashes;
- wall-clock timestamp and monotonic duration.

Artifact lifecycle:

```text
GENERATED
-> SCHEMA_VALID
-> SEMANTICALLY_VALID
-> FROZEN
-> PUBLICATION_ELIGIBLE
```

`SYNTHETIC_NON_EVIDENCE` may reach `SEMANTICALLY_VALID`, but never `FROZEN` or `PUBLICATION_ELIGIBLE`.

### 3.2 Protocol kernel

The protocol kernel owns the canonical task, commitment, audit, availability, challenge, receipt, credit, and next-epoch weight rules.

Two implementations must conform to the same vectors:

- Python reference state machine for property tests and experiment orchestration;
- Solidity contracts for EVM behavior and gas/state measurement.

Canonical lifecycle:

```text
TASK_CREATED
-> RESPONSE_COMMITTED
-> AUDIT_PENDING
-> CHALLENGE_PENDING
-> RECEIPT_ACTIVE
```

Failure dispositions are:

```text
ABSTAINED
REJECTED
CHALLENGED
SLASHED
DA_FAILED
EXPIRED
```

### 3.3 Vertical experiment slices

Each E1-E8 slice must contain:

1. a frozen experiment specification;
2. a failing behavioral, property, contract, or artifact test;
3. the minimum implementation needed to pass;
4. receipt-level raw output;
5. schema and invariant validation;
6. statistical aggregation;
7. deterministic table and figure generation;
8. a claim-support disposition;
9. a hash-bound artifact manifest.

No experiment writes a paper table directly. Tables and figures are derived from validated raw artifacts.

## 4. Technology boundary

- CPython 3.11 baseline;
- `pytest` for example and integration tests;
- `hypothesis` for property and state-machine tests;
- Pydantic and JSON Schema for canonical records;
- Parquet plus Pandas for receipt-level analytical records;
- SciPy and statsmodels for statistical methods;
- Matplotlib for deterministic PDF and SVG figures;
- Solidity `0.8.24`;
- Foundry and Anvil for contract, invariant, fuzz, and gas tests;
- Qwen2.5-1.5B-Instruct as the primary model;
- Qwen2.5-7B-Instruct as the optional scaling model;
- exact model revisions, model hashes, tokenizer hashes, and environment locks before evidence runs;
- CPU deterministic fixtures for CI;
- separately authorized real-model or GPU evidence runs.

## 5. Proposed source boundaries

New production behavior is implemented test-first under `src/poi_mpp/`. Existing flat scripts are treated as historical scaffolds until parity is established.

```text
src/poi_mpp/
├── evidence/
│   ├── models.py
│   ├── canonical.py
│   ├── config.py
│   ├── provenance.py
│   ├── validation.py
│   ├── registry.py
│   └── publication_gate.py
├── protocol/
│   ├── types.py
│   ├── model_registry.py
│   ├── task.py
│   ├── commitment.py
│   ├── audit_compiler.py
│   ├── availability.py
│   ├── challenge.py
│   ├── receipt.py
│   ├── credit.py
│   ├── committee.py
│   └── reference_machine.py
├── worker/
│   ├── model_manifest.py
│   ├── inference.py
│   ├── deterministic_decode.py
│   ├── trace_schema.py
│   ├── trace_capture.py
│   ├── trace_tree.py
│   ├── iec_schema.py
│   └── iec_builder.py
└── auditor/
    ├── exact/
    ├── algebraic/
    │   ├── finite_field.py
    │   └── floating_point.py
    ├── semantic/
    ├── availability/
    └── reports.py
```

Minimum Solidity contracts:

```text
contracts/src/
├── PolicyRegistry.sol
├── ModelRegistry.sol
├── TaskManager.sol
├── CommitmentHub.sol
├── AuditManager.sol
├── ReceiptManager.sol
└── CreditEngine.sol
```

`AuditManager` owns the MPP audit-plan hash, DA disposition, simple challenge state, and deadlines. The design must label this path `MPP_SIMPLE_DISPUTE`; it is not a production dispute VM.

## 6. Public interfaces

### 6.1 Evidence interfaces

```python
def canonical_bytes(domain: str, value: Serializable) -> bytes: ...
def digest(domain: str, value: Serializable) -> str: ...
def freeze_run(config: RunConfig, environment: Environment) -> RunManifest: ...
def validate_artifact(record: ArtifactRecord) -> ValidationReport: ...
def evaluate_publication_gate(
    claim_id: str,
    artifacts: Sequence[ArtifactRecord],
) -> GateDecision: ...
```

### 6.2 Protocol interfaces

```python
def commit_response(
    task: TaskSpec,
    model: ModelManifest,
    response_hash: str,
    trace_root: str,
    evidence_root: str,
    artifact_root: str,
    nonce: bytes,
) -> ResponseCommitment: ...
```

```python
def compile_audit(
    policy: AuditPolicy,
    task: TaskSpec,
    finalized_commitment: ResponseCommitment,
    epoch_beacon: bytes,
    round_index: int,
) -> AuditPlan: ...
```

```python
def transition(
    receipt: Receipt,
    event: ProtocolEvent,
    context: TransitionContext,
) -> Receipt: ...
```

```python
def allocate_credit(
    task: TaskSpec,
    matured_receipts: Sequence[Receipt],
) -> CreditAllocation: ...
```

```python
def derive_active_weight(
    credit: int,
    collateral: int,
    beta: int,
    concentration_cap: int,
) -> int: ...
```

### 6.3 Worker interface

```python
@dataclass(frozen=True)
class ExecutionBundle:
    response: str
    response_hash: str
    trace_root: str
    evidence_root: str
    artifact_root: str
    timings: ExecutionTimings
    retained_artifacts: tuple[ArtifactRef, ...]
```

### 6.4 Auditor interface

```python
@dataclass(frozen=True)
class AuditResult:
    audit_id: str
    commitment_hash: str
    decision: Literal["ACCEPT", "REJECT", "ABSTAIN"]
    checks: tuple[CheckResult, ...]
    assurance_class: str
    residual_risks: tuple[str, ...]
```

## 7. Protocol invariants

The implementation and experiments must preserve all of the following:

1. The audit seed is unavailable before commitment finality.
2. Model, task, response, trace, IEC, and artifact roots are immutable after commitment.
3. Service tasks cannot mint consensus credit.
4. Arbitrary or unregistered tasks cannot mint consensus credit.
5. A receipt cannot become active before audit, DA, and challenge-window completion.
6. A successful challenge produces a slashed disposition.
7. A nullifier cannot be reused.
8. Per task, `sum(credit) <= D_j`.
9. `Q = 0` implies `W = 0`.
10. Collateral caps earned credit but cannot create credit.
11. Current-epoch receipts cannot create current-epoch authority.
12. Python and Solidity produce identical commitment, state, and credit outputs for shared vectors.
13. Unknown evidence origins fail closed.
14. Frozen artifacts are immutable.
15. A table or figure value must trace to validated raw records.

## 8. Worker and trace rules

- Model repository, revision, weights, tokenizer, precision, and generation policy are pinned.
- Warm-up and measured inference are separate.
- Seeds and decode configuration are recorded even for deterministic decoding.
- Trace capture records only declared operations and surfaces.
- Missing required trace surfaces fail or downgrade assurance explicitly.
- IEC generation must not collect private chain-of-thought.
- The response, claim nodes, and evidence mapping are bound in one execution lifecycle.
- A worker cannot certify its own output as publication-eligible.

## 9. Auditor rules

- Exact finite-field Freivalds and approximate floating-point audit are separate implementations and claims.
- Binary-vector exact Freivalds has a per-round error bound of at most `1/2` under its declared exact-arithmetic assumptions; `k` independent rounds give at most `2^-k`.
- Floating-point audit receives no inherited exact theorem. Its tolerance, honest false-reject rate, and corrupted false-accept rate are measured empirically.
- Objective checks return exact deterministic outcomes.
- Grounded semantic checks return empirical `ACCEPT`, `REJECT`, or `ABSTAIN` outcomes.
- Unsupported kernels fail the highest assurance class or produce an explicit downgrade.
- Audit failures are structured outcomes, not swallowed exceptions.

## 10. Solidity roles

The MPP defines separate roles for:

- policy administrator;
- task issuer;
- registered worker;
- audit resolver;
- permissionless challenger.

No account receives all roles in the reference deployment. Foundry invariant tests enforce role separation and unauthorized-action rejection.

## 11. Failure-handling contract

The implementation prohibits:

- `|| true` in experiment orchestration;
- empty CSV success artifacts;
- silently skipped experiments;
- fabricated measurement defaults;
- partial publication tables;
- automatic correction of invalid configurations;
- ignored contract-call failures;
- overwriting frozen result directories.

Required failure behavior:

- typed error code;
- non-zero process exit;
- structured failure record when safe;
- atomic artifact write using temporary output, validation, and rename;
- interrupted runs marked `INCOMPLETE`;
- resume allowed only with matching run and configuration hashes;
- preservation of valid raw artifacts after a later experiment fails;
- publication bundle failure if any required completeness gate fails.

## 12. TDD contract

New production behavior follows:

```text
RED
-> verify the expected failure
-> record RED evidence
GREEN
-> implement the minimum behavior
-> verify targeted pass
REFACTOR
-> improve structure
-> verify affected suites
INTEGRATE
-> run cross-module, property, and conformance tests
EVIDENCE
-> produce raw experiment artifacts
VALIDATE
-> run schema, invariant, statistical, and provenance checks
FREEZE
-> write the immutable manifest
```

Required test categories:

- unit tests;
- property and state-machine tests;
- Python-Solidity conformance tests;
- attack and adversarial tests;
- artifact-schema tests;
- statistical-method tests;
- end-to-end task-to-receipt tests;
- clean-environment reproduction tests.

Mocks are limited to hardware and external-network boundaries. Protocol behavior cannot be established through mocks.

## 13. Gate separation

Every experiment produces two independent decisions.

### 13.1 Artifact completeness

Completeness requires:

- frozen configuration;
- authorized evidence origin;
- valid receipt-level raw records;
- correct denominators;
- environment provenance;
- deterministic aggregation;
- confidence intervals where applicable;
- artifact hashes;
- no invalid or silently omitted rows.

### 13.2 Claim support

Scientific claim disposition is one of:

```text
SUPPORTED
NOT_SUPPORTED
INCONCLUSIVE
```

`NOT_SUPPORTED` and `INCONCLUSIVE` remain valid publication artifacts. Reporting cannot suppress negative results.

## 14. E1: Single-pass cost

**Claim:** One real inference plus trace, IEC, and routine audit is materially cheaper than mandatory two-run verification.

**Evidence origin:** `REAL_MODEL_EXECUTION`.

**Baselines:** native single inference, real two-run inference, and MPP-SPAI.

**Required RED cases:** warm-up contamination, mismatched hashes, fake two-run baseline, trace-disabled SPAI label, invalid duration, and incomplete paired task IDs.

**Measurements:** inference, trace, IEC, routine audit, semantic audit, dispute amortization, memory, retained trace bytes, and energy/cost only when a reliable meter exists.

**Analysis:** paired tasks and seeds with bootstrap confidence intervals.

**Claim rule:** the upper 95% confidence bound of `SPAI total / two-run total` is below `0.90`.

**Outputs:** `E1_receipts.parquet`, T6, F5, and an E1 provenance bundle.

## 15. E2: Execution tamper detection

**Claim:** Post-commit randomized audits detect declared corruption classes at predictable rates.

**Evidence origin:** `REAL_MODEL_EXECUTION` plus controlled, manifest-bound attack transformations.

**Attack classes:** model-root substitution, weight corruption, trace mutation, tensor mutation, response/trace mismatch, index mutation, decode-policy mutation, cross-request splice, replay, and unsupported-kernel paths.

**Required RED cases:** pre-finality seed use, attack without a changed target, deterministic corruption escape, unsupported kernel receiving highest assurance, mixed exact/approximate claims, and missing attack manifests.

**Analysis:** attack type by sampling configuration by independent seed. Exact and approximate paths are reported separately.

**Outputs:** receipt-level attack records, manifests, T7, F6, and an unsupported-surface ledger.

## 16. E3: Grounded semantic assurance

**Claim:** IEC-grounded verification can reject or abstain on invalid grounded claims while preserving useful valid coverage.

**Evidence origin:** development data are `SYNTHETIC_NON_EVIDENCE`; confirmation uses an independently frozen held-out grounded dataset.

**Classes:** supported, unsupported, contradictory, partially supported, ambiguous, numerically inconsistent, and invalid-evidence-reference answers.

**Required RED cases:** missing evidence accepted, unsupported answer accepted, ambiguity forced to a binary decision, empty-term failure, development/confirmation overlap, and synthetic publication leakage.

**Metrics:** FAR, FRR, abstention, coverage, precision, recall, calibration, confusion matrices, reference agreement, and adversarial subgroup results.

**Policy:** `alpha_sem`, useful-coverage requirement, calibration method, and disagreement threshold are frozen before confirmatory execution.

**Outputs:** T4, T8, F7, annotation provenance, and an error-analysis ledger.

## 17. E4: Data availability

**Claim:** Unavailable artifacts cannot silently mature within the declared sampling and reconstruction model.

**Evidence origin:** `REPRODUCIBLE_SIMULATION` plus local artifact-store integration tests.

**Required RED cases:** reconstruction with insufficient shards, activation after DA failure, samples greater than total shards, formula-mode confusion, invalid duplicate sampling, and selective serving mislabeled as static withholding.

**Models:** static withholding with replacement, static withholding without replacement, targeted withholding, selective serving, and correlated shard loss.

Without-replacement sampling uses the exact hypergeometric probability, not `(1-f)^k`.

**Outputs:** T9, F8, DA certificates, reconstruction logs, and an assumption ledger.

## 18. E5: Watcher and dispute economics

**Claim:** Under declared conditions, challenging discoverable invalid receipts is rational and no-challenge risk is measurable.

**Evidence origin:** `REPRODUCIBLE_SIMULATION`.

**Required RED cases:** invalid economic inputs, independent formula used for correlated watchers, omitted challenge loss, omitted outage/collusion scenario, and MPP dispute mislabeled as production dispute.

**Scenarios:** independent watchers, correlated outage, shared infrastructure, heterogeneous cost, collusion, low/high fraud value, bribery/subsidy, and bonded auditor plus permissionless watcher.

**Outputs:** T10, expected-utility surfaces, invalid-maturity sensitivity plots, and an assumption ledger.

The result is a model-bounded simulation, not a universal incentive theorem.

## 19. E6: Sybil and task-budget economics

**Claim:** Credit conservation holds exactly and the selected scheduler does not materially reward identity splitting under the declared model.

**Evidence origin:** `REPRODUCIBLE_SIMULATION` plus protocol property tests.

**Required RED cases:** budget overflow, service-task credit, unregistered-task credit, identity-sensitive capacity allocation, stake-created weight, and immediate current-epoch authority.

**Comparators:** identity-uniform scheduler, capacity-committed scheduler, operator-slot scheduler, task-budget-only ablation, collateral-cap ablation, and concentration-cap ablation.

**Claim rule:** the upper 95% confidence bound of Sybil credit advantage is no greater than the pre-confirmation frozen `epsilon_sybil`.

**Outputs:** T11, F9, F10, invariant reports, and a boundary-condition ledger.

## 20. E7: EVM boundedness and parity

**Claim:** Heavy AI execution remains off-chain, EVM state transitions remain compact and measurable, and Python/Solidity outputs conform.

**Evidence origin:** `FOUNDRY_MEASUREMENT`.

**Test groups:** roles, task classes, commitment uniqueness, commitment-before-audit, DA-before-active, challenges, expiry/slashing, replay rejection, budget conservation, zero-credit weight, epoch delay, fuzz invariants, parity vectors, and gas snapshots.

The first RED tests target current permissive behavior: unauthorized collateral and credit mutation, premature activation, audit overwrite, nonexistent-task commitment, service-task credit, replay, and hash mismatch.

**Measurements:** model registration, task creation, response commitment, audit, challenge, receipt transition, credit allocation, batch sizes, gas median/p95, calldata, and storage deltas.

**Outputs:** T12, F12, Foundry snapshots, compiler/bytecode manifest, and a conformance report.

Local Anvil measurements cannot be labeled as Ethereum-mainnet production costs.

## 21. E8: Next-epoch PoI weight

**Claim:** Only matured prior-epoch receipts create bounded next-epoch weight, and adversarial active-weight risk is reproducibly measured.

**Evidence origin:** `REPRODUCIBLE_SIMULATION`.

**Required RED cases:** non-active receipt weight, immediate authority, cap bypass, invalid probability sum, nondeterministic seeded committees, zero-total-weight error, and missing attacker cost model.

**Scenarios:** honest workers, high-compute attacker, Sybil attacker, collateral-rich no-credit attacker, subsidized compute, collusion, missing receipts, churn, and cap ablation.

**Outputs:** T13, F11, committee histories, threshold-crossing probabilities, and cost/assumption ledgers.

This experiment does not constitute a HotStuff safety proof.

## 22. Sample-size and analysis policy

Receipt counts such as 2,500, 5,000, or 10,000 are operational targets, not evidence of sufficiency by themselves.

Each confirmatory experiment must predeclare:

- estimand;
- expected event rate or pilot basis;
- target confidence-interval width or precision;
- alpha and multiplicity handling where applicable;
- independent unit and clustering assumptions;
- exclusion and missing-data rules;
- deterministic seed schedule;
- minimum and maximum run budgets;
- stop rules.

Pilot data select or validate the design. Pilot observations cannot be silently pooled into confirmatory results.

## 23. End-to-end acceptance journey

The functional completion test is:

```text
registered model
-> protocol-issued grounded task
-> one real inference
-> trace and IEC
-> finalized commitment
-> post-commit audit plan
-> execution, semantic, and DA checks
-> optional injected challenge
-> matured receipt
-> bounded next-epoch credit
-> deterministic committee selection
-> E1-E8-compatible raw records
-> validated tables and figures
-> frozen manifest
```

Required failure journeys are:

- audit rejection;
- semantic abstention;
- DA failure;
- successful challenge and slashing;
- service-task no-credit;
- replay rejection.

## 24. Publication bundle gate

The publication bundle is created only when:

- E1-E8 artifact-completeness gates pass;
- all required raw records exist;
- negative and inconclusive results are preserved;
- synthetic artifacts are excluded from publication evidence;
- Python-Solidity conformance passes;
- model, dataset, configuration, and environment hashes exist;
- statistical scripts reproduce tables;
- figures regenerate deterministically;
- no measured number was manually entered;
- clean-environment replay succeeds;
- the artifact manifest matches;
- the manuscript claim-support matrix is updated.

The bundle status is `MPP_ARTIFACT_COMPLETE` plus per-claim `SUPPORTED`, `NOT_SUPPORTED`, or `INCONCLUSIVE`. It must not be presented as production readiness, external validation, independent replication, or journal acceptance.

## 25. Current scaffold disposition

The current workspace contains useful structure, documentation, dataset generators, and starter implementations. It is not a validated MPP.

Current observed limitations include:

- no Git repository or tracked revision;
- only two Python tests;
- no executable Solidity tests;
- no experiment result artifacts;
- self-test commands that do not execute self-test logic;
- synthetic experiment outputs;
- empty E7 gas scaffolding;
- placeholder figure/report generation;
- `UNCOMPUTED` economic-security values;
- permissive contract state transitions and access control.

These files remain historical scaffolds until replaced or adopted through a genuine RED-GREEN-REFACTOR cycle.

## 26. Completion boundary

The design is fulfilled only when the software can produce a hash-bound, reproducible E1-E8 artifact package from the approved MPP scope, including negative outcomes and residual risks, without using synthetic records as scientific evidence.

The design does not authorize real-value deployment, external data collection, human-subject research, proprietary model transmission, or production security claims.
