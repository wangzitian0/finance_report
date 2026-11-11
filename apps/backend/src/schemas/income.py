"""Schemas for income analytics endpoints."""

from datetime import date

from pydantic import BaseModel

from src.schemas.base import CurrencyCode, MoneyAmount


class AnnualizedIncomeResponse(BaseModel):
    annualized_salary: MoneyAmount
    annualized_bonus: MoneyAmount
    annualized_dividend: MoneyAmount
    annualized_total: MoneyAmount
    currency: CurrencyCode
    as_of: date


class FxConversionErrorResponse(BaseModel):
    detail: str
