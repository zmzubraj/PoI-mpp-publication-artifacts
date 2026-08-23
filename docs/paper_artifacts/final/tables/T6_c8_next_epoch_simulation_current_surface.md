| Scenario ID | Role | Ablation | Total active weight (micros) | Attacker active-weight share | Max operator weight share | P(seat threshold ≥ 1/3) | P(seat threshold ≥ 2/3) | Sampling disposition | Sample size | Claim disposition | Origin | Run ID |
|---|---|---|---:|---:|---:|---:|---:|---|---:|---|---|---|
| `support-receipt-churn` | `SUPPORT` | `CHURN` | 270 | 0.333333 | 0.333333 | 0.65625 | 0 | `COMMITTEE_SAMPLED` | 10 | `INCONCLUSIVE` | `REPRODUCIBLE_SIMULATION` | `run-e8-publication-v1` |
| `boundary-zero-credit-rich` | `BOUNDARY` | `COLLATERAL_RICH_ZERO_CREDIT` | 180 | 0 | 0.5 | 0 | 0 | `COMMITTEE_SAMPLED` | 10 | `INCONCLUSIVE` | `REPRODUCIBLE_SIMULATION` | `run-e8-publication-v1` |
| `support-collusion-bounded` | `SUPPORT` | `COLLUSION` | 360 | 0.5 | 0.25 | 0.875 | 0.203125 | `COMMITTEE_SAMPLED` | 10 | `INCONCLUSIVE` | `REPRODUCIBLE_SIMULATION` | `run-e8-publication-v1` |
| `negative-cap-removed` | `NEGATIVE_CONTROL` | `CONCENTRATION_CAP_REMOVED` | 480 | 0.625 | 0.625 | 0.929688 | 0.929688 | `COMMITTEE_SAMPLED` | 10 | `INCONCLUSIVE` | `REPRODUCIBLE_SIMULATION` | `run-e8-publication-v1` |
| `support-high-compute-capped` | `SUPPORT` | `HIGH_COMPUTE` | 300 | 0.4 | 0.4 | 0.742188 | 0 | `COMMITTEE_SAMPLED` | 10 | `INCONCLUSIVE` | `REPRODUCIBLE_SIMULATION` | `run-e8-publication-v1` |
| `boundary-pending-only` | `BOUNDARY` | `MISSING_RECEIPTS` | 0 | 0 | 0 | N/A | N/A | `ZERO_TOTAL_WEIGHT` | 10 | `INCONCLUSIVE` | `REPRODUCIBLE_SIMULATION` | `run-e8-publication-v1` |
| `boundary-zero-total-weight` | `BOUNDARY` | `MISSING_RECEIPTS` | 0 | 0 | 0 | N/A | N/A | `ZERO_TOTAL_WEIGHT` | 10 | `INCONCLUSIVE` | `REPRODUCIBLE_SIMULATION` | `run-e8-publication-v1` |
| `support-honest-baseline` | `SUPPORT` | `NONE` | 270 | 0.333333 | 0.333333 | 0.617188 | 0 | `COMMITTEE_SAMPLED` | 10 | `INCONCLUSIVE` | `REPRODUCIBLE_SIMULATION` | `run-e8-publication-v1` |
| `support-subsidized-compute` | `SUPPORT` | `SUBSIDIZED_COMPUTE` | 300 | 0.4 | 0.4 | 0.753906 | 0 | `COMMITTEE_SAMPLED` | 10 | `INCONCLUSIVE` | `REPRODUCIBLE_SIMULATION` | `run-e8-publication-v1` |
| `support-sybil-split` | `SUPPORT` | `SYBIL_SPLIT` | 300 | 0.4 | 0.4 | 0.726563 | 0 | `COMMITTEE_SAMPLED` | 10 | `INCONCLUSIVE` | `REPRODUCIBLE_SIMULATION` | `run-e8-publication-v1` |
