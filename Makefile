.DEFAULT_GOAL := test-all

PYTHON := .venv/bin/python

.PHONY: install data sanity test test-unit test-integration test-contracts test-all reproduce
.PHONY: experiments e3-authorized report figures manifest all clean

E3_REQUEST_MANIFEST ?= docs/paper_artifacts/final/external_review/E3_AUTHORITY_REQUEST_MANIFEST.json
E3_AUTHORITY_RECORD ?=
E3_AUTHORITY_SIGNATURE ?=
E3_ALLOWED_SIGNERS ?=
E3_CONFIRMATORY_CONFIG ?=
E3_MODEL_MANIFEST ?=
E3_RAW_CONFIG ?=
E3_INPUTS ?=
E3_OUTPUTS ?=
E3_TRACE ?=
E3_PROVENANCE ?=
E3_ARTIFACT_ROOT ?=

install:
	$(PYTHON) -m pip install --requirement requirements.lock

# Generates deterministic controlled datasets.
data:
	$(PYTHON) datasets/make_objective_dataset.py --out datasets/generated/objective.jsonl
	$(PYTHON) datasets/make_grounded_dataset.py --out datasets/generated/grounded.jsonl

sanity:
	$(PYTHON) proof_backend/commitments.py --self-test
	$(PYTHON) proof_backend/audit_seed.py --self-test
	$(PYTHON) proof_backend/receipt.py --self-test
	$(PYTHON) auditor/freivalds.py --self-test
	$(PYTHON) auditor/exact_checks.py --self-test

# Compatibility alias for existing callers.
test:
	$(MAKE) test-unit

# Unit-level Python tests exclude cross-system and clean-replay checks.
test-unit:
	$(PYTHON) -m pytest tests -q --ignore=tests/integration --ignore=tests/e2e --ignore=tests/reproducibility

# Cross-system tests remain explicit and fail if their suite has not been implemented.
test-integration:
	$(PYTHON) -m pytest tests/integration tests/e2e tests/reproducibility -q

test-contracts:
	cd contracts && forge test

# No target silently skips a missing suite or failed command.
test-all: test-unit test-integration test-contracts

reproduce:
	$(PYTHON) scripts/reproduce.py

experiments:
	$(PYTHON) experiments/e1_single_pass_cost.py --out results/raw/e1_single_pass_cost.csv
	$(PYTHON) experiments/e2_tamper_detection.py --out results/raw/e2_tamper_detection.csv
	@echo "E3 WAITING_EXTERNAL: use 'make e3-authorized' only after externally signed authority and real execution inputs exist."
	$(PYTHON) experiments/e4_da_withholding.py --out results/raw/e4_da_withholding.csv
	$(PYTHON) experiments/e5_watcher_economics.py --out results/raw/e5_watcher_economics.csv
	$(PYTHON) experiments/e6_sybil_economics.py --out results/raw/e6_sybil_economics.csv
	$(PYTHON) experiments/e7_evm_boundedness.py --out results/raw/e7_evm_boundedness.csv
	$(PYTHON) experiments/e8_consensus_weight_sim.py --out results/raw/e8_consensus_weight_sim.csv

e3-authorized:
	@test -n "$(E3_AUTHORITY_RECORD)" || { echo "E3_AUTHORITY_RECORD is required (external regular file)" >&2; exit 2; }
	@test -n "$(E3_AUTHORITY_SIGNATURE)" || { echo "E3_AUTHORITY_SIGNATURE is required (external detached signature)" >&2; exit 2; }
	@test -n "$(E3_ALLOWED_SIGNERS)" || { echo "E3_ALLOWED_SIGNERS is required (external allowed-signers file)" >&2; exit 2; }
	@test -n "$(E3_CONFIRMATORY_CONFIG)" || { echo "E3_CONFIRMATORY_CONFIG is required" >&2; exit 2; }
	@test -n "$(E3_MODEL_MANIFEST)" || { echo "E3_MODEL_MANIFEST is required" >&2; exit 2; }
	@test -n "$(E3_RAW_CONFIG)" || { echo "E3_RAW_CONFIG is required" >&2; exit 2; }
	@test -n "$(E3_INPUTS)" || { echo "E3_INPUTS is required" >&2; exit 2; }
	@test -n "$(E3_OUTPUTS)" || { echo "E3_OUTPUTS is required" >&2; exit 2; }
	@test -n "$(E3_TRACE)" || { echo "E3_TRACE is required" >&2; exit 2; }
	@test -n "$(E3_PROVENANCE)" || { echo "E3_PROVENANCE is required" >&2; exit 2; }
	@test -n "$(E3_ARTIFACT_ROOT)" || { echo "E3_ARTIFACT_ROOT is required and must not pre-exist" >&2; exit 2; }
	$(PYTHON) experiments/e3_semantic_eval.py \
		--request-manifest "$(E3_REQUEST_MANIFEST)" \
		--authority-record "$(E3_AUTHORITY_RECORD)" \
		--authority-signature "$(E3_AUTHORITY_SIGNATURE)" \
		--allowed-signers "$(E3_ALLOWED_SIGNERS)" \
		--confirmatory-config "$(E3_CONFIRMATORY_CONFIG)" \
		--model-manifest "$(E3_MODEL_MANIFEST)" \
		--raw-config "$(E3_RAW_CONFIG)" \
		--inputs "$(E3_INPUTS)" \
		--outputs "$(E3_OUTPUTS)" \
		--trace "$(E3_TRACE)" \
		--provenance "$(E3_PROVENANCE)" \
		--artifact-root "$(E3_ARTIFACT_ROOT)"

figures:
	$(PYTHON) scripts/generate_figures.py

manifest:
	$(PYTHON) scripts/build_artifact_manifest.py

report: figures manifest

all: test-all

clean:
	rm -rf datasets/generated/* results/raw/* results/figures/* results/tables/* results/logs/* results/artifact_manifest.json
