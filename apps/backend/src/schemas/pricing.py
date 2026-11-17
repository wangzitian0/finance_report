"""Pydantic schemas for pricing, market data, and manual valuation endpoints."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from src.audit import DataProvenance
from src.pricing import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
)
from src.schemas.base import (
    BaseResponse,
    CurrencyCode,
    ListResponse,
    MoneyAmount,
    NonNegativeMoneyAmount,
    default_list,
)

SourceStr = Annotated[str, Field(min_length=1, max_length=120)]
RecurrenceDays = Annotated[int, Field(ge=1, le=3660)]


class MarketDataSyncRequest(BaseModel):
    """Market data sync request for scheduler or E2E callers."""

    start_date: date | None = None
    end_date: date | None = None
    pairs: list[str] | None = Field(default=None, description="FX pairs in BASE/QUOTE format")
    symbols: list[str] | None = Field(default=None, description="Stock symbols")


class ProviderDisagreementResponse(BaseModel):
    """Provider disagreement payload."""

    asset: str
    observed_date: date
    primary_source: str
    secondary_source: str
    primary_value: str
    secondary_value: str
    relative_difference: str
    threshold: str


class MarketDataSyncResponse(BaseModel):
    """Scheduler-friendly market data sync counters."""

    kind: str
    requested: int
    inserted: int
    skipped: int
    missing: int
    disagreements: list[ProviderDisagreementResponse]


class MarketDataStatusResponse(BaseModel):
    """Read-only market data freshness status for authenticated users."""

    kind: str
    scope: str
    fresh: bool
    last_success_at: str | None
    last_success_date: str | None
    last_observation_date: str | None


class PriceUpdateRequest(BaseModel):
    asset_identifier: Annotated[str, Field(min_length=1, max_length=100)]
    price_date: date
    price: NonNegativeMoneyAmount
    currency: CurrencyCode


class PriceUpdateBatchRequest(BaseModel):
    updates: list[PriceUpdateRequest]


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


class ManualValuationSnapshotCreate(BaseModel):
    component_type: ManualValuationComponentType
    as_of_date: date
    value: NonNegativeMoneyAmount
    currency: CurrencyCode
    source: SourceStr
    valuation_basis: ManualValuationBasis | None = None
    notes: str | None = None
    liquidity_class: ManualValuationLiquidityClass | None = None
    recurrence_days: RecurrenceDays | None = None
    reminder_date: date | None = None


class ManualValuationSnapshotResponse(BaseResponse):
    id: UUID
    user_id: UUID
    component_type: ManualValuationComponentType
    liquidity_class: ManualValuationLiquidityClass
    as_of_date: date
    value: MoneyAmount
    currency: CurrencyCode
    source: str
    valuation_basis: ManualValuationBasis | None = None
    notes: str | None = None
    recurrence_days: int | None = None
    reminder_date: date | None = None
    provenance: DataProvenance = "manual"
    created_at: datetime
    updated_at: datetime


class ValuationComponentResponse(BaseModel):
    id: UUID
    component_type: ManualValuationComponentType
    liquidity_class: ManualValuationLiquidityClass
    as_of_date: date
    value: MoneyAmount
    currency: CurrencyCode
    source: str
    provenance: DataProvenance = "manual"


class ValuationComponentsResponse(BaseModel):
    items: list[ValuationComponentResponse]
    total_assets: MoneyAmount
    total_liabilities: MoneyAmount
    net_worth_delta: MoneyAmount
    warnings: list[dict[str, str]] = default_list()


ManualValuationSnapshotListResponse = ListResponse[ManualValuationSnapshotResponse]
