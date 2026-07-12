"""Audit-plane metrics: the North-Star confidence measurement series.

Vision names a single North-Star Metric — "the proportion of low-confidence data
trends down over time." `ConfidenceMetricSnapshot` is the append-only series that
makes that trend observable (EPIC-018 AC18.12).
"""

from decimal import Decimal

from sqlalchemy import Index, Integer, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin


class ConfidenceMetricSnapshot(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """A point-in-time capture of a user's low-confidence-data proportion.

    Append-only: each capture is a new row (`created_at` is the series axis);
    snapshots are never edited in place, so the series read newest-first is the
    trend the North-Star review watches.
    """

    __tablename__ = "confidence_metric_snapshots"
    __table_args__ = (Index("ix_confidence_metric_snapshots_user_created", "user_id", "created_at"),)

    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    low_confidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Proportion in [0, 1]; Decimal (never float) so the metric is exact.
    low_confidence_proportion: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    # Full tier histogram, e.g. {"TRUSTED": 1, "HIGH": 1, "MEDIUM": 1, "LOW": 3}.
    tier_breakdown: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, default=dict)
