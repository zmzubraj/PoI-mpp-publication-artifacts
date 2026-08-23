# Complete Proof of Intelligence Consensus Architecture

## A Single-Pass, Optimistic, EVM-Compatible Protocol for Verifiable AI Responses, with a Narrow Publication-Artifact MPP

## Abstract

Proof of Intelligence (PoI) should not require a second full frontier-model execution for every accepted response, and it should not require a full zero-knowledge proof of the common path for every response. This manuscript presents a complete protocol architecture in which a single model execution yields a user-visible answer together with committed execution and semantic audit surfaces. After commitment finality, post-commit randomness selects audit obligations, and only successfully matured receipts may contribute to next-epoch protocol weight. The full architecture covers commitment, audit compilation, optimistic dispute, data-availability retention, bounded task credit, and EVM-compatible receipt and credit management.

This manuscript also reports the current state of a deliberately narrow Minimum Publishable Prototype (MPP). The approved first-publication MPP is limited to 1B-8B open-weight models, a local EVM/Foundry environment, and canonical artifacts for experiments E1-E8. It explicitly excludes 70B and larger validation, mixture-of-experts execution, confidential GPU/TEE execution, a production dispute VM, production decentralized data availability, and a production consensus client. The canonical manifest (SHA-256 `bd882ca072602e13cc14850a44d1b769111f6b032e56901e9419a3263593c943`) records `INCONCLUSIVE` E1, E2, E4, and E8 results; `SUPPORTED` E5-E7 results within their declared simulation or local-Foundry boundaries; and `WAITING_EXTERNAL` E3 artifacts. The package is not publication-ready because external evaluator authority, authenticated independent manual review, and the publication-freeze sentinel remain unresolved. The manuscript therefore separates the proposed full architecture from the implemented MPP, and separates implemented software from measured evidence.

## Evidence and status box

Canonical publication-artifact status:

| Item | Current status |
|---|---|
| Canonical manifest | `publication/artifact_manifest.json`, SHA-256 `bd882ca072602e13cc14850a44d1b769111f6b032e56901e9419a3263593c943` |
| E1 / C1 | `INCONCLUSIVE` real-model fixed-order pilot (T6, F5) |
| E2 / C2 | `INCONCLUSIVE` narrow real-model pilot (T7, F6) |
| E3 / C3 | `WAITING_EXTERNAL`; T4, T8, and F7 have no evidence |
| E4 / C4 | `INCONCLUSIVE` declared playback simulation (T9, F8) |
| E5 / C5 | `SUPPORTED` declared reproducible simulation only (T10; no figure) |
| E6 / C6 | `SUPPORTED` declared reproducible simulation only (T11, F9, F10) |
| E7 / C7 | `SUPPORTED` local Foundry measurement (T12, F12) |
| E8 / C8 | `INCONCLUSIVE` reproducible simulation (T13, F11) |
| Publication readiness | `NOT_PUBLICATION_READY` |
| Blocking gates | External evaluator authority for E3; authenticated independent manual review; absent publication-freeze sentinel |

This box is descriptive, not a score. A canonical artifact bundle exists, but its existence does not close the three blocking gates or authorize submission. AI work, AI approval, and user approval are not independent review.

## 1. Introduction

The expensive part of modern AI serving is the model execution itself. A PoI system that requires a second large-model generation for every accepted response, or a full proof of all tensor operations for the common path, inherits an immediate structural cost barrier. The systems question addressed here is whether useful AI responses can be made auditable without paying either of those costs on the normal path.

The proposed answer is Single-Pass Auditable Intelligence (SPAI): one committed response, one model execution, one set of committed execution and semantic audit surfaces, one post-commit randomized audit process, and one maturity rule that converts only successfully audited events into bounded protocol authority. The architectural goal is not to claim novelty for optimistic fraud proofs, algebraic matrix checks, remote attestation, data-availability sampling, or weighted Byzantine fault tolerance in isolation. The architectural claim is narrower: these components can be composed into a complete PoI path that avoids two common-path cost barriers while preserving explicit failure states and assurance tiers.

This manuscript must be read in two distinct layers:

1. the full protocol architecture proposed by the paper; and
2. the current repository-backed MPP, which implements a narrower, evidence-gated subset for publication artifacts.

That separation is necessary because the architecture is broader than the current evidence package, and the repository intentionally refuses to promote missing, simulated, synthetic, or externally blocked surfaces into completed empirical claims.

