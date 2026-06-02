"""Pydantic schemas for portfolio management."""

from datetime import date, datetime
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
    created_at: datetime | None = None


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


class PortfolioSummaryDashboardResponse(PortfolioSummaryResponse):
    """Dashboard portfolio summary including YTD income figures."""

    realized_pnl_ytd: Annotated[Decimal, Field(decimal_places=2)]
    dividend_income_ytd: Annotated[Decimal, Field(decimal_places=2)]


class InvestmentPerformanceHoldingRow(BaseModel):
    """Per-holding row for the investment performance report schedule."""

    asset_identifier: str
    quantity: Annotated[Decimal, Field(decimal_places=6)]
    cost_basis: Annotated[Decimal, Field(decimal_places=2)]
    market_value: Annotated[Decimal, Field(decimal_places=2)]
    unrealized_pnl: Annotated[Decimal, Field(decimal_places=2)]
    realized_pnl: Annotated[Decimal, Field(decimal_places=2)]
    dividend_income: Annotated[Decimal, Field(decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]


class InvestmentPerformanceAllocationRow(BaseModel):
    """Allocation row for one report-schedule dimension."""

    dimension: str
    category: str
    value: Annotated[Decimal, Field(decimal_places=2)]
    percentage: Annotated[Decimal, Field(decimal_places=2)]
    count: int


class InvestmentPerformanceDataFreshness(BaseModel):
    """Market data freshness metadata for the report schedule."""

    latest_price_date: date | None
    market_data_provider: str | None
    stale: bool
    stale_holdings: list[str] = Field(default_factory=list)
    manual_override_basis: str | None = None


class InvestmentPerformanceReportScheduleResponse(BaseModel):
    """Report-ready investment performance schedule consumed by EPIC-005."""

    period_start: date
    period_end: date
    as_of_date: date
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    xirr: Annotated[Decimal | None, Field(decimal_places=2)]
    time_weighted_return: Annotated[Decimal | None, Field(decimal_places=2)]
    money_weighted_return: Annotated[Decimal | None, Field(decimal_places=2)]
    realized_pnl: Annotated[Decimal, Field(decimal_places=2)]
    unrealized_pnl: Annotated[Decimal, Field(decimal_places=2)]
    dividend_income: Annotated[Decimal, Field(decimal_places=2)]
    dividend_yield: Annotated[Decimal | None, Field(decimal_places=2)]
    holdings: list[InvestmentPerformanceHoldingRow]
    allocation: list[InvestmentPerformanceAllocationRow]
    data_freshness: InvestmentPerformanceDataFreshness
    source_links: list[str]
    notes: list[str]


class DividendEventResponse(BaseModel):
    """Dividend event shown on a holding detail page."""

    id: UUID
    ex_date: date
    pay_date: date
    amount: Annotated[Decimal, Field(decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    reinvested: bool = False


class RealizedLotResponse(BaseModel):
    """Lot-level realized P&L row for a holding detail page."""

    lot_id: UUID
    acquired_date: date | None = None
    sold_date: date
    quantity: Annotated[Decimal, Field(decimal_places=6)]
    basis: Annotated[Decimal, Field(decimal_places=2)]
    proceeds: Annotated[Decimal, Field(decimal_places=2)]
    gain_loss: Annotated[Decimal, Field(decimal_places=2)]
    holding_period: int | None = None
    currency: Annotated[str, Field(min_length=3, max_length=3)]


class CostBasisMethodUpdateRequest(BaseModel):
    """Payload for per-holding cost basis method updates."""

    cost_basis_method: CostBasisMethod


class BrokerageImportRequest(BaseModel):
    """Request to import parsed brokerage positions."""

    payload: dict
    filename: str | None = None
    source_document_id: str | None = None


class BrokerageImportResponse(BaseModel):
    """Response for brokerage position import."""

    broker: str
    parsed_positions: int = Field(ge=0)
    created_atomic_positions: int = Field(ge=0)
    existing_atomic_positions: int = Field(ge=0)
    reconcile_created: int = Field(ge=0)
    reconcile_updated: int = Field(ge=0)
    reconcile_disposed: int = Field(ge=0)
    skipped: int = Field(ge=0)


HoldingListResponse = ListResponse[HoldingResponse]
RealizedPnLListResponse = ListResponse[RealizedPnLResponse]
UnrealizedPnLListResponse = ListResponse[UnrealizedPnLResponse]
