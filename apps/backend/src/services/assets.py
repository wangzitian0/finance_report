"""Asset Management Service."""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.logger import get_logger
from src.models.account import Account, AccountType
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus

logger = get_logger(__name__)


class AssetService:
    """Service for managing asset positions."""

    async def get_positions(self, db: AsyncSession, user_id: UUID) -> Sequence[ManagedPosition]:
        """Get all active managed positions for a user."""
        query = (
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .where(ManagedPosition.status == PositionStatus.ACTIVE)
            .options(selectinload(ManagedPosition.account))
        )
        result = await db.execute(query)
        return result.scalars().all()

    async def reconcile_positions(self, db: AsyncSession, user_id: UUID) -> None:
        """Reconcile managed positions from latest atomic snapshots.

        This is a simplified reconciliation that trusts the latest snapshot for quantity.
        Cost basis calculation requires transaction history matching (future work).
        """
        query = (
            select(AtomicPosition)
            .where(AtomicPosition.user_id == user_id)
            .order_by(
                AtomicPosition.asset_identifier,
                AtomicPosition.broker,
                AtomicPosition.snapshot_date.desc(),
            )
            .distinct(AtomicPosition.asset_identifier, AtomicPosition.broker)
        )

        result = await db.execute(query)
        latest_snapshots = result.scalars().all()

        for snap in latest_snapshots:
            broker_name = snap.broker or "Unknown Broker"
            account = await self._get_or_create_broker_account(db, user_id, broker_name)

            pos_query = (
                select(ManagedPosition)
                .where(ManagedPosition.account_id == account.id)
                .where(ManagedPosition.asset_identifier == snap.asset_identifier)
            )
            pos_res = await db.execute(pos_query)
            position = pos_res.scalar_one_or_none()

            if position:
                if position.quantity != snap.quantity:
                    logger.info(
                        "Updating position quantity",
                        asset=snap.asset_identifier,
                        old_qty=str(position.quantity),
                        new_qty=str(snap.quantity),
                    )
                    position.quantity = snap.quantity

                if snap.quantity == Decimal("0"):
                    position.status = PositionStatus.DISPOSED
                    position.disposal_date = snap.snapshot_date
                else:
                    position.status = PositionStatus.ACTIVE
                    position.disposal_date = None

            else:
                if snap.quantity > Decimal("0"):
                    logger.info("Creating new managed position", asset=snap.asset_identifier)
                    position = ManagedPosition(
                        user_id=user_id,
                        account_id=account.id,
                        asset_identifier=snap.asset_identifier,
                        quantity=snap.quantity,
                        cost_basis=Decimal("0"),
                        acquisition_date=snap.snapshot_date,
                        status=PositionStatus.ACTIVE,
                        currency=snap.currency,
                        position_metadata={"broker": snap.broker},
                    )
                    db.add(position)

        await db.flush()

    async def _get_or_create_broker_account(
        self, db: AsyncSession, user_id: UUID, broker_name: str
    ) -> Account:
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
