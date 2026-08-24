# Independent domain-expert review packet

Purpose: provide an unsigned packet for a real accountable external reviewer to assess the current manuscript and reviewed bundle boundaries.

This file is not a completed review, not a verdict, and not a signature-bearing record.

## Current claim matrix boundary

Use `../manuscript/POI_SUBMISSION_MANUSCRIPT.md` as the current narrative source of truth. The tracked canonical machine-readable bundle is `../../../../publication/artifact_manifest.json`; its current hash is recorded in `EXTERNAL_REVIEW_HANDOFF_MANIFEST.json`. That bundle is review input only: this unsigned packet does not satisfy the independent-review or freeze gate.

Current claim status:

| Claim | Current status | Evidence origin ceiling |
|---|---|---|
| `C1` | inconclusive | canonical authorized real-model fixed-order pilot; the design ceiling prevents support for C1 |
| `C2` | inconclusive | canonical authorized real-model narrow pilot; the tested scope prevents support for C2 |
| `C3` | waiting external | E3 confirmatory evaluator authority and evidence are absent |
| `C4` | inconclusive | canonical declared-outcome-playback simulation, not executed reconstruction |
| `C5` | supported within simulation scope | canonical reproducible simulation only |
| `C6` | supported within simulation scope | canonical reproducible simulation only |
| `C7` | supported | local Foundry measurement only |
| `C8` | inconclusive | reproducible simulation only |

## Evidence access list

The external reviewer should be given read access to the canonical manifest-closed artifact set and the following manuscript inputs. This unsigned packet is not itself freeze-eligible.

| Relative path | Current role |
|---|---|
| `../manuscript/POI_SUBMISSION_MANUSCRIPT.md` | manuscript draft under review |
| `../../../MAIN_RESULTS_TARGETS.md` | claim language and blocker contract |
| `../../../PAPER_ARTIFACT_MAP.md` | artifact closure rules |
| `../tables/T4_experiment_design_and_current_status.md` | experiment-by-experiment current status |
| `../tables/T7_limitations_and_nonclaims.md` | explicit non-claims |
| `../../../../publication/artifact_manifest.json` | canonical artifact closure, hashes, dispositions, and omissions |
| `../../../../publication/tables/claim_matrix.json` | canonical claim-to-artifact status matrix |
| `../../../../publication/tables/omissions.json` | explicit E3 omission ledger |
| `EXTERNAL_REVIEW_HANDOFF_MANIFEST.json` | deterministic selection and hash closure for all review inputs |
| `../review/SUBMISSION_READINESS_VALIDATION.md` | developmental killer-question audit and unresolved submission blockers |

The freeze-eligible handoff must bind the canonical `publication/artifact_manifest.json` and every reviewed manuscript/review file to exact SHA-256 values. Candidate creation copies those inputs into a self-contained `review_handoff/inputs/` tree and recomputes the handoff manifest against the candidate-specific publication evidence.

If the reviewer is assessing a freeze-eligible bundle rather than only the manuscript, the reviewed hash set must also include the actual reviewed bundle files required by the verifier:

- `claim_support_matrix.json`
- `publication/artifact_manifest.json`
- `review_handoff/EXTERNAL_REVIEW_HANDOFF_MANIFEST.json`

The candidate `manifest.json` and `verification_report.json` are mutable freeze-state records and therefore are not reviewer-signed inputs. They are recomputed and reverified during promotion; the handoff manifest is the stable reviewed-content anchor.

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
