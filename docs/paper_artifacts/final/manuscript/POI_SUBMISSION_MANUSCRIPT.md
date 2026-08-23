# Complete Proof of Intelligence Consensus Architecture

## A Single-Pass, Optimistic, EVM-Compatible Protocol for Verifiable AI Responses, with a Narrow Publication-Artifact MPP

## Abstract

Proof of Intelligence (PoI) should not require a second full frontier-model execution for every accepted response, and it should not require a full zero-knowledge proof of the common path for every response. This manuscript presents a complete protocol architecture in which a single model execution yields a user-visible answer together with committed execution and semantic audit surfaces. After commitment finality, post-commit randomness selects audit obligations, and only successfully matured receipts may contribute to next-epoch protocol weight. The full architecture covers commitment, audit compilation, optimistic dispute, data-availability retention, bounded task credit, and EVM-compatible receipt and credit management.

This manuscript also reports the current state of a deliberately narrow Minimum Publishable Prototype (MPP). The approved first-publication MPP is limited to 1B-8B open-weight models, a local EVM/Foundry environment, and reproducible artifact plumbing for experiments E1-E8. It explicitly excludes 70B and larger validation, mixture-of-experts execution, confidential GPU/TEE execution, a production dispute VM, production decentralized data availability, and a production consensus client. Within that narrow scope, the repository implements the evidence kernel, protocol kernel, and artifact pipeline, but the canonical publication process remains intentionally incomplete. As of August 23, 2026, claims C1-C6 remain incomplete; local Foundry verification supports only the narrow C7 engineering boundary and still requires a regenerated canonical paper artifact; and the historical C8 surface is a reproducible but inconclusive simulation snapshot pending canonical regeneration. The manuscript therefore separates the proposed full architecture from the implemented MPP, and separates implemented software from measured evidence.

## Evidence and status box

Historical local Task 22 candidate state (diagnostic only; not canonical publication provenance):

| Item | Current status |
|---|---|
| Bundle state | `CANDIDATE_VERIFIED` |
| Completeness | `INCOMPLETE` |
| C1-C6 | incomplete / inconclusive |
| C7 | supported (`LOCAL_FOUNDRY_MEASUREMENT`) |
| C8 | complete but inconclusive (`REPRODUCIBLE_SIMULATION`) |
| Freeze sentinel | absent |
| Manual scientific review authentication | absent |
| Current blockers | No admissible E1-E6 publication artifact is currently present; E1 is a fixed-order pilot design, E2 has a narrow scope, E3 lacks external evaluator authority, E4 is declared-outcome playback rather than executed reconstruction, and E5-E6 still require clean version-bound runs; authenticated external manual review is absent |

This box is descriptive, not a score. It summarizes a historical ignored local Task 22 candidate snapshot. That temporary snapshot is not tracked, is not an admissible publication source, and must be replaced by a clean, version-bound canonical bundle before paper submission.

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

Within its approved scope, the MPP software is materially implemented: evidence schemas, protocol objects, Python-Solidity parity surfaces, reporting builders, Foundry contract scaffolds, and the candidate verification path are present. However, the publication bundle is not complete. That distinction is recorded mechanically by the current Task 22 candidate status rather than inferred from prose.

### 4.3 Historical local candidate state

An earlier Task 22 run exists only under the ignored local `results/tmp/` tree. It is retained as diagnostic history, not as canonical publication provenance. Its recorded state was:

- bundle state: `CANDIDATE_VERIFIED`
- completeness: `INCOMPLETE`
- claims C1-C6: `INCONCLUSIVE` because required publication artifacts are absent
- claim C7: `SUPPORTED`
- claim C8: `INCONCLUSIVE`
- sentinel: absent

The ignored temporary files that recorded this state are not admissible evidence and are intentionally not cited as paper provenance. A clean, version-bound canonical bundle must regenerate the verification report and claim matrix.

## 5. Experimental design and artifact contract

Experiments E1-E8 are defined in `docs/EXPERIMENT_PLAN.md`, mapped to paper artifacts in `docs/EXPERIMENT_ARTIFACT_MATRIX.md`, and collected through `docs/ARTIFACT_COLLECTION_GUIDE.md`. The paper-facing artifact contract is intentionally strict:

- no manually typed scientific results in tables or figures;
- every paper artifact must derive from configuration, raw output, and code;
- synthetic plumbing must not be promoted into publication evidence;
- incomplete and inconclusive states must remain visible.

That contract matters because the current manuscript includes both evidence-bearing and non-evidence-bearing surfaces, and they must not be conflated.

## 6. Current evidence

### 6.1 Claim-level summary

The current claim-support matrix yields:

- C1: incomplete / inconclusive
- C2: incomplete / inconclusive
- C3: incomplete / inconclusive
- C4: incomplete / inconclusive
- C5: incomplete / inconclusive
- C6: incomplete / inconclusive
- C7: complete / supported
- C8: complete / inconclusive

The rest of this section therefore separates incomplete empirical targets, measured local evidence, and reproducible simulation.

