"""Task 21 local orchestration exports."""

from __future__ import annotations

from typing import Any


__all__ = [
    "LocalMPPConfig",
    "LocalMPPResult",
    "RealPathBlocker",
    "SyntheticDisposition",
    "load_local_mpp_config",
    "main",
    "run_local_mpp",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from poi_mpp.orchestration import run_mpp

    return getattr(run_mpp, name)


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
