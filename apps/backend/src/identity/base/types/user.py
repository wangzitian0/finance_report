"""Identity-owned user-settings wire vocabulary."""

from pydantic import BaseModel, field_validator

from src.audit import Currency, InvalidCurrencyError


class BaseCurrencyResponse(BaseModel):
    """Effective base reporting currency for the current user."""

    base_currency: str


class BaseCurrencyUpdate(BaseModel):
    """Update payload for the current user's base reporting currency."""

    base_currency: str

    @field_validator("base_currency")
    @classmethod
    def validate_iso_4217(cls, value: str) -> str:
        try:
            return Currency(value).code
        except InvalidCurrencyError as exc:
            raise ValueError(str(exc)) from exc


class UserAiSettingsUpdate(BaseModel):
    """AI feature flag settings that can be overridden per user."""

    enable_ai_reconciliation: bool | None = None
    enable_ai_classification: bool | None = None
    auto_accept_ai_suggestions: bool | None = None


class UserAiSettingsResponse(BaseModel):
    """Effective AI feature settings for the current user."""

    enable_ai_reconciliation: bool
    enable_ai_classification: bool
    #: What the user chose. A user without a choice gets True.
    auto_accept_ai_suggestions: bool
    #: What the system uses: the choice, AI classification, and the process flag of the operator together.
    auto_accept_ai_suggestions_active: bool


__all__ = [
    "BaseCurrencyResponse",
    "BaseCurrencyUpdate",
    "UserAiSettingsResponse",
    "UserAiSettingsUpdate",
]
