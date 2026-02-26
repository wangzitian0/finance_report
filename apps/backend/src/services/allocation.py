"""Portfolio allocation service - sector, geography, asset class breakdowns."""

from collections import defaultdict
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

logger = get_logger(__name__)


class AllocationBreakdown:
    """Allocation breakdown for a category (sector, geography, or asset class)."""

    def __init__(self, category: str, value: Decimal, percentage: Decimal, count: int):
        """
        Initialize allocation breakdown.

        Args:
            category: Category name (e.g., "Technology", "US", "Stock")
            value: Total value in base currency
            percentage: Percentage of total portfolio
            count: Number of positions in this category
        """
        self.category = category
        self.value = value
        self.percentage = percentage
        self.count = count

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "category": self.category,
            "value": float(self.value),
            "percentage": float(self.percentage),
            "count": self.count,
        }


async def get_sector_allocation(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date | None = None,) -> list[AllocationBreakdown]:
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

    # Get active positions
    query = select(ManagedPosition).where(
        ManagedPosition.user_id == user_id,
        ManagedPosition.status == PositionStatus.ACTIVE,
    )
    result = await db.execute(query)
    positions = result.scalars().all()

    # Aggregate by sector
    sector_values: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    sector_counts: dict[str, int] = defaultdict(int)
    total_value = Decimal("0")

    for pos in positions:
        # Get latest atomic position for market value and sector
        atomic_query = (
            select(AtomicPosition)
            .where(
                AtomicPosition.user_id == user_id,
                AtomicPosition.asset_identifier == pos.asset_identifier,
                AtomicPosition.snapshot_date <= as_of_date,
            )
            .order_by(AtomicPosition.snapshot_date.desc())
            .limit(1)
        )
        atomic_result = await db.execute(atomic_query)
        atomic = atomic_result.scalar_one_or_none()

        if atomic:
            # Convert to base currency
            value_base = await fx.convert_amount(
                db=db,
                amount=atomic.market_value or Decimal("0"),
                from_currency=atomic.currency,
                to_currency=settings.base_currency,
                as_of_date=as_of_date,
            )

            sector = atomic.sector or "Unknown"
            sector_values[sector] += value_base
            sector_counts[sector] += 1
            total_value += value_base

    # Calculate percentages
    breakdowns = []
    for sector, value in sector_values.items():
        percentage = (value / total_value * Decimal("100")) if total_value > 0 else Decimal("0")
        breakdowns.append(
            AllocationBreakdown(
                category=sector,
                value=value,
                percentage=percentage,
                count=sector_counts[sector],
            )
        )

    # Sort by value descending
    breakdowns.sort(key=lambda x: x.value, reverse=True)

    return breakdowns


async def get_geography_allocation(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date | None = None,) -> list[AllocationBreakdown]:
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

    # Get active positions
    query = select(ManagedPosition).where(
        ManagedPosition.user_id == user_id,
        ManagedPosition.status == PositionStatus.ACTIVE,
    )
    result = await db.execute(query)
    positions = result.scalars().all()

    # Aggregate by geography
    geo_values: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    geo_counts: dict[str, int] = defaultdict(int)
    total_value = Decimal("0")

    for pos in positions:
        # Get latest atomic position for market value and geography
        atomic_query = (
            select(AtomicPosition)
            .where(
                AtomicPosition.user_id == user_id,
                AtomicPosition.asset_identifier == pos.asset_identifier,
                AtomicPosition.snapshot_date <= as_of_date,
            )
            .order_by(AtomicPosition.snapshot_date.desc())
            .limit(1)
        )
        atomic_result = await db.execute(atomic_query)
        atomic = atomic_result.scalar_one_or_none()

        if atomic:
            # Convert to base currency
            value_base = await fx.convert_amount(
                db=db,
                amount=atomic.market_value or Decimal("0"),
                from_currency=atomic.currency,
                to_currency=settings.base_currency,
                as_of_date=as_of_date,
            )

            geography = atomic.geography or "Unknown"
            geo_values[geography] += value_base
            geo_counts[geography] += 1
            total_value += value_base

    # Calculate percentages
    breakdowns = []
    for geography, value in geo_values.items():
        percentage = (value / total_value * Decimal("100")) if total_value > 0 else Decimal("0")
        breakdowns.append(
            AllocationBreakdown(
                category=geography,
                value=value,
                percentage=percentage,
                count=geo_counts[geography],
            )
        )

    # Sort by value descending
    breakdowns.sort(key=lambda x: x.value, reverse=True)

    return breakdowns


async def get_asset_class_allocation(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date | None = None,) -> list[AllocationBreakdown]:
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

    # Get active positions
    query = select(ManagedPosition).where(
        ManagedPosition.user_id == user_id,
        ManagedPosition.status == PositionStatus.ACTIVE,
    )
    result = await db.execute(query)
    positions = result.scalars().all()

    # Aggregate by asset class
    asset_values: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    asset_counts: dict[str, int] = defaultdict(int)
    total_value = Decimal("0")

    for pos in positions:
        # Get latest atomic position for market value and asset_type
        atomic_query = (
            select(AtomicPosition)
            .where(
                AtomicPosition.user_id == user_id,
                AtomicPosition.asset_identifier == pos.asset_identifier,
                AtomicPosition.snapshot_date <= as_of_date,
            )
            .order_by(AtomicPosition.snapshot_date.desc())
            .limit(1)
        )
        atomic_result = await db.execute(atomic_query)
        atomic = atomic_result.scalar_one_or_none()

        if atomic:
            # Convert to base currency
            value_base = await fx.convert_amount(
                db=db,
                amount=atomic.market_value or Decimal("0"),
                from_currency=atomic.currency,
                to_currency=settings.base_currency,
                as_of_date=as_of_date,
            )

            # Map enum to readable string
            asset_type = atomic.asset_type.value if atomic.asset_type else "unknown"
            # Capitalize first letter for display
            asset_class = asset_type.replace("_", " ").title()

            asset_values[asset_class] += value_base
            asset_counts[asset_class] += 1
            total_value += value_base

    # Calculate percentages
    breakdowns = []
    for asset_class, value in asset_values.items():
        percentage = (value / total_value * Decimal("100")) if total_value > 0 else Decimal("0")
        breakdowns.append(
            AllocationBreakdown(
                category=asset_class,
                value=value,
                percentage=percentage,
                count=asset_counts[asset_class],
            )
        )

    # Sort by value descending
    breakdowns.sort(key=lambda x: x.value, reverse=True)

    return breakdowns
