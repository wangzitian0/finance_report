"""Pydantic schemas for asset management."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

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
from src.schemas.provenance import DataProvenance

SourceStr = Annotated[str, Field(min_length=1, max_length=120)]
RecurrenceDays = Annotated[int, Field(ge=1, le=3660)]


class DepreciationResponse(BaseModel):
    position_id: UUID
    asset_identifier: str
    period_depreciation: MoneyAmount
    accumulated_depreciation: MoneyAmount
    book_value: MoneyAmount
    method: str
    useful_life_years: int
    salvage_value: MoneyAmount


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


class ManualValuationSnapshotUpdate(BaseModel):
    component_type: ManualValuationComponentType | None = None
    as_of_date: date | None = None
    value: NonNegativeMoneyAmount | None = None
    currency: CurrencyCode | None = None
    source: SourceStr | None = None
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
