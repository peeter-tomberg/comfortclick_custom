"""Validate numeric controller readings used by room climate entities."""

import math
from typing import Any


def numeric_value(value: Any) -> float | None:
    """Return a finite number, or unknown for missing and invalid readings."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None
