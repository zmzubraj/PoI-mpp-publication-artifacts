"""Deterministic formatting helpers for publication reporting."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Any

from poi_mpp.reporting.load import PublicationEligibilityError


_QUANTUM = Decimal("0.000001")


def require_finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise PublicationEligibilityError((f"{label} must be a finite number",))
    return float(value)


def canonical_decimal(value: Any) -> str:
    finite = require_finite_number(value, label="canonical decimal")
    decimal_value = Decimal(str(finite)).quantize(_QUANTUM, rounding=ROUND_HALF_UP)
    text = format(decimal_value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text if text else "0"


def csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return canonical_decimal(value) if isinstance(value, float) else str(value)
    if isinstance(value, (list, tuple)):
        return "|".join(csv_cell(item) for item in value)
    return str(value)


def deterministic_sort_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(f"{key}={csv_cell(row[key])}" for key in sorted(row))


__all__ = ["canonical_decimal", "csv_cell", "deterministic_sort_key", "require_finite_number"]
