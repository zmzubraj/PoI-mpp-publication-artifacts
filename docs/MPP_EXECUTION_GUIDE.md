# Minimum Publishable Prototype — Execution Guide

## Stage 0 — Freeze the scientific claim

Publication claim:

> A single model execution can produce a user-facing response plus committed execution/semantic audit surfaces; after commitment, unpredictable audits and bounded disputes can produce a matured, availability-gated receipt that creates next-epoch PoI authority without a second frontier-model run or mandatory full per-response zkML.

Do not claim more than this in the first empirical paper.

## Stage 1 — Protocol plumbing

Build and test:

- ModelRegistry
- TaskManager
- CommitmentHub
- AuditManager
- ReceiptManager
- CreditEngine
- local EVM deployment

Exit gate:

`createTask -> commitResponse -> audit -> finalizeReceipt -> activeWeight` works for a toy receipt.

## Stage 2 — Real inference

Integrate primary open-weight model.

Requirements:

- deterministic decoding for benchmark tasks;
- reproducible model/version hash;
- trace sidecar;
- IEC builder;
- response commitment.

Exit gate:

One real inference creates a complete receipt candidate.

## Stage 3 — Real execution audit

Implement:

- selected linear-layer fingerprints;
- Freivalds checks;
- exact tokenizer/decode/cheap-op checks;
- tamper injector.

Exit gate:

Injected corruption is detected at statistically predictable rates.

## Stage 4 — Semantic audit

Implement grounded claims/evidence tasks and verifier classes.

Exit gate:

FAR/FRR/ABSTAIN are measured on held-out data.

## Stage 5 — Availability and dispute

Add:

- erasure coding;
- shard commitments;
- sampling certificate;
- simple challenge window;
- dispute bond and outcome state.

Exit gate:

Withheld artifacts cannot silently become ACTIVE beyond the configured probabilistic target.

## Stage 6 — Economics

Implement:

- task budget D_j;
- bounded credit c_ij;
- epoch-local Q_i;
- collateral cap B_i/beta;
- concentration cap;
- Sybil scheduler simulation.

Exit gate:

Identity splitting and self-created tasks do not materially inflate credit.

## Stage 7 — Consensus simulation

Do not build a full production consensus client yet.

Use a deterministic simulator for:

- matured receipt arrival;
- Q_i update;
- W_i cap;
- VRF committee sampling;
- weighted BFT threshold checks.

Exit gate:

The simulator reproduces the equations in the paper and supports adversarial scenarios.

## Stage 8 — Publication freeze

Freeze:

- commit hash;
- model IDs;
- dataset manifests;
- experiment configs;
- seeds;
- raw results;
- artifact manifests;
- figure/table generation commands.

Then update the paper's Results section from generated artifacts only.