## 2. Scope and contribution boundary

### 2.1 Proposed full architecture

The proposed full architecture includes:

- one-pass AI execution with post-commit audits;
- open-weight execution checks from committed traces and algebraic audits;
- an optimistic challenge and dispute path;
- a confidential or proprietary execution lane based on attestation;
- data-availability retention and withholding response;
- bounded task credit and next-epoch weight conversion;
- EVM-compatible receipt and credit settlement; and
- future scaling to larger frontier or MoE deployments.

Conceptual figure and algorithm sources are preserved in editable form under:

- `docs/diagrams/D1_system_architecture.mmd`
- `docs/diagrams/D2_spai_sequence.mmd`
- `docs/diagrams/D3_receipt_state.mmd`
- `docs/diagrams/D4_audit_compiler.mmd`
- `docs/diagrams/D5_economic_flow.mmd`
- `docs/diagrams/D6_semantic_audit.mmd`
- `docs/algorithms/A1_SPAI.md`
- `docs/algorithms/A2_AuditCompiler.md`
- `docs/algorithms/A3_VerifySPAIEvent.md`
- `docs/algorithms/A4_PoI_Credit.md`
- `docs/algorithms/A5_Optimistic_Dispute.md`

### 2.2 Implemented first-publication MPP

The approved first-publication MPP is narrower. Its frozen design logic is the three-layer structure already fixed in the repository:

1. evidence kernel: canonical schemas, hashing, provenance, configuration, and artifact validation;
2. protocol kernel: task -> commitment -> audit -> challenge or DA -> receipt -> credit lifecycle;
3. vertical experiment slices: E1-E8, each with its own RED-GREEN-REFACTOR cycle and publication gate.

The publication MPP is limited to:

- one 1B-3B open-weight primary model and one optional 7B-8B scaling model;
- objective and grounded task classes only;
- a local EVM using Foundry and Anvil;
- reproducible E1-E8 artifact plumbing;
- explicit negative, incomplete, and inconclusive reporting.

The publication MPP explicitly defers:

- 70B or larger validation;
- MoE or distributed production serving;
- confidential GPU or TEE execution;
- a production-grade dispute VM;
- production DA infrastructure;
- a production consensus client.

### 2.3 Evidence-origin rule

Synthetic data is permitted only for plumbing tests and must remain labeled `SYNTHETIC_NON_EVIDENCE`. Paper tables and figures may derive only from:

- authorized real execution;
- Foundry measurement; or
- explicitly declared reproducible simulation.

This rule is enforced by the repository’s artifact contract and is essential to interpreting the current manuscript honestly.

## 3. Proposed full architecture

### 3.1 Single-pass auditable event

The core protocol path is:

`task -> execute once -> trace + Intelligence Evidence Capsule -> commitment -> post-commit audit -> challenge or DA gate -> matured receipt -> next-epoch weight`

The key design rule is that the concrete audit sample is not known before the response commitment is finalized. This preserves audit unpredictability while avoiding a second full model run on the normal path.

Suggested conceptual callout:

- Figure F1 placeholder: system architecture from `docs/diagrams/D1_system_architecture.mmd`
- Figure F2 placeholder: SPAI sequence from `docs/diagrams/D2_spai_sequence.mmd`
- Algorithm A1: SPAI procedure from `docs/algorithms/A1_SPAI.md`

### 3.2 Execution assurance lanes

The full architecture defines two execution-assurance lanes:

- an open-weight lane based on trace commitments, bounded exact checks, and randomized algebraic audits; and
- a confidential lane based on remote attestation and policy-gated execution provenance.

Only the open-weight lane belongs to the current first-publication MPP. The confidential lane is architecture only in this manuscript and is not an empirically supported repository result.

### 3.3 Semantic verification and the Intelligence Evidence Capsule

The architecture binds claims, evidence roots, dependency edges, uncertainty tags, executable artifacts, and coverage maps to the same response event. The semantic audit taxonomy distinguishes objective, grounded, open-semantic, and underdetermined classes. The implemented MPP preserves only the objective and grounded subset. Open-ended semantic competence remains outside the current publication-validated surface.

Suggested conceptual callout:

- Figure F4 placeholder: semantic pipeline from `docs/diagrams/D6_semantic_audit.mmd`
- Algorithm A3: verification procedure from `docs/algorithms/A3_VerifySPAIEvent.md`

### 3.4 Receipt, credit, and next-epoch authority

