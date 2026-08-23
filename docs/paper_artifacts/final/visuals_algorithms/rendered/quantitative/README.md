# Quantitative manuscript derivatives

The paper-used PNG derivatives are generated deterministically from canonical `publication/figures/*.json` inputs by `scripts/build_paper_figures.py`:

- `F5_single_pass_cost.png`
- `F6_audit_soundness.png`
- `F9_sybil_advantage.png`
- `F10_economic_security.png`
- `F12_evm_gas_state_scaling.png`

They are presentation derivatives only. The canonical JSON/SVG evidence and hashes under `publication/` remain authoritative.

`F8_da_withholding.png` and `F11_consensus_dynamics.png` are supplemental raster conversions of canonical inconclusive figures. They are not emitted by the paper-figure builder and are not embedded in the evidence-bound manuscript.
