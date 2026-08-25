# PoI MPP submission-readiness validation

## Audit record

- Manuscript or project: *Complete Proof of Intelligence Consensus Architecture*
- Version/date: repository manuscript and evidence bundle inspected through 2026-08-25
- Authorization: the user authorized local model, experiment, artifact, and manuscript work; externally signed E3 pre-execution authority and post-execution artifact attestation were verified against the signed revision, but that cryptographic verification does not establish independent scientific review
- Confidentiality and processing: local-only repository inspection; no unpublished material was uploaded to an external service in this audit
- Field and study type: blockchain/AI systems architecture with real-model pilots, local EVM measurements, and reproducible simulations
- Maturity: narrow MPP prototype with heterogeneous internal evidence
- Target venue and article type: undecided; the dated venue portfolio recommends *Blockchain: Research and Applications* / full length research paper, pending accountable-author selection
- Venue requirements checked: official author/scope pages for *Blockchain: Research and Applications*, IEEE TDSC regular papers, and IEEE OJ-CS research articles were inspected on 2026-08-24; no template is authoritative until a venue is selected and the rules are refreshed
- Materials reviewed: manuscript Markdown/DOCX/PDF, canonical publication manifest, claim matrix, omission ledger, E1-E8 tables and figures, algorithm and Mermaid sources, replay/freeze code, external-review request schemas
- Materials unavailable or not independently confirmed: accountable out-of-band evaluator identity/independence/private-key custody confirmation, independently signed domain-expert review, external reproduction return, detached review signature, frozen bundle sentinel, selected-venue template and completed checklist, author/CRediT/declaration approvals
- Reviewer role: AI developmental audit only; not an independent human or editorial decision

## Fresh-current E3 revalidation

The retained canonical E3 receipt remains bound to signed revision
`ab78c6fddd0b872e92ed607504400964eb3559a8`; it preserves the externally attested
negative result and C3 `NOT_SUPPORTED`. On 2026-08-25 both canonical
verification commands were re-run against the current repository request manifest
and the current files under `/Users/rainbow/Documents/POI_E3_EXTERNAL`. Authority
verification failed `request manifest sha256 mismatch`, and result-attestation
verification failed because that same pre-execution authority check failed.
Exact current hashes are retained in the machine-generated request and verifier
output rather than copied into this narrative audit, avoiding a circular request
regeneration dependency. The current result-attestation record is dated
`2026-08-25`, matching the current verification date. The detached signatures
remain cryptographically valid for the exact authority and attestation
JSON files, and the four attested artifact hashes match the current artifact
files, but those narrower checks do not repair the broken current
request -> authority -> attestation chain. Fresh-current E3 end-to-end
verification is therefore `BLOCKED_HASH_CHAIN_DRIFT`; it is not evidence that
the retained negative result should be removed or upgraded.

## Contribution map

**Gap:** Mandatory re-execution or universal proof generation makes common-path verification of AI responses costly. **Question:** Can one committed model execution expose post-commit audit surfaces and mature into bounded protocol authority without overstating unverified semantics or production consensus security? **Method:** SPAI binds task, model, response, trace, evidence, audit, challenge/data-availability, receipt, credit, and next-epoch weight state. **Evidence:** E1 and E2 real-model pilots, the externally attested E3 real-model negative result, E4-E6 and E8 reproducible simulations, and E7 local Foundry measurements. **Limitations:** E1/E2/E4/E8 are inconclusive, E5/E6 are simulation-only, E7 is local-only, and E3 is `NOT_SUPPORTED` because FAR 0.500 (1/2) exceeded `alpha_sem = 0.25`; n=8 and invalid n=2. **Implication:** the repository supports a technically coherent, fail-closed MPP artifact architecture, not general semantic verification or production consensus security.

## Executive verdict

