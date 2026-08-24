# Quantitative manuscript derivatives

The paper-used PNG derivatives are generated deterministically from canonical `publication/figures/*.json` inputs by `scripts/build_paper_figures.py`:

- `F5_single_pass_cost.png`
- `F6_audit_soundness.png`
- `F8_da_withholding.png`
- `F9_sybil_advantage.png`
- `F10_economic_security.png`
- `F11_consensus_dynamics.png`
- `F12_evm_gas_state_scaling.png`

They are presentation derivatives only. The canonical JSON/SVG evidence and hashes under `publication/` remain authoritative.

F8 and F11 remain explicitly inconclusive simulation figures. Their inclusion in
the manuscript exposes negative and boundary evidence; it does not promote the
underlying simulations into real execution or production evidence.