The full architecture mints non-transferable intelligence receipts that pass through commitment, audit, challenge, and maturity stages before bounded task credit is allocated. Only matured, policy-eligible receipts contribute to next-epoch weight. This separates service work from consensus authority and preserves the rule that collateral cannot mint PoI weight by itself.

Suggested conceptual callout:

- Figure F3-style state machine from `docs/diagrams/D3_receipt_state.mmd`
- Figure economic flow placeholder from `docs/diagrams/D5_economic_flow.mmd`
- Algorithm A4: credit update rule from `docs/algorithms/A4_PoI_Credit.md`
- Algorithm A5: optimistic dispute procedure from `docs/algorithms/A5_Optimistic_Dispute.md`

## 4. Implemented MPP

### 4.1 Repository structure

The implemented repository follows the frozen three-layer design and places the publication logic under a deterministic artifact pipeline. The practical shape is:

`raw data -> aggregation script -> table or figure artifact -> manuscript`

This means the manuscript is downstream of the evidence kernel rather than a freehand reporting layer.

Relevant repository contracts include:

- `README.md`
- `docs/EXPERIMENT_PLAN.md`
- `docs/EXPERIMENT_ARTIFACT_MATRIX.md`
- `docs/ARTIFACT_COLLECTION_GUIDE.md`
- `docs/PAPER_ARTIFACT_MAP.md`
- `docs/MAIN_RESULTS_TARGETS.md`

### 4.2 End-to-end state

Within its approved scope, the MPP software is materially implemented: evidence schemas, protocol objects, Python-Solidity parity surfaces, reporting builders, Foundry contract scaffolds, and a canonical publication-artifact pipeline are present. The manifest is the source of truth for result status; software implementation does not compensate for an inconclusive experiment, an absent authority, missing independent review, or an absent freeze sentinel.

### 4.3 Canonical publication state

The canonical artifact manifest contains E1, E2, and E4-E8 result surfaces and records the E3 omission ledger. It does not make the manuscript publication-ready. E3 remains `WAITING_EXTERNAL`, and the independent-review and freeze-sentinel gates remain open. These gate states are part of the scientific interpretation rather than formatting or administrative details.

## 5. Experimental design and artifact contract

Experiments E1-E8 are defined in `docs/EXPERIMENT_PLAN.md`, mapped to paper artifacts in `docs/EXPERIMENT_ARTIFACT_MATRIX.md`, and collected through `docs/ARTIFACT_COLLECTION_GUIDE.md`. The paper-facing artifact contract is intentionally strict:

- no manually typed scientific results in tables or figures;
- every paper artifact must derive from configuration, raw output, and code;
- synthetic plumbing must not be promoted into publication evidence;
- incomplete and inconclusive states must remain visible.

That contract matters because the current manuscript includes both evidence-bearing and non-evidence-bearing surfaces, and they must not be conflated.

## 6. Current evidence

### 6.1 Claim-level summary

The canonical claim matrix records C1 `INCONCLUSIVE`, C2 `INCONCLUSIVE`, E3
`WAITING_EXTERNAL`, C4 `INCONCLUSIVE`, C5 `SUPPORTED` within a declared
simulation, C6 `SUPPORTED` within a declared simulation, E7 local boundedness
`SUPPORTED`, and E8 `INCONCLUSIVE`. Those dispositions are non-compensating.

### 6.2 E1 and E2: bounded real-model pilots

E1 (T6, F5) is a fixed-order real-model pilot with two paired observations and
six measured rows. The mean two-run baseline is 5197.17125 ms, the mean MPP
single-pass measurement is 2678.932229 ms, and the paired delta is 2518.239021
ms with bootstrap interval [2440.923209, 2595.554833]. Fixed ordering leaves
E1 `INCONCLUSIVE`; this result cannot support a general C1 cost-advantage
claim.

E2 (T7, F6) is a narrow real-model pilot. It records 4/4 detected attacked
observations across three exact and one empirical floating-point surface, with
Wilson interval [0.5101091635454027, 1.0], plus one honest control and no false
positive. It remains `INCONCLUSIVE`, not a general execution-audit efficacy
claim.

### 6.3 E3-E6: authority boundary and declared simulations

E3 has no evidence artifact. T4, T8, and F7 are `WAITING_EXTERNAL` because
external evaluator authority has not been supplied. Semantic performance must
not be reported before that gate is resolved.