- Supported developmental stage: `TECHNICALLY_PROMISING`
- Submission status: `NOT_READY`
- Lowest-stage rationale: a substantial, reproducible narrow MPP exists and E3 is an attested negative result, but independent expert review, external reproduction, evaluator identity/key-custody confirmation, venue selection, and the final freeze are absent; strongest-prior-art novelty has not been independently closed
- Non-guarantee: this is an evidence-bounded developmental audit, not an acceptance, percentile, impact, prize, or editorial prediction

## Requirement-by-requirement completion audit

| Objective requirement | Current evidence | Status | Consequence / exact next proof |
|---|---|---|---|
| Local 1B-8B open-weight model artifact | pinned Qwen2.5-1.5B manifest and hashes; local replay configuration binds the reviewed revision | `PROVEN_LOCAL` | retain exact model/tokenizer/runtime hashes in any new run |
| Authorized E1 execution | canonical T6/F5, `REAL_MODEL_EXECUTION`, fixed-order pilot | `PROVEN_BUT_INCONCLUSIVE` | counterbalanced frozen design is required before any general cost claim |
| Authorized E2 execution | canonical T7/F6, `REAL_MODEL_EXECUTION`, frozen 4-by-4 audit surface | `PROVEN_BUT_INCONCLUSIVE` | broader attacks, tasks, models, and independent replication are required for generalization |
| E3 semantic execution | verified external pre-execution authority; verified post-execution attestation; T4/T8/F7/raw `REAL_MODEL_EXECUTION`; FAR 0.500 (1/2), FRR 0.167 (1/6), ABSTAIN 0.125 (1/8), coverage 0.875 (7/8), Brier 0.178; n=8, invalid n=2 | `COMPLETE_NEGATIVE_RESULT / C3_NOT_SUPPORTED` | preserve exact negative result; obtain accountable out-of-band identity/independence/key-custody confirmation and independent replication before any broader claim |
| E4 execution/evidence | canonical declared-outcome playback simulation | `PROVEN_SIMULATION_INCONCLUSIVE` | executed reconstruction is required for a stronger DA claim |
| E5 execution/evidence | canonical reproducible simulation | `PROVEN_SIMULATION_ONLY` | no deployment or open-network watcher claim is supported |
| E6 execution/evidence | canonical reproducible simulation | `PROVEN_SIMULATION_ONLY` | no open-network Sybil-resistance claim is supported |
| No synthetic result promoted | claim matrix and manuscript distinguish real execution, Foundry, simulation, absence, and `SYNTHETIC_NON_EVIDENCE` plumbing | `PROVEN_FOR_CANONICAL_BUNDLE` | external reviewer must recheck origin labels and omission closure |
| Final manuscript prose | English evidence-bound Markdown plus rendered DOCX/PDF | `PROVEN_AS_VENUE_NEUTRAL_DRAFT` | target-venue template, declarations, accountable author approval, and portal preview remain |
| Final diagrams | editable Mermaid sources plus reviewed raster/vector derivatives | `PROVEN_ARTIFACT_SET` | external reviewer must confirm scientific fidelity, final-size readability, accessibility, and venue format |
| Final tables | editable CSV/Markdown tables plus canonical machine-readable sources | `PROVEN_ARTIFACT_SET` | external reviewer must verify denominators, intervals, negative results, and exact manuscript agreement |
| Final algorithms | Algorithms 1-5 in manuscript plus detailed source specifications | `PROVEN_ARTIFACT_SET` | independent cryptographic/protocol review remains |
| Primitive novelty score and overall assessment | developmental scorecard exists outside the paper | `PROVEN_DEVELOPMENTAL_ONLY` | reproducible strongest-prior-art search and independent challenge are required for a novelty verdict |
| External semantic-evaluator authority and artifact attestation | detached signatures and exact hash bindings verified against signed revision | `CRYPTOGRAPHICALLY_VERIFIED` | separately confirm the recorded evaluator's real-world identity, independence, expertise, and private-key custody; signature validity alone is not independent scientific evaluation |
| Signed independent domain-expert review | unsigned schema and request packet only | `MISSING_EXTERNAL` | real reviewer identity, independence basis, completed checks, reviewed hashes, detached signature, and trusted allowed-signers file |
| E1/E2 claim narrowing | versioned audit preserves fixed-order and narrow-surface ceilings | `CLAIM_NARROWED` | only a new frozen design plus authorized real execution and external reproduction may reopen C1/C2 |
| External reproduction package | deterministic manifest, clean-room protocol, schemas, and signature contract exist | `WAITING_EXTERNAL` | a real independent team must execute and return authenticated logs, discrepancies, and attestation |
| Publication freeze sentinel | absent by design while independent and human gates are open | `BLOCKED` | clean versioned candidate, authenticated review and reproduction, accountable declarations/venue decision, verifier pass, then sentinel generation |
| Submission-ready venue package | dated three-venue portfolio and official requirements snapshot exist, but no venue/article type is selected | `PARTIAL_DECISION_PACKAGE_ONLY` | accountable author selects venue; refresh and apply its current template/checklist and perform final human PDF/portal review |

