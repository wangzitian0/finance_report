"""Reconciliation statistics aggregation (split from reconciliation.py)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logger import get_logger
from src.models import (
    AtomicTransaction,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.ratio import Ratio

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReconciliationStats:
    """Reconciliation statistics dataclass."""

    total_transactions: int
    matched_transactions: int
    unmatched_transactions: int
    pending_review: int
    auto_accepted: int
    match_rate: float
    score_distribution: dict[str, int] | None = None


async def get_reconciliation_stats(
    db: AsyncSession,
    user_id: UUID,
    *,
    include_distribution: bool = False,
) -> ReconciliationStats:
    """Get reconciliation statistics for a user.

    Counts Layer-2 atomic transactions and their reconciliation matches.
    A transaction is "matched" when it has an active (non-superseded)
    accepted/auto-accepted match; "unmatched" otherwise.
    """
    # Total atomic transactions for the user
    total_result = await db.execute(
        select(func.count(AtomicTransaction.id)).where(AtomicTransaction.user_id == user_id)
    )
    total = total_result.scalar_one()

    # Match status counts via ReconciliationMatch joined on atomic_txn_id
    match_base = (
        select(func.count(ReconciliationMatch.id))
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(AtomicTransaction.user_id == user_id)
        .where(ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED)
    )

    # Count DISTINCT atomic transactions that have an accepted/auto-accepted
    # match. A single atomic transaction can carry multiple active accepted
    # matches; counting rows would inflate `matched` and let match_rate exceed
    # 100%.
    matched_result = await db.execute(
        select(func.count(distinct(ReconciliationMatch.atomic_txn_id)))
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(AtomicTransaction.user_id == user_id)
        .where(ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED)
        .where(
            ReconciliationMatch.status.in_(
                [
                    ReconciliationStatus.ACCEPTED,
                    ReconciliationStatus.AUTO_ACCEPTED,
                ]
            )
        )
    )
    pending_result = await db.execute(
        match_base.where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
    )
    auto_result = await db.execute(match_base.where(ReconciliationMatch.status == ReconciliationStatus.AUTO_ACCEPTED))

    matched = matched_result.scalar_one()
    pending = pending_result.scalar_one()
    auto = auto_result.scalar_one()
    unmatched = max(total - matched, 0)

    # Score distribution (optional)
    score_distribution: dict[str, int] | None = None
    if include_distribution:
        score_result = await db.execute(
            select(ReconciliationMatch.match_score)
            .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
            .where(AtomicTransaction.user_id == user_id)
        )
        scores = score_result.scalars().all()
        buckets = {"0-59": 0, "60-79": 0, "80-89": 0, "90-100": 0}
        for score in scores:
            if score < 60:
                buckets["0-59"] += 1
            elif score < 80:
                buckets["60-79"] += 1
            elif score < 90:
                buckets["80-89"] += 1
            else:
                buckets["90-100"] += 1
        score_distribution = buckets

    # Compute match rate with zero-division guard. The API still exposes a JSON
    # number, but the percent boundary is the shared Ratio policy.
    match_rate_ratio = Ratio.fraction(matched, total) if total else Ratio.zero()
    match_rate = float(match_rate_ratio.to_percent())

    return ReconciliationStats(
        total_transactions=total,
        matched_transactions=matched,
        unmatched_transactions=unmatched,
        pending_review=pending,
        auto_accepted=auto,
        match_rate=match_rate,
        score_distribution=score_distribution,
    )
