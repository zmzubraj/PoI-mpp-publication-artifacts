# External Engineering Review Handoff — E3-v2 Phase 3

Gate state: `WAITING_EXTERNAL_ENGINEERING_REVIEW`

The reviewer must be a real person who did not author the reviewed batch and
has no undisclosed conflict. AI review is developmental only.

The integration owner will provide:

- the exact reviewed Git commit SHA;
- SHA-256 for every reviewed file;
- focused and integrated test commands and complete captured output;
- the finding/remediation ledger;
- the quarantined-file paths and hashes;
- this unsigned review template.

The reviewer must independently inspect the exact commit, rerun or witness the
tests in a clean checkout, and complete every field below without placeholders.
They must specifically review trust-path reuse, request/material binding,
`APPROVED` and `LIMITED_SCOPE`, symlink/repository-local rejection, replay and
staleness, model-cache byte verification, real-versus-synthetic origin,
one-to-one raw artifact closure, and atomic failure behavior.

Required signed record fields:

```json
{"schema_version":"POI_MPP_E3_V2_PHASE3_ENGINEERING_REVIEW_V1","reviewer_identity":"<REAL_STABLE_ID>","expertise_scope":"<NONBLANK>","independence_basis":"<NONBLANK>","conflicts":"<NONE_OR_DISCLOSED>","reviewed_commit_sha":"<40_HEX>","reviewed_checkpoint_manifest_sha256":"<64_HEX>","reviewed_file_hashes":{},"test_evidence_sha256":"<64_HEX>","findings":[],"verdict":"PASS|REMEDIATE|BLOCK","review_date":"YYYY-MM-DD","identity_binding_reference":"<OUT_OF_BAND_REFERENCE>","independence_verification_reference":"<OUT_OF_BAND_REFERENCE>","key_custody_verification_reference":"<OUT_OF_BAND_REFERENCE>"}
```

Canonicalize the completed JSON, sign its exact bytes with an external key and
the namespace `poi-e3-v2-phase3-engineering-review`, and provide the detached
signature and an external allowed-signers file. No private key enters the
repository or handoff archive.

Cryptographic validity proves only that the listed key signed the exact bytes.
The project owner must separately verify the reviewer's identity, independence,
expertise, conflicts, and key custody. Until both checks pass and the verdict is
`PASS`, the HOLD remains in force.
