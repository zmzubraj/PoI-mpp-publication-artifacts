# MPP Alignment and Evidence-Bounded Scorecard

Date: Sunday, August 23, 2026

Scope of this review:

- Source paper: `Read 1st - Complete_Proof_of_Intelligence_Consensus_Architecture_EVM.docx`
- Repository scope and design: `README.md`, `docs/superpowers/specs/2026-08-20-poi-mpp-publication-artifact-design.md`, `docs/superpowers/plans/2026-08-20-poi-mpp-publication-artifact-implementation.md`
- Publication-artifact contract: `docs/EXPERIMENT_PLAN.md`, `docs/EXPERIMENT_ARTIFACT_MATRIX.md`, `docs/ARTIFACT_COLLECTION_GUIDE.md`, `docs/PUBLICATION_GATES.md`, `docs/PAPER_ARTIFACT_MAP.md`, `docs/MAIN_RESULTS_TARGETS.md`, `docs/REPRODUCIBILITY_CHECKLIST.md`
- Current execution state: `.superpowers/sdd/2026-08-20-poi-mpp-publication-artifact-implementation/progress.md` plus a historical ignored local Task 22 candidate snapshot that is diagnostic only and not admissible publication provenance

This is a repository-grounded assessment. It is not an independent-human review, not a prior-art verdict, and not a publication acceptance judgment.

## Executive judgment

The repository is well aligned with the paper's first-publication MPP interpretation if the paper is read narrowly: one 1B-8B open-weight lane, local EVM/Foundry, and reproducible E1-E8 artifact plumbing with fail-closed evidence gates. It is not aligned with the full architecture if the paper is read as already supporting frontier-scale, confidential, or production-grade deployment claims.

The strongest present conclusion is:

- architecture proposal: coherent and substantially mapped into the repository
- MPP software implementation: materially complete inside the approved narrow scope
- empirical validation: still incomplete for most central claims
- reproducibility: strong at the software/artifact-kernel level, intentionally incomplete at the publication-freeze level
- publication readiness for central empirical claims: not ready

## Why the paper's aggregate scores should not be used

Paper Section 17.1 assigns theory-forward aggregate scores such as `94 / 100`, `91 / 100`, and `90 / 100`. Those numbers are not supported by a reproducible strongest-prior-art package, a completed empirical evidence ladder, or a fully complete publication bundle inside this repository.

The main problem is compensability: strong architecture coherence, code completion, or fail-closed gating cannot compensate for missing executed evidence on E1-E6, missing external semantic authority, or the absence of an independently authenticated manual review record.

For this MPP, aggregate percentages should therefore be replaced by non-compensating statuses.

## Evidence-bounded non-compensating scorecard

| Dimension | Status | Basis |
|---|---|---|
| Primitive novelty | `PROVISIONAL_PENDING_REPRODUCIBLE_PRIOR_ART_SEARCH` | The paper's Section 16 presents a boundary argument, but the repository does not contain a reproducible strongest-prior-art search package or an independently challenged novelty case. |
| Architecture coherence | `ALIGNED_WITH_NARROW_MPP_SCOPE` | The approved design in `docs/superpowers/specs/2026-08-20-poi-mpp-publication-artifact-design.md` matches the paper's core single-pass, post-commit audit, receipt, and next-epoch-weight path. |
| Implementation maturity | `MPP_SOFTWARE_IMPLEMENTED_AND_VERIFIED` | Tasks 12-22 are recorded as complete in `.superpowers/.../progress.md`, including E7/E8/reporting/reproducibility and Task 21/22 orchestration surfaces. |
| Empirical evidence | `LIMITED_AND_NON-COMPENSATING` | A historical ignored local candidate snapshot recorded `C1`-`C6` incomplete, `C7` supported, and `C8` inconclusive; those ignored files are not admissible publication provenance and require canonical regeneration. |
| Reproducibility | `SOFTWARE_REPRODUCIBLE_PUBLICATION_FREEZE_INCOMPLETE` | `README.md`, `docs/REPRODUCIBILITY_CHECKLIST.md`, and the Task 22 candidate replay show strong fail-closed replay behavior, but the bundle remains intentionally `INCOMPLETE`. |
| Publication readiness | `NOT_READY_FOR_CENTRAL_EMPIRICAL_CLAIMS` | `docs/MAIN_RESULTS_TARGETS.md` and the Task 22 verification report explicitly retain blockers for `E1`-`E6`, local model authority, external evaluator authority, and independent manual review. |