## Critical gate ledger

| ID | Gate/question | Status | Evidence and location | Consequence | Smallest adequate action |
|---|---|---|---|---|---|
| KQ-01 | Is the problem precise and the contribution bounded? | `PASS` | manuscript Sections 1-2 distinguish full architecture from the narrow MPP | supports coherent systems framing | preserve the two-layer boundary in every venue version |
| KQ-02 | Is primitive novelty established against strongest prior art? | `PARTIAL` | CommitLLM and opML are identified as close predecessors; no reproducible independent search case exists | primitive novelty cannot be claimed as resolved | freeze queries, screening, chaining, closest-predecessor matrix, and independent challenge |
| KQ-03 | Does the design support the general single-pass cost claim? | `FAIL` | E1 is a two-pair fixed-order pilot capped at `INCONCLUSIVE` | no general efficiency claim | run a separately frozen counterbalanced design with precision rationale |
| KQ-04 | Does the execution-audit experiment support broad soundness? | `FAIL` | E2 covers four attacked observations and one honest control in a narrow frozen surface | no general soundness or robustness claim | expand task/model/attack scope and obtain independent replication |
| KQ-05 | Is semantic verification empirically supported? | `FAIL` | externally attested E3 real-model run has FAR 0.500 (1/2) > `alpha_sem = 0.25`; C3 is `NOT_SUPPORTED`; n=8, invalid n=2 | general semantic-performance claims are inadmissible | preserve the negative result; any new claim requires a separately frozen, powered design and independent replication |
| KQ-06 | Are simulations labeled and prevented from becoming empirical evidence? | `PASS` | E4-E6/E8 origins and manuscript captions explicitly say simulation | protects evidence integrity | external reviewer rechecks all tables, captions, and abstract wording |
| KQ-07 | Is local EVM evidence traceable and bounded? | `PASS` | E7 T12/F12 and raw Foundry bundle; manuscript reports 15 rows and local-only limits | supports local boundedness only | retain raw bundle and Foundry/toolchain hashes |
| KQ-08 | Are effect sizes, denominators, and uncertainty reported where applicable? | `PARTIAL` | E1/E2 denominators and intervals are present; simulation and E7 scopes are explicit | adequate for current descriptive claims, not broader inference | independent methods review of every table/caption |
| KQ-09 | Are negative and inconclusive findings visible? | `PASS` | manuscript Table 1, limitations, claim matrix, and omissions retain negative states | reduces selective-reporting risk | do not remove these states during venue compression |
| KQ-10 | Can central outputs be regenerated from versioned code and inputs? | `PARTIAL` | canonical manifest and replay pipeline exist; freeze is incomplete and one live E7 reporting test has shown intermittent long execution | reproducibility is strong but not release-closed | clean candidate replay, investigate live E7 test duration, and archive logs/SBOM |
| KQ-11 | Are figures honest, editable, and accessible? | `PARTIAL` | quantitative figures derive from canonical JSON; Mermaid and table sources are editable; manual final-size checks exist | independent accessibility/scientific visual review still absent | external reviewer affirms editability/accessibility checks |
| KQ-12 | Are citations and priority claims verified? | `PARTIAL` | all 12 retained references are normalized to primary or official sources, but prior-art coverage remains bounded | citation normalization passes; novelty and priority remain unresolved | complete the reproducible strongest-prior-art search and independent challenge |
| KQ-13 | Are real-world and production claims supported? | `FAIL` | no field, mainnet, production DA, production dispute VM, or production consensus evaluation | production/general deployment claims are inadmissible | keep as future work or collect matching external evidence |
| KQ-14 | Are ethics, conflicts, authorship, funding, and AI-use declarations complete? | `UNKNOWN` | no accountable author/CRediT/declaration package was available | venue package cannot be finalized | accountable authors complete and approve declarations under venue policy |
| KQ-15 | Has a qualified independent human reviewed the complete package? | `FAIL` | only unsigned request templates exist | submission freeze is blocked | obtain authenticated independent domain-expert review |
| KQ-16 | Are current venue rules and reporting requirements satisfied? | `PARTIAL` | official rules for three candidates were checked on 2026-08-24; selection, template application, and checklist remain open | “submission-ready” cannot be established | accountable author selects venue, then refresh and apply that venue's exact rules |
| KQ-17 | Is the complete uploaded package inspected? | `FAIL` | no submission portal package exists | final formatting/anonymity/file checks cannot occur | build venue package and perform accountable human portal preview |

