# PoI MPP target-venue portfolio

Checked: 2026-08-25

Decision state: `WAITING_ACCOUNTABLE_AUTHOR_VENUE_SELECTION`

This portfolio narrows the submission route for the evidence-bound PoI MPP
manuscript. It records current official author instructions and a recommended
default, but it does not select a venue, approve declarations, close the E3 or
independent-review gates, or authorize submission.

## Recommended primary candidate

### Blockchain: Research and Applications — full length research paper

Recommendation: strongest current subject-matter and first-submission fit.

Rationale:

- The journal scope expressly includes smart contracts and distributed ledgers,
  consensus and fault tolerance, blockchain protocols and algorithms, security
  and privacy, performance optimization, and integration with emerging
  technologies. These surfaces match the proposed PoI protocol and the narrow
  local-EVM/open-weight-model artifact evaluation.
- The journal accepts full length research papers.
- For a new submission, the official guide permits one Word or PDF manuscript
  for refereeing; correct production formatting is deferred until revision.
- Review is single anonymized and suitable manuscripts are normally assessed by
  at least two independent expert reviewers.

Verified initial-submission requirements relevant to this manuscript:

- concise, factual, stand-alone abstract;
- no more than six keywords;
- figures, captions, tables, titles, descriptions, and footnotes must agree with
  their in-text citations;
- a competing-interest statement is required even when there are no interests;
- corresponding-author contact information and approved author metadata;
- CRediT contribution roles supplied by the corresponding author;
- funding source and sponsor-role disclosure;
- declaration of generative-AI use in manuscript preparation when applicable;
- optional but encouraged highlights: three to five bullets, each no more than
  85 characters, supplied as a separate editable file;
- separate editable source files are required at revision/production stage.

Official sources:

- Guide for Authors: https://www.sciencedirect.com/journal/blockchain-research-and-applications/publish/guide-for-authors
- Aims and Scope: https://www.sciencedirect.com/journal/blockchain-research-and-applications

Current policy record:

- fees/access model: the journal is open access. Its official open-access page
  lists a nominal full-length article publishing charge of USD 1,600 and, as
  checked on the date above, states that Zhejiang University Press covers the
  charge for accepted peer-reviewed submissions. This coverage is time-sensitive
  and must be rechecked before submission.
- data/code policy: the guide encourages depositing research data in a relevant
  repository, linking or citing the dataset, and explaining any inability to
  share. Software used in the work should be cited as a research output.
- AI policy: generative-AI use in manuscript preparation must be declared in the
  required section; AI tools may not be listed as authors. This repository's AI
  assistance still requires an accountable-author-approved, fact-specific
  disclosure.
- review/anonymity model: single-anonymized peer review; suitable manuscripts
  are normally sent to at least two independent expert reviewers.

Official access/fee source:

- Open access options: https://www.sciencedirect.com/journal/blockchain-research-and-applications/publish/open-access-options

Current blocking fit issue: the manuscript architecture fits, but C3 is `NOT_SUPPORTED` by the externally attested E3 run, E1/E2 remain inconclusive pilots, evaluator identity, independence, and private-key custody still require accountable out-of-band confirmation, independently signed domain review is absent, and author declarations are unapproved. The current
bundle therefore does not satisfy the scientific or accountable-human submission
gate for this journal.

## Aspirational security/dependability candidate

### IEEE Transactions on Dependable and Secure Computing — regular paper

Fit:

- TDSC covers foundations, methodologies, mechanisms, design, modeling,
  evaluation, measurement, and simulation for dependable and secure systems.
- PoI could fit only if framed around a specific security/dependability problem
  and supported by substantially stronger evaluation; generic systems-management
  or architecture-only framing is explicitly outside scope.

Verified format requirements:

- regular paper target: 12 double-column pages;
- submissions may extend to 18 pages subject to mandatory overlength charges;
- the limit includes references and author biographies;
- supplemental material must be submitted separately and has no stated page
  limit;
- the correct IEEE template must be obtained through the IEEE Template Selector.

Official sources:

- Scope and call: https://www.computer.org/digital-library/journals/tq/cfp-dependable-secure-computing
- Author information: https://www.computer.org/csdl/journal/tq/write-for-us/15068

Current disposition: aspirational only. The negative and very small E3 result,
inconclusive E1 and E2 designs, bounded prior-art search, and lack of external replication do not
currently support a TDSC submission claim.

## Broad open-access computing candidate

### IEEE Open Journal of the Computer Society — research article

Fit:

- OJ-CS accepts peer-reviewed open-access articles across the IEEE Computer
  Society's computing scope, so the cross-domain AI/blockchain system is within
  its broad topical boundary.

Verified format requirements:

- use the official IEEE Open Journals Word or LaTeX article template;
- limit: 12 double-column pages;
- submit figures individually in PS, EPS, PDF, PNG, or TIF format.

Official source:

- Call and submission instructions: https://www.computer.org/digital-library/journals/oj/cfp-open-journal

Current disposition: plausible alternate after evidence closure. The existing
16-page single-column PDF cannot establish compliance with a 12-page
double-column limit; the official template must be applied and measured after
venue selection.

## Accountable-author decision package

Before any venue is selected or a submission artifact is created, accountable
humans must approve and provide:

- author list and order;
- corresponding author and complete contact information;
- CRediT roles;
- funding statement and sponsor role;
- competing-interest statement;
- AI-use declaration consistent with the selected venue policy;
- ethics or not-applicable rationale for the actual E3 data and evaluator notes;
- data, code, model-license, and repository availability terms;
- confirmation that the work is not under consideration elsewhere;
- final manuscript, figure, table, supplement, and portal-preview approval.

The recommended default is `Blockchain: Research and Applications / full length
research paper`, but that recommendation is not a venue-selection decision and
does not authorize submission.

Acceptance probability: `NOT ESTIMABLE`. No target-matched, current calibration
dataset is available, so this portfolio does not invent acceptance odds.

## Next gated transition

After the accountable author selects a venue:

1. record the selected venue, article type, and submission stage;
2. refresh the official instructions on that date;
3. obtain and hash the official template when required;
4. create the venue-specific checklist and source package;
5. close E3 and authenticated independent-review gates;
6. rebuild, mechanically validate, and render-inspect the venue PDF;
7. obtain accountable-human approval of declarations and portal preview.
