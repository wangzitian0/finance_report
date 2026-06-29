"""Pydantic schemas for asset management."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, field_validator

from src.models.layer3 import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    PositionStatus,
)
from src.schemas.base import BaseResponse, ListResponse, MoneyAmount, NonNegativeMoneyAmount, Quantity
from src.schemas.provenance import DataProvenance


class ManagedPositionResponse(BaseResponse):
    """Schema for managed position response."""

    id: UUID
    user_id: UUID
    account_id: UUID
    asset_identifier: str
    quantity: Quantity
    cost_basis: MoneyAmount
    acquisition_date: date
    disposal_date: date | None = None
    status: PositionStatus
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    position_metadata: dict | None = None
    created_at: datetime
    updated_at: datetime

    # #1098: expose the base/reporting-currency view alongside the native one so
    # /assets/positions reconciles with /portfolio/holdings (which returns base).
    # Both are derived from the single convert_money authority, converted once.
    # Null when no FX rate is available — an FX failure must never 500 a read
    # (the #1388 lesson), so the reporting view degrades to null instead.
    reporting_cost_basis: MoneyAmount | None = None
    reporting_currency: Annotated[str, Field(min_length=3, max_length=3)] | None = None

    # Denormalized fields from related Account (optional)
    account_name: str | None = None

    # #1482: the bare `currency`/`cost_basis` are this endpoint's NATIVE view,
    # but /portfolio/holdings uses the same names for its REPORTING view — so a
    # client reading `currency` gets a different meaning per endpoint. Expose the
    # native view under the same explicit names both endpoints share
    # (`native_currency`/`native_cost_basis`), so clients never depend on the
    # endpoint-local meaning of the bare field. Pure aliases of the native fields.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def native_currency(self) -> str:
        """Explicit native-currency alias of `currency` (identical across endpoints)."""
        return self.currency

    @computed_field  # type: ignore[prop-decorator]
    @property
    def native_cost_basis(self) -> MoneyAmount:
        """Explicit native cost-basis alias of `cost_basis`."""
        return self.cost_basis


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
    period_depreciation: MoneyAmount
    accumulated_depreciation: MoneyAmount
    book_value: MoneyAmount
    method: str
    useful_life_years: int
    salvage_value: MoneyAmount


class ManualValuationSnapshotCreate(BaseModel):
    """Payload for creating a manual valuation snapshot."""

    component_type: ManualValuationComponentType
    as_of_date: date
    value: NonNegativeMoneyAmount
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    source: Annotated[str, Field(min_length=1, max_length=120)]
    valuation_basis: ManualValuationBasis | None = None
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
    value: NonNegativeMoneyAmount | None = None
    currency: Annotated[str, Field(min_length=3, max_length=3)] | None = None
    source: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    valuation_basis: ManualValuationBasis | None = None
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
    value: MoneyAmount
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    source: str
    valuation_basis: ManualValuationBasis | None = None
    notes: str | None = None
    recurrence_days: int | None = None
    reminder_date: date | None = None
    provenance: DataProvenance = "manual"
    created_at: datetime
    updated_at: datetime


class ValuationComponentResponse(BaseModel):
    """Latest manual valuation component included in net worth views."""

    id: UUID
    component_type: ManualValuationComponentType
    liquidity_class: ManualValuationLiquidityClass
    as_of_date: date
    value: MoneyAmount
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    source: str
    provenance: DataProvenance = "manual"


class ValuationComponentsResponse(BaseModel):
    """Aggregated latest manual valuation components."""

    items: list[ValuationComponentResponse]
    total_assets: MoneyAmount
    total_liabilities: MoneyAmount
    net_worth_delta: MoneyAmount


class RestrictedHoldingResponse(BaseModel):
    """Restricted equity or locked holding surfaced for dashboard visibility."""

    ticker: str
    quantity: Quantity
    vesting_schedule: str | None = None
    unlock_date: date | None = None
    fair_value: MoneyAmount
    currency: Annotated[str, Field(min_length=3, max_length=3)]


ManagedPositionListResponse = ListResponse[ManagedPositionResponse]
ManualValuationSnapshotListResponse = ListResponse[ManualValuationSnapshotResponse]
