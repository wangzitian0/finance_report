"""North-Star confidence metric: the low-confidence share of posted ledger facts.

Vision North-Star Metric: "the proportion of low-confidence data trends down over
time." The measurable node is the posted/reconciled journal entry — the ledger
fact that backs report numbers — whose confidence tier is derived from its
source_type (see `confidence_tier.derive_confidence_tier`). LOW-tier entries over
total are the metric; recording it over time makes the trend observable
(EPIC-018 AC18.12).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.journal import JournalEntry, JournalEntryStatus
from src.models.metrics import ConfidenceMetricSnapshot
from src.services.confidence_tier import ConfidenceTier, derive_confidence_tier

_PROPORTION_QUANT = Decimal("0.00001")
_TIERS: tuple[ConfidenceTier, ...] = ("TRUSTED", "HIGH", "MEDIUM", "LOW")


@dataclass(frozen=True)
class ConfidenceMetricResult:
    """A computed North-Star point (not yet persisted)."""

    total_count: int
    low_confidence_count: int
    low_confidence_proportion: Decimal
    tier_breakdown: dict[str, int]


class ConfidenceMetricService:
    """Computes and records the North-Star low-confidence proportion."""

    async def compute(self, db: AsyncSession, user_id: UUID) -> ConfidenceMetricResult:
        """Deterministic LOW-tier share over a user's posted/reconciled ledger facts.

        Grouping by source_type (a pure input to tier derivation) keeps this a
        single read with no row-by-row Python tiering.

        Semantics: this is a **cumulative** lifetime ratio over all posted/reconciled
        entries to date — a stock, not a per-period flow. As history grows the ratio
        becomes less sensitive to recent improvements; a trailing-window variant is a
        deliberate future option, not the current contract.
        """
        rows = await db.execute(
            select(JournalEntry.source_type, func.count(JournalEntry.id))
            .where(JournalEntry.user_id == user_id)
            .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
            .group_by(JournalEntry.source_type)
        )
        breakdown: dict[str, int] = {tier: 0 for tier in _TIERS}
        for source_type, count in rows.all():
            breakdown[derive_confidence_tier(source_type)] += int(count)

        total = sum(breakdown.values())
        low = breakdown["LOW"]
        proportion = (Decimal(low) / Decimal(total)).quantize(_PROPORTION_QUANT) if total else Decimal("0")
        return ConfidenceMetricResult(
            total_count=total,
            low_confidence_count=low,
            low_confidence_proportion=proportion,
            tier_breakdown=breakdown,
        )

    async def record_snapshot(self, db: AsyncSession, user_id: UUID) -> ConfidenceMetricSnapshot:
        """Append the current metric as a new (immutable) point in the time series."""
        result = await self.compute(db, user_id)
        snapshot = ConfidenceMetricSnapshot(
            user_id=user_id,
            total_count=result.total_count,
            low_confidence_count=result.low_confidence_count,
            low_confidence_proportion=result.low_confidence_proportion,
            tier_breakdown=result.tier_breakdown,
        )
        db.add(snapshot)
        await db.flush()
        await db.refresh(snapshot)
        return snapshot

    async def list_snapshots(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        limit: int = 100,
    ) -> Sequence[ConfidenceMetricSnapshot]:
        """Return the recorded series, newest first."""
        result = await db.execute(
            select(ConfidenceMetricSnapshot)
            .where(ConfidenceMetricSnapshot.user_id == user_id)
            .order_by(ConfidenceMetricSnapshot.created_at.desc(), ConfidenceMetricSnapshot.id.desc())
            .limit(limit)
        )
        return result.scalars().all()
