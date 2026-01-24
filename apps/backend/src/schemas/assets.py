"""Pydantic schemas for asset management."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from src.models.layer3 import PositionStatus
from src.schemas.base import BaseResponse, ListResponse


class ManagedPositionResponse(BaseResponse):
    """Schema for managed position response."""

    id: UUID
    user_id: UUID
    account_id: UUID
    asset_identifier: str
    quantity: Annotated[Decimal, Field(decimal_places=6)]
    cost_basis: Annotated[Decimal, Field(decimal_places=2)]
    acquisition_date: date
    disposal_date: date | None = None
    status: PositionStatus
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    position_metadata: dict | None = None
    created_at: datetime
    updated_at: datetime

    # Denormalized fields from related Account (optional)
    account_name: str | None = None


class ReconcilePositionsResponse(BaseModel):
    """Response for position reconciliation."""

    message: str
    created: int = Field(ge=0)
    updated: int = Field(ge=0)
    disposed: int = Field(ge=0)
    skipped: int = Field(default=0, ge=0)
    skipped_assets: list[str] = Field(default_factory=list)


ManagedPositionListResponse = ListResponse[ManagedPositionResponse]
