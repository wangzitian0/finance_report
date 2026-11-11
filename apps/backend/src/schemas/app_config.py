"""Pydantic schemas for app-level configuration (#1340, Phase D)."""

from pydantic import BaseModel, field_validator

from src.audit import Currency, InvalidCurrencyError


class BaseCurrencyResponse(BaseModel):
    base_currency: str


class BaseCurrencyUpdate(BaseModel):
    base_currency: str

    @field_validator("base_currency")
    @classmethod
    def validate_iso_4217(cls, value: str) -> str:
        try:
            return Currency(value).code
        except InvalidCurrencyError as exc:
            raise ValueError(str(exc)) from exc
