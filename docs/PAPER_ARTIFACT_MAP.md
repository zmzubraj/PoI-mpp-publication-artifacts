# Paper Artifact Map

## Main figures

| Figure | Claim | Source script | Raw input | Output |
|---|---|---|---|---|
| F1 | Unified protocol architecture | `scripts/generate_figures.py` | protocol spec | `results/figures/F1_architecture.pdf` |
| F2 | SPAI sequence | `scripts/generate_figures.py` | state machine | `results/figures/F2_sequence.pdf` |
| F3 | Execution audit pipeline | `scripts/generate_figures.py` | audit schema | `results/figures/F3_execution_audit.pdf` |
| F4 | Semantic audit pipeline | `scripts/generate_figures.py` | E3 raw results | `results/figures/F4_semantic.pdf` |
| F5 | Cost comparison | `experiments/e1_single_pass_cost.py` | E1 CSV | `results/figures/F5_cost.pdf` |
| F6 | Tamper detection | `experiments/e2_tamper_detection.py` | E2 CSV | `results/figures/F6_tamper.pdf` |
| F7 | Semantic FAR/FRR/ABSTAIN | `experiments/e3_semantic_eval.py` | E3 CSV | `results/figures/F7_semantic_metrics.pdf` |
| F8 | DA withholding | `experiments/e4_da_withholding.py` | E4 CSV | `results/figures/F8_da.pdf` |
| F9 | Sybil advantage | `experiments/e6_sybil_economics.py` | E6 CSV | `results/figures/F9_sybil.pdf` |
| F10 | Economic attack cost | `simulations/economic_security.py` | simulation CSV | `results/figures/F10_economics.pdf` |
| F11 | Consensus weight | `experiments/e8_consensus_weight_sim.py` | E8 CSV | `results/figures/F11_consensus.pdf` |
| F12 | EVM gas/state | `scripts/collect_gas.py` | Foundry report | `results/figures/F12_evm.pdf` |

## Main tables

| Table | Source | Artifact |
|---|---|---|
| T1 requirements | `docs/ARTIFACT_COLLECTION_GUIDE.md` | manual/theory |
| T4 dataset composition | dataset manifest generator | CSV |
| T6 single-pass cost | E1 | CSV |
| T7 audit security | E2 | CSV |
| T8 semantic quality | E3 | CSV |
| T9 DA | E4 | CSV |
| T10 watcher | E5 | CSV |
| T11 Sybil | E6 | CSV |
| T12 EVM | Foundry gas report | CSV |
| T13 consensus | E8 | CSV |
| T14 reproducibility | `scripts/build_artifact_manifest.py` | JSON/CSV |
