"""Portfolio allocation service - sector, geography, asset class breakdowns.

Moved from ``services/allocation.py`` (#1643, standard-preserving move): FX
conversion now goes through ``pricing``'s published ``convert_amount``.
"""

from collections import defaultdict
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.audit.ratio import Ratio
from src.extraction.orm.layer2 import AtomicPosition
from src.extraction.orm.layer3 import ManagedPosition
from src.ledger import Account
from src.observability import get_logger
from src.portfolio.extension.performance import batch_latest_atomic_positions
from src.pricing import convert_amount

# Bound from the bare published root (config publishes no named symbols).
settings = src.config.settings

logger = get_logger(__name__)


class AllocationBreakdown:
    """Allocation breakdown for a category (sector, geography, or asset class)."""

    def __init__(self, category: str, value: Decimal, percentage: Decimal, count: int):
        self.category = category
        self.value = value
        self.percentage = percentage
        self.count = count

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "category": self.category,
            "value": self.value,
            "percentage": self.percentage,
            "count": self.count,
        }


async def _get_active_positions_with_atomics(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date,
) -> list[tuple[AtomicPosition, Decimal]]:
    """
    Fetch positions held as of as_of_date and their latest atomic snapshots in batch.

    Returns list of (AtomicPosition, value_in_base_currency) tuples for positions
    that have atomic data. Point-in-time (#1791 follow-up): as_of_date may be a
    historical date (callers default to today but may pass an explicit one), so
    inclusion is decided by each position's own snapshot quantity on that date,
    not by ManagedPosition.status which reflects today. Positions are keyed by
    (asset_identifier, broker), not asset_identifier alone -- the same ticker
    held at two different brokers must not collapse into one.
    """
    query = (
        select(ManagedPosition.asset_identifier, Account.name)
        .join(Account, ManagedPosition.account_id == Account.id)
        .where(ManagedPosition.user_id == user_id)
    )
    result = await db.execute(query)
    position_keys = result.all()
    asset_ids = [identifier for identifier, _broker in position_keys]

    atomic_map = await batch_latest_atomic_positions(db, user_id, asset_ids, as_of_date)

    enriched = []
    for identifier, broker in position_keys:
        atomic = atomic_map.get((identifier, broker))
        if atomic is None or atomic.quantity == Decimal("0"):
            continue
        value_base = await convert_amount(
            db,
            atomic.market_value or Decimal("0"),
            atomic.currency,
            settings.base_currency,
            as_of_date,
        )
        enriched.append((atomic, value_base))

    return enriched


def _build_allocation(
    enriched: list[tuple],
    key_fn: Callable[[AtomicPosition], str],
) -> list[AllocationBreakdown]:
    """Build allocation breakdowns from enriched position data."""
    category_values: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    category_counts: dict[str, int] = defaultdict(int)
    total_value = Decimal("0")

    for atomic, value_base in enriched:
        category = key_fn(atomic)
        category_values[category] += value_base
        category_counts[category] += 1
        total_value += value_base

    breakdowns = []
    for category, value in category_values.items():
        allocation_ratio = Ratio.fraction_or_zero(value, total_value)
        breakdowns.append(
            AllocationBreakdown(
                category=category,
                value=value,
                percentage=allocation_ratio.to_percent(),
                count=category_counts[category],
            )
        )

    breakdowns.sort(key=lambda x: x.value, reverse=True)
    return breakdowns


async def get_sector_allocation(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date | None = None,
) -> list[AllocationBreakdown]:
    """
    Calculate sector allocation breakdown.

    Args:
        db: Database session
        user_id: User ID
        as_of_date: Calculate as of this date (default: today)

    Returns:
        list[AllocationBreakdown]: Sector breakdown sorted by value (descending)
    """
    if as_of_date is None:
        as_of_date = date.today()

    enriched = await _get_active_positions_with_atomics(db, user_id, as_of_date)
    return _build_allocation(enriched, lambda a: a.sector or "Unknown")


async def get_geography_allocation(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date | None = None,
) -> list[AllocationBreakdown]:
    """
    Calculate geography allocation breakdown.

    Args:
        db: Database session
        user_id: User ID
        as_of_date: Calculate as of this date (default: today)

    Returns:
        list[AllocationBreakdown]: Geography breakdown sorted by value (descending)
    """
    if as_of_date is None:
        as_of_date = date.today()

    enriched = await _get_active_positions_with_atomics(db, user_id, as_of_date)
    return _build_allocation(enriched, lambda a: a.geography or "Unknown")


async def get_asset_class_allocation(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date | None = None,
) -> list[AllocationBreakdown]:
    """
    Calculate asset class allocation breakdown.

    Args:
        db: Database session
        user_id: User ID
        as_of_date: Calculate as of this date (default: today)

    Returns:
        list[AllocationBreakdown]: Asset class breakdown sorted by value (descending)
    """
    if as_of_date is None:
        as_of_date = date.today()

    def _asset_class_key(atomic):
        asset_type = atomic.asset_type
        if not asset_type:
            return "Unknown"
        # Handle both Enum member and string (from tests or DB)
        val = asset_type.value if hasattr(asset_type, "value") else str(asset_type)
        return val.replace("_", " ").title()

    enriched = await _get_active_positions_with_atomics(db, user_id, as_of_date)
    return _build_allocation(enriched, _asset_class_key)