## Alignment with the proposed architecture

## 1. Single-pass auditable event

Paper Sections 2 and 6 define the core path as:

`task -> execute once -> commit -> post-commit audit -> challenge/DA -> mature receipt -> next-epoch weight`

The repository's declared vertical slice matches this directly:

- `README.md` defines the same core path
- `docs/superpowers/specs/2026-08-20-poi-mpp-publication-artifact-design.md` freezes the same bounded path
- Task 21 in `.superpowers/.../progress.md` states that synthetic task-to-committee mechanics and failure journeys are implemented and verified

Assessment: `ALIGNED`

## 2. Evidence kernel

The paper requires explicit commitment objects, audit surfaces, assurance tiers, and maturity rules. The repository formalizes that as the evidence kernel:

- canonical schemas, hashing, provenance, validation, and publication gates are first-class design objects in `docs/superpowers/specs/2026-08-20-poi-mpp-publication-artifact-design.md`
- the implementation plan centers `src/poi_mpp/evidence/` and fail-closed artifact lifecycles in `docs/superpowers/plans/2026-08-20-poi-mpp-publication-artifact-implementation.md`
- Task 22 candidate/frozen state discipline is explicit in `README.md` and `docs/REPRODUCIBILITY_CHECKLIST.md`

Assessment: `ALIGNED`

## 3. Protocol kernel

The paper's protocol kernel covers task creation, commitment, audit compilation, challenge/DA, receipt maturity, credit, and next-epoch weight. The repository mirrors that split:

- Python protocol kernel and Solidity contracts are explicit in the design spec
- contract surfaces in the design spec match the paper's Section 8 contract decomposition: policy/model/task/commitment/audit/receipt/credit
- Task 7-8 parity hardening and Task 21 end-to-end orchestration in `.superpowers/.../progress.md` indicate the Python-Solidity contract boundary was treated as a primary implementation surface

Assessment: `ALIGNED_WITH_MPP_SIMPLE_DISPUTE_LABEL`

Important limitation:

- the repository deliberately labels the dispute path `MPP_SIMPLE_DISPUTE`, not a production dispute VM; this is consistent with the approved MPP narrowing, but narrower than the full paper architecture

## 4. Semantic verification lane

The paper's semantic claims are ambitious but internally cautious: grounded/objective tasks first, open semantic uncertainty must abstain. The repository remains aligned only in the narrow grounded/objective direction:

- `README.md` limits the MPP to objective and grounded evidence tasks
- the design spec excludes universal open-semantic PoI from the first publication MPP
- the progress ledger records that Task 14 remains blocked for real confirmation without external evaluator authority

Assessment: `ALIGNED_BUT_UNVALIDATED`

## 5. EVM compatibility

The paper's EVM claim is not "everything runs on-chain"; it is "heavy AI work stays off-chain while compact commitments, disputes, receipts, and credit remain EVM-compatible." The repository is strongly aligned with that narrower statement:

- `README.md` states that the normal EVM path stores compact state only
- `docs/EXPERIMENT_PLAN.md` and `docs/EXPERIMENT_ARTIFACT_MATRIX.md` isolate E7 as the boundedness experiment
- current Task 22 claim matrix shows `C7` complete and `SUPPORTED`

Assessment: `ALIGNED_AND_EMPIRICALLY_NARROWLY_SUPPORTED`

## 6. Consensus-weight conversion

The paper's architecture converts matured receipts into next-epoch weight. The repository implements and reports this surface, but only as a reproducible simulation for the publication bundle:

