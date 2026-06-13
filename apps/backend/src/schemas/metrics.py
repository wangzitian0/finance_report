"""Schemas for the North-Star confidence metric endpoint (EPIC-018 AC18.12)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ConfidenceMetricPoint(BaseModel):
    """A North-Star measurement: the LOW-tier share of posted ledger facts."""

    total_count: int
    low_confidence_count: int
    low_confidence_proportion: Decimal
    tier_breakdown: dict[str, int]


class ConfidenceMetricSnapshotResponse(ConfidenceMetricPoint):
    """A recorded point in the append-only series."""

    id: UUID
    captured_at: datetime


class ConfidenceNorthStarResponse(BaseModel):
    """The live metric plus its recorded trend (newest first)."""

    current: ConfidenceMetricPoint
    series: list[ConfidenceMetricSnapshotResponse]
