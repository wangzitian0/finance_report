"""Managed-position service (split from services/assets.py, #1677/#1610).

Manual asset positions and reconciliation from parsed brokerage facts are
portfolio-owned; the valuation-snapshot half lives in
``src.pricing.extension.valuation``.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Currency, InvalidCurrencyError
from src.audit.money.currency import normalize_currency_code
from src.audit.quantity import Quantity, Unit
from src.extraction.orm.layer2 import AtomicPosition
from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus
from src.ledger import Account, AccountType, account_service
from src.observability import get_logger
from src.platform.base.errors import DomainError
from src.portfolio.orm.portfolio import InvestmentTransaction, InvestmentTransactionType

logger = get_logger(__name__)

ASSET_QUANTITY_UNIT = Unit("units")
_CURRENCY_ALIASES: dict[str, str] = {"CNH": "CNY"}


def _resolve_snapshot_currency(raw_currency: str | None, *, asset_identifier: str) -> Currency:
    """Normalize a snapshot currency (aliasing legacy CNH -> CNY) and validate ISO-4217 (#2661)."""
    if raw_currency is None:
        return Currency("USD")
    normalized = normalize_currency_code(raw_currency)
    canonical = _CURRENCY_ALIASES.get(normalized, normalized)
    try:
        return Currency(canonical)
    except InvalidCurrencyError as exc:
        raise PositionServiceError(
            f"Position {asset_identifier!r} has unsupported currency {raw_currency!r}",
            status_code=422,
        ) from exc


class PositionServiceError(DomainError):
    """Position service failure (was PositionServiceError, #1677)."""


@dataclass
class ReconcileResult:
    """Result of position reconciliation."""

    created: int = 0
    updated: int = 0
    disposed: int = 0
    skipped: int = 0
    skipped_assets: list[str] = field(default_factory=list)


class PositionService:
    """Managed-position operations (was AssetService's position half)."""

    async def get_position(
        self,
        db: AsyncSession,
        user_id: UUID,
        position_id: UUID,
    ) -> ManagedPosition | None:
        """Get a single managed position by ID."""
        query = (
            select(ManagedPosition).where(ManagedPosition.id == position_id).where(ManagedPosition.user_id == user_id)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def reconcile_positions(self, db: AsyncSession, user_id: UUID) -> ReconcileResult:
        """Reconcile managed positions from latest atomic snapshots.

        Uses a window function to get the latest snapshot per (asset, broker) pair.
        A snapshot has a market value and no purchase cost, so this function never
        writes ``cost_basis``. Only a recorded purchase writes it (#2920).

        Returns:
            ReconcileResult with counts of created, updated, and disposed positions.

        Raises:
            PositionServiceError: If reconciliation fails.
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

            snapshot_currency = _resolve_snapshot_currency(snap.currency, asset_identifier=snap.asset_identifier)
            account = await self._get_or_create_broker_account(db, user_id, broker_name, snapshot_currency.code)

            pos_query = (
                select(ManagedPosition)
                .where(ManagedPosition.user_id == user_id)
                .where(ManagedPosition.account_id == account.id)
                .where(ManagedPosition.asset_identifier == snap.asset_identifier)
            )
            pos_res = await db.execute(pos_query)
            position = pos_res.scalar_one_or_none()
            snapshot_quantity = Quantity(quantity, ASSET_QUANTITY_UNIT).quantize()

            if position:
                position.currency = _resolve_snapshot_currency(
                    position.currency, asset_identifier=position.asset_identifier
                ).code
                quantity_changed = position.quantity != quantity
                snapshot_date = snap.snapshot_date.isoformat()
                snapshot_changed = (position.position_metadata or {}).get(
                    "latest_snapshot_date"
                ) != snapshot_date or position.currency != snapshot_currency.code
                snapshot_currency_changed = position.currency != snapshot_currency.code
                if quantity_changed or snapshot_changed:
                    logger.info(
                        "Updating managed position from latest atomic snapshot",
                        asset=snap.asset_identifier,
                        old_qty=str(position.quantity),
                        new_qty=str(quantity),
                    )
                    position.quantity = quantity
                    if snapshot_currency_changed:
                        position.cost_basis = None
                    position.currency = snapshot_currency.code
                    position.position_metadata = {
                        **(position.position_metadata or {}),
                        "broker": snap.broker,
                        "latest_snapshot_date": snapshot_date,
                    }

                if snapshot_quantity.is_zero():
                    position.status = PositionStatus.DISPOSED
                    position.disposal_date = snap.snapshot_date
                    result.disposed += 1
                else:
                    position.status = PositionStatus.ACTIVE
                    position.disposal_date = None
                    if quantity_changed or snapshot_changed:
                        result.updated += 1

            else:
                # Create position for non-zero quantities (positive or negative)
                if not snapshot_quantity.is_zero():
                    logger.info("Creating new managed position", asset=snap.asset_identifier)
                    position = ManagedPosition(
                        user_id=user_id,
                        account_id=account.id,
                        asset_identifier=snap.asset_identifier,
                        quantity=quantity,
                        cost_basis=None,
                        acquisition_date=snap.snapshot_date,
                        status=PositionStatus.ACTIVE,
                        currency=snapshot_currency.code,
                        position_metadata={
                            "broker": snap.broker,
                            "latest_snapshot_date": snap.snapshot_date.isoformat(),
                        },
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

    async def _get_or_create_broker_account(
        self, db: AsyncSession, user_id: UUID, broker_name: str, currency: str | None = None
    ) -> Account:
        """Find or create an asset account for the broker.

        A newly created account adopts the currency of the holding that triggered
        it (``currency``) rather than a hardcoded ``USD`` — a Hong Kong (HKD) or
        Singapore (SGD) brokerage must not be stamped as a USD account. Existing
        accounts keep their currency; ``USD`` remains the fallback when no
        snapshot currency is available.
        """

        async def _find_broker_account(session: AsyncSession) -> Account | None:
            query = (
                select(Account)
                .where(Account.user_id == user_id)
                .where(Account.name == broker_name)
                .where(Account.type == AccountType.ASSET)
                .where(Account.is_active.is_(True))
                .order_by(Account.created_at, Account.id)
                .limit(1)
            )
            res = await session.execute(query)
            return res.scalar_one_or_none()

        return await account_service.find_or_create_account(
            db,
            user_id=user_id,
            find=_find_broker_account,
            build=lambda: Account(
                user_id=user_id,
                name=broker_name,
                type=AccountType.ASSET,
                currency=normalize_currency_code(currency) or "USD",
                code="AUTO-ASSET",
            ),
        )

    async def list_realized_lots(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        ticker: str,
        limit: int,
        offset: int,
    ) -> Sequence[tuple[InvestmentTransaction, ManagedPosition | None]]:
        """List SELL lot transactions paired with their originating managed position."""
        result = await db.execute(
            select(InvestmentTransaction, ManagedPosition)
            .outerjoin(ManagedPosition, InvestmentTransaction.position_id == ManagedPosition.id)
            .where(
                InvestmentTransaction.user_id == user_id,
                InvestmentTransaction.transaction_type == InvestmentTransactionType.SELL,
                InvestmentTransaction.asset_identifier == ticker,
            )
            .order_by(InvestmentTransaction.transaction_date.desc(), InvestmentTransaction.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [(txn, pos) for txn, pos in result.all()]

    async def update_cost_basis_method(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        ticker: str,
        cost_basis_method: CostBasisMethod,
    ) -> int:
        """Update cost_basis_method for all active managed positions matching a ticker."""
        positions = list(
            (
                await db.execute(
                    select(ManagedPosition).where(
                        ManagedPosition.user_id == user_id,
                        ManagedPosition.asset_identifier == ticker,
                        ManagedPosition.status == PositionStatus.ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        )
        for position in positions:
            position.cost_basis_method = cost_basis_method
        return len(positions)
