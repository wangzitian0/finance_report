"""Accounting equation out-of-balance diagnostic types (Flow 24)."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "EquationDiagnosticCategory",
    "EquationDiagnosticResult",
]


class EquationDiagnosticCategory(str, Enum):
    BALANCED = "BALANCED"
    UNPOSTED_DRAFT = "UNPOSTED_DRAFT"
    ONE_SIDED_ENTRY = "ONE_SIDED_ENTRY"
    UNCLASSIFIED_ACCOUNT = "UNCLASSIFIED_ACCOUNT"
    FX_ROUNDING_DRIFT = "FX_ROUNDING_DRIFT"
    UNKNOWN_DISCREPANCY = "UNKNOWN_DISCREPANCY"


class EquationDiagnosticResult(BaseModel):
    """Structured diagnostic evaluation of accounting equation state."""

    model_config = ConfigDict(frozen=True)

    is_balanced: bool
    equation_delta: Decimal
    primary_category: EquationDiagnosticCategory
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_action: str
    details: dict[str, Any] = Field(default_factory=dict)
