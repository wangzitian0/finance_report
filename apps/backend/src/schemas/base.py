"""Base schema classes and generic types."""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


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
