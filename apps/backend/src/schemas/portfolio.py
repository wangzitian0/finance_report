"""Pydantic schemas for portfolio management."""

from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from src.audit import DataProvenance
from src.extraction import reject_json_floats
from src.portfolio import CostBasisMethod, PositionStatus
from src.schemas.base import (
    BaseResponse,
    CurrencyCode,
    ListResponse,
    MoneyAmount,
    Percent,
    Quantity,
    default_list,
)

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
    statement_id: UUID | None = None
    payload: dict | None = None
    filename: str | None = None
    source_document_id: str | None = None

    @field_validator("payload")
    @classmethod
    def _payload_carries_no_floats(cls, value: dict | None) -> dict | None:
        if value is not None:
            reject_json_floats(value, "payload")
        return value

    @model_validator(mode="after")
    def _require_statement_or_payload(self) -> "BrokerageImportRequest":
        if (self.statement_id is None) == (self.payload is None):
            raise ValueError("Provide either statement_id or payload, not both")
        return self


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


class AllocationBreakdownResponse(BaseModel):
    category: str
    value: Decimal = Field(decimal_places=2, description="Allocated monetary value for the category.")
    percentage: Decimal = Field(decimal_places=2, description="Share of total portfolio value as a percentage.")
    count: int


class DividendCreateRequest(BaseModel):
    payment_date: date
    amount: Decimal = Field(decimal_places=2, gt=0, description="Gross dividend payout amount.")
    currency: str = Field(min_length=3, max_length=3, description="ISO 4217 dividend currency code.")
    dividend_type: str = "ordinary"
    notes: str | None = None
    cash_account_id: UUID | None = None
    dividend_income_account_id: UUID | None = None
    withholding_tax: Decimal = Field(
        default=Decimal("0.00"),
        decimal_places=2,
        ge=0,
        description="Tax withheld at source in the dividend currency.",
    )
    withholding_tax_account_id: UUID | None = None
