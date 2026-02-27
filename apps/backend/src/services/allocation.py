"""Portfolio allocation service - sector, geography, asset class breakdowns."""

from collections import defaultdict
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.logger import get_logger
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus
from src.services import fx
from src.services.performance import batch_latest_atomic_positions

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
    Fetch active positions and their latest atomic snapshots in batch.

    Returns list of (AtomicPosition, value_in_base_currency) tuples for positions
    that have atomic data.
    """
    query = select(ManagedPosition).where(
        ManagedPosition.user_id == user_id,
        ManagedPosition.status == PositionStatus.ACTIVE,
    )
    result = await db.execute(query)
    positions = result.scalars().all()

    asset_ids = [pos.asset_identifier for pos in positions]
    atomic_map = await batch_latest_atomic_positions(db, user_id, asset_ids, as_of_date)

    enriched = []
    for pos in positions:
        atomic = atomic_map.get(pos.asset_identifier)
        if atomic:
            value_base = await fx.convert_amount(
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
        percentage = (value / total_value * Decimal("100")) if total_value > 0 else Decimal("0")
        breakdowns.append(
            AllocationBreakdown(
                category=category,
                value=value,
                percentage=percentage,
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
