# E3 semantic evaluator authority request checklist

Purpose: obtain accountable external evaluator authority for the E3 confirmatory path only, without treating permission to execute as evidence that execution succeeded.

This file is an unsigned request checklist. It is not an authority record and not an approval.

## Why E3 needs external authority

E3 is the grounded semantic assurance slice.

Current repository statement:

- experiment: `E3`
- design summary: grounded semantic assurance using held-out grounded items
- required publication artifacts: `T4` + `T8` + `F7`
- evidence-origin contract: `REAL_MODEL_EXECUTION` for confirmation
- current publication status: canonical omission records explicitly retain `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`; no authorized confirmatory E3 evidence is present
- current claim disposition: `WAITING_EXTERNAL`

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

## Two separate external records

The lifecycle has two non-interchangeable external records:

1. **Pre-execution scope authorization.** The evaluator reviews the deterministic `E3_AUTHORITY_REQUEST_MANIFEST.json`, chooses `APPROVED` or `LIMITED_SCOPE`, records privacy limits, and signs the exact authority record. This is the only record validated by `scripts/verify_e3_authority.py`.
2. **Post-execution result attestation.** After an authorized real E3 run exists, a separate future attestation may bind the generated raw bundle, `T4`, `T8`, and `F7`. It must not be created, pre-signed, or implied during pre-execution authorization.

The pre-execution record always contains `result_attestation_status=NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION`. It cannot certify C3, any metric, or any future artifact.

## Deterministic pre-execution request set

The following tracked source set and canonical manifest should be shown to the external authority. The canonical report manifest is `../../../../publication/artifact_manifest.json` (SHA-256 `7177d57747304d003160cdcb45bd572337028a8ffed8793dfa57e2d1444aaabf`); it records E3 as an explicit omission, not evidence.

| Relative path | Why it matters |
|---|---|
| `../../../../../Makefile` | fail-closed authorized E3 invocation and external-input handoff |
| `../manuscript/POI_SUBMISSION_MANUSCRIPT.md` | current manuscript claim boundary |
| `../../../EXPERIMENT_PLAN.md` | experiment intent and E3 role |
| `../../../EXPERIMENT_ARTIFACT_MATRIX.md` | E3 to artifact mapping |
| `../../../PAPER_ARTIFACT_MAP.md` | paper artifact closure rules |
| `../../../MAIN_RESULTS_TARGETS.md` | current blockers and claim rule |
| `../tables/T4_experiment_design_and_current_status.md` | current E3 design/status summary |
| `../tables/T7_limitations_and_nonclaims.md` | explicit non-claims and review limits |
| `../../../../publication/artifact_manifest.json` | canonical artifact closure and E3 omission status |
| `../../../../publication/tables/omissions.json` | explicit `T4`, `T8`, and `F7` waiting-external records |

The authoritative request selection is generated, not copied from this prose:

```text
./.venv/bin/python scripts/build_e3_authority_request.py
./.venv/bin/python scripts/build_e3_authority_request.py --check
./.venv/bin/python scripts/build_e3_authority_package.py
./.venv/bin/python scripts/build_e3_authority_package.py --check
```

`E3_AUTHORITY_REQUEST_MANIFEST.json` binds every selected artifact to its exact SHA-256 value and byte length, includes a canonical E3-only scope digest, and includes its own self-digest. `E3_AUTHORITY_REQUEST_PACKAGE.zip` contains that manifest and only those hash-bound inputs, with deterministic archive metadata. Both remain unsigned request and delivery material. Neither creates identity, authority, a signature, a key, execution evidence, or result attestation. Any separately required freeze-level `verification_report.json` and `claim_support_matrix.json` must be generated and bound without treating this request, package, or an authority record as result evidence.

## Separate future post-execution bind set

A later result attestation, created only after authorized execution, should bind the generated artifacts when they exist:

- `publication/tables/T4_dataset_composition.json`
- `publication/tables/T8_semantic_verification.csv`
- `publication/figures/F7_semantic_verification_quality.svg`
- `results/publication/<run_id>/raw_e3_execution.zip`

These artifacts are not currently present as authorized confirmatory publication evidence in the current candidate. They are deliberately excluded from the pre-execution authority record because their hashes do not yet exist.

After the pre-execution authority record and detached signature have been supplied by the accountable external evaluator, invoke the runner only with external trust material and authorized real-execution inputs. The Make target fails before execution if any required input is absent:

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

