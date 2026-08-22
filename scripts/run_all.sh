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

# Offline-only execution. localhost Anvil exception: the runner may only talk to
# the loopback RPC it starts itself; no model downloads or remote fallbacks.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export PIP_NO_INDEX=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
unset http_proxy https_proxy all_proxy
unset FTP_PROXY ftp_proxy

"${python_bin}" "${repo_root}/scripts/run_mpp.py" --config "${config_path}" --output-root "${output_root}"
"${python_bin}" -m pytest -o addopts='' "${repo_root}/tests/e2e" -q
