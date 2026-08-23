# Main Results Targets

## Canonical publication-artifact status

Source of truth: `publication/artifact_manifest.json`, SHA-256
`bd882ca072602e13cc14850a44d1b769111f6b032e56901e9419a3263593c943`.

The canonical bundle contains result artifacts for E1, E2, and E4-E8. It is
**not publication-ready**. The remaining non-compensating blockers are:

- E3 is `WAITING_EXTERNAL`: T4, T8, and F7 have no evidence because
  `WAITING_EXTERNAL_EVALUATOR_AUTHORITY` remains unresolved.
- An authenticated independent manual review is absent. AI output, AI approval,
  and user approval are not independent review.
- The publication-freeze sentinel is absent. Its absence cannot be repaired by
  positive dispositions elsewhere in the bundle.

The approved first-publication scope is 1B-8B open-weight models and a local
Foundry boundary. It defers 70B/MoE validation, confidential GPU/TEE execution,
a production dispute VM, production data availability, and a production
consensus client.

## Claim-facing evidence map

| Claim / experiment | Canonical artifacts | Disposition and allowed interpretation |
|---|---|---|
| C1 / E1 single-pass cost | T6, F5 | `INCONCLUSIVE`. Fixed-order real-model pilot: two paired observations and six measured rows. Mean two-run baseline is 5197.17125 ms; mean MPP single-pass is 2678.932229 ms; delta is 2518.239021 ms with bootstrap interval [2440.923209, 2595.554833]. The fixed order caps the result at `INCONCLUSIVE`; it does not support a general cost-advantage claim. |
| C2 / E2 execution audit | T7, F6 | `INCONCLUSIVE`. Narrow real-model pilot: 4/4 attacked observations detected, three exact surfaces plus one empirical floating-point surface, Wilson interval [0.5101091635454027, 1.0], and one honest control with no false positive. This is not a general execution-audit effectiveness claim. |
| C3 / E3 semantic verifier | T4, T8, F7 | `WAITING_EXTERNAL`. No evidence artifact; external evaluator authority is required before semantic performance may be reported. |
| C4 / E4 data availability | T9, F8 | `INCONCLUSIVE`. Declared playback simulation only; it is not executed reconstruction evidence and does not support C4. |
| C5 / E5 watcher/dispute economics | T10 | `SUPPORTED` only for the declared reproducible simulation scenarios. No figure is present; do not generalize to production watcher economics. |
| C6 / E6 Sybil/task-budget neutrality | T11, F9, F10 | `SUPPORTED` only for the declared reproducible simulation scenarios. It is not open-network Sybil-resistance evidence. |
| C7 / E7 EVM boundedness | T12, F12 | `SUPPORTED` only for the local Foundry measurement boundary: 15 rows, maximum gas 467937, and maximum fraction of the configured block limit 0.00043580029159784317. This is not Ethereum-mainnet or production-throughput evidence. |
| C8 / E8 next-epoch weight | T13, F11 | `INCONCLUSIVE` reproducible simulation with 10 rows. It describes modeled receipt-to-weight dynamics, not demonstrated consensus security. |

## Publication rule

Paper text, tables, figures, and captions must preserve the canonical
disposition, evidence origin, scope, and explicit limits for each artifact. A
`SUPPORTED` simulation result is not real-world deployment evidence; a local
Foundry measurement is not a mainnet claim; and no artifact may compensate for
the E3 authority, independent-review, or freeze-sentinel blockers.
