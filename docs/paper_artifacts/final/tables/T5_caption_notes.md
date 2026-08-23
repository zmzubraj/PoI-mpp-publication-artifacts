Table 5. Historical local C7 EVM boundedness snapshot; not current canonical publication provenance.

Origin:
- retained as a tracked presentation snapshot from an ignored local Task 22 candidate;
- the ignored temporary source is not admissible publication provenance;
- a clean, version-bound E7 run must regenerate and hash-bind this table before submission.

Units:
- `gas_used` is EVM gas.
- `fraction_of_block_limit` is a unitless ratio of measured gas to the configured local block gas limit.
- `storage_change_upper_bound_bytes` is an upper bound in bytes computed from changed storage slots.

Denominators and sample notes:
- `sample_size=15` reflects the canonical local measurement set used for this run.
- `uncertainty=N/A_single_measurement` means these rows are current measured surfaces, not interval-estimated benchmarks.

Status:
- The underlying local Foundry boundary is testable, but this snapshot must not be cited as the canonical evidence artifact.
- After canonical regeneration, the evidence ceiling remains a local boundedness statement for `C7`, never Ethereum mainnet production cost evidence.
