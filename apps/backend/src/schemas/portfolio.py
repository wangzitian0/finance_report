"""Pydantic schemas for portfolio management."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from src.models.layer3 import CostBasisMethod, PositionStatus
from src.schemas.base import BaseResponse, ListResponse, MoneyAmount, NonNegativeMoneyAmount, Percent, Quantity
from src.schemas.provenance import DataProvenance


class HoldingResponse(BaseResponse):
    """Schema for portfolio holding summary."""

    id: UUID
    user_id: UUID
    account_id: UUID
    asset_identifier: str
    quantity: Quantity
    cost_basis: MoneyAmount
    market_value: MoneyAmount
    unrealized_pnl: MoneyAmount
    unrealized_pnl_percent: Percent
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    # #1098: pre-conversion native cost basis + currency, so a holding's base view
    # (cost_basis/currency) reconciles with the native view returned by
    # /assets/positions. These are the raw position values before convert_money.
    native_cost_basis: MoneyAmount
    native_currency: Annotated[str, Field(min_length=3, max_length=3)]
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
    # EPIC-022 #868/#888: conservative provenance. "imported" only when the
    # holding's latest snapshot is backed by a concrete source document; None
    # when we cannot prove import (we never infer "manual", to honour the rule
    # that manual data must not masquerade as imported — and vice versa).
    provenance: DataProvenance | None = Field(
        default=None,
        description="Normalized source provenance when known; null when not safely derivable.",
    )

    # #1482: the bare `currency`/`cost_basis` are this endpoint's REPORTING view,
    # but /assets/positions uses the same names for its NATIVE view. Expose the
    # reporting view under the same explicit names both endpoints share
    # (`reporting_currency`/`reporting_cost_basis`), so native vs reporting is
    # identically named everywhere and clients never depend on the endpoint-local
    # meaning of the bare field. Pure aliases of the reporting fields.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def reporting_currency(self) -> str:
        """Explicit reporting-currency alias of `currency` (identical across endpoints)."""
        return self.currency

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reporting_cost_basis(self) -> MoneyAmount:
        """Explicit reporting cost-basis alias of `cost_basis`."""
        return self.cost_basis


class HoldingsListResponse(ListResponse[HoldingResponse]):
    """Holdings page in the repo-standard items+total wrapper (#1796).

    ``warnings`` discloses point-in-time snapshots excluded from the page (e.g.
    no reconciled managed position as of the requested date) — previously only
    logged, so the response silently read as complete.
    """

    warnings: list[dict[str, str]] = Field(
        default_factory=list,
        description=(
            "Point-in-time snapshots excluded from the page (e.g. no reconciled "
            "managed position as of the requested date) — disclosed instead of "
            "silently omitted (#1796)."
        ),
    )


class RealizedPnLResponse(BaseModel):
    """Schema for realized P&L response."""

    period_start: date
    period_end: date
    total_realized_pnl: MoneyAmount
    total_realized_pnl_percent: Percent
    positions_count: int
    details: list[dict]


class UnrealizedPnLResponse(BaseModel):
    """Schema for unrealized P&L response."""

    as_of_date: date
    total_unrealized_pnl: MoneyAmount
    total_unrealized_pnl_percent: Percent
    total_market_value: MoneyAmount
    total_cost_basis: MoneyAmount
    holdings_count: int
    details: list[dict]


class PriceUpdateRequest(BaseModel):
    """Schema for manual price update request."""

    asset_identifier: Annotated[str, Field(min_length=1, max_length=100)]
    price_date: Annotated[date, Field(description="Date of the price (default: today)")]
    price: NonNegativeMoneyAmount
    currency: Annotated[str, Field(min_length=3, max_length=3)]


class PriceUpdateResponse(BaseModel):
    """Schema for price update response."""

    success: bool
    message: str
    asset_identifier: str
    price_date: date
    price: MoneyAmount
    currency: str
    source: str
    created_at: datetime | None = None


class PriceUpdateBatchResponse(BaseModel):
    """Typed response for ``POST /portfolio/prices/update`` (#1008).

    Replaces a raw ``dict`` return so the batch result is declared in OpenAPI and
    consumable by the generated frontend client.
    """

    updated_count: int = Field(..., description="Number of price overrides applied.")
    results: list[PriceUpdateResponse] = Field(default_factory=list)


class CostBasisMethodUpdateResponse(BaseModel):
    """Typed response for ``PATCH /portfolio/{ticker}`` (#1008)."""

    updated_count: int = Field(..., description="Number of active positions updated.")
    cost_basis_method: CostBasisMethod


class PortfolioSummaryResponse(BaseModel):
    """Schema for overall portfolio summary."""

    total_market_value: MoneyAmount
    total_cost_basis: MoneyAmount
    total_unrealized_pnl: MoneyAmount
    total_unrealized_pnl_percent: Percent
    total_realized_pnl: MoneyAmount
    total_realized_pnl_percent: Percent
    net_pnl: MoneyAmount
    net_pnl_percent: Percent
    holdings_count: int
    active_positions_count: int
    disposed_positions_count: int
    currency: Annotated[str, Field(min_length=3, max_length=3)]


class PortfolioSummaryDashboardResponse(PortfolioSummaryResponse):
    """Dashboard portfolio summary including YTD income figures."""

    realized_pnl_ytd: MoneyAmount
    dividend_income_ytd: MoneyAmount


class InvestmentPerformanceHoldingRow(BaseModel):
    """Per-holding row for the investment performance report schedule."""

    asset_identifier: str
    quantity: Quantity
    cost_basis: MoneyAmount
    market_value: MoneyAmount
    unrealized_pnl: MoneyAmount
    realized_pnl: MoneyAmount
    dividend_income: MoneyAmount
    currency: Annotated[str, Field(min_length=3, max_length=3)]


class InvestmentPerformanceAllocationRow(BaseModel):
    """Allocation row for one report-schedule dimension."""

    dimension: str
    category: str
    value: MoneyAmount
    percentage: Percent
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
    realized_pnl: MoneyAmount
    unrealized_pnl: MoneyAmount
    dividend_income: MoneyAmount
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
    amount: MoneyAmount
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    reinvested: bool = False


class RealizedLotResponse(BaseModel):
    """Lot-level realized P&L row for a holding detail page."""

    lot_id: UUID
    acquired_date: date | None = None
    sold_date: date
    quantity: Quantity
    basis: MoneyAmount
    proceeds: MoneyAmount
    gain_loss: MoneyAmount
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
    # #1484: the broker ASSET account these positions reconciled into (null when
    # no single broker account applies, e.g. zero positions or a mixed-broker
    # payload). The statements import handler also uses it to anchor the source
    # statement (statement.account_id); the user-scoped /portfolio import has no
    # statement context and just reports the reconciled account.
    account_id: UUID | None = None


HoldingListResponse = ListResponse[HoldingResponse]
RealizedPnLListResponse = ListResponse[RealizedPnLResponse]
UnrealizedPnLListResponse = ListResponse[UnrealizedPnLResponse]
