# MPP Alignment and Evidence-Bounded Scorecard

Date: Sunday, August 23, 2026

## Scope and authority

This assessment reconciles the manuscript-facing material with the canonical
`publication/artifact_manifest.json` (SHA-256
`7177d57747304d003160cdcb45bd572337028a8ffed8793dfa57e2d1444aaabf`), its
tables, figures, claim matrix, and omission ledger. It is a repository-grounded
editorial assessment, not an independent-human review, a prior-art verdict, or
a publication-acceptance judgment.

The first-publication MPP is intentionally limited to 1B-8B open-weight
models, local Foundry measurement, and the E1-E8 artifact contract. It does
not validate 70B/MoE workloads, confidential GPU/TEE execution, a production
dispute VM, production data availability, or a production consensus client.

## Executive judgment

The manuscript and repository are aligned only if they retain the canonical
dispositions and their scope ceilings. A canonical publication bundle exists,
but the work is **not publication-ready**: E3 requires external evaluator
authority, authenticated independent manual review is absent, and the
publication-freeze sentinel is absent. AI work, AI approval, and user approval
are not independent review.

## Non-compensating scorecard

| Dimension | Status | Basis |
|---|---|---|
| Primitive novelty | `PROVISIONAL_PENDING_REPRODUCIBLE_PRIOR_ART_SEARCH` | No reproducible strongest-prior-art package or independently challenged novelty case is present. |
| Architecture coherence | `ALIGNED_WITH_NARROW_MPP_SCOPE` | The paper's single-pass, post-commit-audit, receipt, and next-epoch path matches the bounded evidence and protocol kernels. |
| Implementation maturity | `MPP_SOFTWARE_IMPLEMENTED_WITH_EVIDENCE_GATES` | The bounded software and artifact pipeline are implemented; this does not upgrade scientific claim maturity. |
| Empirical evidence | `HETEROGENEOUS_AND_NON-COMPENSATING` | E1/E2/E4/E8 are inconclusive; E5/E6 are supported only in declared simulations; E7 is supported only in local Foundry scope; E3 has no evidence. |
| Reproducibility | `CANONICAL_ARTIFACTS_PRESENT_FREEZE_INCOMPLETE` | Canonical manifest, artifacts, claim matrix, and omission ledger exist, but the freeze sentinel and independent review gates are not closed. |
| Publication readiness | `NOT_PUBLICATION_READY` | E3 external authority, independent manual review, and freeze sentinel are independent blockers. |

## Claim-by-claim evidence status

| Claim / experiment | Artifacts | Canonical disposition | Manuscript rule |
|---|---|---|---|
| C1 / E1 | T6, F5 | `INCONCLUSIVE` | Fixed-order real-model pilot, two paired observations and six rows: mean two-run 5197.17125 ms; MPP 2678.932229 ms; delta 2518.239021 ms; bootstrap interval [2440.923209, 2595.554833]. Do not state a general cost advantage. |
| C2 / E2 | T7, F6 | `INCONCLUSIVE` | Narrow real-model pilot: 4/4 attacked observations detected, three exact plus one empirical surface, Wilson interval [0.5101091635454027, 1.0], one honest control with no false positive. Do not state general detection effectiveness. |
| C3 / E3 | T4, T8, F7 | `WAITING_EXTERNAL` | No evidence. Do not report semantic performance before external evaluator authority. |
| C4 / E4 | T9, F8 | `INCONCLUSIVE` | Declared playback simulation; not executed reconstruction evidence. |
| C5 / E5 | T10 | `SUPPORTED` | Only the declared reproducible-simulation scenarios are supported; no figure exists. |
| C6 / E6 | T11, F9, F10 | `SUPPORTED` | Only the declared reproducible-simulation scenarios are supported; not open-network Sybil resistance. |
| C7 / E7 | T12, F12 | `SUPPORTED` | Local Foundry only: 15 rows, maximum gas 467937, maximum block-limit fraction 0.00043580029159784317. Not a mainnet or production-performance claim. |
| C8 / E8 | T13, F11 | `INCONCLUSIVE` | Ten-row reproducible simulation; not demonstrated consensus security. |

## Architecture alignment

The repository aligns with the paper's bounded architecture:

- the core path is `task -> execute once -> commit -> post-commit audit ->
  challenge/DA -> mature receipt -> next-epoch weight`;
- the evidence and protocol kernels preserve explicit provenance, lifecycle,
  and failure states; and
- EVM settlement is limited to compact commitments, audit, receipt, and credit
  state while heavy AI execution stays off-chain.

The alignment does not extend to claimed production deployment, frontier-scale
execution, confidential execution, or a full production dispute/consensus
stack. Those remain deferred architecture, not MPP evidence.

## Replacement for aggregate score language

Replace numerical feasibility or readiness scores with these disclosures:

| Paper category | Evidence-bounded replacement |
|---|---|
| Overall protocol feasibility | `COHERENT_ARCHITECTURE_PENDING_NOVELTY_AND_EVIDENCE_GATES` |
| Common-path cost efficiency | `INCONCLUSIVE_FIXED_ORDER_REAL_MODEL_PILOT` |
| Execution-audit assurance | `INCONCLUSIVE_NARROW_REAL_MODEL_PILOT` |
| Semantic verification strength | `WAITING_EXTERNAL_EVALUATOR_AUTHORITY` |
| Data-availability assurance | `INCONCLUSIVE_DECLARED_PLAYBACK_SIMULATION` |
| Watcher/dispute economics | `SUPPORTED_DECLARED_SIMULATION_ONLY` |
| Sybil/task-budget neutrality | `SUPPORTED_DECLARED_SIMULATION_ONLY` |
| EVM compatibility | `SUPPORTED_LOCAL_FOUNDRY_BOUNDARY_ONLY` |
| Next-epoch consensus weight | `INCONCLUSIVE_REPRODUCIBLE_SIMULATION` |
| Production deployment | `NOT_READY` |

## Residual risks and final disposition

The paper must not let a `SUPPORTED` simulation result imply field viability or
let local Foundry measurement imply mainnet economics. It must retain E3's
absence of evidence and never equate AI/user approval with independent review.
The canonical bundle materially improves provenance, but it does not close the
external-authority, independent-review, or freeze-sentinel gates. Therefore the
current final disposition is `NOT_PUBLICATION_READY`.
