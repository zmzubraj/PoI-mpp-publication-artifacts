.PHONY: install data sanity test contracts experiments report figures manifest all clean

install:
	python -m pip install -r requirements.txt

# Generates deterministic controlled datasets.
data:
	python datasets/make_objective_dataset.py --out datasets/generated/objective.jsonl
	python datasets/make_grounded_dataset.py --out datasets/generated/grounded.jsonl

sanity:
	python proof_backend/commitments.py --self-test
	python proof_backend/audit_seed.py --self-test
	python proof_backend/receipt.py --self-test
	python auditor/freivalds.py --self-test
	python auditor/exact_checks.py --self-test

# Run Python unit tests.
test:
	python -m pytest -q

# Foundry contracts, if Foundry is installed.
contracts:
	cd contracts && forge test

experiments:
	bash scripts/run_all.sh

figures:
	python scripts/generate_figures.py

manifest:
	python scripts/build_artifact_manifest.py

report: figures manifest

all: install data sanity test experiments report

clean:
	rm -rf datasets/generated/* results/raw/* results/figures/* results/tables/* results/logs/* results/artifact_manifest.json
