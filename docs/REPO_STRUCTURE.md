# Repository Structure

- `contracts/` — bounded EVM state: model/task/commitment/audit/receipt/credit.
- `worker/` — model adapter, trace sidecar, IEC builder.
- `auditor/` — Freivalds-style execution checks, exact cheap-op checks, semantic verification.
- `proof_backend/` — commitments, challenge seed, receipt objects; replace/extend with zk micro-step backend later.
- `datasets/` — controlled objective and grounded datasets.
- `experiments/` — publication experiments E1–E8.
- `simulations/` — reserve for BFT / adversarial market simulations.
- `results/` — raw results and figures.
- `configs/` — frozen experiment parameters.
- `scripts/` — one-command reproduction.
