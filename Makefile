.DEFAULT_GOAL := test-all

PYTHON := .venv/bin/python

.PHONY: install data sanity test test-unit test-integration test-contracts test-all reproduce \\
	experiments report figures manifest all clean

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
	$(PYTHON) experiments/e3_semantic_eval.py --out results/raw/e3_semantic_eval.csv
	$(PYTHON) experiments/e4_da_withholding.py --out results/raw/e4_da_withholding.csv
	$(PYTHON) experiments/e5_watcher_economics.py --out results/raw/e5_watcher_economics.csv
	$(PYTHON) experiments/e6_sybil_economics.py --out results/raw/e6_sybil_economics.csv
	$(PYTHON) experiments/e7_evm_boundedness.py --out results/raw/e7_evm_boundedness.csv
	$(PYTHON) experiments/e8_consensus_weight_sim.py --out results/raw/e8_consensus_weight_sim.csv

figures:
	$(PYTHON) scripts/generate_figures.py

manifest:
	$(PYTHON) scripts/build_artifact_manifest.py

report: figures manifest

all: test-all

clean:
	rm -rf datasets/generated/* results/raw/* results/figures/* results/tables/* results/logs/* results/artifact_manifest.json