## Fatal flaws and stop conditions

No fabricated evidence or hidden synthetic promotion was found in the canonical bundle. The following are submission stop conditions rather than ordinary prose defects:

| ID | Status | Claim affected | Why blocking | Required resolution |
|---|---|---|---|---|
| STOP-1 | `OPEN` | semantic assurance / C3 | the authorized E3 result is negative (`NOT_SUPPORTED`) and the n=8 sample cannot establish general reliability | retain C3 as unsupported; only a new preregistered, authorized, adequately sized and independently replicated study may test a revised claim |
| STOP-2 | `OPEN` | independent validity of the package | no authenticated external domain-expert review exists | completed hash-bound record and verified detached signature |
| STOP-3 | `OPEN` | formal submission readiness | no target venue, article type, current template, or author declarations are fixed | accountable author decision and venue-specific QA |
| STOP-4 | `OPEN` | frozen reproducibility claim | no final freeze sentinel can be issued while external gates remain open | close upstream gates, replay clean candidate, verify, then freeze |
| STOP-5 | `OPEN` | fresh-current E3 trust chain | current repository request and current external authority/attestation files fail canonical verification with `request manifest sha256 mismatch` | accountable evaluator restores the exact historical signed inputs or issues an honestly labelled reconciliation record binding the current files; do not fabricate retroactive pre-execution authority |

## Novelty matrix

| Prior work | Verified overlap | Material proposed difference | Evidence strength | Remaining novelty risk |
|---|---|---|---|---|
| CommitLLM | open-weight LLM commit-and-audit, challenge-time trace opening, exact and Freivalds-style checks | PoI adds semantic-evidence binding, receipt maturity, task-budgeted credit, and next-epoch weight | official project repository / grey literature | closest implementation predecessor; composition may be obvious without independent challenge |
| opML | optimistic fraud-proof route for on-chain ML | PoI integrates a broader receipt/credit/consensus lifecycle | primary arXiv paper | optimistic dispute is not a new primitive |
| zkGPT | verifiable LLM inference through non-interactive zero knowledge | PoI targets a lighter optimistic common path | peer-reviewed USENIX paper | comparison lacks equal-hardware benchmark evidence |
| Optimistic TEE-Rollups | optimistic plus confidential-computing architecture for generative-AI inference | confidential lane is deferred; PoI emphasizes evidence-to-consensus lifecycle | arXiv preprint | overlapping system composition may narrow novelty further |
| HotStuff and weighted-BFT lineage | epoch/committee consensus mechanisms | PoI proposes bounded task-derived weight as an input | peer-reviewed foundational work plus architecture proposal | no live consensus validation establishes safety or value |

