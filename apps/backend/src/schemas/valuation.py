"""Pydantic schemas for valuation snapshots."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from src.models.valuation import (
    ValuationComponentType,
    ValuationConfidence,
    ValuationSide,
    ValuationSource,
)
from src.schemas.base import BaseResponse, ListResponse


class ValuationSnapshotCreate(BaseModel):
    """Request body for creating a valuation snapshot."""

    component_type: ValuationComponentType
    component_name: Annotated[str, Field(min_length=1, max_length=120)]
    side: ValuationSide
    value: Annotated[Decimal, Field(decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    as_of_date: date
    source: ValuationSource = ValuationSource.MANUAL
    confidence: ValuationConfidence = ValuationConfidence.TRUSTED
    stale_after_days: Annotated[int, Field(ge=0, le=3650)] = 30
    include_in_total_net_worth: bool = True
    include_in_liquid_net_worth: bool = False
    restricted_until: date | None = None
    notes: Annotated[str | None, Field(max_length=2000)] = None
    snapshot_metadata: dict | None = None


class ValuationSnapshotResponse(BaseResponse):
    """Response schema for a valuation snapshot."""

    id: UUID
    user_id: UUID
    component_type: ValuationComponentType
    component_name: str
    side: ValuationSide
    value: Annotated[Decimal, Field(decimal_places=2)]
    currency: str
    as_of_date: date
    source: ValuationSource
    confidence: ValuationConfidence
    stale_after_days: int
    include_in_total_net_worth: bool
    include_in_liquid_net_worth: bool
    restricted_until: date | None = None
    notes: str | None = None
    snapshot_metadata: dict | None = None
    freshness: str
    created_at: datetime
    updated_at: datetime


class ValuationComponentResponse(ValuationSnapshotResponse):
    """Latest valuation snapshot for a logical component."""

    pass


ValuationSnapshotListResponse = ListResponse[ValuationSnapshotResponse]
ValuationComponentListResponse = ListResponse[ValuationComponentResponse]


def derive_freshness(as_of_date: date, stale_after_days: int, reference_date: date) -> str:
    """Derive freshness for a snapshot using date arithmetic."""
    if stale_after_days == 0:
        return "fresh" if as_of_date == reference_date else "stale"
    return "stale" if as_of_date + timedelta(days=stale_after_days) < reference_date else "fresh"
