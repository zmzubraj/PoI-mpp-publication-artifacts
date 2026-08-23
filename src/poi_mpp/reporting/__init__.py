"""Deterministic reporting helpers for publication-bound experiment slices."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "E1Summary": "poi_mpp.reporting.e1",
    "summarize_e1_rows": "poi_mpp.reporting.e1",
    "E2Summary": "poi_mpp.reporting.e2",
    "summarize_e2_rows": "poi_mpp.reporting.e2",
    "E3MetricPolicy": "poi_mpp.reporting.e3",
    "E3Summary": "poi_mpp.reporting.e3",
    "semantic_metrics": "poi_mpp.reporting.e3",
    "E4Summary": "poi_mpp.reporting.e4",
    "f8_points": "poi_mpp.reporting.e4",
    "summarize_e4_rows": "poi_mpp.reporting.e4",
    "t9_rows": "poi_mpp.reporting.e4",
    "E5Summary": "poi_mpp.reporting.e5",
    "invalid_maturity_sensitivity_points": "poi_mpp.reporting.e5",
    "publication_precheck_reasons": "poi_mpp.reporting.e5",
    "summarize_e5_rows": "poi_mpp.reporting.e5",
    "t10_rows": "poi_mpp.reporting.e5",
    "PublicationEligibilityError": "poi_mpp.reporting.load",
    "ReportBuildSpec": "poi_mpp.reporting.load",
    "load_publication_inputs": "poi_mpp.reporting.load",
    "build_publication_report": "poi_mpp.reporting.manifest",
    "validate_existing_manifest": "poi_mpp.reporting.manifest",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
