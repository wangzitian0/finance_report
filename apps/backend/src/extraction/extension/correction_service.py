"""EPIC-018 Phase 2: Correction Service for feedback learning loop."""

import time
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.correction import CorrectionLog
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Account
from src.observability import get_logger

logger = get_logger(__name__)

# Simple in-memory cache for few-shot examples per user
_correction_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour


def _cache_key(user_id: UUID) -> str:
    return f"corrections:{user_id}"


def invalidate_correction_cache(user_id: UUID) -> None:
    """Invalidate the correction cache for a user."""
    key = _cache_key(user_id)
    _correction_cache.pop(key, None)


def clear_all_correction_cache() -> None:
    """Clear all correction caches (for testing)."""
    _correction_cache.clear()


async def record_correction(
    db: AsyncSession,
    *,
    user_id: UUID,
    transaction_id: UUID,
    corrected_category: str,
    corrected_account_id: UUID | None = None,
) -> CorrectionLog:
    """Record a user correction to a transaction category.

    Categories are no longer pre-suggested at extraction time, so
    ``original_category`` is left unset and only the user-corrected
    category is recorded.
    """
    # Fetch the atomic transaction with ownership verification
    result = await db.execute(
        select(AtomicTransaction)
        .where(AtomicTransaction.id == transaction_id)
        .where(AtomicTransaction.user_id == user_id)
    )
    txn = result.scalar_one_or_none()
    if not txn:
        raise ValueError(f"Transaction {transaction_id} not found")

    if corrected_account_id is not None:
        account_result = await db.execute(
            select(Account.id).where(Account.id == corrected_account_id).where(Account.user_id == user_id)
        )
        if account_result.scalar_one_or_none() is None:
            raise ValueError(f"Account {corrected_account_id} not found")

    correction = CorrectionLog(
        user_id=user_id,
        transaction_id=transaction_id,
        original_category=None,
        corrected_category=corrected_category,
        corrected_account_id=corrected_account_id,
        transaction_description=txn.description,
    )
    db.add(correction)
    await db.flush()

    # Invalidate cache for this user
    invalidate_correction_cache(user_id)

    logger.info(
        "Correction recorded",
        user_id=str(user_id),
        transaction_id=str(transaction_id),
        corrected=corrected_category,
    )

    return correction


async def get_correction_stats(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> dict:
    """Get correction statistics for a user.

    Returns top corrected categories, accuracy rate, and total corrections.
    """
    # Total corrections
    total_result = await db.execute(select(func.count(CorrectionLog.id)).where(CorrectionLog.user_id == user_id))
    total = total_result.scalar() or 0

    if total == 0:
        return {
            "total_corrections": 0,
            "top_corrections": [],
            "correction_rate_by_category": {},
        }

    # Top corrected patterns (original → corrected)
    pattern_query = (
        select(
            CorrectionLog.original_category,
            CorrectionLog.corrected_category,
            func.count(CorrectionLog.id).label("count"),
        )
        .where(CorrectionLog.user_id == user_id)
        .group_by(CorrectionLog.original_category, CorrectionLog.corrected_category)
        .order_by(func.count(CorrectionLog.id).desc())
        .limit(20)
    )
    pattern_result = await db.execute(pattern_query)
    patterns = pattern_result.all()

    top_corrections = [
        {
            "original_category": row.original_category,
            "corrected_category": row.corrected_category,
            "count": row.count,
        }
        for row in patterns
    ]

    # Correction rate by original category: how many times each category was corrected
    category_totals: dict[str, int] = {}
    for row in patterns:
        cat = row.original_category or "None"
        category_totals[cat] = category_totals.get(cat, 0) + row.count

    correction_rate_by_category = {cat: round(count / total * 100, 1) for cat, count in category_totals.items()}

    return {
        "total_corrections": total,
        "top_corrections": top_corrections,
        "correction_rate_by_category": correction_rate_by_category,
    }


async def get_few_shot_examples(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 10,
) -> list[dict]:
    """Get few-shot correction examples for prompt injection.

    Returns the most common correction patterns formatted for the AI prompt.
    Uses a per-user cache with 1-hour TTL.
    """
    key = _cache_key(user_id)

    # Check cache
    if key in _correction_cache:
        cached_time, cached_examples = _correction_cache[key]
        if time.time() - cached_time < _CACHE_TTL_SECONDS:
            return cached_examples

    # Query recent corrections grouped by pattern
    query = (
        select(
            CorrectionLog.original_category,
            CorrectionLog.corrected_category,
            CorrectionLog.transaction_description,
            func.count(CorrectionLog.id).label("count"),
        )
        .where(CorrectionLog.user_id == user_id)
        .group_by(
            CorrectionLog.original_category,
            CorrectionLog.corrected_category,
            CorrectionLog.transaction_description,
        )
        .order_by(func.count(CorrectionLog.id).desc())
        .limit(50)
    )
    result = await db.execute(query)
    rows = result.all()

    if not rows:
        _correction_cache[key] = (time.time(), [])
        return []

    # Deduplicate by correction pattern, keep most common examples
    seen_patterns: set[tuple[str | None, str]] = set()
    examples: list[dict] = []

    for row in rows:
        pattern = (row.original_category, row.corrected_category)
        if pattern in seen_patterns:
            continue
        seen_patterns.add(pattern)

        example = {
            "description": row.transaction_description or "",
            "original_category": row.original_category or "Other",
            "corrected_category": row.corrected_category,
        }
        examples.append(example)
        if len(examples) >= limit:
            break

    # Cache the result
    _correction_cache[key] = (time.time(), examples)

    return examples
