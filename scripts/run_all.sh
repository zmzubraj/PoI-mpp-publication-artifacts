#!/usr/bin/env bash
set -euo pipefail

mkdir -p results/raw results/figures results/tables results/logs

python experiments/e1_single_pass_cost.py --out results/raw/e1_single_pass_cost.csv | tee results/logs/e1.log
python experiments/e2_tamper_detection.py --out results/raw/e2_tamper_detection.csv | tee results/logs/e2.log
python experiments/e3_semantic_eval.py --out results/raw/e3_semantic_eval.csv | tee results/logs/e3.log
python experiments/e4_da_withholding.py --out results/raw/e4_da_withholding.csv | tee results/logs/e4.log
python experiments/e5_watcher_economics.py --out results/raw/e5_watcher_economics.csv | tee results/logs/e5.log
python experiments/e6_sybil_economics.py --out results/raw/e6_sybil_economics.csv | tee results/logs/e6.log
python experiments/e8_consensus_weight_sim.py --out results/raw/e8_consensus_weight_sim.csv | tee results/logs/e8.log

python experiments/e7_evm_boundedness.py --out results/raw/e7_evm_boundedness.csv | tee results/logs/e7.log || true
