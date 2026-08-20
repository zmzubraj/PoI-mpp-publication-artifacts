# EVM Contracts

These contracts are MPP scaffolds for protocol-state evidence. They are **not production-safe** and must not be deployed with real value without authorization checks, access control, state-machine validation, reentrancy/DoS analysis, and independent audit.

## Required publication tests

- Task class separation: SERVICE cannot mint consensus credit.
- Commitment finality before audit activation.
- Receipt cannot activate before audit/DA gates.
- Credit budget is conserved per task.
- `Q=0 => W=0` even with collateral.
- Challenge/reward/slashing state transitions are correct.
- Gas/state are measured under representative batch sizes.