Search status: bounded predecessor verification only. No frozen multi-database query ledger, screening counts, known-item recovery, patent/standard search, citation-chain closure, non-English coverage, or differently owned independent search challenge is available.

## Real-world and generalization audit

| Claim | Current environment | Comparator | Outcome | Boundary/failure condition | Supported maturity |
|---|---|---|---|---|---|
| single-pass common-path cost | one local 1.5B model, two fixed-order pairs | local two-run baseline | descriptive timing delta | order, thermal, hardware, task, and model dependence | internal pilot |
| execution-audit detection | four attacks plus one control | frozen exact/field/float checks | 4/4 observed detection with wide Wilson interval | narrow attack and tensor surface | internal pilot |
| semantic assurance | one 1.5B real-model run; n=8, invalid n=2 | frozen `alpha_sem = 0.25` rule | FAR 0.500, FRR 0.167, ABSTAIN 0.125, coverage 0.875, Brier 0.178; C3 `NOT_SUPPORTED` | tiny frozen surface; no general semantic reliability | internal negative real-model evidence with externally signed artifact attestation |
| watcher and Sybil economics | declared simulations | frozen scenario alternatives | scenario-bounded support | model assumptions and open-network behavior | simulated |
| EVM boundedness | local Foundry | configured local block limit | max observed gas 467,937 | no mainnet/state-growth/fee-market evidence | internal local measurement |
| consensus security | reproducible simulation | frozen ablations | inconclusive | no live network, adversarial operators, or longitudinal evidence | simulated |

## Manuscript and evidence package findings

- Manuscript architecture: coherent, standard systems-paper flow with explicit scope and limitations; still venue-neutral.
- Claims and citations: central numeric claims trace to the canonical bundle; novelty and priority remain provisional.
- Methods and statistics: sufficient to disclose current pilot boundaries, but E1 precision/design and E2 breadth do not support general claims.
- Reproducibility: strong manifest/provenance discipline; final clean freeze and independent reproduction are absent.
- Figures: paper-used quantitative PNGs derive from canonical JSON; canonical SVG/JSON remain authoritative.
- Tables: editable CSV/Markdown sources exist and preserve origin/status boundaries.
- Diagrams: editable Mermaid sources exist; production/deferred paths are labeled.
- Algorithms: five manuscript algorithms and detailed source specifications exist.
- Images/integrity: no evidentiary photographs or microscopy; graphical material is architectural or data-derived.
- Reporting checklist: no venue-specific checklist selected or completed.
- Ethics/disclosures: author, funding, conflict, contribution, AI-use, and submission approvals remain accountable-human tasks.
- Data/code availability: local repository paths and hashes exist; no archival DOI or long-term release record is established.
- Submission files: venue-neutral DOCX/PDF exist; there is no final venue template, cover letter, supplementary package, anonymity check, or portal preview.

## Simulated editor and reviewer objections

### Editorial screen

The paper presents an ambitious architecture, but the central semantic experiment produced a negative result on only eight items and most other evidence is either a tiny pilot or simulation, leaving insufficient evidence for a broad publication claim.

### Domain reviewer

CommitLLM and opML already cover important execution-commitment and optimistic-dispute primitives; the paper must demonstrate that the receipt-credit-consensus composition is materially non-obvious and useful.

### Methods/statistics reviewer

E1 is confounded by fixed order and two pairs, while E2 is too narrow for a general soundness claim; both require stronger prespecified designs or much narrower claims.

### Reproducibility reviewer

The repository is unusually disciplined, but an unfrozen worktree, missing independent reproduction/review records, and incomplete release packaging prevent independent end-to-end reproduction of the submission claim.

### Real-world adopter

Local Foundry gas and simulations do not establish performance, safety, incentive compatibility, or operational reliability under a real network and adversarial participants.

### Ethics/integrity reviewer

