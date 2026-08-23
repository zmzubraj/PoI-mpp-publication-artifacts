# Independent domain-expert review packet

Purpose: provide an unsigned packet for a real accountable external reviewer to assess the current manuscript and reviewed bundle boundaries.

This file is not a completed review, not a verdict, and not a signature-bearing record.

## Current claim matrix boundary

Use `../manuscript/POI_SUBMISSION_MANUSCRIPT.md` as the current narrative source of truth. No canonical machine-readable review bundle is presently attached to this unsigned draft packet; one must be generated from the clean, version-bound publication build before external review can satisfy the freeze gate.

Current claim status:

| Claim | Current status | Evidence origin ceiling |
|---|---|---|
| `C1` | incomplete / inconclusive | an authorized fixed-order pilot exists only as ignored local raw output; no admissible publication artifact is present, and the design cannot support C1 |
| `C2` | incomplete / inconclusive | an authorized narrow pilot exists only as ignored local raw output; no admissible publication artifact is present, and the tested scope cannot support C2 |
| `C3` | incomplete / inconclusive | E3 confirmatory authority absent |
| `C4` | incomplete / inconclusive | no admissible publication artifact is present; the current implementation is declared-outcome playback rather than executed reconstruction |
| `C5` | incomplete / inconclusive | no tracked or frozen publication artifact is present |
| `C6` | incomplete / inconclusive | no tracked or frozen publication artifact is present |
| `C7` | supported | local Foundry measurement only |
| `C8` | inconclusive | reproducible simulation only |

## Evidence access list

The external reviewer should ultimately be given read access to a canonical hash-bound artifact set. The following tracked source files are the current draft inputs, but their hashes must be recomputed after the canonical bundle is generated; this unsigned packet is not itself freeze-eligible.

| Relative path | Current role |
|---|---|
| `../manuscript/POI_SUBMISSION_MANUSCRIPT.md` | manuscript draft under review |
| `../../../MAIN_RESULTS_TARGETS.md` | claim language and blocker contract |
| `../../../PAPER_ARTIFACT_MAP.md` | artifact closure rules |
| `../tables/T4_experiment_design_and_current_status.md` | experiment-by-experiment current status |
| `../tables/T7_limitations_and_nonclaims.md` | explicit non-claims |

The canonical handoff must add the generated `manifest.json`, `claim_support_matrix.json`, `publication/artifact_manifest.json`, and `verification_report.json`, with exact SHA-256 values computed from the final reviewed revisions.

If the reviewer is assessing a freeze-eligible bundle rather than only the manuscript, the reviewed hash set must also include the actual reviewed bundle files required by the verifier:

- `manifest.json`
- `claim_support_matrix.json`
- `publication/artifact_manifest.json`
- `verification_report.json`

## Required review questions

The external reviewer should answer at least the following questions:

1. Does the manuscript preserve the current claim boundary without upgrading `C1`-`C6`?
2. Does the manuscript preserve `C7` as local Foundry boundedness only?
3. Does the manuscript preserve `C8` as reproducible simulation and inconclusive?
4. Are denominators and scope limits explicit where quantitative evidence is mentioned?
5. Are negative findings, absences, and blockers retained rather than hidden?
6. Are simulation surfaces labeled as simulation rather than empirical confirmation?
7. Are table and figure references tied to editable, traceable artifact paths?
8. Are accessibility and editability requirements for paper artifacts adequately represented?
9. Is claim language aligned with the machine-readable claim matrix?
10. Does the manuscript avoid treating AI output, user approval, or producer review as independent review?
11. Are deferred 70B/MoE, confidential GPU/TEE, and production dispute VM surfaces clearly separated from the implemented first-publication MPP?
12. Are there any places where the manuscript implies publication-complete, production-ready, or independently validated status without support?

## Conflicts and independence declaration requirements

A real reviewer record should declare:

- reviewer identity
- relevant expertise scope
- independence basis
- whether any conflict of interest exists
- if a conflict exists, its exact nature

The reviewer must be external to the producer chain for the review to count toward the independent review gate.

## Required checks for a freeze-eligible independent review record

The repository verifier requires the following check set to be explicitly marked by the external reviewer:

- denominator
- interval
- negative_results
- simulation_labeling
- editability
- accessibility
- claim_language

For a freeze-satisfying record, each of those checks must be affirmed by the actual reviewer in the completed signed record.

## Signed-verdict contract

The future completed signed record must satisfy all of the following:

- use `schema_version=POI_MPP_MANUAL_REVIEW_V1`
- use `status=COMPLETE`
- use `review_basis=INDEPENDENT_DOMAIN_EXPERT_REVIEW`
- carry a strict ISO `review_date`
- include reviewer identity, expertise scope, independence basis, and reviewed run id
- include reviewed artifact hashes matching the reviewed bundle
- be signed outside the bundle
- be verifiable against a trusted allowed-signers file outside the bundle

Use `independent_domain_expert_review_record.schema.json` for machine validation of a future completed record.

## Producer/verifier separation rule

The following do not satisfy the independent review gate:

- AI-generated verdict text without a real accountable signer
- user approval alone
- producer self-review
- an unsigned template
- a signed record whose identity or independence basis is unverified

## Non-claims

This packet does not:

- provide a verdict;
- provide a review date;
- provide a signature;
- provide a reviewer identity;
- satisfy `manual_review_authenticated`;
- satisfy the production freeze gate.
