# SDD ledger — plan: /Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts/docs/superpowers/plans/2026-08-20-poi-mpp-publication-artifact-implementation.md

Spec: `/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts/docs/superpowers/specs/2026-08-20-poi-mpp-publication-artifact-design.md`

## Setup evidence

- Static security preflight: reviewed manifests, Makefile, shell entrypoint, Foundry config, executable/binary surfaces, credential/network/destructive patterns, and DOCX package relationships. No credible malware, exfiltration, dynamic download-and-execute, macro, external DOCX relationship, privilege escalation, or broad destructive command found. Residual risk: dependency ranges were not locked at import; wheel-only isolated install was used for baseline tooling.
- Imported baseline commit: `db31cc0`.
- Isolated branch/worktree: `feature/poi-mpp-publication-artifacts` at `/Users/rainbow/Documents/ZTech/Research/poi_mpp_workspace/.worktrees/poi-mpp-publication-artifacts`.
- Baseline Python: `.venv/bin/python -m pytest -q` -> 2 passed.
- Baseline Foundry: `forge test` -> contracts compile; no Solidity tests found.
- Ruling: repository bootstrap occurred before Task 1 because the imported workspace had no Git history and a linked worktree cannot exist without a repository — preserve the import as its own baseline commit, then treat Task 1's `git init` command as already satisfied — cost if wrong: one extra baseline commit in history.
- Ruling: Task 1 must use the existing Python 3.11 interpreter and isolated `.venv`; the machine default `python3` is 3.14 and outside the frozen runtime contract — cost if wrong: local command wrappers may need adjustment on another machine.
- Ruling: Foundry's compile-only baseline with zero tests is a RED baseline, not verification of contract behavior — cost if wrong: none beyond requiring Task 7 to supply the missing behavioral tests.

## Preflight self-consistency matrix

| Task | Tests vs implementation and files | Finding |
|---|---|---|
| 1 | Repository-contract test matches lock, package root, Make targets, and modified build files. | Consistent; `git init` already satisfied by bootstrap ruling. |
| 2 | Enum/lifecycle/hash tests match evidence models, canonical serialization, and vectors. | Consistent. |
| 3 | Strict config/provenance tests match schema, config, and frozen manifest implementation. | Consistent. |
| 4 | Validation/registry/gate tests match atomic writes and fail-closed dispositions. | Consistent. |
| 5 | Commitment/compiler/state/property tests match the Python protocol machine. | Consistent. |
| 6 | Conservation/weight/committee tests match credit and selection APIs. | Consistent. |
| 7 | Role, lifecycle, invariant, and replay tests match the seven Solidity contract surfaces. | Consistent. |
| 8 | Cross-language vector and integration tests match exporter and Solidity vector test. | Consistent. |
| 9 | Worker tests match pinned execution, trace, tree, IEC, and inference modules. | Consistent. |
| 10 | Exact/field/float tests match three deliberately separate auditor families. | Consistent. |
| 11 | Semantic and split-isolation tests match verifier, calibration, and dataset manifests. | Consistent. |
| 12 | E1 test/config/CLI/reporting files produce paired receipt cost artifacts. | Consistent; real model authorization remains an execution gate. |
| 13 | E2 tests bind attacks to receipts and detection/residual outputs. | Consistent. |
| 14 | E3 tests enforce calibration/confirmatory separation and semantic outputs. | Consistent; generated datasets remain plumbing-only. |
| 15 | E4 tests match exact DA sampling variants and reconstruction records. | Consistent. |
| 16 | E5 tests match correlated watcher/dispute economics and assumptions. | Consistent. |
| 17 | E6 tests match Sybil/task-budget invariants and boundary ledger. | Consistent. |
| 18 | E7 tests match Foundry JSON parsing, gas/state outputs, and compiler manifest. | Consistent. |
| 19 | E8 tests match next-epoch committee simulation and assumption ledger. | Consistent. |
| 20 | Reporting tests match validated-input-only tables, figures, statistics, and manifest. | Consistent. |
| 21 | E2E tests match real happy path and explicit rejected/abstained/slashed paths. | Consistent. |
| 22 | Clean replay test matches verifier, docs updates, frozen bundle, and completion marker. | Consistent. |

## Preflight shared-interface matrix

