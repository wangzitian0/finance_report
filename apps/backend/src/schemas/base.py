"""Base schema classes and generic types."""

from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from src.audit import normalize_currency_code

T = TypeVar("T")

CurrencyCode = Annotated[str, BeforeValidator(normalize_currency_code), Field(min_length=3, max_length=3)]
MoneyAmount = Annotated[Decimal, Field(decimal_places=2)]
NonNegativeMoneyAmount = Annotated[Decimal, Field(decimal_places=2, ge=Decimal("0"))]
Quantity = Annotated[Decimal, Field(decimal_places=6)]
Percent = Annotated[Decimal, Field(decimal_places=2)]


class BaseResponse(BaseModel):
    """Base for all response schemas with from_attributes config."""

    model_config = ConfigDict(from_attributes=True)


class ListResponse(BaseModel, Generic[T]):  # noqa: UP046
    """Generic list response with item count."""

    items: list[T]
    total: int