The runner calls `scripts/verify_e3_authority.py` as its sole trust-verification boundary before reading execution inputs. It does not create a model run, evaluator identity, authority decision, result attestation, C3 decision, or publication claim. `E3_OUTPUTS` and `E3_TRACE` must therefore be outputs of the separately authorized real-model execution, not synthetic or producer-invented substitutes.

The post-execution verifier parses typed T4 JSON, typed T8 CSV, structured F7 SVG metadata, and a typed raw-run manifest. All included artifacts must use distinct canonical paths and bind the same model, configuration, input, output, trace, provenance, run, and pre-execution-authority hashes. Merely embedding `E3`, `C3`, or `REAL_MODEL_EXECUTION` tokens is insufficient. A `LIMITED_SCOPE` authorization must retain the minimum attestable core (`RAW_E3_EXECUTION`, `T8`, and at least one authorized metric); it can authenticate only an exact signed subset and always returns `INCOMPLETE_NONPUBLICATION`. Even a full `APPROVED` input set returns `COMPLETE_INPUT_SET_REQUIRES_SEPARATE_C3_ADJUDICATION`, never automatic C3 support.

Use `e3_result_attestation_record.schema.json` for that separate record. Verify the completed record, both detached signatures, the external allowed-signers file, and the exact generated artifact root with:

```text
./.venv/bin/python scripts/verify_e3_result_attestation.py \
  --request-manifest docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_MANIFEST.json \
  --authority-record /external/path/e3_authority_record.json \
  --authority-signature /external/path/e3_authority_record.json.sig \
  --attestation-record /external/path/e3_result_attestation.json \
  --attestation-signature /external/path/e3_result_attestation.json.sig \
  --allowed-signers /external/path/allowed_signers \
  --artifact-root /external/path/e3_artifacts
```

These paths are examples only. The verifier requires the signature inputs to remain outside the repository and returns `NOT_EVALUATED_BY_THIS_ATTESTATION`; downstream claim adjudication remains separate.

## Checklist for the requesting side

- [ ] confirm that the requested scope is E3 only, not a blanket authorization for all claims
- [ ] confirm that the authority is external to the producing chain
- [ ] generate and verify the canonical `E3_AUTHORITY_REQUEST_MANIFEST.json`
- [ ] generate and verify the deterministic unsigned `E3_AUTHORITY_REQUEST_PACKAGE.zip`
- [ ] provide the exact E3 capability request without upgrading current claim status
- [ ] provide privacy and confidentiality handling expectations
- [ ] state that `C3` is currently `WAITING_EXTERNAL` with no authorized confirmatory evidence
- [ ] state that pre-execution approval binds the request manifest, while later result attestation must separately bind exact generated-artifact hashes
- [ ] state that no AI output or producer self-attestation can substitute for the authority decision
- [ ] after authorized execution, require a separately signed result attestation that binds the exact run and all `T4`, `T8`, `F7`, and raw-execution hashes

## Checklist for the future external authority record

The future externally completed authority record should include all of the following:

- authority identity
- authority organization or accountable basis
- expertise scope relevant to grounded semantic evaluation
- authorized task class and limits
- reviewed request-manifest path, SHA-256, and self-digest
- decision scope
- date in strict ISO format
- explicit `APPROVED` or `LIMITED_SCOPE` decision
- explicit `NOT_INCLUDED_PRE_EXECUTION_AUTHORIZATION` result-attestation status
- external detached-signature reference
- note that the detached signature and allowed-signers registry live outside the repository and bundle

Use `semantic_evaluator_authority_record.schema.json` for the future completed record, then verify its exact bytes with:

```text
./.venv/bin/python scripts/verify_e3_authority.py \
  --request-manifest docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_MANIFEST.json \
  --authority-record /external/path/e3_authority_record.json \
  --allowed-signers /external/path/allowed_signers \
  --signature /external/path/e3_authority_record.json.sig
```

The last three paths are examples only. No identity, authority record, key, allowed-signers file, or signature is supplied by this repository.

## Non-claims

This checklist does not:

- grant authority;
- certify E3;
- certify C3;
- satisfy the freeze gate;
- create a detached signature;
- create an allowed-signers registry;
- attest to post-execution results or authorize automatic E3 execution.