| Producer | Consumer | Contract checked | Finding |
|---|---|---|---|
| 1 | 2 | Package root and deterministic test commands. | Compatible. |
| 1 | 3 | Package root and lock surface. | Compatible. |
| 1 | 4 | Package root and test commands. | Compatible. |
| 1 | 5 | Package root and test commands. | Compatible. |
| 1 | 6 | Package root and test commands. | Compatible. |
| 1 | 7 | Contract test command. | Compatible. |
| 1 | 8 | Integration and contract commands. | Compatible. |
| 1 | 9 | Package root and lock surface. | Compatible. |
| 1 | 10 | Package root and test commands. | Compatible. |
| 1 | 11 | Package root and test commands. | Compatible. |
| 1 | 12 | Package root, lock, and experiment command surface. | Compatible. |
| 1 | 13 | Package root, lock, and experiment command surface. | Compatible. |
| 1 | 14 | Package root, lock, and experiment command surface. | Compatible. |
| 1 | 15 | Package root and experiment command surface. | Compatible. |
| 1 | 16 | Package root and experiment command surface. | Compatible. |
| 1 | 17 | Package root and experiment command surface. | Compatible. |
| 1 | 18 | Python/Foundry command surface. | Compatible. |
| 1 | 19 | Package root and experiment command surface. | Compatible. |
| 1 | 20 | Package root and reporting/reproduce commands. | Compatible. |
| 1 | 21 | Package root and `reproduce` orchestration hook. | Compatible. |
| 1 | 22 | Clean-environment and `reproduce` contract. | Compatible. |
| 2 | 3 | Canonical hashing and `RunManifest`. | Compatible. |
| 2 | 4 | Artifact models, stages, and hashes. | Compatible. |
| 2 | 5 | Domain-separated protocol object hashing. | Compatible. |
| 2 | 6 | Canonical credit/committee records. | Compatible. |
| 2 | 7 | Cross-language object/event hash semantics. | Compatible. |
| 2 | 8 | Fixed hash vectors. | Compatible. |
| 2 | 9 | Model, trace, IEC, and execution bundle hashes. | Compatible. |
| 2 | 10 | Typed audit artifact hashes. | Compatible. |
| 2 | 11 | Semantic result and dataset-manifest hashes. | Compatible. |
| 2 | 12 | E1 receipt/result records. | Compatible. |
| 2 | 13 | E2 attack and result records. | Compatible. |
| 2 | 14 | E3 semantic/result records. | Compatible. |
| 2 | 15 | E4 availability/result records. | Compatible. |
| 2 | 16 | E5 economics/result records. | Compatible. |
| 2 | 17 | E6 Sybil/result records. | Compatible. |
| 2 | 18 | E7 Foundry measurement records. | Compatible. |
| 2 | 19 | E8 simulation/result records. | Compatible. |
| 2 | 20 | Validated input hashes and output manifest. | Compatible. |
| 2 | 21 | End-to-end artifact-chain hashes. | Compatible. |
| 2 | 22 | Frozen bundle and verification hashes. | Compatible. |
| 3 | 4 | Frozen run provenance enters validation/gating. | Compatible. |
| 3 | 9 | Pinned model/environment/run manifest. | Compatible. |
| 3 | 12 | Frozen E1 run specification. | Compatible. |
| 3 | 14 | Frozen confirmatory E3 specification. | Compatible. |
| 3 | 18 | Compiler/environment provenance. | Compatible. |
| 3 | 20 | Environment/config/model/dataset hashes. | Compatible. |
| 3 | 21 | Authorized local E2E run configuration. | Compatible. |
| 3 | 22 | Clean replay and frozen manifest. | Compatible. |
| 4 | 12 | Validated E1 artifacts and separate claim decision. | Compatible. |
| 4 | 13 | Validated E2 artifacts and separate claim decision. | Compatible. |
| 4 | 14 | Validated E3 artifacts and separate claim decision. | Compatible. |
| 4 | 15 | Validated E4 artifacts and separate claim decision. | Compatible. |
| 4 | 16 | Validated E5 artifacts and separate claim decision. | Compatible. |
| 4 | 17 | Validated E6 artifacts and separate claim decision. | Compatible. |
| 4 | 18 | Validated Foundry measurements. | Compatible. |
| 4 | 19 | Validated simulation artifacts. | Compatible. |
| 4 | 20 | Validated-input-only reporting gate. | Compatible. |
| 4 | 21 | Atomic end-to-end registry and gate. | Compatible. |
| 4 | 22 | Final fail-closed publication gate. | Compatible. |
| 5 | 6 | Receipt and task state feed credit/committee logic. | Compatible. |
| 5 | 7 | Python protocol state mirrored by Solidity. | Compatible. |
| 5 | 8 | Protocol vectors for parity. | Compatible. |
| 5 | 9 | Task/model/commitment inputs for worker execution. | Compatible. |
| 5 | 10 | Audit plans and receipt audit results. | Compatible. |
| 5 | 12 | Receipt-level E1 records. | Compatible. |
| 5 | 13 | Receipt/attack lifecycle. | Compatible. |
| 5 | 15 | DA/challenge lifecycle. | Compatible. |
| 5 | 17 | Task-budget and credit lifecycle. | Compatible. |
| 5 | 19 | Receipt-derived active weights. | Compatible. |
| 5 | 21 | Full task-to-credit lifecycle. | Compatible. |
- Task 18: fix round 1 complete on 2026-08-21 (canonical collector path enforcement, symlink/off-repo fail-closed support gate, gas no-prewarm rewrite, storage upper-bound renaming, atomic bundle/summary writes, raw hash invalidation `039e...` -> regenerated `c5e7fe21...`; focused E7 tests PASS, parity PASS, `tests/experiments` PASS, full Python suite PASS, GasSnapshots gas-report PASS, full Foundry suite PASS, compileall PASS, git diff --check PASS).
| 6 | 7 | Credit and committee state contract. | Compatible. |
| 6 | 8 | Credit/committee parity vectors. | Compatible. |
| 6 | 17 | Credit conservation and Sybil budget analysis. | Compatible. |
| 6 | 19 | Active weights and committee sampling. | Compatible. |
| 6 | 21 | End-to-end credit/committee transition. | Compatible. |
| 7 | 8 | Solidity state/hash implementation. | Compatible. |
| 7 | 18 | Versioned events and gas/state behavior. | Compatible. |
| 7 | 21 | Local-EVM protocol journey. | Compatible. |
| 8 | 18 | Parity report required by E7. | Compatible. |
| 8 | 22 | Parity report required by publication freeze. | Compatible. |
| 9 | 10 | Execution bundle and trace inputs to auditors. | Compatible. |
| 9 | 11 | Execution output for semantic verification. | Compatible. |
| 9 | 12 | Real single-pass cost measurement. | Compatible. |
| 9 | 13 | Baseline execution for tamper variants. | Compatible. |
| 9 | 14 | Grounded execution outputs. | Compatible. |
| 9 | 21 | Real worker leg of E2E journey. | Compatible. |
| 10 | 12 | Audit-cost and receipt inputs. | Compatible. |
| 10 | 13 | Attack-detection outcomes. | Compatible. |
| 10 | 21 | Exact/algebraic audit leg. | Compatible. |
| 11 | 14 | Semantic verification and calibration/isolation contract. | Compatible. |
| 11 | 21 | Semantic audit leg. | Compatible. |
| 12 | 20 | E1 validated rows to T6/F5. | Compatible. |
| 13 | 20 | E2 validated rows to T7/F6. | Compatible. |
| 14 | 20 | E3 validated rows to T4/T8/F7. | Compatible. |
| 15 | 20 | E4 validated rows to T9/F8. | Compatible. |
| 16 | 20 | E5 validated rows to T10. | Compatible. |
| 17 | 20 | E6 validated rows to T11/F9/F10. | Compatible. |
| 18 | 20 | E7 Foundry rows to T12/F12. | Compatible. |
| 19 | 20 | E8 simulation rows to T13/F11. | Compatible. |
| 12 | 21 | E1 real-execution orchestration path. | Compatible. |
| 13 | 21 | E2 tamper/failure orchestration path. | Compatible. |
| 14 | 21 | E3 semantic orchestration path. | Compatible. |
| 15 | 21 | E4 DA/challenge orchestration path. | Compatible. |
| 16 | 21 | E5 watcher/dispute orchestration path. | Compatible. |
| 17 | 21 | E6 credit/Sybil orchestration path. | Compatible. |
| 18 | 21 | E7 local-EVM orchestration path. | Compatible. |
| 19 | 21 | E8 next-epoch orchestration path. | Compatible. |
| 20 | 22 | Deterministic tables/figures/manifests enter frozen bundle. | Compatible. |
| 21 | 22 | End-to-end artifact chain enters clean replay and freeze. | Compatible. |

