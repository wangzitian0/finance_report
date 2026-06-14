"""Base schema classes and generic types."""

from typing import Annotated, Any, Generic, TypeVar, overload

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

T = TypeVar("T")


@overload
def normalize_currency_code(value: str) -> str: ...


@overload
def normalize_currency_code(value: Any) -> Any: ...


def normalize_currency_code(value: Any) -> Any:
    """Normalize an ISO-4217 currency code to its canonical upper-case form.

    Single source of truth for the soft ``.strip().upper()`` currency
    normalization that was previously duplicated across routers/services.
    Used as a Pydantic ``BeforeValidator``, so it must accept arbitrary input:
    non-``str`` values are passed through unchanged so Pydantic raises its own
    type error. The ``str`` overload keeps direct callers typed as ``str``.
    """
    return value.strip().upper() if isinstance(value, str) else value


# Reusable typed ISO-4217 currency code: a 3-letter, upper-cased ``str``.
# Replaces the soft ``str`` + ad-hoc ``.strip().upper()`` pattern so currency is
# validated and normalized at the schema boundary instead of inside handlers.
# Normalization runs *before* the length constraints so surrounding whitespace
# is stripped prior to the 3-character length check.
CurrencyCode = Annotated[str, BeforeValidator(normalize_currency_code), Field(min_length=3, max_length=3)]


class BaseResponse(BaseModel):
    """Base for all response schemas with from_attributes config."""

    model_config = ConfigDict(from_attributes=True)


class ListResponse(BaseModel, Generic[T]):  # noqa: UP046
    """Generic list response with item count.

    Provides a simple items + total structure without full pagination metadata.
    For paginated responses, use query parameters (limit/offset) at the router level.
    """

    items: list[T]
    total: int  # Total count of items matching the query (may exceed len(items))