The evidence-origin rules are strong, but authorship, conflicts, funding, AI-use disclosure, evaluator identity/independence/key-custody confirmation, and reviewer accountability must be completed by real responsible humans.

## Prioritized remediation

| Priority | Action | Owner | Required evidence | Acceptance test | Dependencies | Effort | New data? |
|---|---|---|---|---|---|---|---|
| P0 | confirm E3 evaluator identity, independence, expertise, and key custody | accountable evaluator and author | out-of-band identity binding, conflict/independence declaration, and custody confirmation referencing the verified key fingerprint and hashes | accountable signed record is authenticated without changing the attested result | evaluator contact and trusted channel | external | no |
| P0 | reconcile the fresh-current E3 hash chain | accountable evaluator and author | exact historical signed request/authority inputs or a new, honestly labelled reconciliation record with detached signature and complete hash bindings | both canonical verifiers pass for one internally consistent package, without describing later reconciliation as retroactive pre-execution authority | evaluator contact and trusted channel | external | no |
| P0 | obtain independent domain-expert review | independent qualified human | complete review record, all checks, conflicts, independence basis, signature | verifier reports `manual_review_authenticated=true` | reviewable candidate bundle | external | no, unless reviewer requests |
| P1 | preserve and independently reproduce E3 negative result | independent external team | exact clean-room replay logs, discrepancies, raw provenance, and detached attestation | authenticated reproduction record agrees or reports discrepancies without upgrading C3 | external team and package | substantial | yes |
| P1 | close strongest-prior-art case | search owner plus independent challenger | reproducible queries, screening, chaining, novelty matrix, contradiction ledger | independent challenge reconciled | search access | substantial | no experimental data |
| P1 | strengthen or narrow C1/C2 | methods owner | counterbalanced E1 and broader E2, or permanently narrowed claims | prespecified gates and independent reproduction pass | compute and design freeze | substantial | yes |
| P1 | select target venue/article type from the dated portfolio | accountable authors | signed or otherwise accountable venue/article-type decision | selected template/checklist contract frozen after a current-rule refresh | author decision | small | no |
| P2 | preserve the closed retained-reference audit | citation owner | 12 retained references normalized with no unresolved retained item | reference audit and manuscript bibliography remain consistent | manuscript changes | small | no |
| P2 | complete declarations and AI-use statement | accountable authors | authorship, CRediT, funding, conflicts, ethics/N/A, data/code, AI disclosure | venue checklist and author approvals complete | venue selection | medium | no |
| P2 | investigate live E7 reporting duration | engineering owner | bounded test log and root-cause result | both live tests finish within declared timeout | local Foundry | small-medium | no |
| P3 | apply venue formatting and portal QA | publication owner plus accountable human | final template, fonts, anonymity, page limits, source uploads, portal preview | human checklist signed | all upstream gates | medium | no |

## Residual unknowns and required human checks

- qualified domain expert: required for protocol, economic, cryptographic, and claim-language review
- statistician/methodologist: required if C1/C2 are retained as inferential claims
- ethics/legal/privacy: required if E3 prompts, labels, evaluator notes, or proprietary evidence carry restrictions
- independent reproduction: not yet demonstrated by an external team
- image/plagiarism tools: no authoritative clearance performed
- journal/editor clarification: three candidate routes are documented, but accountable-author venue selection remains undecided
- accountable authors: must approve authorship, declarations, AI disclosure, final PDF, and submission portal

## Re-audit history

