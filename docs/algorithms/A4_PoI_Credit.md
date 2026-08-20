# Algorithm A4 — PoI Credit and Next-Epoch Weight

## Inputs

Matured receipt set for epoch `e`, task budgets `D_j`, difficulty scores, assurance factors, worker bonds, concentration caps.

## Equations

For task `j`:

`sum_i c_ij <= D_j`

Example bounded allocation:

`c_ij = D_j * s_ij * a_ij / max(1, sum_h s_hj * a_hj)`

Epoch credit:

`Q_i^(e+1) = sum_j c_ij`

Active weight:

`W_i^(e+1) = min(Q_i^(e+1), B_i/beta, ConcentrationCap_i)`

Committee probability:

`p_i = W_i / sum_k W_k`

## Security invariant

`Q_i = 0 => W_i = 0`.

Collateral is an authority bound/slashing resource, not a source of PoI authority.
