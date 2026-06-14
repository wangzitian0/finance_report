"""Schemas for income analytics endpoints."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

from src.schemas.base import CurrencyCode


class AnnualizedIncomeResponse(BaseModel):
    """Annualized income summary derived from posted income journal lines."""

    annualized_salary: Annotated[Decimal, Field(decimal_places=2)]
    annualized_bonus: Annotated[Decimal, Field(decimal_places=2)]
    annualized_dividend: Annotated[Decimal, Field(decimal_places=2)]
    annualized_total: Annotated[Decimal, Field(decimal_places=2)]
    # Typed, normalized ISO-4217 presentation currency (was a soft ``str``).
    currency: CurrencyCode
    as_of: date


class FxConversionErrorResponse(BaseModel):
    """Structured error body returned when income FX conversion cannot complete.

    Declares the FX-failure response shape for the annualized-income endpoint so
    the contract is explicit rather than an undocumented bare 400 detail string.
    """

    detail: str = Field(description="Human-readable FX conversion failure reason")
