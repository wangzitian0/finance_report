"""Asset Management Service."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy.orm import selectinload\nfrom sqlalchemy.orm import selectinload
from sqlalchemy.orm import selectinload

from src.logger import get_logger
from src.models.account import Account, AccountType
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus

logger = get_logger(__name__)


class AssetServiceError(Exception):
    """Base exception for asset service errors."""

    pass


@dataclass
class ReconcileResult:
    """Result of position reconciliation."""

    created: int = 0
    updated: int = 0
    disposed: int = 0
    skipped: int = 0
    skipped_assets: list[str] = field(default_factory=list)


@dataclass
class DepreciationResult:
    """Result of depreciation calculation."""

    position_id: UUID
    asset_identifier: str
    period_depreciation: Decimal
    accumulated_depreciation: Decimal
    book_value: Decimal
    method: str
    useful_life_years: int
    salvage_value: Decimal


class AssetService:
    """Service for managing asset positions."""

    async def get_position(
        self,
        db: AsyncSession,
        user_id: UUID,
        position_id: UUID,
    ) -> ManagedPosition | None:
        """Get a single managed position by ID."""
        query = (
            select(ManagedPosition)
            .where(ManagedPosition.id == position_id)
            .where(ManagedPosition.user_id == user_id)
            .options(selectinload(ManagedPosition.account))
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def get_positions(
        self,
        db: AsyncSession,
        user_id: UUID,
        status_filter: PositionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Sequence[ManagedPosition], int]:
        """Get managed positions for a user with optional filtering and pagination."""
        query = (
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .options(selectinload(ManagedPosition.account))
            .order_by(ManagedPosition.asset_identifier)
        )

        if status_filter:
            query = query.where(ManagedPosition.status == status_filter)

        # Get total count
        count_query = select(func.count()).select_from(ManagedPosition).where(ManagedPosition.user_id == user_id)
        if status_filter:
            count_query = count_query.where(ManagedPosition.status == status_filter)
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        # Apply pagination
        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        return result.scalars().all(), total

    async def reconcile_positions(self, db: AsyncSession, user_id: UUID) -> ReconcileResult:
        """Reconcile managed positions from latest atomic snapshots.

        Uses a window function to get the latest snapshot per (asset, broker) pair.
        Cost basis uses market_value as proxy (true lot tracking is future work).

        Returns:
            ReconcileResult with counts of created, updated, and disposed positions.

        Raises:
            AssetServiceError: If reconciliation fails.
        """
        result = ReconcileResult()

        latest_subquery = (
            select(
                AtomicPosition.id,
                func.row_number()
                .over(
                    partition_by=[AtomicPosition.asset_identifier, AtomicPosition.broker],
                    order_by=AtomicPosition.snapshot_date.desc(),
                )
                .label("rn"),
            )
            .where(AtomicPosition.user_id == user_id)
            .subquery()
        )

        query = (
            select(AtomicPosition)
            .join(latest_subquery, AtomicPosition.id == latest_subquery.c.id)
            .where(latest_subquery.c.rn == 1)
        )

        db_result = await db.execute(query)
        latest_snapshots = db_result.scalars().all()

        for snap in latest_snapshots:
            # Validate snapshot data - defensive check against corrupted/legacy data
            if snap.quantity is None or snap.market_value is None:
                logger.warning(
                    "Skipping snapshot with null data - potential data integrity issue",
                    snapshot_id=str(snap.id),
                    asset=snap.asset_identifier,
                    quantity_null=snap.quantity is None,
                    market_value_null=snap.market_value is None,
                )
                result.skipped += 1
                result.skipped_assets.append(snap.asset_identifier)
                continue

            # Handle negative quantities (short positions) - treat as regular positions
            quantity = snap.quantity

            broker_name = snap.broker or "Unknown Broker"
            if not snap.broker:
                logger.warning(
                    "Snapshot missing broker - using fallback",
                    snapshot_id=str(snap.id),
                    asset=snap.asset_identifier,
                )

            account = await self._get_or_create_broker_account(db, user_id, broker_name)

            pos_query = (
                select(ManagedPosition)
                .where(ManagedPosition.user_id == user_id)
                .where(ManagedPosition.account_id == account.id)
                .where(ManagedPosition.asset_identifier == snap.asset_identifier)
            )
            pos_res = await db.execute(pos_query)
            position = pos_res.scalar_one_or_none()

            if position:
                quantity_changed = position.quantity != quantity
                if quantity_changed:
                    logger.info(
                        "Updating position quantity",
                        asset=snap.asset_identifier,
                        old_qty=str(position.quantity),
                        new_qty=str(quantity),
                    )
                    position.quantity = quantity
                    position.cost_basis = snap.market_value

                if quantity == Decimal("0"):
                    position.status = PositionStatus.DISPOSED
                    position.disposal_date = snap.snapshot_date
                    result.disposed += 1
                else:
                    position.status = PositionStatus.ACTIVE
                    position.disposal_date = None
                    if quantity_changed:
                        result.updated += 1

            else:
                # Create position for non-zero quantities (positive or negative)
                if quantity != Decimal("0"):
                    logger.info("Creating new managed position", asset=snap.asset_identifier)
                    position = ManagedPosition(
                        user_id=user_id,
                        account_id=account.id,
                        asset_identifier=snap.asset_identifier,
                        quantity=quantity,
                        cost_basis=snap.market_value,
                        acquisition_date=snap.snapshot_date,
                        status=PositionStatus.ACTIVE,
                        currency=snap.currency,
                        position_metadata={"broker": snap.broker},
                    )
                    db.add(position)
                    result.created += 1

        await db.flush()
        logger.info(
            "Reconciliation complete",
            user_id=str(user_id),
            created=result.created,
            updated=result.updated,
            disposed=result.disposed,
            skipped=result.skipped,
        )
        return result

    async def _get_or_create_broker_account(self, db: AsyncSession, user_id: UUID, broker_name: str) -> Account:
        """Find or create an asset account for the broker."""
        query = (
            select(Account)
            .where(Account.user_id == user_id)
            .where(Account.name == broker_name)
            .where(Account.type == AccountType.ASSET)
        )
        res = await db.execute(query)
        account = res.scalar_one_or_none()

        if not account:
            account = Account(
                user_id=user_id,
                name=broker_name,
                type=AccountType.ASSET,
                currency="USD",
                code="AUTO-ASSET",
            )
            db.add(account)
            await db.flush()

        return account

    def calculate_depreciation(
        self,
        position: ManagedPosition,
        method: Literal["straight-line", "declining-balance"],
        useful_life_years: int,
        salvage_value: Decimal,
        as_of_date: date,
    ) -> DepreciationResult:
        """Calculate depreciation for a position.

        Straight-line: (cost - salvage) / useful_life
        Declining-balance: 2 * (1/useful_life) * book_value (double declining)
        """
        if useful_life_years <= 0:
            raise AssetServiceError("Useful life must be positive")

        if position.status == PositionStatus.DISPOSED:
            raise AssetServiceError("Cannot depreciate disposed position")

        cost_basis = position.cost_basis
        acquisition_date = position.acquisition_date

        years_held = (as_of_date - acquisition_date).days / Decimal("365.25")
        years_held = min(years_held, Decimal(useful_life_years))

        if years_held < 0:
            raise AssetServiceError("as_of_date cannot be before acquisition_date")

        depreciable_amount = cost_basis - salvage_value
        if depreciable_amount < 0:
            depreciable_amount = Decimal("0")

        if method == "straight-line":
            annual_depreciation = depreciable_amount / useful_life_years
            accumulated = annual_depreciation * years_held
            period_depreciation = annual_depreciation

        else:  # declining-balance (double declining)
            rate = Decimal("2") / useful_life_years
            accumulated = Decimal("0")
            book_value = cost_basis

            full_years = int(years_held)
            for _ in range(full_years):
                period_dep = book_value * rate
                if book_value - period_dep < salvage_value:
                    period_dep = book_value - salvage_value
                accumulated += period_dep
                book_value -= period_dep
                if book_value <= salvage_value:
                    break

            period_depreciation = book_value * rate if book_value > salvage_value else Decimal("0")

        accumulated = min(accumulated, depreciable_amount)
        book_value = cost_basis - accumulated

        return DepreciationResult(
            position_id=position.id,
            asset_identifier=position.asset_identifier,
            period_depreciation=period_depreciation.quantize(Decimal("0.01")),
            accumulated_depreciation=accumulated.quantize(Decimal("0.01")),
            book_value=book_value.quantize(Decimal("0.01")),
            method=method,
            useful_life_years=useful_life_years,
            salvage_value=salvage_value,
        )

    async def get_depreciation_schedule(
        self,
        db: AsyncSession,
        user_id: UUID,
        position_id: UUID,
        method: Literal["straight-line", "declining-balance"] = "straight-line",
        useful_life_years: int = 5,
        salvage_value: Decimal = Decimal("0"),
        as_of_date: date | None = None,
    ) -> DepreciationResult:
        """Get depreciation schedule for a position."""
        position = await self.get_position(db, user_id, position_id)
        if not position:
            raise AssetServiceError("Position not found")

        return self.calculate_depreciation(
            position=position,
            method=method,
            useful_life_years=useful_life_years,
            salvage_value=salvage_value,
            as_of_date=as_of_date or date.today(),
        )
