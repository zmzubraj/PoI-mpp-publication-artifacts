# E3 authority: stale-signature handoff note

> Status: `TECHNICALLY_PROMISING / NOT_READY` — latest engineering passes verification, but the **existing external signature is stale** and must be replaced before authorized E3 execution can begin.

This note is for the accountable external evaluator. It documents the current engineering state, what changed since the last review, and exactly what signature material you must produce.

## Why this handoff note exists

The engineering implementation for the E3 confirmatory path is complete and self-consistent:

- Authorized E3 runner: `experiments/e3_semantic_eval.py` (commit `a5e3ad4`)
- Reuse of canonical `scripts/verify_e3_authority.py` for trust verification
- `APPROVED` / `LIMITED_SCOPE` enforcement
- Synthetic / incorrect `evidence_origin` rejection
- Deterministic binding of model, config, inputs, outputs, trace, provenance hashes
- Deterministic `RAW_E3_EXECUTION`, `T4`, `T8`, `F7` export paths
- Focused E3 tests pass; full Python suite exit 0; Foundry 55/55 pass
- Engineering review: PASS
- Canonical request / package / handoff `--check`: PASS

However, **no real scientific E3 execution has been authorized or performed yet**. The blocker is that the manifest changed and the old signature no longer matches.

## What changed since your last review

Your previously signed authority record (V1) covered an implementation package whose manifest had **21 inputs** and whose request-manifest SHA-256 was:

```
bcfe954cd9ec3b550595505a50242a83d977cb559f27fe49dca5d36d7895dbba
```

After the authorized-runner commit (`a5e3ad4`) and the export-path additions, the `REQUEST_INPUTS` set grew to **22 files**. The checklist prose was also updated to list all 22 inputs. The canonical manifest was regenerated and now hashes to:

```
a252355a0927ec50d9bd6b20f807d2402faa574014efaeb4c4902016e5ec3529
```

## What you must provide now

Please re-review the **latest package** and produce a new **V2 authority record** with a detached Ed25519 signature.

### Latest package

- Path: `docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_PACKAGE.zip`
- SHA-256: `a93ce4aecb7c83857f03cb0b0316f209b6acad2d1859a36b898ef4e6ba587530`
- Contains the canonical manifest whose `self_digest` is `a641ad94ae46a12093a83906c6aaeb6b2b849bef14779203cbf784ea678980e6`

The zip contains:

- `E3_AUTHORITY_REQUEST_MANIFEST.json` — the canonical request (22 inputs, self-digest bound)
- All 22 input files, hash-bound and deterministic-archive metadata

You verify the package contents by extracting and re-running:

```text
unzip -d _verify docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_PACKAGE.zip
mkdir -p _verify/docs/paper_artifacts/final/external_review
cp docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_PACKAGE.zip \
   _verify/docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_PACKAGE.zip
cd _verify
../.venv/bin/python scripts/build_e3_authority_request.py --check
../.venv/bin/python scripts/build_e3_authority_package.py --check
```

### V2 authority record fields you must produce

The record follows `semantic_evaluator_authority_record.schema.json` and must include:

- `schema_version`: `POI_MPP_E3_AUTHORITY_RECORD_V2`
- `authority_identity` / `authority_basis` / `expertise_scope`
- `authorized_scope.experiment_id`: `E3`
- `authorized_scope.claim_id`: `C3`
- `authorized_scope.task_class`: `GROUNDED_SEMANTIC_ASSURANCE`
- `authorized_scope.evidence_origin`: `REAL_MODEL_EXECUTION`
- `authorized_scope.metric_scope`: `ABSTAIN`, `FAR`, `FRR`, `calibration`, `coverage`
- `authorized_scope.artifact_scope`: `F7`, `RAW_E3_EXECUTION`, `T4`, `T8`
- `authorized_scope.privacy_scope`: your stated privacy limits
- `authorized_scope.request_scope_digest`: must match the manifest's `requested_scope_digest`
- `reviewed_request_manifest.path`: `E3_AUTHORITY_REQUEST_MANIFEST.json`
- `reviewed_request_manifest.sha256`: `a252355a0927ec50d9bd6b20f807d2402faa574014efaeb4c4902016e5ec3529`
- `reviewed_request_manifest.self_digest`: `a641ad94ae46a12093a83906c6aaeb6b2b849bef14779203cbf784ea678980e6`
- `decision`: `APPROVED` or `LIMITED_SCOPE`
- `decision_notes`
- `authorization_date`: strict ISO `YYYY-MM-DD`
- `result_attestation_status`: `NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION`
- `external_signature_required`: `true`
- `signature_reference`: external path reference (outside repo)
- `allowed_signers_reference`: external path reference (outside repo)

