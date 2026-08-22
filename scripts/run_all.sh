#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
python_bin="${repo_root}/.venv/bin/python"
config_path="${repo_root}/configs/e2e/local.yaml"
output_root="${1:-${repo_root}/results/e2e/local}"

cleanup() {
  :
}
trap cleanup EXIT

"${python_bin}" "${repo_root}/scripts/run_mpp.py" --config "${config_path}" --output-root "${output_root}"
"${python_bin}" -m pytest -o addopts='' "${repo_root}/tests/e2e" -q
