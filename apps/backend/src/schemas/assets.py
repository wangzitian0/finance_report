"""Pydantic schemas for asset management."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from src.models.layer3 import ManualValuationComponentType, ManualValuationLiquidityClass, PositionStatus
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


class DepreciationResponse(BaseModel):
    """Response for depreciation calculation."""

    position_id: UUID
    asset_identifier: str
    period_depreciation: Annotated[Decimal, Field(decimal_places=2)]
    accumulated_depreciation: Annotated[Decimal, Field(decimal_places=2)]
    book_value: Annotated[Decimal, Field(decimal_places=2)]
    method: str
    useful_life_years: int
    salvage_value: Annotated[Decimal, Field(decimal_places=2)]


class ManualValuationSnapshotCreate(BaseModel):
    """Payload for creating a manual valuation snapshot."""

    component_type: ManualValuationComponentType
    as_of_date: date
    value: Annotated[Decimal, Field(decimal_places=2, ge=Decimal("0"))]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    source: Annotated[str, Field(min_length=1, max_length=120)]
    notes: str | None = None
    liquidity_class: ManualValuationLiquidityClass | None = None
    recurrence_days: Annotated[int, Field(ge=1, le=3660)] | None = None
    reminder_date: date | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class ManualValuationSnapshotUpdate(BaseModel):
    """Payload for updating a manual valuation snapshot."""

    component_type: ManualValuationComponentType | None = None
    as_of_date: date | None = None
    value: Annotated[Decimal, Field(decimal_places=2, ge=Decimal("0"))] | None = None
    currency: Annotated[str, Field(min_length=3, max_length=3)] | None = None
    source: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    notes: str | None = None
    liquidity_class: ManualValuationLiquidityClass | None = None
    recurrence_days: Annotated[int, Field(ge=1, le=3660)] | None = None
    reminder_date: date | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class ManualValuationSnapshotResponse(BaseResponse):
    """Response for manual valuation snapshots."""

    id: UUID
    user_id: UUID
    component_type: ManualValuationComponentType
    liquidity_class: ManualValuationLiquidityClass
    as_of_date: date
    value: Annotated[Decimal, Field(decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    source: str
    notes: str | None = None
    recurrence_days: int | None = None
    reminder_date: date | None = None
    created_at: datetime
    updated_at: datetime


class ValuationComponentResponse(BaseModel):
    """Latest manual valuation component included in net worth views."""

    id: UUID
    component_type: ManualValuationComponentType
    liquidity_class: ManualValuationLiquidityClass
    as_of_date: date
    value: Annotated[Decimal, Field(decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    source: str


class ValuationComponentsResponse(BaseModel):
    """Aggregated latest manual valuation components."""

    items: list[ValuationComponentResponse]
    total_assets: Annotated[Decimal, Field(decimal_places=2)]
    total_liabilities: Annotated[Decimal, Field(decimal_places=2)]
    net_worth_delta: Annotated[Decimal, Field(decimal_places=2)]


class RestrictedHoldingResponse(BaseModel):
    """Restricted equity or locked holding surfaced for dashboard visibility."""

    ticker: str
    quantity: Annotated[Decimal, Field(decimal_places=6)]
    vesting_schedule: str | None = None
    unlock_date: date | None = None
    fair_value: Annotated[Decimal, Field(decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]


ManagedPositionListResponse = ListResponse[ManagedPositionResponse]
ManualValuationSnapshotListResponse = ListResponse[ManualValuationSnapshotResponse]
