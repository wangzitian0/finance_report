"""Reconciliation statistics aggregation (split from reconciliation.py)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import any_, bindparam, distinct, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import RECONCILIATION_AUTO_ACCEPT_SCORE, RECONCILIATION_REVIEW_SCORE
from src.audit.ratio import Ratio
from src.extraction import effective_statement_transaction_filter
from src.extraction.orm.layer2 import AtomicTransaction
from src.observability import get_logger
from src.reconciliation.extension.repository import posted_statement_source_ids
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus

logger = get_logger(__name__)

__all__ = [
    "RECONCILIATION_AUTO_ACCEPT_SCORE",
    "RECONCILIATION_REVIEW_SCORE",
    "ReconciliationStats",
    "get_reconciliation_stats",
    "posted_statement_source_ids",
]


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
    # The effective transactions of the user. The membership filter is costly, so it runs once.
    # Each later statement names these ids. A statement on ``reconciliation_matches`` then reads
    # the matches of these transactions through the ``atomic_txn_id`` index. A match has no
    # ``user_id``: a join without the ids lets the planner scan the matches of all users (#2617).
    effective_filter = effective_statement_transaction_filter(user_id)
    effective_ids = list((await db.execute(select(AtomicTransaction.id).where(effective_filter))).scalars())
    total = len(effective_ids)
    effective_ids_array = bindparam("effective_ids", effective_ids, type_=ARRAY(PGUUID(as_uuid=True)), unique=True)
    is_effective = AtomicTransaction.id == any_(effective_ids_array)
    match_is_effective = ReconciliationMatch.atomic_txn_id == any_(effective_ids_array)

    # Match status counts over the matches of the effective transactions
    match_base = (
        select(func.count(ReconciliationMatch.id))
        .where(match_is_effective)
        .where(ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED)
        .where(ReconciliationMatch.superseded_by_id.is_(None))
    )

    # Count DISTINCT atomic transactions that are reconciled: they carry an
    # accepted/auto-accepted match, or the system posted them from their own
    # statement (#2465). Counting distinct ids keeps match_rate at most 100%.
    accepted_match_ids = (
        select(ReconciliationMatch.atomic_txn_id)
        .where(match_is_effective)
        .where(ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED)
        .where(ReconciliationMatch.superseded_by_id.is_(None))
        .where(
            ReconciliationMatch.status.in_(
                [
                    ReconciliationStatus.ACCEPTED,
                    ReconciliationStatus.AUTO_ACCEPTED,
                ]
            )
        )
    )
    posted_source_ids = posted_statement_source_ids(user_id)
    matched_result = await db.execute(
        select(func.count(distinct(AtomicTransaction.id)))
        .where(is_effective)
        .where(
            or_(
                AtomicTransaction.id.in_(accepted_match_ids),
                AtomicTransaction.id.in_(posted_source_ids),
            )
        )
    )
    pending_result = await db.execute(
        select(func.count(distinct(ReconciliationMatch.atomic_txn_id)))
        .where(match_is_effective)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        .where(ReconciliationMatch.superseded_by_id.is_(None))
        .where(ReconciliationMatch.atomic_txn_id.notin_(accepted_match_ids))
        .where(ReconciliationMatch.atomic_txn_id.notin_(posted_source_ids))
    )
    auto_result = await db.execute(match_base.where(ReconciliationMatch.status == ReconciliationStatus.AUTO_ACCEPTED))

    matched = matched_result.scalar_one()
    pending = pending_result.scalar_one()
    auto = auto_result.scalar_one()
    unmatched = max(total - matched - pending, 0)

    # Score distribution (optional)
    score_distribution: dict[str, int] | None = None
    if include_distribution:
        score_result = await db.execute(
            select(ReconciliationMatch.match_score)
            .where(match_is_effective)
            .where(ReconciliationMatch.status.notin_((ReconciliationStatus.REJECTED, ReconciliationStatus.SUPERSEDED)))
            .where(ReconciliationMatch.superseded_by_id.is_(None))
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
    match_rate_ratio = Ratio.fraction_or_zero(matched, total)
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
