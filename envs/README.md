# Reproducible Environment

## Python

- Python == 3.11.* (CPython)
- Dependencies: `../requirements.lock`
- Reviewed model-runtime wheel hashes: `model_runtime_wheels.sha256`
- Project metadata: `../pyproject.toml`

The publication MPP model runtime is pinned to `torch==2.13.0`,
`transformers==5.14.1`, `tokenizers==0.22.2`, and `safetensors==0.8.0`.
Install only from a reviewed wheelhouse whose selected filenames match the
SHA-256 ledger, then run model acquisition and inference with Hugging Face and
Transformers offline modes enabled. The Hugging Face CLI bootstrap helpers are
outside the authorized execution path and must not be invoked.

Use the exact lockfile for a reviewed environment; `requirements.txt` is
historical scaffolding and is not a reproducible installation path.

## EVM

Foundry/Anvil is an external system dependency. Record the exact versions used for publication here before the final experimental freeze.

Recommended files to add after setup:

- `foundry_version.txt`
- `solc_version.txt`
- `anvil_version.txt`
- `docker_digest.txt`
- `cuda_version.txt`
- `nvidia_driver.txt`
