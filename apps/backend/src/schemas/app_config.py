"""Pydantic schemas for app-level configuration (#1340, Phase D)."""

from pydantic import BaseModel, field_validator

from src.audit.money import Currency, InvalidCurrencyError


class BaseCurrencyResponse(BaseModel):
    """The effective base reporting currency (persisted override else env default)."""

    base_currency: str


class BaseCurrencyUpdate(BaseModel):
    """Request body to set the effective base reporting currency.

    The code is validated against ISO 4217 via ``src.audit.money.Currency`` so an
    invalid code is rejected at the request boundary (HTTP 422) and never
    persisted; the stored value is the normalized (upper-cased) code.
    """

    base_currency: str

    @field_validator("base_currency")
    @classmethod
    def validate_iso_4217(cls, value: str) -> str:
        """Reuse the Currency value type to validate + normalize the code."""
        try:
            return Currency(value).code
        except InvalidCurrencyError as exc:
            raise ValueError(str(exc)) from exc
