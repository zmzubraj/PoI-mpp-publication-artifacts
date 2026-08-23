# E3 semantic evaluator authority request checklist

Purpose: obtain accountable external evaluator authority for the E3 confirmatory path only.

This file is an unsigned request checklist. It is not an authority record and not an approval.

## Why E3 needs external authority

E3 is the grounded semantic assurance slice.

Current repository statement:

- experiment: `E3`
- design summary: grounded semantic assurance using held-out grounded items
- required publication artifacts: `T4` + `T8` + `F7`
- evidence-origin contract: `REAL_MODEL_EXECUTION` for confirmation
- current publication status: no authorized confirmatory publication artifact currently present
- current claim disposition: `INCONCLUSIVE`

Reference surfaces:

- `../../../EXPERIMENT_PLAN.md`
- `../../../EXPERIMENT_ARTIFACT_MATRIX.md`
- `../tables/T4_experiment_design_and_current_status.md`
- `../tables/T7_limitations_and_nonclaims.md`
- `../manuscript/POI_SUBMISSION_MANUSCRIPT.md`

## Required external capability

The external evaluator authority must be able to do all of the following:

- evaluate grounded semantic outputs on held-out or otherwise authorized grounded items;
- assess or authorize the computation of `FAR`, `FRR`, `ABSTAIN`, coverage, and calibration surfaces;
- assess privacy or confidentiality constraints around prompts, evidence, labels, or evaluator notes;
- distinguish operational semantic validation from open-ended claims of universal intelligence;
- bind any authorization to exact artifact hashes and execution scope;
- sign the resulting authority record outside the bundle.

## Current draft request set

The following tracked source set should be shown to the external authority only after a canonical bundle has been generated and the exact final revisions have been hashed. The values from an earlier temporary candidate are intentionally not carried forward because that candidate is not the current canonical bundle.

| Relative path | Why it matters |
|---|---|
| `../manuscript/POI_SUBMISSION_MANUSCRIPT.md` | current manuscript claim boundary |
| `../../../EXPERIMENT_PLAN.md` | experiment intent and E3 role |
| `../../../EXPERIMENT_ARTIFACT_MATRIX.md` | E3 to artifact mapping |
| `../../../PAPER_ARTIFACT_MAP.md` | paper artifact closure rules |
| `../../../MAIN_RESULTS_TARGETS.md` | current blockers and claim rule |
| `../tables/T4_experiment_design_and_current_status.md` | current E3 design/status summary |
| `../tables/T7_limitations_and_nonclaims.md` | explicit non-claims and review limits |

The canonical authority handoff must add the generated `verification_report.json` and `claim_support_matrix.json` and bind every listed artifact to its exact SHA-256 value.

## Future bind set once E3 artifacts exist

An actual authority decision for confirmatory E3 publication use should also bind the future generated artifacts when they exist:

- `publication/tables/T4_dataset_composition.status.json`
- `publication/tables/T8_semantic_verification.csv`
- `publication/figures/F7_semantic_verification_quality.svg`
- any raw E3 execution bundle or evaluator-side artifact designated by the execution contract

These artifacts are not currently present as authorized confirmatory publication evidence in the current candidate.

## Checklist for the requesting side

- [ ] confirm that the requested scope is E3 only, not a blanket authorization for all claims
- [ ] confirm that the authority is external to the producing chain
- [ ] generate and provide the full canonical hash-bound request set derived from the draft inputs above
- [ ] provide the exact E3 capability request without upgrading current claim status
- [ ] provide privacy and confidentiality handling expectations
- [ ] state that `C3` is currently incomplete / inconclusive
- [ ] state that any future approval must bind exact artifact hashes
- [ ] state that no AI output or producer self-attestation can substitute for the authority decision

## Checklist for the future external authority record

The future externally completed authority record should include all of the following:

- authority identity
- authority organization or accountable basis
- expertise scope relevant to grounded semantic evaluation
- authorized task class and limits
- reviewed hash set
- decision scope
- date in strict ISO format
- external signature reference
- note that the signature and any allowed-signers registry live outside the bundle

Use `semantic_evaluator_authority_record.schema.json` for machine validation of a future completed record.

## Non-claims

This checklist does not:

- grant authority;
- certify E3;
- certify C3;
- satisfy the freeze gate;
- create a detached signature;
- create an allowed-signers registry.