Preflight conflicts requiring changes: none beyond the recorded bootstrap and interpreter rulings.

Task 1: review (spec needs changes; Important: build backend not exact-pinned; Important: `envs/README.md` exposes stale Python >=3.10 and `requirements.txt` install path; no Critical/Minor).
Task 1: Ruling: expand the Task 1 fix scope to `envs/README.md` because it is the repository's existing public environment contract and directly contradicts the frozen CPython 3.11 / exact-lock baseline — cost if wrong: one documentation file is updated earlier than its original ownership map anticipated.
Task 1: fix round 1/5 (2 addressed, 0 open — exact build-backend pin; exact Python/lock documentation; commits 8e29929..a29d84b).
Task 1: complete (commits db31cc0..a29d84b, review clean).
Task 2: Ruling: extend dependency ownership to `pyproject.toml` and `requirements.lock` because the plan mandates immutable Pydantic models but the imported manifest omits Pydantic; add one exact direct Pydantic pin and its exact wheel dependencies, preserving CPython 3.11 — cost if wrong: Task 2 touches two baseline files and may require later dependency-contract review.
Task 2: fix round 1/5 (0 addressed, 1 open — public `trusted_load()` reintroduced arbitrary terminal minting; commits b44b9c7..607f514).
Task 2: fix round 2/5 (1 addressed, 0 open — public restore/context bypass removed; commits 607f514..ac9868a).
Task 2: minor (deferred): `ArtifactRecord.advance_to()` docstring still says direct construction supports frozen-record deserialization, but direct terminal construction is now rejected.
Task 2: complete (commits a29d84b..ac9868a, review clean; 1 deferred minor).
Task 3: review (spec needs changes; Critical: arbitrary schema hash/path can freeze; Important: CPU/GPU hard-coded absent; Minor: manually constructed environment facts lack path/credential-pattern rejection).
Task 3: fix round 1/5 (2 addressed, 0 Critical/Important open — approved schema authority and allowlisted CPU/GPU collection; commits 377d82b..816e004).
Task 3: minor (deferred): safe-public-fact path matcher does not reject embedded assignments such as `GPU=/Users/...` or `path=C:\\Users\\...`.
Task 3: minor (deferred): `collect_environment()` docstring still says CPU/GPU are always absent although collectors now populate safe available facts.
Task 3: complete (commits ac9868a..816e004, Critical/Important review clean; 2 deferred minors).
Task 4: review (spec needs changes; Critical: forged/empty evidence can freeze; Critical: duplicate/cyclic graphs complete; Critical: failure can be raised after target publication; Important: nested states/CI/denominator bait fail open; Important: symlink-sensitive containment; Important: duplicate canonical serializer).
Task 4: minor (deferred): publication gate catches every Exception and exposes raw error strings instead of only stable typed reason codes.
Task 4: fix round 1/5 (3 addressed, 4 open — post-link interrupt ambiguity; lost failed-state validators; symlinked parent traversal; pattern-only temp deletion; commits fcdf2e2..f87723d).
Task 4: fix round 2/5 (4 carried findings addressed in original form, 3 new Important findings open — pre-link BaseException swallowing; recovery self-authorizes missing parent closure; temp unlink remains TOCTOU; commits f87723d..8fa85fe).
Task 4: fix round 3/5 (3 addressed, 0 Critical/Important open — pre-link BaseException re-raise with owned-temp cleanup; recovery validates against actual registered parent closure; private-directory + final identity recheck before temp unlink; commits 8fa85fe..eb7960d).
Task 4: complete (commits fcdf2e2..eb7960d, Critical/Important review clean; 1 deferred minor remains; direct verification rerun: 6 targeted registry probes PASS, 54 protocol-gate tests PASS).
Task 5: fix round 1/5 (3 carried blockers addressed, 1 new Important open — DA-before-terminal-audit emitted a receipt that failed canonical revalidation; commits 3c26a67..18c316f).
Task 5: fix round 2/5 (1 addressed, 0 Critical/Important open — audit-after-DA now fails closed and emitted lifecycle states round-trip validate; commits 18c316f..eeb13a8).
Task 5: complete (commits eb7960d..eeb13a8, independent review clean; 23 focused Task 5, 29 protocol, and 136 full Python tests reported PASS; event ordering freezes audit-before-DA as current protocol behavior).
Task 6: implementation candidate pending Task 5 closure and independent review (commit 4acdf98; implementation was produced outside the assigned read-only review scope, so reported RED/GREEN evidence is non-authorizing until a fresh reviewer gates the diff).
Task 6: fix round 1/5 (3 addressed, 0 Critical/Important open — canonical active-receipt revalidation; duplicate receipt/nullifier rejection; exact target epoch; negative/oversized committee inputs fail closed; commits 4acdf98..b80f10b).
Task 6: complete (commits 3c26a67..b80f10b, independent review clean; 11 focused Task 6 and 34 protocol tests PASS; full Python suite reported 141 PASS).
Task 7: review (CHANGES REQUIRED — late activation backfilled historical credit; receipt operator could slash without auditor challenge; slashed receipt nullifier could be reused; 14/14 baseline Foundry tests passed but adversarial repros succeeded).
Task 7: fix round 1/5 (3 carried findings addressed, 2 new Important open — exact-deadline liveness failure and protocol epoch/block-height conflation; commits 4a1b46c..cdcd754).
Task 7: fix round 2/5 (2 addressed, 0 Critical/Important open — immutable canonical block-derived epoch source, exact current-epoch task creation, >= deadline activation only in next epoch, late expiry, aligned activatability; commits cdcd754..ac9f04c).
Task 7: minor (deferred): Foundry emits optional invariant-target discovery warnings because the current harness has no explicit target curation.
Task 7: minor (deferred): CommitmentHub is payable without ETH accounting/withdrawal; accidental ETH can be stranded.
Task 7: complete (commits b80f10b..ac9f04c, independent security review clean; forge fmt PASS and 22/22 Foundry tests PASS).
Task 8: blocked (pre-alignment Python/Solidity commitment identities/hash algorithms and credit allocation semantics diverged; no fixtures fabricated).
Task 8: Ruling: preserve evidence-kernel SHA-256 canonical JSON, but migrate the parity-critical protocol wire contract to typed EVM ABI + Keccak-256 with uint256 ids, address workers, bytes32 roots/nonces, aligned enum ordinals, validated envelope finality, and deterministic sorted receipt-batch credit — cost if wrong: breaking migration across Task 5-7 protocol APIs/tests and Solidity ABIs.
Task 8: review (CHANGES REQUIRED — zero-budget and empty-batch credit semantics diverged; fixture was Python-generated rather than Solidity-derived).
Task 8: fix round 1/5 (3 addressed, 0 Critical/Important open — matched no-op/fail-closed/replay semantics and fresh deterministic Solidity witness export; commits 8644b519..80e59b83).
Task 8: minor (deferred): some non-behavioral fixture input fields are deterministically reconstructed in Python, while all asserted outputs/revert selectors are Solidity-witness-derived.
Task 8: complete (commits ac9f04c..80e59b83, independent xhigh review clean; 39 protocol, 151 full Python, 38 Foundry tests reported PASS; 14 HashVectors PASS; two exports byte-stable).
Task 9: review (CHANGES REQUIRED — incomplete model identity attestation; unsafe trace op names; noncanonical event ordering; empty IEC claim override; untyped protocol manifest).
Task 9: fix round 1/5 (5 addressed, 0 Critical/Important open; commits 79670c1..0a11eee).
Task 9: complete (commits 80e59b83..0a11eee, independent review clean; 16 worker and 167 full Python tests reported PASS; no real model execution claimed).
Task 10: review (CHANGES REQUIRED — zero-reference float metrics raised instead of auditing; AuditResult.model_copy permitted evidence-origin/assurance mutation).
Task 10: fix round 1/5 (2 addressed, 0 Critical/Important open; finite zero-reference metrics, guarded revalidated copies, explicit 31-bit field ceiling; commits 325d824..a62e9ce).
Task 10: minor (deferred): explicit unsafe Pydantic model_construct can bypass AuditResult validators; no in-scope call site found.
Task 10: complete (commits 0a11eee..a62e9ce, independent review clean; 19 auditor and 186 full Python tests reported PASS).
Task 9: implementation candidate pending independent review (commit pending from 80e59b83 base; added pinned worker manifest, deterministic decode, trace/IEC bundle execution, and 9 new worker tests; direct verification: 9 focused worker tests PASS, 160 full Python tests PASS, compileall PASS, git diff --check PASS).
Task 9: fix round 1/5 (5 addressed, 0 Critical/Important open in scoped fix set — manifest mismatch checks now include commitment-bearing identity fields; `TraceEvent.op_name` uses safe-public-text rules; trace sidecars require contiguous zero-based indices; explicit empty `claim_texts` now fail closed; `ExecutionBundle.protocol_model_manifest` is typed and execute-boundary objects are revalidated; commits 79670c1..0a11eee).
Task 10: implementation candidate pending independent review (owned exact/algebraic auditor split under `src/poi_mpp/auditor`; direct verification: RED import failure for missing package, 17 focused Task 10 tests PASS, 17 `tests/auditor` PASS, 184 full Python tests PASS, compileall PASS, git diff --check PASS).
Task 10: fix round 1/5 (3 addressed, 0 Critical/Important open in scoped fix set — zero-reference float metrics now remain finite; `AuditResult.model_copy` forbids provenance/assurance promotion and revalidates allowed updates; field audits reject moduli above the exact 31-bit MPP ceiling before primality work; direct verification: 13 focused regression tests PASS, 19 `tests/auditor` PASS, 186 full Python tests PASS, compileall PASS, git diff --check PASS).
Task 11: review (CHANGES REQUIRED — caller-supplied semantic labels could force `SUPPORTED` without any text-grounding check; confirmatory isolation ignored cross-split `source_hash` reuse; manifests allowed duplicate `content_hash`/`source_hash` rows within one split).
Task 11: Ruling: keep the verifier annotation-driven for this MPP slice, but make semantic label trust explicit and fail closed on untrusted annotations/numeric facts instead of pretending raw text was semantically verified — cost if wrong: later real-model semantic work may need a wider label-authority contract.
Task 11: fix round 1/5 (3 addressed, 0 Critical/Important open — explicit `SemanticLabelAuthority` now gates annotations/numeric facts; cross-split `source_hash` reuse now fails isolation; manifests reject duplicate `content_hash`/`source_hash` rows and normalize `source_family`; commit faec72b..7b7f267).
Task 11: complete (commits a62e9ce..7b7f267, local gated review clean; 22 focused semantic/dataset tests PASS, 208 full Python tests PASS, compileall PASS, git diff --check PASS; annotation-driven scope remains explicit and non-lexical by design).
Task 12: Ruling: implement the E1 library, guarded CLI, exact Parquet dependency pin, and CPU-fixture verification now, but do not execute the real-model pilot until a frozen authorized run/provenance bundle exists — cost if wrong: one later task may need to revisit the CLI handoff once real model authority is granted.
Task 12: complete (commits 7b7f267..21970ba, local gated review clean; 3 focused E1 tests PASS, 211 full Python tests PASS, compileall PASS, git diff --check PASS; `pyarrow==25.0.1` pinned for real Parquet output; live pilot intentionally unexecuted under the recorded authority boundary).
Task 11: independent re-review reopened (Critical: caller-mintable trusted semantic authority via model_construct/raw helper; Important: Unicode source-family alias leakage).
Task 11: fix round 2/5 (Unicode NFKC+casefold fixed; raw trusted issuance still forgeable; commit 7e2b463).
Task 11: fix round 3/5 (all annotation/numeric authority now fail-closed ABSTAIN; model_construct disabled; accepting helper removed; commit 611f53f).
Task 11: complete (commits a62e9ce..611f53f, independent review clean; 29 semantic/dataset and 218 full Python tests reported PASS; explicit limitation: Task11 cannot issue semantic ACCEPT until Task14 supplies a defensible registry-backed authority capability).
Task 12: independent review reopened (Important: unquoted YAML hashes; content-hash mismatch; one/mismatched pair claim support; runner-supplied timing accepted).
Task 19: implementation candidate pending independent review (added replay-authoritative E8 next-epoch committee simulation, deterministic committee-history thresholds, manual publication-boundary CLI, reporting precheck/summary helpers, frozen confirmatory contract, and 10 focused E8 tests under owned Task19 files only).
Task 19: direct verification (10 focused `tests/experiments/test_e8_consensus.py` PASS; `./.venv/bin/python -m pytest tests/experiments -q` PASS; `./.venv/bin/python -m pytest -q` PASS; `./.venv/bin/python -m compileall -q src tests experiments` PASS; `git diff --check` PASS; explicit scope: `REPRODUCIBLE_SIMULATION` only, zero-total-weight epochs return typed nonterminal dispositions, and CLI keeps publication freeze/manual routing fail-closed).
Task 19: fix round 1/5 (Critical addressed locally — confirmatory contract now binds exact frozen scenario closure, per-support max attacker share/probability assertions, exact boundary dispositions, and paired concentration-cap ablation criteria with shared exogenous hash and same-seed rule; placeholder hashes rejected; checked-in `configs/confirmatory/e8.yaml` replaced with canonical scenario hashes for the complete publication scenario set; attacker-dominant support rows remain `INCONCLUSIVE` under contract rather than minting `SUPPORTED`).
Task 19: fix round 1/5 direct verification (13 focused `tests/experiments/test_e8_consensus.py` PASS including attacker-dominance, pair-closure, and placeholder/incomplete-contract regressions; `./.venv/bin/python -m pytest tests/experiments -q` PASS; `./.venv/bin/python -m pytest -q` PASS; `./.venv/bin/python -m compileall -q src tests experiments` PASS; `git diff --check` PASS; preserved `REPRODUCIBLE_SIMULATION` only and manual publication-freeze boundary).
Task 19: fix round 2/5 (Important addressed locally — support assertion validators now reject contradictory nested caps and vacuous `<1.0` bypasses; negative paired deltas must be nonzero/non-vacuous; checked-in `configs/confirmatory/e8.yaml` now uses one consistent non-vacuous falsification policy across support scenarios instead of `1.0` upper caps, with comments marking them as criteria rather than results; current canonical frozen E8 simulations summarize to `INCONCLUSIVE` under that stricter contract, not `SUPPORTED`).
Task 19: fix round 2/5 direct verification (17 focused `tests/experiments/test_e8_consensus.py` PASS including contradictory-cap, vacuous-cap, vacuous-delta, and checked-in-contract-inconclusive regressions; direct canonical probe `load_e8_confirmatory_contract(configs/confirmatory/e8.yaml)` + `summarize_e8_rows(_publication_rows(), contract=...)` -> `claim_disposition=INCONCLUSIVE`; `./.venv/bin/python -m pytest tests/experiments -q` PASS; `./.venv/bin/python -m pytest -q` PASS; `./.venv/bin/python -m compileall -q src tests experiments` PASS; `git diff --check` PASS; preserved `REPRODUCIBLE_SIMULATION` only and manual publication-freeze boundary).
Task 19: complete (commits 4bcb2ff..8d8aa52, independent review clean; 17 focused E8 tests and adversarial contract/attacker/authority probes PASS; canonical frozen reproducible simulation disposition remains `INCONCLUSIVE`, with no real consensus or publication-freeze claim).
Task 12: fix round 1/5 (four carried findings addressed; two new Important origin/authorization escalation findings open; commit 13e784c).
Task 12: fix round 2/5 (LOCAL_TEST_ONLY/pilot scopes nonterminal; exact publication scope required; row/config/manifest identity+origin equality; one synthetic stage-label finding open; commit 05637b0).
Task 12: fix round 3/5 (synthetic origin always nonterminal SEMANTICALLY_VALID; commit 0082d38).
Task 12: complete (commits 7b7f267..0082d38, independent review clean; 12 focused E1 and 227 collected full Python tests reported PASS; no live pilot executed, no real cost result claimed).
Task 13: review (CHANGES REQUIRED — caller-relabeled audit surfaces; duplicate rows inflated denominators; small-N/mixed-origin artifacts froze).
Task 13: fix round 1/5 (routing/uniqueness/CI/origin gates addressed; Critical forged row metadata remained; commit 92370db).
Task 13: fix round 2/5 (self-validating rows added; seed not bound to actual transform remained; commit 001ef90).
Task 13: fix round 3/5 (deterministic replay proof and synthetic-only fixture boundary added; replay validation transition broken; commit b8917ac).
Task 13: fix round 4/5 (fresh xhigh implementer atomically rebuilt replay rows; validated state was lost at aggregation; commit 7f99bf7).
Task 13: fix round 5/5 (fresh xhigh implementer added explicit external replay context at summary/freeze and canonical recomputation; commit c9588ab).
Task 13: complete (commits 0082d38..c9588ab, independent review clean; 27 focused E2 and 254 full Python tests reported PASS; no authorized real pilot or T7/F6 result executed).
Task 13: implementation candidate pending review (commit 32c80b3; frozen E2 attack matrix, manifest-bound receipts, deterministic replay, publication gating; 9 focused Task 13, 40 adjacent, and 243 full Python tests reported PASS).
Task 13: review (CHANGES REQUIRED — caller-controlled surface relabeling; replay rows counted without prior-nullifier membership; duplicate receipt/observation keys admitted; publication freeze thresholds underconstrained).
Task 13: fix round 1/5 (4 addressed, 0 carried open in scoped fix set — canonical family/surface binding, prior-nullifier replay requirement, duplicate receipt/observation rejection, frozen publication minimums; commits 32c80b3..92370db).
Task 13: fix round 2/5 (3 addressed, 0 carried open in scoped fix set — context-free row self-validation, replay validation required before aggregation/freeze, canonical row revalidation in summary/publication builders; commits 92370db..001ef90).
Task 13: fix round 3/5 (4 addressed, 0 carried open in scoped fix set — manifest replay-proof witness contract, seed-insensitive denominator handling, reloaded replay publication rejection retained, fixture origin restricted to SYNTHETIC_NON_EVIDENCE; commits 001ef90..b8917ac).
Task 13: independent re-review reopened (Important: `validate_attack_receipt(...)` could not atomically upgrade an initially `UNVALIDATED` replay row after explicit prior-nullifier evidence, so direct replay validation failed even though already-revalidated rows passed).
Task 13: fix round 4/5 (1 addressed, local verification PASS — replay rows now rebuild canonical detected/accepted/residual/hash fields atomically from explicit prior-nullifier context; matching prior membership yields `CONFIRMED_REPLAY`, nonmatching yields `VERIFIED_NOT_REPLAY`, and reloaded rows still cannot self-authorize without explicit prior context; focused 23 PASS, adjacent 54 PASS, full Python 250 PASS, compileall PASS, git diff --check PASS; pending fresh independent review because collaboration controls were unavailable in this turn).
Task 13: fix round 5/5 (1 addressed locally — aggregation/publication now require explicit replay context keyed by canonical `(attack_instance_id, observation_key)` and recompute summary from the same context to block replay-summary bypass; focused 27 PASS, adjacent 58 PASS, full Python 254 PASS, compileall PASS, git diff --check PASS; pending fresh independent review because collaboration controls are unavailable in this turn).
Task 14: review (CHANGES REQUIRED — simulation-origin runs satisfied the confirmatory publication gate; caller-minted evaluator rows passed on `evaluator_id` alone despite hash/origin/basis mismatch; forged provenance manifests were treated as verified without recomputed freeze-run equality).
Task 14: fix round 1/5 (all carried findings addressed locally — call boundary now revalidates config/rows from canonical dumps; E3 publication requires REAL_MODEL_EXECUTION plus exact run/dataset/row/provenance/evaluator origin equality; verified provenance bundles are recomputed through the evidence-kernel verifier and row evaluator hash/origin/independence basis must exactly match the verified registry; focused 8 PASS, adjacent semantic/dataset 37 PASS, adversarial simulation/evaluator/provenance probes PASS-closed, full Python suite PASS, compileall PASS, git diff --check PASS; pending fresh independent review because collaboration controls are unavailable in this turn).
Task 14: implementation candidate (commit d10f132; confirmatory metric harness added, no real confirmation run).
Task 14: review/fix outside read-only scope (commit bd0604a; caller-mutated config/row and origin/provenance checks tightened; non-authorizing until fresh review).
Task 14: fresh review (CHANGES REQUIRED — evaluator authority self-mintable; rows not closed over frozen source/annotation manifests; CLI ignored confirmatory schema).
Task 14: fix round 1/5 (real confirmation fail-closed WAITING_EXTERNAL; separate synthetic plumbing; exact manifest closure and schema loader; one provenance-precedence finding open; commit 31c58b9).
Task 14: fix round 2/5 (verified provenance required before WAITING_EXTERNAL; commit 63397a0).
Task 14: complete (commits c9588ab..63397a0, independent review clean; 14 focused E3 tests PASS; no real confirmation or semantic acceptance result executed; external evaluator authority remains required).
Task 15: review (CHANGES REQUIRED — live tampered shards could be certified; symlink escape; status-blind claim support; duplicate-row minor).
Task 15: fix round 1/5 (frozen layout verification, anchored no-follow reads, explicit availability-vs-detection claims, uniqueness/minimum-N/interval gates; commit c114d70).
Task 15: complete (commits 63397a0..c114d70, independent review clean; 15 focused E4 tests PASS; no real artifact/result generated).
Task 16: review (CHANGES REQUIRED — unscoped simulation rows could support; reruns inflated scenario breadth; bribery semantics were inert; later review found caller-mintable outputs, missing run authorization, and post-replay resource caps).
Task 16: fix rounds 1-3/5 (exact publication scope and scenario uniqueness; canonical deterministic replay plus frozen confirmatory-contract closure; typed RunConfig authorization binding and pre-replay global/contract simulation caps; commits ca7049b..1a278b8).
Task 16: complete (commits c114d70..1a278b8, independent review clean; 14 focused E5 tests and adversarial probes PASS; simulation-only implementation, no real artifact/result or publication freeze executed).
Task 17: implementation complete (typed E6 Sybil/task-budget simulator and reporting added; paired-seed operator-level schedulers stay flat across `1..64` identities; publication support now requires canonical replay, confirmatory-contract closure, and exact run authorization binding; unsafe negative controls retained; focused E6 tests PASS, `tests/experiments` PASS, full Python suite PASS, compileall PASS, git diff --check PASS).
Task 17: fix round 1/5 (negative-control semantics now require role/model-bound contract closure plus split-row failure evidence over frozen `epsilon_sybil`; exact accounting invariants split into task-accounting equality, credit-issuance equality, budget non-exceedance, and explicit utilization; flat contract-bound safe negatives stay `INCONCLUSIVE`; zero-success accounting regression added; focused E6 tests PASS, `tests/experiments` PASS, full Python suite PASS, compileall PASS, git diff --check PASS).
Task 17: complete (commits 510a4fd..78ee602, independent review clean; 12 focused E6 tests plus adversarial flat-negative, relabel, accounting, authority, replay, and cap probes PASS; reproducible-simulation only, no real artifact/result or publication freeze executed).
Task 18: implementation complete (typed E7 Foundry measurement contract/bundle/reporting added; raw-report authority now re-parses canonical Foundry JSON and rejects forged rows; local block-limit boundedness is measured over the exact E7 operation/batch matrix and bound to Task 8 parity attachment; focused E7 tests PASS, parity integration PASS, `tests/experiments` PASS, full Python suite PASS, GasSnapshots Foundry suite PASS, full Foundry suite PASS, compileall PASS, git diff --check PASS; local Foundry evidence only, no publication freeze executed).
Task 18: fix round 1/5 (canonical collector path enforcement, symlink/off-repo fail-closed support gate, gas no-prewarm rewrite, storage upper-bound renaming, raw hash invalidation `039e...` -> regenerated `c5e7fe21...`; focused E7 tests PASS, parity PASS, `tests/experiments` PASS, full Python suite PASS, GasSnapshots gas-report PASS, full Foundry suite PASS, compileall PASS, git diff --check PASS).
Task 18: fix round 2/5 (stored bundle/capability/attachment metadata can no longer mint `SUPPORTED`; live publication boundary now reruns exporter + direct HashVectors + Python parity, binds current parity source-closure/transcript hashes, then recollects the canonical raw E7 report and emits local support only from that call; temp live-publication bundle/summary hashes `993657a0...` / `07d2f7e0...`, parity source-closure hash `4fdf9b92...`; focused E7 tests PASS, parity PASS, `tests/experiments` PASS, full Python suite PASS, GasSnapshots gas-report PASS, full Foundry suite PASS, compileall PASS, git diff --check PASS).
Task 18: complete (commits 0ebc8d1..a8c3f7a, independent review clean; forged capability/model-copy and source-drift probes PASS; canonical local raw witness SHA-256 `c5e7fe21f4d786a789a356fd13992444216d2de451734be72ee5e1cacec7dda4`; local Foundry call-body gas and storage-change upper bounds only, no mainnet or publication-freeze claim).
Task 20: implementation complete (deterministic reporting loader/tables/figures/manifest added; synthetic/manual/path-escape/tamper inputs fail closed; stored E7 bundle metadata stays non-authoritative; live E7 plus frozen E8 temp build produced `SUPPORTED` local T12/F12 and `INCONCLUSIVE` T13/F11 with explicit omissions for absent E1-E6 artifacts; `tests/reporting` PASS, `tests/reporting tests/experiments` PASS, full Python suite PASS, compileall PASS, git diff --check PASS; publication freeze intentionally unavailable in this phase).
Task 20: fix round 1/5 (manifest now records strict canonical input rows with anchored relative paths and recomputes current generator/environment hashes plus input SHA-256s at validation; output-root and leaf reads are anchored no-follow and reject symlink replacement; duplicate input/output/derivation metadata now fails closed; `T4` is explicitly represented as omission/status rather than an empty quantitative table, and the central mapping now covers exact `T4`, `T6`-`T13`, `F5`-`F12`; `tests/reporting` PASS, `tests/reporting tests/experiments` PASS, full Python suite PASS, compileall PASS, git diff --check PASS).
Task 20: fix round 2/5 (live E7 closure now explicitly manifests non-paper `RAW_E7_LIVE_BUNDLE` with schema/run/config/parity-source-closure plus derivation to `T12`/`F12`; generated authoritative outputs are part of exact closure and tampered/missing raw bundle invalidates validation; manifest input/output/derived paths now require canonical POSIX relative form and runtime joins use validated lexical roots before anchored no-follow reads; focused live-E7 reporting tests PASS, `tests/reporting` PASS, `tests/reporting tests/experiments/test_e7_evm.py tests/experiments/test_e8_consensus.py` PASS, full Python suite PASS, compileall PASS, git diff --check PASS; one transient parallel Foundry raw-report race was resolved by serial rerun and is not a product regression).
Task 20: complete (commits 30e8100..b4deac9, independent review clean; live E7 build-to-validation, manifest tamper/input drift/path escape/symlink/hardlink, raw-bundle closure, deterministic mapping, and T4 omission probes PASS; publication freeze intentionally unavailable in this phase).
Task 21: implementation complete (typed local orchestration/config/CLI added under `src/poi_mpp/orchestration`, `scripts/run_mpp.py`, `configs/e2e/local.yaml`, and `tests/e2e`; real path now fails closed at `WAITING_LOCAL_MODEL_ARTIFACT` and then `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`, while synthetic mechanics rerun Task 8 parity, start/stop local Anvil safely, deploy exact local contracts with source/compiler/runtime hash verification, and exercise happy/reject/abstain/DA-fail/slash/service/replay journeys under explicit `SYNTHETIC_NON_EVIDENCE` / `NON_PUBLICATION_MECHANICS`; `tests/e2e` PASS, broad Task 21 regression wave PASS, full Python suite PASS, full Foundry suite PASS, compileall PASS, `bash -n` PASS, `git diff --check` PASS, `shellcheck` unavailable; no real model execution or publication-ready claim).
Task 21: fix round 1/5 (artifact/result path serialization now stores canonical output-root-relative POSIX paths only and reload re-verifies parent/hash closure; happy-path `receipt_state` / `credit_epoch` now come from authoritative `ReceiptManager.getReceipt(...)` plus `AuditManager.getAudit(...)` cross-checks and monkeypatched expectation/readback mismatches fail closed; Anvil logs are bounded to `_ANVIL_LOG_LIMIT` with truncation/hash metadata and subprocesses now run in explicit offline loopback-only mode with proxy inheritance removed; focused e2e 13 PASS, broad Task 21 regression wave 124 PASS, full Python suite PASS, full Foundry suite PASS, compileall PASS, `bash -n` PASS, `git diff --check` PASS, `shellcheck` unavailable; no real model execution or publication-ready claim).
Task 21: fix round 2/5 (removed the remaining manual `successful_challenge_state` overwrite so the production summary now forwards the exact kernel-derived challenge/slash state from `_run_reference_machine_failures()`; added a RED regression that monkeypatches the kernel-derived failure summary to `CHALLENGED`, which fails immediately if a hardcoded `"SLASHED"` is reintroduced; focused regression 2 PASS, `tests/e2e` 14 PASS, broad Task 21 regression wave 125 PASS, full Python suite PASS, compileall PASS, `bash -n` PASS, `git diff --check` PASS; no real model execution or publication-ready claim).
Task 21: code quality fix round 1/5 (runner now works in clean src-layout via deterministic wrapper bootstrap plus `run_all.sh` repo `PYTHONPATH` export and module entrypoint; loader now resolves relative model/tokenizer roots against `config_path.parent` from foreign cwd; model/tokenizer verification is anchored no-follow and rejects symlink roots/components, hardlinked/nonregular leaves, and identity changes with stable non-path-leaking blocker reasons; output-root preparation now rejects symlinked roots/components before any write and direct writer/full runner regressions prove no outside write occurs; targeted smoke/path regressions 10 PASS, `tests/e2e` 23 PASS, broad Task 21 regression wave 134 PASS, full Python suite PASS, full Foundry suite PASS, compileall PASS, `bash -n` PASS, `git diff --check` PASS; no real model execution or publication-ready claim).
Task 21: code quality fix round 2/5 (managed macOS `/var` and `/tmp` aliases now canonicalize only after verified OS-managed prefix checks to canonical `/private/...` paths, while user-created/deeper symlinked model/tokenizer/output roots still fail closed under anchored no-follow traversal; `poi_mpp.orchestration` exports are now lazy so `python -W error -m poi_mpp.orchestration.run_mpp --help` is warning-clean; targeted alias/warning regressions 6 PASS, `tests/e2e` 28 PASS, broad Task 21 regression wave 139 PASS, full Python suite PASS with 376 collected tests, full Foundry suite PASS, compileall PASS, `bash -n` PASS, `git diff --check` PASS; no real model execution or publication-ready claim).
Task 21: complete (commits de05405..c272bdf, separate spec-compliance and code-quality reviews PASS; synthetic task-to-committee mechanics plus six failure journeys verified, real execution remains fail-closed at `WAITING_LOCAL_MODEL_ARTIFACT` then `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`, and no publication evidence/freeze claim was made).
Task 22: hardening round complete (production verifier now rejects `TEST_ONLY_NON_EVIDENCE`, enforces exact bundle closure plus anchored no-follow/hardlink-safe reads, re-runs Task 20 publication-manifest validation, replays the live E7 authority boundary, requires externally authenticated manual-review signatures, stages candidates under ignored `results/tmp/candidates/<run_id>`, and preserves `NEEDS_CONTEXT` for missing production-owned E8 canonical rows/runner; live current-workspace replay on Saturday, August 22, 2026 remains `INCOMPLETE` with blocker chain `WAITING_LOCAL_MODEL_ARTIFACT` -> `WAITING_EXTERNAL_EVALUATOR_AUTHORITY`, missing accountable manual review/signature, absent authorized `E1`-`E6`, and E8 `NEEDS_CONTEXT`; `C7` stays `SUPPORTED`, no `results/frozen/*/MPP_ARTIFACT_COMPLETE` sentinel exists; `tests/reproducibility` PASS, full Python suite PASS, compileall PASS, git diff --check PASS).
Task 22: E8 production replay integration in progress on Saturday, August 22, 2026 (candidate bundles now source `E8` from `load_and_run_e8_publication(default_e8_publication_plan_path(), ...)`, manifest/claim derivation now comes from the validated Task 20 publication outputs, candidate-only replay shows `E8` `COMPLETE` with `C8=INCONCLUSIVE` and no `NEEDS_CONTEXT`, and focused reproducibility regressions for production E8 tamper/missing-artifact paths PASS; full-mode replay and final clean-tree validation still pending because the live E7 authority revalidation path is the remaining slow gate).
Task 22: complete on Saturday, August 22, 2026 (commit `cd25335`; committed-tree `scripts/reproduce.py` now finishes both candidate-only and full-mode runs as honest nonzero `INCOMPLETE` candidates without `UNVERSIONED_BLOCKED`; final full-mode candidate `results/tmp/candidates/task22-741d9fb3f4e8d00f/` verifies with report SHA-256 `80ae07314f4ba040a76bf3bf3b11d97ab06d5bfbd96c44a7b96356d191724672`, blocker set limited to Task21 authority/manual-review plus missing `E1`-`E6`, `C7=SUPPORTED`, `C8=INCONCLUSIVE`, and no `MPP_ARTIFACT_COMPLETE`; `tests/reproducibility` PASS, full Python PASS, `forge test -q` PASS, compileall PASS, `git diff --check` PASS).
