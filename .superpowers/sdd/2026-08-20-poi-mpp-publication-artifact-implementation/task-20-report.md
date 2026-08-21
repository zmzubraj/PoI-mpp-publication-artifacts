# Task 20 — Deterministic publication reporting

## Scope

- Added fail-closed reporting input models, anchored no-follow path loading, and authority-aware experiment ingestion in `src/poi_mpp/reporting/load.py`.
- Added deterministic numeric/csv helpers in `src/poi_mpp/reporting/statistics.py`.
- Added editable table generation plus claim/omission ledgers in `src/poi_mpp/reporting/tables.py`.
- Added deterministic SVG/JSON figure generation with embedded source-hash captions in `src/poi_mpp/reporting/figures.py`.
- Added atomic write, manifest, and closure-validation logic in `src/poi_mpp/reporting/manifest.py`.
- Updated `src/poi_mpp/reporting/__init__.py` exports.
- Replaced the scaffold scripts with argv-only wrappers:
  - `scripts/report_all.py`
  - `scripts/generate_figures.py`
  - `scripts/build_artifact_manifest.py`
- Added RED/GREEN coverage in `tests/reporting/test_publication_reporting.py`.

## RED evidence

- Initial RED run: `./.venv/bin/python -m pytest tests/reporting -v`
- Observed failure: `ModuleNotFoundError: No module named 'poi_mpp.reporting.load'`, confirming the Task 20 reporting surface was absent before implementation.

## Behavior

- The reporting pipeline is now manifest-driven and fail-closed:
  - synthetic/manual/unvalidated payloads are rejected
  - artifact-root path escape and symlink inputs are rejected
  - non-finite numeric values are rejected
  - stored E7 bundle metadata cannot mint `SUPPORTED`
  - E8 reproducible-simulation rows keep their canonical `INCONCLUSIVE` disposition
- Writes are atomic (`write -> fsync -> replace -> read-back hash`) for every generated table, figure, and manifest file.
- Output closure is explicit and re-validatable through `artifact_manifest.json`; later tampering or extra files fail validation.
- Determinism is byte-level for identical validated inputs:
  - stable JSON key order
  - stable CSV row/column ordering
  - fixed SVG layout, fonts, and labels
  - no timestamps or random identifiers
- Figure captions now include source hashes, and omission/status figures are generated explicitly instead of fabricating absent paper artifacts.

## Current publication-state handling

- Current available authoritative build path:
  - `E7`: live local Foundry collection path, can produce `SUPPORTED` local boundedness artifacts only from the live collection boundary
  - `E8`: frozen reproducible simulation path, currently remains `INCONCLUSIVE`
- Current absent inputs remain explicit omissions:
  - `E1`
  - `E2`
  - `E3`
  - `E4`
  - `E5`
  - `E6`
- The pipeline therefore emits:
  - real `T12` / `F12` from the live E7 call
  - real `T13` / `F11` from the frozen E8 rows
  - claim/omission ledgers and status figures for absent artifacts

## Verification

- `./.venv/bin/python -m pytest tests/reporting -v`
- `./.venv/bin/python -m pytest tests/reporting tests/experiments -q`
- `./.venv/bin/python -m pytest -q`
- `./.venv/bin/python -m compileall -q src tests experiments scripts`
- `git diff --check`

## Temp authoritative build probe

- A temporary build was executed from:
  - live local E7 Foundry collection under `PUBLICATION_EVIDENCE_AUTHORIZED`
  - frozen E8 reproducible-simulation rows plus `configs/confirmatory/e8`-equivalent contract content
- Temp output root: machine temp directory under `/private/var/folders/.../tmp.TBky4HCigT/out`
- Temp manifest SHA-256: `47d4f76436cfd3867de29009d69d9e24487e085d731e560c04fc3054000e466f`
- Observed outputs:
  - `T12` / `F12` with `SUPPORTED` local Foundry disposition
  - `T13` / `F11` with `INCONCLUSIVE` reproducible-simulation disposition
  - omission records for `T6/F5`, `T7/F6`, `T8/F7`, `T9/F8`, `T10`, `T11/F9/F10`

## Authority boundary retained

- Task 20 does not publication-freeze artifacts.
- `report_all.py freeze ...` remains intentionally unavailable and returns a fail-closed error.
- The reporting layer does not widen experiment authority beyond the frozen input contracts/configs it consumes.

## Residual risk

- The current loader implements live/authoritative reporting for E7/E8 and omission/status handling for missing E1-E6 inputs. If future authorized E1-E4 bundles need direct ingestion through Task 20 rather than omission routing, that surface should be extended under the same fail-closed contract.
