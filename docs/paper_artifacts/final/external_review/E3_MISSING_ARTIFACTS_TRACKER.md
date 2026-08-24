# E3 artifact tracker — historical pre-execution record and current closure

> Current status (2026-08-24): the previously missing E3 execution artifacts
> were supplied, cryptographically verified against the signed pre-execution
> revision, and integrated as a negative result. This file preserves the former
> handoff boundary as history; it is not a current `WAITING_EXTERNAL` tracker.

## Current verified artifact state

| Artifact | Canonical path | SHA-256 | Origin | Disposition |
|---|---|---|---|---|
| `T4` | `publication/tables/T4_dataset_composition.json` | `0ece2525b8fd9f1cbf4ddb4d29bbc9640f2237d98971d7d833f8ec12ff02fe4a` | `REAL_MODEL_EXECUTION` | `NOT_SUPPORTED` |
| `T8` | `publication/tables/T8_semantic_verification.csv` | `87cb6687a03e375d84decd4b7282b4b7c0293ec777e4bdc24749327ef5f04e1a` | `REAL_MODEL_EXECUTION` | `NOT_SUPPORTED` |
| `F7` | `publication/figures/F7_semantic_verification_quality.svg` | `42cf64100ee7ac17a6b21f3b7b8c4929f5c3f8c7b7879265ad7208652b315211` | `REAL_MODEL_EXECUTION` | `NOT_SUPPORTED` |
| `RAW_E3_EXECUTION` | `results/publication/e3-confirmatory-real-20260824/source/raw_e3_execution.zip` | `b160f2c5a274ce5ccfa94e75f709faa491266e568532340e321797beefab14b3` | `REAL_MODEL_EXECUTION` | `NOT_SUPPORTED` |

The signed request manifest SHA-256 is
`10d44a05f8407583011f405013a10e7c9647144c3e295e571e86035492c82133`
with self-digest
`1c08df9d307c2b60ac2bf4118d560c981e36f84f16394a44816c6c538ed4b30a`.
The authority-record SHA-256 is
`3d32fcedbe3c5112ca2476dbc28467820875c144f30720d9147d94f420292622`;
the result-attestation-record SHA-256 is
`02cbe2bc9bf3cb62c0a244cc1c027ff1ea89c23997d3b538a52d66d67a2e2055`.

## Frozen scientific adjudication

- FAR 0.500 (1/2)
- FRR 0.167 (1/6)
- ABSTAIN 0.125 (1/8)
- coverage 0.875 (7/8)
- Brier 0.178
- total n=8; invalid n=2
- frozen `alpha_sem = 0.25`
- C3 disposition: `NOT_SUPPORTED`

FAR exceeded the frozen threshold. The result is therefore retained as a
negative result and must never be relabeled `SUPPORTED`. The small sample does
not establish general semantic reliability.

## Trust boundary still open

The canonical verifiers authenticate the exact signer key, authority scope,
and attested artifact hashes. Cryptographic validity alone does not prove the
recorded evaluator's real-world identity, independence, expertise, or
private-key custody. Those facts require accountable out-of-band confirmation.
Independent reproduction and independent scientific review also remain open.

## Historical boundary

Before the verified run, this tracker required a separately signed authority
record, a detached post-execution attestation, raw real-model provenance, and
T4/T8/F7. That fail-closed boundary was correct at the time. The signed request
manifest remains an immutable pre-execution artifact and should not be rewritten
to describe the post-execution state.

## Non-claims

This closure does not:

- upgrade C3 to `SUPPORTED`;
- establish general semantic reliability;
- prove evaluator independence or key custody from signature validity alone;
- constitute independent replication or independent scientific review; or
- authorize publication freeze or portal submission.
