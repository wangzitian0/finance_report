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


class CorrectionLoopReplayResponse(BaseModel):
    """The held-out replay of the live correction corpus (EPIC-018 AC18.14).

    The furnace made observable: how much the recurring-correction priors lower the
    held-out low-confidence proportion. `reduced` is the auditable yes/no of whether
    the loop measurably improved the proportion over this corpus.
    """

    holdout_size: int
    grounded: int
    proportion_before: Decimal
    proportion_after: Decimal
    reduced: bool