Sign the record with your Ed25519 key:

```text
ssh-keygen -Y sign -f /external/path/allowed_signers \
    -I <your-authority-identity> \
    -n file \
    -s /external/path/e3_authority_record.json.sig \
    < /external/path/e3_authority_record.json
```

Then place the record bytes + `.sig` outside the repository and run:

```text
./.venv/bin/python scripts/verify_e3_authority.py \
    --request-manifest docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_MANIFEST.json \
    --authority-record /external/path/e3_authority_record.json \
    --allowed-signers /external/path/allowed_signers \
    --signature /external/path/e3_authority_record.json.sig
```

Expected output on success:

```json
{
  "status": "VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY",
  "decision": "<APPROVED|LIMITED_SCOPE>",
  "authority_identity": "...",
  "request_manifest_self_digest": "a641ad94ae46a12093a83906c6aaeb6b2b849bef14779203cbf784ea678980e6",
  "result_attestation_status": "NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION"
}
```

## What happens after your V2 record is verified

1. `verify_e3_authority.py` succeeds → status `VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORIZATION`.
2. Real confirmatory execution inputs are prepared (1B–8B model manifest, pinned config, authorized run configuration, real inputs, real outputs, execution trace, provenance bundle) — **origin must be `REAL_MODEL_EXECUTION`**.
3. The authorized E3 runner is invoked with external trust material:
   ```text
   make e3-authorized \
     E3_AUTHORITY_RECORD=/external/path/e3_authority_record.json \
     E3_AUTHORITY_SIGNATURE=/external/path/e3_authority_record.json.sig \
     E3_ALLOWED_SIGNERS=/external/path/allowed_signers \
     E3_CONFIRMATORY_CONFIG=/authorized/path/e3_confirmatory_config.json \
     E3_MODEL_MANIFEST=/authorized/path/model_manifest.json \
     E3_RAW_CONFIG=/authorized/path/raw_config.json \
     E3_INPUTS=/authorized/path/inputs.jsonl \
     E3_OUTPUTS=/authorized/path/outputs.jsonl \
     E3_TRACE=/authorized/path/trace.jsonl \
     E3_PROVENANCE=/authorized/path/provenance.json \
     E3_ARTIFACT_ROOT=/authorized/output/path/e3_artifacts
   ```
4. Generated artifacts: `RAW_E3_EXECUTION`, `T4`, `T8`, `F7`, and `FAR` / `FRR` / `ABSTAIN` / `coverage` / `calibration`.
5. A **separate** post-execution result attestation is signed binding those exact hashes, verified with `scripts/verify_e3_result_attestation.py`.
6. Publication integration: claim C3 evidence update, omission removal, artifact import, manuscript reconciliation, reproducibility replay, and final scientific review.

## What is still missing (non-authority blocks)

See `E3_MISSING_ARTIFACTS_TRACKER.md` for the full inventory of not-yet-present real-execution artifacts. No AI output or producer self-attestation can fill these.

## Non-claims

This note does not:
- grant authority by itself
- certify E3 or C3
- create the V2 authority record or signature
- attest post-execution results
- authorize automatic execution
