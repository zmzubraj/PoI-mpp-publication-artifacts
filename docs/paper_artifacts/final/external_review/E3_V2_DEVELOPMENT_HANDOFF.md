# E3-v2 development calibration: accountable-human handoff

**Status:** `WAITING_EXTERNAL`

**Scientific effect:** none; historical C3-v1 remains `NOT_SUPPORTED` and C3-v2 remains prospective.
**Scope:** one frozen 1B–3B open-weight model for the primary E3-v2 result. A separately frozen 7B–8B model is optional and must not be pooled with the primary model.

**Engineering checkpoint (2026-08-29):** the local worksheet compiler,
dual-annotation/adjudication sealer, development-bundle validator, deterministic
calibration fitter, and external-authority boundary have focused test coverage.
This is engineering evidence only. No real V2 development annotations or real
V2 calibration observations were present under
`/Users/rainbow/Documents/POI_E3_EXTERNAL` at this checkpoint, so Phase 3
remains `WAITING_EXTERNAL`.

The real-model confirmatory runner is deliberately fail-closed until a separate
accountable confirmatory-freeze approval verifier exists. The stub adapter is
plumbing-only and emits `PIPELINE_SELF_TEST`; it cannot become publication
evidence. Therefore neither 500-item confirmatory execution nor Phase-4 freeze
work is authorized by this Phase-3 handoff.

This handoff identifies the external facts and real executions required to close
Phase 3 of `docs/POI_MPP_V2_IMPLEMENTATION_PLAN.md`. Repository code and
synthetic fixtures cannot complete the real execution or accountable review
inputs for this gate.

## Required accountable inputs

The responsible dataset/model owner must provide all fields below without AI
inference or placeholder substitution:

1. **Model identity and authority**
   - exact model repository and immutable revision;
   - exact tokenizer repository and immutable revision;
   - parameter count within 1B–3B for the primary result;
   - license identifier and accountable license review;
   - local model/tokenizer paths with SHA-256 file closure;
   - deterministic decode policy and reviewed runtime-wheel ledger.
2. **Development corpus**
   - 120–150 total items;
   - exactly 50 expected `ACCEPT` items;
   - exactly 50 expected `REJECT` items;
   - 20–50 expected `ABSTAIN` items;
   - item, label, normalized-content, and deduplication-group hashes;
   - source family, subgroup, difficulty, and attack-family metadata;
   - item-level license and privacy disposition.
3. **Annotation and taxonomy review**
   - annotator identities or stable accountable IDs;
   - blinding statement confirming annotators did not see verifier outputs;
   - independent annotations and adjudication record for disagreements;
   - agreement numerator, denominator, and fraction;
   - reviewed mapping to the canonical error taxonomy;
   - signed or otherwise accountable approval of prompt, output schema,
     contradiction policy, and error-recovery policy.
4. **Execution provenance**
   - every calibration observation must come from authorized
     `REAL_MODEL_EXECUTION`;
   - exact raw prompt, output, trace, configuration, model, tokenizer, runtime,
     and environment bindings;
   - deterministic observation/error ledger and raw-file manifest;
   - no confirmatory item may be inspected, reused, or used for tuning.

## Data separation and run-order contract

- Item construction, annotation, and adjudication occur before model-output
  inspection for the affected item.
- The frozen development manifest is shuffled with a recorded deterministic
  seed before execution so source family, expected decision, difficulty, and
  attack family are not confounded with run order.
- Independent items, not repeated tokens or repeated generations from one item,
  are the unit of analysis.
- Near-duplicate and source-family groups are recorded before any confirmatory
  set is constructed.
- Until a confirmatory manifest exists, leakage status remains
  `NOT_YET_ASSESSABLE`; it cannot authorize confirmatory verification.
- Once the confirmatory manifest exists, Phase 4 must append a separate
  zero-overlap report with status `CLEAR`. It must not rewrite the provisional
  development report or the Phase-3 threshold freeze. The confirmatory policy
  binds this later report independently before Phase 5.

## Evidence-origin boundary

- Synthetic plumbing fixtures must be labeled `SYNTHETIC_NON_EVIDENCE`.
- Synthetic fixtures may test deterministic threshold-selection mechanics only.
- `REPRODUCIBLE_SIMULATION` may not be relabeled as a real calibration run.
- A frozen Phase-3 calibration requires `REAL_MODEL_EXECUTION` for every
  observation.
- Development calibration is not confirmatory publication evidence and does not
  support C3 by itself.

## Required Phase-3 output bundle

The bundle must be rooted outside the repository during accountable preparation
and must contain, at minimum:

```text
POI_E3_V2_DEVELOPMENT/
  owner_declaration.json
  model/
    pinned_model_manifest.json
    file_hashes.sha256
  dataset/
    dataset_manifest_v2.json
    items/
    labels/
    annotations/
    annotation_agreement.json
    adjudication_ledger.json
    license_privacy_ledger.json
  policy/
    claim_spec.json
    prompt_template.txt
    output_schema.json
    contradiction_policy.json
    error_recovery_policy.json
    error_taxonomy_review.json
  execution/
    environment_manifest.json
    deterministic_decode_policy.json
    raw_outputs/
    raw_traces/
    observation_ledger.json
  calibration/
    error_ledger.json
    development_leakage_report.json
    calibration_freeze_v2.json
    calibration_metrics.json
  manifest.json
```

All JSON files must use canonical UTF-8 serialization, all referenced files must
remain under the bundle root without symlinks, and `manifest.json` must close the
SHA-256 set. No repository-local key, self-declared independence statement, or
AI-generated identity can substitute for accountable ownership.

## Phase-3 gate decision

Set Phase 3 to `COMPLETE` only after all of the following are freshly verified:

- composition and raw-file hashes close;
- every observation has real-model provenance;
- row-level authoritative manifest closure holds, including annotation-hash and
  error-family/attack-family binding;
- the error taxonomy and all policy inputs have accountable review;
- the deterministic selection rule produces one immutable freeze;
- the provisional development leakage report remains
  `NOT_YET_ASSESSABLE` with no confirmatory manifest hash;
- an independent read-only engineering review reports no blocking Phase-3
  contract defect.

Phase 3 does **not** include confirmatory overlap clearance or confirmatory
verification. Phase 4 later creates a separate `CLEAR` confirmatory leakage
report and binds it into the confirmatory semantic policy before Phase 5
verification.

Until the accountable human/external inputs above exist, the exact disposition
remains `WAITING_EXTERNAL`, not `SUPPORTED`, `COMPLETE`, or submission-ready.