E4 (T9, F8) is an `INCONCLUSIVE` declared playback simulation, not executed
reconstruction evidence. E5 (T10) is `SUPPORTED` only for its declared
watcher/dispute-economic simulation scenarios and has no figure. E6 (T11, F9,
F10) is `SUPPORTED` only for its declared Sybil/task-budget simulation
scenarios. Neither E5 nor E6 supplies production or open-network evidence.

### 6.4 E7 and E8: local measurement and simulation

E7 (T12, F12) contains 15 `SUPPORTED` local Foundry measurements. The largest
observed gas value is 467937 for `CREDIT_ALLOCATE` at batch size 8, and the
maximum fraction of the configured block limit is 0.00043580029159784317. This
supports local boundedness only; it does not establish Ethereum-mainnet
economics, production throughput, or production consensus performance.

E8 (T13, F11) contains 10 `INCONCLUSIVE` reproducible-simulation rows. It may
describe modeled receipt-to-weight dynamics, but it is not demonstrated
consensus security.

## 7. Discussion

### 7.1 What the repository currently demonstrates

The repository currently demonstrates:

- a coherent reduction of the full PoI architecture into a bounded publication MPP;
- a fail-closed evidence kernel with explicit provenance, validation, and omission handling;
- Python-Solidity parity discipline for the implemented protocol kernel;
- local EVM boundedness evidence for the approved contract surfaces; and
- a reproducible simulation surface for next-epoch weight conversion.

### 7.2 What it does not yet demonstrate

The repository does not yet demonstrate:

- external-evaluator-authorized semantic confirmation for E3;
- a publication-freeze sentinel;
- authenticated independent manual review;
- 70B or larger model validation;
- MoE or distributed production validation;
- confidential GPU or TEE execution evidence;
- a production-grade dispute VM;
- a production consensus client; or
- a frozen publication bundle with authenticated independent manual review.

## 8. Limitations and evidence-origin disclosure

This manuscript enforces five evidence-boundary disclosures.

First, score tables and unsupported percentages are omitted. The current repository state does not justify compensating aggregate scores across architecture, implementation, evidence, and readiness.

Second, novelty remains provisional. This repository contains architecture and artifact evidence, but it does not contain a reproducible strongest-prior-art search package or an independent novelty challenge sufficient to defend a stronger novelty claim.

Third, semantic claims are narrow. The implemented MPP is limited to objective and grounded tasks, not open-ended semantic competence.

Fourth, empirical support is heterogeneous. E1, E2, E4, and E8 are `INCONCLUSIVE`; E5 and E6 are supported only within declared simulation scenarios; and E7 is supported only for local Foundry boundedness. E3 is evidence-absent and `WAITING_EXTERNAL`.

Fifth, the canonical bundle remains not publication-ready because it preserves unresolved gates rather than relabeling them as success. External evaluator authority, authenticated independent manual review, and the publication-freeze sentinel remain required. Neither AI production nor user approval is independent review.

## 9. Deferred future phases

The following surfaces are deferred and should remain labeled as future work rather than current evidence:

- 70B, 600B, and MoE execution validation;
- confidential or proprietary execution with GPU or TEE attestation;
- a production-grade dispute VM;
- production DA infrastructure;
- weighted BFT integration in a production consensus client;
- independent cryptographic, semantic, contract, and economic audits; and
- a fully frozen publication bundle with authenticated external manual review.

## 10. Conclusion

The proposed PoI architecture addresses a real systems problem: how to make useful AI responses auditable without requiring a second full frontier-model execution or a full common-path proof for each accepted response. The architecture combines response commitment, execution and semantic audit surfaces, post-commit randomness, optimistic dispute, DA retention, bounded task credit, and EVM-compatible receipt management into a coherent protocol proposal.

The current repository substantiates that this architecture can be reduced into a disciplined first-publication MPP. The strongest present repository-grounded result is local EVM boundedness (E7). E1 and E2 have canonical but inconclusive real-model pilot artifacts; E4 and E8 are inconclusive simulations; E5 and E6 are supported only within their declared simulations; and E3 remains blocked for external authority. The manuscript must preserve each boundary.

The correct current interpretation is therefore not that the architecture is fully validated, and not that it is merely conceptual. It is that a coherent PoI MPP has been implemented with strong fail-closed artifact discipline, while the central publication evidence package remains only partially complete.

## Artifact callouts for manuscript integration

### Conceptual figures

