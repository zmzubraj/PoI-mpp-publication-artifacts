# Proof of Intelligence — Minimum Publishable Prototype Workspace

This repository is the **Minimum Publishable Prototype (MPP)** for the Proof-of-Intelligence consensus architecture.

The MPP is intentionally narrower than the full protocol. Its purpose is to generate real, reproducible evidence for the paper's central research claims without implementing the entire frontier-scale system.

## Core vertical slice

`Task -> Single model execution -> Trace + Intelligence Evidence Capsule -> Commitment -> Post-commit randomized audit -> Optional dispute -> Data-availability gate -> Matured receipt -> Next-epoch PoI weight`

## What this repository must demonstrate

1. A real open-weight model can execute once and emit a user-facing response plus auditable trace/evidence commitments.
2. Concrete audit samples are generated only after the response commitment is finalized.
3. Execution tampering can be detected with bounded randomized audits and exact cheap-operation checks.
4. Grounded semantic checks can distinguish supported, unsupported, contradictory and uncertain answers with an explicit `ABSTAIN` state.
5. A receipt cannot become active while required artifacts are unavailable.
6. Service tasks cannot directly mint consensus credit; only protocol-eligible tasks can.
7. A matured receipt can be converted into next-epoch PoI weight under the credit/bond rules.
8. The normal EVM path stores compact state only; heavy AI work remains off chain.

## Prototype scope

### Primary
- 1B–3B open-weight instruct model.
- Optional 7B–8B scaling run.
- Objective tasks and grounded evidence tasks.
- Local EVM test chain (Anvil/Foundry).
- Commitment + trace + randomized audit + simple optimistic dispute.
- Grounded semantic verifier with calibrated `ABSTAIN`.
- Erasure-coded artifact availability experiment.
- PoI credit and next-epoch committee simulation.

### Explicitly out of MPP scope
- Production 70B/600B/trillion-parameter deployment.
- Full MoE distributed serving.
- Full per-response zkML proof.
- Production H100/B200 confidential-computing lane.
- Production decentralized DA network.
- New production L1 consensus client.
- Universal open-ended semantic intelligence verification.

Those are extension targets, not requirements for the first publication evidence package.

## Experiment IDs

| ID | Experiment | Main claim |
|---|---|---|
| E1 | Single-pass cost | One model execution + audit is cheaper than a two-run baseline. |
| E2 | Execution tamper detection | Post-commit execution audits detect injected corruption. |
| E3 | Grounded semantic assurance | IEC + deterministic/semantic checks produce measurable FAR/FRR/ABSTAIN. |
| E4 | Data-availability gating | Withheld artifacts fail to mature into active receipts at the expected rate. |
| E5 | Watcher/dispute economics | Invalid receipts are economically challengeable. |
| E6 | Sybil/task-budget neutrality | Identity splitting does not create material extra protocol credit. |
| E7 | EVM boundedness | Normal-path gas/state remain compact and predictable. |
| E8 | Next-epoch PoI consensus | Matured receipts become bounded validator/sequencer weight. |

## Reproducibility contract

Every reported number must be traceable to:

`config -> dataset manifest -> command -> raw output -> analysis script -> figure/table`

Do not place manually typed numbers into the paper. The publication tables and figures should be generated from `results/raw/` by scripts.

## Task 22 candidate replay

Run:

```bash
make reproduce
```

Current expected outcome on Saturday, August 22, 2026:

- `scripts/reproduce.py` writes a typed candidate bundle under `results/candidates/<run_id>/`
- the command exits nonzero with `INCOMPLETE`
- no `results/frozen/<run_id>/` directory is created
- no `MPP_ARTIFACT_COMPLETE` sentinel is created

Current expected blockers:

- `E1`-`E6` do not have authorized executed publication artifacts in this workspace
- Task 21 real replay remains blocked at `WAITING_LOCAL_MODEL_ARTIFACT` and then `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`
- accountable manual scientific/rendered review is absent
- dirty or unversioned evidence cannot freeze

The current candidate path is intentionally evidence-closure only. It may preserve `SUPPORTED`, `NOT_SUPPORTED`, or `INCONCLUSIVE` claim dispositions when the underlying evidence exists, but it does not certify publication completeness until every gate passes.

## First commands

```bash
make install
make data
make sanity
make experiments
make report
```

The real-model dependencies are optional in the default environment. The repository starts with deterministic synthetic/small-scale tests so protocol plumbing can be validated before GPU-heavy work.
