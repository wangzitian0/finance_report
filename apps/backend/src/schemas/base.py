"""Base schema classes and generic types."""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class BaseResponse(BaseModel):
    """Base for all response schemas with from_attributes config."""

    model_config = ConfigDict(from_attributes=True)


class ListResponse(BaseModel, Generic[T]):
    """Generic paginated list response."""

    items: list[T]
    total: int