- E8 is explicitly mapped to `T13` and `F11` in `docs/EXPERIMENT_ARTIFACT_MATRIX.md`
- `docs/MAIN_RESULTS_TARGETS.md` says E8 is a canonical `REPRODUCIBLE_SIMULATION` surface
- current Task 22 claim matrix marks `C8` complete but `INCONCLUSIVE`

Assessment: `ALIGNED_BUT_ONLY_SIMULATION-LEVEL`

## MPP scope fit versus full-paper scope

The paper includes broader surfaces than the approved first publication MPP:

- confidential/proprietary lane
- 70B, 600B, and MoE scaling
- production dispute VM
- production DA
- production consensus client
- independent cryptographic, semantic, smart-contract, and systems audits

The repository does not claim to implement those now, and the approved design explicitly excludes them in `docs/superpowers/specs/2026-08-20-poi-mpp-publication-artifact-design.md`.

That is a strength, not a weakness, provided the paper is edited to preserve the separation between:

- current MPP evidence
- future extension architecture

Assessment: `ALIGNED_IF_PAPER_LANGUAGE_IS_RESCOPED`

## Claim-by-claim evidence status

The following statuses were recorded by a historical ignored local Task 22 candidate. They are diagnostic history, not a current canonical claim-support artifact:

| Claim | Intended meaning | Current repository status |
|---|---|---|
| `C1` | single-pass cost advantage | `INCOMPLETE / INCONCLUSIVE` |
| `C2` | execution audit detects corruption | `INCOMPLETE / INCONCLUSIVE` |
| `C3` | semantic verifier utility | `INCOMPLETE / INCONCLUSIVE` |
| `C4` | DA gates authority | `INCOMPLETE / INCONCLUSIVE` |
| `C5` | optimistic dispute economics | `INCOMPLETE / INCONCLUSIVE` |
| `C6` | Sybil splitting does not materially inflate credit | `INCOMPLETE / INCONCLUSIVE` |
| `C7` | EVM path remains bounded | `COMPLETE / SUPPORTED` |
| `C8` | verified work can drive next-epoch weight | `COMPLETE / INCONCLUSIVE` |

This historical table is retained only to explain the prior diagnostic state. A clean, version-bound bundle must regenerate the claim matrix before publication use. Subsequent authorized E1 and E2 pilots exist only as ignored local raw workspace outputs and are not admissible publication artifacts. No admissible E4-E6 publication output is currently present. E1 is additionally bounded by a fixed-order pilot design, E2 by its narrow tested scope, and E4 by its declared-outcome-playback method boundary.

## Replacement for the paper's Section 17.1 score table

Use this instead of percentage scores:

| Paper category | Replace with | Reason |
|---|---|---|
| Overall protocol feasibility | `COHERENT_ARCHITECTURE_PENDING_NOVELTY_AND_EVIDENCE_GATES` | Coherence is real; novelty and evidence are not yet fully established. |
| Research-prototype implementability | `IMPLEMENTED_WITH_VERIFIED_MPP_NARROWING` | The repository demonstrates substantial implementation, but only inside the approved narrow scope. |
| EVM/L2/appchain implementability | `NARROWLY_SUPPORTED_FOR_LOCAL_EVM_BOUNDARY` | E7 support is real, but only for local Foundry measurement and compact-state boundedness. |
| Frontier-model compatibility | `ARCHITECTURALLY_PLAUSIBLE_EMPIRICALLY_UNRESOLVED` | The paper argues for 70B+/MoE compatibility, but the MPP intentionally does not validate that. |
| Common-path cost efficiency | `UNRESOLVED_AFTER_EXECUTED_E1_PILOT` | An authorized fixed-order E1 pilot exists only as ignored local raw output; it is not an admissible publication artifact, and the design cannot support C1. |
| Semantic verification strength | `UNRESOLVED_PENDING_E3_AND_EXTERNAL_AUTHORITY` | The semantic lane is implemented, but confirmation remains blocked. |
| Cryptographic/optimistic execution assurance | `PARTIALLY_IMPLEMENTED_PENDING_EXECUTED_E2_AND_DISPUTE_ECONOMICS` | There is meaningful software progress, but not the full empirical case. |
| Scalability architecture | `PLAUSIBLE_EXTENSION_ARCHITECTURE` | This is an architecture statement, not a demonstrated MPP result. |
| Production-ready theoretical protocol | `THEORETICAL_ONLY_DO_NOT_SCORE` | A numerical score overstates the absence of strongest-prior-art and empirical closure. |
| Production deployable today | `NOT_READY` | The repository itself preserves this by fail-closed bundle incompleteness. |

