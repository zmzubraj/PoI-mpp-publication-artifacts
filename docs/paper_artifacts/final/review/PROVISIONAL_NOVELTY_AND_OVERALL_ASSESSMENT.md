# Provisional novelty and overall assessment

Assessment date: 2026-08-23

This developmental assessment is intentionally outside the manuscript. It is not an independent peer review, acceptance forecast, strongest-prior-art verdict, or compensating publication gate. Scores are heuristic central estimates on a 0-100 scale with explicit uncertainty. A high score in one dimension cannot repair a failed or absent evidence, authority, integrity, or review gate.

## Evidence boundary

The assessment is grounded in the canonical PoI MPP artifact manifest, SHA-256 `416c4fd909e10304c361af056f0fddbc3ab47c67aeedad8f22fb69d839801e49`, the current evidence dispositions for E1-E8, and a bounded primary-source predecessor check. The latter is not yet a reproducible, independently challenged literature search package.

Strong predecessors identified in the bounded check include:

- [CommitLLM](https://github.com/lambdaclass/CommitLLM), an open-weight LLM commit-and-audit protocol with challenge-time trace opening and exact or Freivalds-style checks;
- [opML](https://arxiv.org/abs/2401.17555), an optimistic interactive fraud-proof design for on-chain machine learning;
- [zkGPT](https://www.usenix.org/conference/usenixsecurity25/presentation/qu-zkgpt), a non-interactive zero-knowledge framework for LLM inference; and
- [Optimistic TEE-Rollups](https://arxiv.org/abs/2512.20176), a hybrid optimistic and confidential-computing architecture for generative-AI inference.

The closest implementation-level overlap is CommitLLM. This materially lowers any claim that committed open-weight LLM execution, post-commit trace audit, or Freivalds-style checking is itself a new primitive. opML similarly lowers an isolated optimistic-dispute novelty claim.

## Non-compensating assessment

| Dimension | Central score | Uncertainty band | Evidence-bounded interpretation |
|---|---:|---:|---|
| Primitive execution-verification novelty | 35 | 25-45 | Low-to-moderate. CommitLLM and opML substantially overlap the primitive execution/audit and optimistic-dispute surfaces. |
| Protocol-composition differentiation | 68 | 55-75 | Potentially differentiating integration of execution and semantic evidence, retention, receipt maturity, task-budgeted credit, and next-epoch weight. Material novelty is not independently established. |
| Semantic-evidence novelty and validation | 20 | 10-30 | E3 is `WAITING_EXTERNAL`; no authorized semantic result exists. Architecture cannot substitute for evidence. |
| Narrow-MPP implementation maturity | 78 | 70-85 | Substantial evidence, protocol, replay, reporting, and local EVM implementation exists within the frozen narrow scope. This is not production maturity. |
| Empirical evidence maturity | 42 | 32-52 | E1, E2, E4, and E8 are inconclusive; E5 and E6 are simulation-only; E7 is local Foundry; E3 is absent. |
| Reproducibility discipline | 82 | 72-88 | Canonical manifests, provenance, fail-closed statuses, deterministic derivatives, and replay controls are strong. Final freeze remains blocked. |
| Publication readiness | 38 | 25-48 | External evaluator authority, authenticated independent manual review, and the publication-freeze sentinel remain absent. |
| Overall research-case potential | 57 | 45-66 | A coherent and technically promising architecture case, but only provisionally differentiating and not publication-ready for central empirical claims. |

The overall score is a communication aid, not an arithmetic gate. The defensible current novelty stage is **POTENTIALLY_DIFFERENTIATING**. The defensible publication status is **NOT READY**. No acceptance probability is estimable from the available evidence.

## What would change the assessment

The highest-information next actions are:

1. freeze a reproducible strongest-prior-art search with exact queries, screening, citation chaining, closest-predecessor comparison, and defeating evidence;
2. obtain a differently owned independent novelty challenge;
3. close E3 through authenticated external evaluator authority and authorized real evaluation;
4. replace the fixed-order E1 pilot with a separately frozen counterbalanced design if the cost claim remains central;
5. obtain authenticated independent domain-expert manuscript and artifact review; and
6. generate the publication-freeze sentinel only after all required evidence and review gates close on a clean, versioned worktree.

Until those actions are complete, the paper should claim a disciplined and evidence-gated PoI MPP architecture, not definitive primitive novelty, general semantic verification, production consensus security, or publication readiness.
