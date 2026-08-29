# E3-v2 Phase-3 Engineering Finding and Remediation Ledger

Status: `ENGINEERING_COMPLETE_WAITING_EXTERNAL_SIGNED_REVIEW`

This ledger records developmental engineering findings only. It is not an
independent-review verdict and does not authorize model execution.

| ID | RED finding | Remediation | Verification |
|---|---|---|---|
| P3-01 | Development preparation loaded the confirmatory authority verifier, making the development request schema unusable. | Dispatch by request schema and use `verify_development_authority` for the development path; its detached signature check delegates to `scripts/verify_e3_authority.py`. | Development and confirmatory regression tests. |
| P3-02 | Request material hashes were not fully re-derived and symlink components could evade a post-resolution check. | Rebuild the complete request from validated bundle materials and current repository inputs; reject every symlink component, stale request, stale authority, scope drift, and material drift. | Authority adversarial suite. |
| P3-03 | `APPROVED`/`LIMITED_SCOPE` semantics were not exact. | Require exact requested scope for `APPROVED`; require a strict requested subset retaining `RAW_E3_EXECUTION` for development `LIMITED_SCOPE`; retain the existing confirmatory limited-scope HOLD. | Scope adversarial and confirmatory regression tests. |
| P3-04 | The runner re-verified authority through a second path and omitted full authority lineage. | Consume the single verified prepared grant; bind authority record, request, allowed-signers, signature, scopes, and material hashes into a self-digested execution manifest. | Runner adversarial suite. |
| P3-05 | Partial writes could expose an incomplete final run directory. | Write to an external staging directory and rename atomically only after manifest closure; remove staging on failure. | Injected-write-failure tests. |
| P3-06 | A declared model manifest did not prove the locally loaded bytes matched it. | Resolve offline cache only, re-hash every declared model/tokenizer file, reject missing, symlinked, unsafe, or mismatched bytes, then load the verified snapshot path. | Pinned-byte tamper test. |
| P3-07 | Real output parsing did not require the frozen three-field schema. | For the real adapter require exact `decision`, `support_fraction`, and `calibrated_confidence`; fail closed to `ABSTAIN,0,0`. | Structured-output adversarial test. |
| P3-08 | The exporter trusted well-formed prompt/raw-output hashes and did not close trace/summary/manifest or record coverage. | Re-derive prompt and raw-output hashes; require one-to-one dataset/trace closure and exact real adapter/origin. | Exporter mutation tests. |
| P3-09 | Calibration did not require the authority and execution manifest inputs and was not transactional. | Re-verify development authority, bind the execution lineage and material hashes, reject confirmatory material, and atomically emit a self-digested calibration bundle. | Calibration integration and injected-write-failure tests. |
| P3-10 | Stub outputs used a noncanonical plumbing label. | Label every stub row and manifest `SYNTHETIC_NON_EVIDENCE`; the exporter rejects it from calibration. | Runner origin and exporter origin tests. |
| P3-11 | An unapproved evaluator workflow and a false state note existed untracked. | Move both files to the recoverable workspace quarantine outside the Git worktree; do not use them. | Clean in-scope status check and quarantine hashes in the checkpoint record. |
| P3-12 | Independent developmental AI review of commit `0fd5497f7dc3e15ef3699d50ba3824821962404d` found that a non-`OK` parse row was forced to `ABSTAIN` but could retain caller-controlled support/confidence values and influence calibration. | For every fail-closed parse row, normalize both `support_fraction` and `calibrated_confidence` to `0.0` before constructing the observation. | A new adversarial RED test first reproduced the injected `1.0/1.0` influence; the GREEN implementation passes the isolated test and the focused Phase-3 suite. |

Residual gate: an independently owned, signed engineering review record plus
out-of-band identity, independence, expertise, and private-key-custody evidence
is still absent. State remains `WAITING_EXTERNAL_ENGINEERING_REVIEW`.

## Developmental AI review record

This record is not the required accountable-human signed review.

- Initial reviewed commit: `0fd5497f7dc3e15ef3699d50ba3824821962404d`.
- Finding: `P3-12`, calibration-signal integrity for fail-closed parse rows.
- Remediation commit: `023f65964beab43ed1cd04ffc4b6f2618f790155`.
- Follow-up disposition: the original finding is resolved; no additional
  blocking finding was discovered in the targeted remediation slice.
- Initial focused review execution: `38 passed`; Foundry: `56 passed, 0 failed`.
- Post-remediation targeted reviewer execution: `11 passed`.
- Integration-owner post-remediation focused execution: `39 passed`.
- Canonical authority-request, authority-package, and external-reproduction
  `--check` executions passed after remediation.

The reviewer did not assert a real-world identity, accountable independence,
or private-key custody. Those claims require external evidence under
`E3_V2_PHASE3_EXTERNAL_ENGINEERING_REVIEW_HANDOFF.md`.
