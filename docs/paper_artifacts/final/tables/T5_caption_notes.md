Table 5. Paper-facing static presentation of canonical E7/T12 local Foundry boundedness.

Origin:
- canonical `publication/tables/T12_evm_boundedness.csv` and F12;
- canonical manifest SHA-256 `bd882ca072602e13cc14850a44d1b769111f6b032e56901e9419a3263593c943`.

Units:
- `gas_used` is EVM gas.
- `fraction_of_block_limit` is a unitless ratio of measured gas to the configured local block gas limit.
- `storage_change_upper_bound_bytes` is an upper bound in bytes computed from changed storage slots.

Denominators and sample notes:
- `sample_size=15` reflects the canonical local measurement set used for this run.
- `uncertainty=N/A_single_measurement` means these rows are current measured surfaces, not interval-estimated benchmarks.

Status:
- The canonical E7 table has 15 rows, maximum gas 467937, and maximum configured-block-limit fraction 0.00043580029159784317.
- The evidence ceiling remains a local boundedness statement for E7, never Ethereum mainnet production cost evidence.
