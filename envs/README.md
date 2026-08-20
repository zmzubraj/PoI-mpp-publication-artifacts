# Reproducible Environment

## Python

- Python == 3.11.* (CPython)
- Dependencies: `../requirements.lock`
- Project metadata: `../pyproject.toml`

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