- F1 architecture source: `docs/diagrams/D1_system_architecture.mmd`
- F2 SPAI sequence source: `docs/diagrams/D2_spai_sequence.mmd`
- F3 receipt and audit-compiler sources: `docs/diagrams/D3_receipt_state.mmd` and `docs/diagrams/D4_audit_compiler.mmd`
- F4 semantic pipeline source: `docs/diagrams/D6_semantic_audit.mmd`

### Algorithms

- Algorithm 1: `docs/algorithms/A1_SPAI.md`
- Algorithm 2: `docs/algorithms/A2_AuditCompiler.md`
- Algorithm 3: `docs/algorithms/A3_VerifySPAIEvent.md`
- Algorithm 4: `docs/algorithms/A4_PoI_Credit.md`
- Algorithm 5: `docs/algorithms/A5_Optimistic_Dispute.md`

### Current quantitative publication artifacts

The attached canonical publication bundle is rooted at `publication/artifact_manifest.json` with SHA-256 `bd882ca072602e13cc14850a44d1b769111f6b032e56901e9419a3263593c943`. It includes the claim matrix, omission ledger, and E1, E2, E4-E8 artifacts. Its presence does not authorize submission: E3 authority, authenticated independent manual review, and the publication-freeze sentinel remain open gates.

## References

[1] K. D. Conway, C. So, X. Yu, and K. Wong. “opML: Optimistic Machine Learning on Blockchain.” arXiv:2401.17555, 2024.

[2] Optimism Collective. “Fault Proof.” OP Stack Specification, accessed August 23, 2026.

[3] A. Chan, A. Ding, F. Chen, A. Wu, B. Zhang, and A. Tian. “Optimistic TEE-Rollups: A Hybrid Architecture for Scalable and Verifiable Generative AI Inference on Blockchain.” arXiv:2512.20176, 2025.

[4] NVIDIA. “Attestation and Key-Release Flow.” In *Deploying Proprietary Models Securely with NVIDIA Confidential Computing on Self-Hosted Virtual Machines*, updated June 4, 2026.

[5] LambdaClass. “CommitLLM.” Official project repository and engineering documentation, accessed August 23, 2026. Grey literature.

[6] H. Ji, M. Mascagni, and Y. Li. “Gaussian Variant of Freivalds’ Algorithm for Efficient and Reliable Matrix Product Verification.” arXiv:1705.10449, 2017.

[7] Intel Trust Authority. “GPU Remote Attestation with Intel Trust Authority.” Official documentation, updated June 16, 2026.

[8] D. Ribeiro Alves, V. Patankar, M. Pereira, J. Stephens, N. Vaziri, and S. Kannan. “EigenAI: Deterministic Inference, Verifiable Results.” arXiv:2602.00182, 2026.

[9] W. Qu, Y. Sun, X. Liu, T. Lu, Y. Guo, K. Chen, and J. Zhang. “zkGPT: An Efficient Non-interactive Zero-knowledge Proof Framework for LLM Inference.” In *Proceedings of the 34th USENIX Security Symposium (USENIX Security 25)*, 2025.

[10] Z. Peng, C. Zhao, T. Wang, G. Liao, Z. Lin, Y. Liu, B. Cao, L. Shi, Q. Yang, and S. Zhang. “A Survey of Zero-Knowledge Proof Based Verifiable Machine Learning.” *Artificial Intelligence Review* 59, 157 (2026).

[11] Hearth. “A Verified-Inference Layer-1 Secured by Proof of Inference.” Source-carried draft whitepaper reference, July 2026. Grey literature; stable official primary source not verified in this manuscript pass.

[12] Ambient. “Litepaper: Proof of Logits & Verified Inference,” together with official product documentation describing “machine intelligence as currency,” accessed August 23, 2026. Grey literature.

[13] M. Yu, S. Sahraei, S. Li, S. Avestimehr, S. Kannan, and P. Viswanath. “Coded Merkle Tree: Solving Data Availability Attacks in Blockchains.” In *Financial Cryptography and Data Security (FC 2020)*, LNCS 12059, pp. 114-134, 2020.

[14] M. Yin, D. Malkhi, M. K. Reiter, G. G. Gueta, and I. Abraham. “HotStuff: BFT Consensus with Linearity and Responsiveness.” In *Proceedings of the 2019 ACM Symposium on Principles of Distributed Computing (PODC 2019)*, pp. 347-356, 2019.

[15] Ethereum.org. “Node Architecture” and “Consensus Mechanisms,” accessed August 23, 2026.
