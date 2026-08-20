# Algorithm A5 — Optimistic Dispute Bisection (prototype target)

## Preconditions

- candidate receipt is PENDING;
- watcher deposits challenge bond;
- disputed trace interval is committed.

## Flow

```text
1. Watcher submits challenge and disputed interval.
2. Worker responds with interval commitment/opening.
3. Parties recursively bisect disagreement interval.
4. Continue until one deterministic micro-transition remains.
5. Execute bounded verifier for the micro-transition.
6. Slash invalid party.
7. Pay protocol-defined challenge reward.
8. Update receipt state.
```

## Prototype note

A minimal MPP can implement a simplified single-step dispute first. Full general transformer-kernel bisection is an extension and should not be shown as implemented unless the code supports it.