## Bottom-line assessment by dimension

### Primitive novelty

Status: `PROVISIONAL_PENDING_REPRODUCIBLE_PRIOR_ART_SEARCH`

Reason:

- the paper's Section 16 is a narrative novelty boundary, not a reproducible strongest-prior-art package
- the repository does not expose a dedicated prior-art search case, search ledger, or independent novelty challenge artifact

Recommended paper language:

- "The novelty claim is provisional pending a reproducible strongest-prior-art search and independent challenge."

### Architecture coherence

Status: `STRONG_WITHIN_APPROVED_MPP_SCOPE`

Reason:

- the repo consistently implements the same three-layer structure: evidence kernel, protocol kernel, vertical experiment slices
- the paper's main single-pass path is preserved across `README.md`, the design spec, and the implementation plan

### Implementation maturity

Status: `HIGH_FOR_MPP_SOFTWARE`

Reason:

- the repository contains a full test-driven surface spanning evidence, protocol, worker, auditor, reporting, EVM, E7/E8, Task 21 orchestration, and Task 22 replay
- `.superpowers/.../progress.md` records completion and review closure for the major MPP task groups

Important caveat:

- implementation maturity is not the same as empirical claim maturity

### Empirical evidence

Status: `LOW_TO_MODERATE_OVERALL`

Reason:

- central empirical support is currently concentrated in `C7`
- `C8` is complete but inconclusive and explicitly labeled `REPRODUCIBLE_SIMULATION`
- `C1`-`C6` remain incomplete in the live candidate bundle

### Reproducibility

Status: `STRONG_FAIL-CLOSED_SOFTWARE_REPRODUCIBILITY`

Reason:

- the candidate replay contract is explicit in `README.md` and `docs/REPRODUCIBILITY_CHECKLIST.md`
- the repository preserves `CANDIDATE_VERIFIED` versus `FROZEN_VERIFIED`
- the bundle remains nonzero `INCOMPLETE` rather than fabricating completion

Important caveat:

- publication reproducibility of the scientific bundle is not complete until the missing evidence and independent review gates are satisfied

### Publication readiness

Status: `NOT_READY`

Reason:

- `docs/MAIN_RESULTS_TARGETS.md` and the Task 22 verification report explicitly preserve blockers
- no frozen sentinel exists
- no authenticated independent manual review is present
- no current canonical bundle contains admissible publication artifacts for `E1`-`E6`; only ignored local raw E1/E2 pilot outputs currently exist

## Residual risks and objections

1. The paper's percentage scores create a false impression of empirical closure.
2. The paper's primitive novelty claim is not yet backed by a reproducible strongest-prior-art case.
3. The architecture is stronger than the current evidence package; that distinction must remain visible.
4. The current repository is a strong MPP engineering artifact, but not yet a central-claim-complete publication artifact.
5. The paper should not let future-scope claims about 70B/MoE, confidential GPU/TEE, or production consensus read as if they were validated by this repository state.

## Final disposition

If the paper is revised to treat this repository as:

- a narrow first-publication MPP,
- with strong architecture-to-code alignment,
- strong fail-closed reproducibility discipline,
- one positively supported EVM boundedness claim,
- one inconclusive next-epoch simulation claim,
- and the remaining central empirical claims still open,

then the repository and paper are substantially aligned.

If the paper continues to use aggregate 0-100 scores or broad feasibility language without those caveats, the alignment becomes overstated.
