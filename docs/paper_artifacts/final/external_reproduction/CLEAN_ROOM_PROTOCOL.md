# PoI MPP clean-room external reproduction protocol

## Preconditions

- Use a fresh clone or verified source archive at the declared commit.
- Record OS, CPU/GPU, RAM, Python, Node, Foundry, Solidity, and model revisions.
- Do not copy repository-local caches, untracked result directories, private
  keys, signatures, or allowed-signers files from the producer.
- Keep evaluator identity material, detached signatures, and the allowed-signers
  file outside the repository and outside symlink targets into the repository.
- Treat synthetic fixtures only as plumbing and preserve
  `SYNTHETIC_NON_EVIDENCE`; they may not satisfy confirmatory evidence gates.

## Deterministic checks

Record exact stdout, stderr, exit code, wall time, and SHA-256 for every output:

```text
./.venv/bin/python -m pytest -q
(cd contracts && forge test)
./.venv/bin/python scripts/report_all.py validate --output-root publication
./.venv/bin/python scripts/reproduce.py --mode candidate-only
./.venv/bin/python scripts/verify_bundle.py --bundle-root <candidate-root>
npm run build:paper-docx
```

Expected fail-closed states are not discrepancies: the verified E3 artifacts must
reproduce FAR 0.500 (1/2), FRR 0.167 (1/6), ABSTAIN 0.125 (1/8), coverage
0.875 (7/8), and Brier calibration 0.178, with `C3=NOT_SUPPORTED` because FAR
exceeds frozen `alpha_sem=0.25`. Evaluator identity, independence, expertise,
and private-key custody still require out-of-band confirmation; independent
review and publication freeze remain open; E1 and E2 remain `INCONCLUSIVE`;
simulation and local-Foundry scope ceilings remain unchanged.

## Discrepancy handling

Record every missing input, changed hash, command failure, non-deterministic
output, numerical difference, platform limitation, and interpretation dispute in
`discrepancy_report.schema.json`. Do not silently normalize or waive a mismatch.

## Authentication contract

Serialize the completed attestation as UTF-8 JSON and sign that exact file with
an externally controlled OpenSSH key. Verify from outside the repository:

```text
ssh-keygen -Y verify -f <external-allowed-signers> -I <principal> -n file -s <attestation.sig> < <attestation.json>
```

Repository-local or symlinked signature/trust files are inadmissible. A valid
signature proves only key possession over the bytes; the accountable human must
separately verify real-world identity and independence.
