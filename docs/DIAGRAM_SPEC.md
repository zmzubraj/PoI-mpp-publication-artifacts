# Diagram and Figure Specification

## Figure conventions

- Blue = protocol/cryptographic state.
- Green = successful/matured state.
- Gold = challenge/audit state.
- Red = dispute/failure/ABSTAIN.
- Gray = infrastructure or off-chain support.

Do not visually imply that an attestation is equivalent to a cryptographic proof.

## Required diagrams

### D1 — System architecture

```text
Requester
   |
   v
Task Contract ---> Model Registry ---> Worker / Model Runtime
                         |                    |
                         |                    +--> Trace Sidecar
                         |                    +--> IEC Builder
                         |                    +--> Artifact Store
                         |
                         v
                  Commitment Hub
                         |
                epoch randomness
                         v
               Audit Compiler
                  /          \\
                 /            \\
          Exec Audit       Semantic Audit
               \                /
                \              /
                 v            v
                   Receipt Manager
                         |
                challenge window
                         |
                         v
                 Credit Engine
                         |
                         v
                Consensus Adapter
                         |
                         v
                   BFT / VRF
```

### D2 — Sequence diagram

Use lifelines for Requester, Worker, Chain, Auditor, Watcher, DA, Consensus.

### D3 — Receipt lifecycle state machine

`COMMITTED -> PENDING_AUDIT -> PENDING_CHALLENGE -> ACTIVE`

branches to `ABSTAIN`, `SLASHED`, `EXPIRED`.

### D4 — Audit algorithm

`commit -> seed -> sample -> open -> verify -> dispute?`

### D5 — Economic flow

`task budget -> receipt score -> bounded credit -> collateral cap -> next epoch weight`.

### D6 — Semantic verification

`response -> IEC -> obligations -> verifier mesh -> LCB -> decision`.
