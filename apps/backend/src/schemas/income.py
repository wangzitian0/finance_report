"""Schemas for income analytics endpoints."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field


class AnnualizedIncomeResponse(BaseModel):
    """Annualized income summary derived from posted income journal lines."""

    annualized_salary: Annotated[Decimal, Field(decimal_places=2)]
    annualized_bonus: Annotated[Decimal, Field(decimal_places=2)]
    annualized_dividend: Annotated[Decimal, Field(decimal_places=2)]
    annualized_total: Annotated[Decimal, Field(decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    as_of: date