| Date | Changed evidence | Questions re-run | Status changes | Remaining blockers |
|---|---|---|---|---|
| 2026-08-24 | evidence-bound manuscript, deterministic quantitative derivatives, current manifest, replay and external-review templates | full critical-gate set | local model/replay and artifact handoff improved; readiness remains `NOT_READY` | independent signed review, venue package, freeze sentinel |
| 2026-08-24 | citation cleanup, seven canonical quantitative figures, pinned DOCX dependency, candidate-only replay correction | KQ-10, KQ-11, KQ-12 and delivery checks | retained citations have no unresolved item; delivery and replay evidence improved; readiness remains `NOT_READY` | independent signed review, venue package, freeze sentinel |
| 2026-08-24 | official three-venue portfolio and accountable-author decision package | KQ-16 and venue-package requirement | venue-rule knowledge moved from `UNKNOWN` to `PARTIAL`; readiness remains `NOT_READY` | accountable venue selection, independent signed review, declarations, template/checklist, freeze sentinel |
| 2026-08-24 | permanent E1/E2 claim-narrowing audit and deterministic external-reproduction handoff | KQ-03, KQ-04, independent reproduction | current claims are explicitly narrowed; external reproduction remains `WAITING_EXTERNAL`; readiness remains `NOT_READY` | real external team execution, authenticated attestation, independent review, declarations, freeze sentinel |
| 2026-08-24 | externally authorized and post-execution-attested E3 real-model run | KQ-05, STOP-1, provenance and semantic claim boundary | C3 changed from `WAITING_EXTERNAL` to `NOT_SUPPORTED`; readiness remains `NOT_READY` | preserve negative result; confirm identity/independence/key custody; obtain independent reproduction and review |
| 2026-08-25 | fresh-current E3 authority and result-attestation verification against the current repository request and current external directory | provenance, trust-chain freshness, STOP-5 | both canonical verifiers fail closed with `request manifest sha256 mismatch`; retained signed-revision negative result and C3 `NOT_SUPPORTED` remain unchanged | accountable evaluator restores exact historical signed inputs or issues an honestly labelled reconciliation record; identity/independence/key custody and independent review remain external |

## P1/P2 gate table

This table is operational, not a readiness promotion. `COMPLETE` means the local
artifact requested for that row exists and passed its bounded mechanical checks;
it does not replace external or accountable-human decisions.

| Item | Current state | Evidence boundary | Exact next human or external action |
|---|---|---|---|
| strongest-prior-art novelty case | `WAITING_EXTERNAL` | dated bounded primary package is reproducible; novelty remains `NOVELTY_UNRESOLVED`; differently owned AI challenge is developmental only | qualified independent search owner reviews the frozen package, expands access-limited patent/standards/full-text surfaces, signs the exact reviewed hashes, and reconciles any stronger predecessor |
| E1 general efficiency | `INCONCLUSIVE/CLAIM_NARROWED` | two-pair fixed-order real-model pilot only | retain narrow pilot language, or separately authorize a frozen counterbalanced confirmatory design before any new run |
| E2 broad soundness | `INCONCLUSIVE/CLAIM_NARROWED` | one model/task/layer/token surface; four attacks plus one control | retain narrow pilot language, or predeclare broader tasks/models/attacks and independent replication before execution |
| independent external reproduction | `WAITING_EXTERNAL` | deterministic unsigned clean-room package exists | external team verifies identity/independence, executes the exact package, and returns authenticated logs, discrepancy report, and detached signature |
| venue and article type | `WAITING_USER` | dated three-venue portfolio exists; recommendation is non-binding | accountable author selects venue/article type and approves a current-rule refresh |
| authorship and declarations | `WAITING_USER` | fail-closed structured author input form exists | all accountable authors provide and approve factual authorship, CRediT, funding, conflicts, ethics/N/A, availability, AI-use, and final-approval records |
| venue-specific package | `BLOCKED` | no venue has been selected; therefore no official template is authoritative | after venue selection, obtain and hash the official template, apply current limits/anonymity/checklists, and build the source/supplement/cover-letter package |
| final figures and tables | `WAITING_EXTERNAL` | hashes, editable sources, captions, and developmental integrity/accessibility ledger exist | qualified independent human verifies scientific fidelity, grayscale/color-vision behavior, final-size typography, denominators/units, and signs the record |
| final PDF and portal approval | `WAITING_USER` | unsigned fail-closed checklist exists | accountable author reviews exact PDF, declarations, uploads, and portal preview bound to hashes, then records approval; do not submit beforehand |
