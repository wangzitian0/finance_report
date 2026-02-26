"""Pydantic schemas for portfolio management."""

from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from src.models.layer3 import CostBasisMethod, PositionStatus
from src.schemas.base import BaseResponse, ListResponse


class HoldingResponse(BaseResponse):
    """Schema for portfolio holding summary."""

    id: UUID
    user_id: UUID
    account_id: UUID
    asset_identifier: str
    quantity: Annotated[Decimal, Field(decimal_places=6)]
    cost_basis: Annotated[Decimal, Field(decimal_places=2)]
    market_value: Annotated[Decimal, Field(decimal_places=2)]
    unrealized_pnl: Annotated[Decimal, Field(decimal_places=2)]
    unrealized_pnl_percent: Annotated[Decimal, Field(decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    acquisition_date: date
    disposal_date: date | None = None
    status: PositionStatus
    cost_basis_method: CostBasisMethod | None = None
    # Denormalized fields from related Account (optional)
    account_name: str | None = None
    # Asset classification from AtomicPosition
    asset_type: str | None = None
    sector: str | None = None
    geography: str | None = None


class RealizedPnLResponse(BaseModel):
    """Schema for realized P&L response."""

    period_start: date
    period_end: date
    total_realized_pnl: Annotated[Decimal, Field(decimal_places=2)]
    total_realized_pnl_percent: Annotated[Decimal, Field(decimal_places=2)]
    positions_count: int
    details: list[dict]


class UnrealizedPnLResponse(BaseModel):
    """Schema for unrealized P&L response."""

    as_of_date: date
    total_unrealized_pnl: Annotated[Decimal, Field(decimal_places=2)]
    total_unrealized_pnl_percent: Annotated[Decimal, Field(decimal_places=2)]
    total_market_value: Annotated[Decimal, Field(decimal_places=2)]
    total_cost_basis: Annotated[Decimal, Field(decimal_places=2)]
    holdings_count: int
    details: list[dict]


class PriceUpdateRequest(BaseModel):
    """Schema for manual price update request."""

    asset_identifier: Annotated[str, Field(min_length=1, max_length=100)]
    price_date: Annotated[date, Field(description="Date of the price (default: today)")]
    price: Annotated[Decimal, Field(decimal_places=2, ge=0)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]


class PriceUpdateResponse(BaseModel):
    """Schema for price update response."""

    success: bool
    message: str
    asset_identifier: str
    price_date: date
    price: Annotated[Decimal, Field(decimal_places=2)]
    currency: str
    source: str
    created_at: date | None = None


class PortfolioSummaryResponse(BaseModel):
    """Schema for overall portfolio summary."""

    total_market_value: Annotated[Decimal, Field(decimal_places=2)]
    total_cost_basis: Annotated[Decimal, Field(decimal_places=2)]
    total_unrealized_pnl: Annotated[Decimal, Field(decimal_places=2)]
    total_unrealized_pnl_percent: Annotated[Decimal, Field(decimal_places=2)]
    total_realized_pnl: Annotated[Decimal, Field(decimal_places=2)]
    total_realized_pnl_percent: Annotated[Decimal, Field(decimal_places=2)]
    net_pnl: Annotated[Decimal, Field(decimal_places=2)]
    net_pnl_percent: Annotated[Decimal, Field(decimal_places=2)]
    holdings_count: int
    active_positions_count: int
    disposed_positions_count: int
    currency: Annotated[str, Field(min_length=3, max_length=3)]


HoldingListResponse = ListResponse[HoldingResponse]
RealizedPnLListResponse = ListResponse[RealizedPnLResponse]
UnrealizedPnLListResponse = ListResponse[UnrealizedPnLResponse]