### 6.2 E1-E6: incomplete publication targets

The repository pre-allocates paper artifact names for E1-E6, but the authorized evidence needed for claim support is not present in the current candidate.

Current missing quantitative targets are:

- C1: `publication/tables/T6_single_pass_cost.csv` and `publication/figures/F5_single_pass_cost.svg`
- C2: `publication/tables/T7_execution_audit_security.csv` and `publication/figures/F6_audit_soundness.svg`
- C3: `publication/tables/T4_dataset_composition.status.json`, `publication/tables/T8_semantic_verification.csv`, and `publication/figures/F7_semantic_verification_quality.svg`
- C4: `publication/tables/T9_data_availability.csv` and `publication/figures/F8_da_withholding.svg`
- C5: `publication/tables/T10_watcher_dispute_economics.csv`
- C6: `publication/tables/T11_sybil_economics.csv`, `publication/figures/F9_sybil_advantage.svg`, and `publication/figures/F10_economic_security.svg`

Interpretation:

- the artifact names exist as targets in the reporting contract;
- their presence in the design map does not make them evidentiary results;
- no quantitative claim should be drawn for C1-C6 from the current candidate bundle.

Suggested caption pattern for these deferred measured surfaces:

> Placeholder artifact name allocated by the publication pipeline. The corresponding experiment is incomplete or unauthorized in the August 23, 2026 candidate bundle; no quantitative claim should be inferred from this placeholder.

### 6.3 E7: local EVM boundedness

The strongest currently supported claim is C7, which corresponds to bounded EVM-path behavior for the current MPP contract set under local Foundry measurement.

Measured artifact sources:

- `publication/tables/T12_evm_boundedness.csv`
- `publication/figures/F12_evm_gas_state_scaling.svg`
- `publication/raw/E7_live_bundle.json`

Current evidence status:

- all published E7 rows are marked `SUPPORTED`;
- the largest observed gas value in the current candidate is `467,937` for `CREDIT_ALLOCATE` at batch size `8`;
- the largest reported fraction of the local block gas limit is `0.000436`;
- the evidence origin is local Foundry measurement, not mainnet execution and not production consensus throughput evidence.

Suggested caption:

> **Figure F12 / Table T12.** Local Foundry measurements of the MPP normal path and bounded receipt-credit operations. Heavy AI execution remains off-chain, while the EVM stores compact commitment, audit, receipt, and credit state. These measurements support local boundedness for the current MPP contract set only; they do not establish Ethereum mainnet deployment economics or production throughput.

### 6.4 E8: next-epoch consensus-weight simulation

The repository also generates a complete E8 publication surface, but its disposition remains inconclusive.

Simulation artifact sources:

- `publication/tables/T13_consensus_safety.csv`
- `publication/figures/F11_consensus_dynamics.svg`
- `publication/figures/F11_consensus_dynamics.json`

Current evidence status:

- all current E8 publication rows are `INCONCLUSIVE`;
- the evidence origin is explicitly `REPRODUCIBLE_SIMULATION`;
- the surface is suitable for describing the modeled weight-conversion logic, but not for claiming demonstrated consensus security.

Suggested caption:

> **Figure F11 / Table T13.** Reproducible simulation of next-epoch committee weight dynamics under bounded-receipt scenarios. These artifacts show how the protocol maps matured receipts into candidate next-epoch weight, but the current disposition remains inconclusive and should not be represented as an empirical consensus-security proof.

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

- executed publication-grade E1-E6 evidence;
- externally authorized semantic confirmation for E3;
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

Fourth, empirical support is narrow. C7 is supported locally; C8 is present only as reproducible but inconclusive simulation; C1-C6 remain incomplete.

Fifth, the canonical publication process remains intentionally incomplete because the repository preserves unresolved gates rather than relabeling them as success. The exact Qwen 1.5B local model artifact has been acquired and hash-verified. Authorized E1 and E2 local pilots exist only as ignored raw workspace outputs and are not admissible publication artifacts: E1 used a fixed-order pilot design that cannot support C1, and E2 covered only one narrow model-task-layer-token-slice boundary. No admissible E4-E6 publication artifact is currently present; E4 is explicitly declared-outcome playback rather than executed reconstruction, while E5-E6 still require clean, version-bound simulation runs. External evaluator authority and authenticated external manual review also remain absent.

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

The current repository substantiates that this architecture can be reduced into a disciplined first-publication MPP. The strongest present repository-grounded result is local EVM boundedness (C7). The next-epoch weight pipeline (C8) is implemented as a reproducible simulation surface but remains inconclusive. The remaining central empirical claims (C1-C6) are still incomplete in the canonical publication candidate and must remain incomplete in the manuscript until authorized executed evidence exists.

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

No clean, version-bound canonical quantitative publication bundle is currently attached to this manuscript. The tracked T5 and T6 paper tables are historical presentation snapshots only; they must be regenerated from canonical E7/E8 outputs and hash-bound before submission. The future canonical bundle must include the claim matrix, omission ledger, E7 table and figure, and E8 table and figure.

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
