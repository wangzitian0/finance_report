"""Pydantic schemas for portfolio management."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, field_validator

from src.extraction import CostBasisMethod, PositionStatus, reject_json_floats
from src.schemas.base import (
    BaseResponse,
    CurrencyCode,
    ListResponse,
    MoneyAmount,
    NonNegativeMoneyAmount,
    Percent,
    Quantity,
    default_dict,
    default_list,
)
from src.schemas.provenance import DataProvenance

NonNegInt = Annotated[int, Field(ge=0)]
OptionalRate = Annotated[Decimal | None, Field(decimal_places=2)]


class HoldingResponse(BaseResponse):
    id: UUID
    user_id: UUID
    account_id: UUID
    asset_identifier: str
    quantity: Quantity
    cost_basis: MoneyAmount
    market_value: MoneyAmount
    unrealized_pnl: MoneyAmount
    unrealized_pnl_percent: Percent
    currency: CurrencyCode
    native_cost_basis: MoneyAmount
    native_currency: CurrencyCode
    acquisition_date: date
    disposal_date: date | None = None
    status: PositionStatus
    cost_basis_method: CostBasisMethod | None = None
    account_name: str | None = None
    asset_type: str | None = None
    sector: str | None = None
    geography: str | None = None
    provenance: DataProvenance | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reporting_currency(self) -> str:
        return self.currency

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reporting_cost_basis(self) -> MoneyAmount:
        return self.cost_basis


class HoldingsListResponse(ListResponse[HoldingResponse]):
    warnings: list[dict[str, str]] = default_list()


class RealizedPnLResponse(BaseModel):
    period_start: date
    period_end: date
    total_realized_pnl: MoneyAmount
    total_realized_pnl_percent: Percent
    positions_count: int
    details: list[dict]


class UnrealizedPnLResponse(BaseModel):
    as_of_date: date
    total_unrealized_pnl: MoneyAmount
    total_unrealized_pnl_percent: Percent
    total_market_value: MoneyAmount
    total_cost_basis: MoneyAmount
    holdings_count: int
    details: list[dict]


class PriceUpdateRequest(BaseModel):
    asset_identifier: Annotated[str, Field(min_length=1, max_length=100)]
    price_date: date
    price: NonNegativeMoneyAmount
    currency: CurrencyCode


class PriceUpdateResponse(BaseModel):
    success: bool
    message: str
    asset_identifier: str
    price_date: date
    price: MoneyAmount
    currency: str
    source: str
    created_at: datetime | None = None


class PriceUpdateBatchResponse(BaseModel):
    updated_count: int
    results: list[PriceUpdateResponse] = default_list()


class CostBasisMethodUpdateResponse(BaseModel):
    updated_count: int
    cost_basis_method: CostBasisMethod


class PortfolioSummaryResponse(BaseModel):
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
    currency: CurrencyCode


class PortfolioSummaryDashboardResponse(PortfolioSummaryResponse):
    realized_pnl_ytd: MoneyAmount
    dividend_income_ytd: MoneyAmount


class InvestmentPerformanceHoldingRow(BaseModel):
    asset_identifier: str
    quantity: Quantity
    cost_basis: MoneyAmount
    market_value: MoneyAmount
    unrealized_pnl: MoneyAmount
    realized_pnl: MoneyAmount
    dividend_income: MoneyAmount
    currency: CurrencyCode


class InvestmentPerformanceMarketValuationSelection(BaseModel):
    asset_identifier: str
    observation_id: UUID
    requested_as_of: date


class InvestmentPerformanceAllocationRow(BaseModel):
    dimension: str
    category: str
    value: MoneyAmount
    percentage: Percent
    count: int


class InvestmentPerformanceDataFreshness(BaseModel):
    latest_price_date: date | None
    market_data_provider: str | None
    stale: bool
    stale_holdings: list[str] = default_list()
    manual_override_basis: str | None = None


class InvestmentPerformanceReportScheduleResponse(BaseModel):
    period_start: date
    period_end: date
    as_of_date: date
    currency: CurrencyCode
    xirr: OptionalRate
    time_weighted_return: OptionalRate
    money_weighted_return: OptionalRate
    realized_pnl: MoneyAmount
    unrealized_pnl: MoneyAmount
    dividend_income: MoneyAmount
    dividend_yield: OptionalRate
    holdings: list[InvestmentPerformanceHoldingRow]
    market_valuation_selections: list[InvestmentPerformanceMarketValuationSelection] = default_list()
    allocation: list[InvestmentPerformanceAllocationRow]
    data_freshness: InvestmentPerformanceDataFreshness
    source_links: list[str]
    notes: list[str]


class DividendEventResponse(BaseModel):
    id: UUID
    ex_date: date
    pay_date: date
    amount: MoneyAmount
    currency: CurrencyCode
    reinvested: bool = False
    journal_entry_id: UUID | None = None


class PerformanceMetricsResponse(BaseModel):
    xirr: OptionalRate = None
    time_weighted_return: OptionalRate = None
    money_weighted_return: OptionalRate = None
    unavailable_reasons: dict[str, str] = default_dict()


class RealizedLotResponse(BaseModel):
    lot_id: UUID
    acquired_date: date | None = None
    sold_date: date
    quantity: Quantity
    basis: MoneyAmount
    proceeds: MoneyAmount
    gain_loss: MoneyAmount
    holding_period: int | None = None
    currency: CurrencyCode


class CostBasisMethodUpdateRequest(BaseModel):
    cost_basis_method: CostBasisMethod


class BrokerageImportRequest(BaseModel):
    payload: dict
    filename: str | None = None
    source_document_id: str | None = None

    @field_validator("payload")
    @classmethod
    def _payload_carries_no_floats(cls, value: dict) -> dict:
        reject_json_floats(value, "payload")
        return value


class BrokerageImportResponse(BaseModel):
    broker: str
    parsed_positions: NonNegInt
    created_atomic_positions: NonNegInt
    existing_atomic_positions: NonNegInt
    reconcile_created: NonNegInt
    reconcile_updated: NonNegInt
    reconcile_disposed: NonNegInt
    skipped: NonNegInt
    account_id: UUID | None = None
