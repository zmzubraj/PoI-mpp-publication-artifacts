# Reproducibility Checklist

## Automated gate

- [ ] exact Git commit recorded and not `UNVERSIONED_BLOCKED`
- [ ] Python environment manifest and `requirements.lock` hash recorded
- [ ] Foundry version and Solidity compiler version recorded when E7 is exercised
- [ ] model identifier, model file hashes, and dataset hash recorded for every real-model artifact
- [ ] every run config is frozen and hash-bound before replay
- [ ] raw logs, raw tables, and generated paper artifacts are linked in one closure manifest
- [ ] `make reproduce` performs a clean candidate replay without sourcing shell fragments or network installs
- [ ] candidate bundles are recorded as `CANDIDATE_VERIFIED` and do not contain `MPP_ARTIFACT_COMPLETE`
- [ ] frozen bundles are recorded as `FROZEN_VERIFIED` and are reverified before `MPP_ARTIFACT_COMPLETE` is written last
- [ ] `scripts/verify_bundle.py` revalidates closure from filesystem contents rather than trusting status strings
- [ ] no manually typed scientific results appear in publication tables or figures

## Missing evidence

- [ ] each of `E1`-`E8` has its required authorized paper artifacts (`T4`, `T6`-`T13`, `F5`-`F12`) or an explicit omission record
- [ ] E7 support comes only from a fresh local Foundry collection plus current parity verification
- [ ] E8 comes only from `load_and_run_e8_publication(default_e8_publication_plan_path(), ...)`, remains labeled `REPRODUCIBLE_SIMULATION`, and keeps its measured `SUPPORTED` / `NOT_SUPPORTED` / `INCONCLUSIVE` disposition without relabeling
- [ ] Task 21 real-path blocker chain is recorded when real execution remains blocked
- [ ] synthetic or manual fixtures are rejected from publication completeness

## Accountable review

- [ ] accountable rendered/scientific review record exists
- [ ] reviewer identity, review basis, review date, and reviewed artifact hashes are recorded
- [ ] `review_date` is strict ISO `YYYY-MM-DD`, parseable, and not later than the bundle-generation date
- [ ] only `INDEPENDENT_DOMAIN_EXPERT_REVIEW` can satisfy the production freeze gate
- [ ] `expertise_scope`, `independence_basis`, and `reviewed_run_id` are non-empty
- [ ] detached reviewer signature and trusted allowed-signers registry are supplied from outside the bundle
- [ ] denominator, interval, negative-result, simulation-label, editability, accessibility, and claim-language checks are explicitly marked
- [ ] AI output, self-review, or user approval is not mislabeled as independent review

## Independent validation

- [ ] confirmatory external evaluator authority is present for E3 before any freeze claim
- [ ] missing-authority blockers remain explicit instead of being downgraded to `SUPPORTED`
- [ ] privacy-sensitive prompts or evidence are redacted or hashed where required
- [ ] `MPP_ARTIFACT_COMPLETE` is written only after all automated gates and accountable review pass
