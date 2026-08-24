# E3 authority handoff: historical stale-signature record and closure

> Current status (2026-08-24): `HISTORICAL_BLOCK_RESOLVED`. The stale-signature
> condition documented below was resolved by a V2 pre-execution authority record.
> The authorized real-model run and externally signed post-execution artifact
> attestation were subsequently verified. This file is retained for audit history;
> it is not a current request for authority.

## Historical request transition

The earlier authority record covered a 21-input request with request-manifest
SHA-256:

```text
bcfe954cd9ec3b550595505a50242a83d977cb559f27fe49dca5d36d7895dbba
```

After the authorized runner and export paths were included, the frozen request
contained 22 inputs. The signed current request revision is commit `ab78c6f`; its
manifest bindings are:

- `reviewed_request_manifest.sha256`: `10d44a05f8407583011f405013a10e7c9647144c3e295e571e86035492c82133`
- `reviewed_request_manifest.self_digest`: `1c08df9d307c2b60ac2bf4118d560c981e36f84f16394a44816c6c538ed4b30a`
- authority record SHA-256:
  `3d32fcedbe3c5112ca2476dbc28467820875c144f30720d9147d94f420292622`

The historical package can still be mechanically checked in an isolated
extraction:

```text
unzip -d _verify docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_PACKAGE.zip
mkdir -p _verify/docs/paper_artifacts/final/external_review
cp docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_PACKAGE.zip \
   _verify/docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_PACKAGE.zip
cd _verify
../.venv/bin/python scripts/build_e3_authority_request.py --check
../.venv/bin/python scripts/build_e3_authority_package.py --check
```

## Current verified execution and adjudication

Canonical verifier replay against the signed revision returned:

- authority status: `VERIFIED_EXTERNAL_PRE_EXECUTION_AUTHORITY`
- authority decision: `APPROVED`
- post-execution status: `VERIFIED_EXTERNAL_POST_EXECUTION_ATTESTATION`
- run ID: `e3-confirmatory-real-20260824`
- evidence origin: `REAL_MODEL_EXECUTION`
- result-attestation SHA-256:
  `02cbe2bc9bf3cb62c0a244cc1c027ff1ea89c23997d3b538a52d66d67a2e2055`

Attested artifact hashes:

- T4: `0ece2525b8fd9f1cbf4ddb4d29bbc9640f2237d98971d7d833f8ec12ff02fe4a`
- T8: `87cb6687a03e375d84decd4b7282b4b7c0293ec777e4bdc24749327ef5f04e1a`
- F7: `42cf64100ee7ac17a6b21f3b7b8c4929f5c3f8c7b7879265ad7208652b315211`
- raw execution ZIP:
  `b160f2c5a274ce5ccfa94e75f709faa491266e568532340e321797beefab14b3`

Measured E3 results are FAR 0.500 (1/2), FRR 0.167 (1/6), ABSTAIN 0.125
(1/8), coverage 0.875 (7/8), and Brier calibration 0.178. Under the frozen
`alpha_sem=0.25` rule, FAR exceeds the threshold and C3 is `NOT_SUPPORTED`.
The run contains only n=8 items and invalid n=2, so it does not establish
general semantic reliability.

## Remaining trust and publication boundary

Cryptographic verification authenticates exact signed bytes, declared principal,
and artifact hashes. It does not by itself prove the evaluator's real-world
identity, independence, expertise, or private-key custody. Those facts require
accountable out-of-band confirmation. Independent reproduction, independent
domain-expert review, author declarations, venue selection, final rendered-PDF
approval, portal preview, and the publication-freeze sentinel also remain open.

This historical note does not authorize a new execution, upgrade C3, create an
independent scientific review, or make the manuscript submission-ready.
