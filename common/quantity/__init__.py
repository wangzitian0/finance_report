"""``common.quantity`` — the project's quantity narrow waist."""

from __future__ import annotations

from common.quantity.errors import (
    FloatNotAllowedError,
    InvalidUnitError,
    QuantityError,
    UnitMismatchError,
)
from common.quantity.quantity import (
    QUANTITY_DP,
    QUANTITY_QUANTUM,
    QUANTITY_ROUNDING,
    Quantity,
)
from common.quantity.unit import Unit

__all__ = [
    "QUANTITY_DP",
    "QUANTITY_QUANTUM",
    "QUANTITY_ROUNDING",
    "FloatNotAllowedError",
    "InvalidUnitError",
    "Quantity",
    "QuantityError",
    "Unit",
    "UnitMismatchError",
]
