"""Asset Management Service."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.logger import get_logger
from src.models.account import Account, AccountType
from src.models.layer2 import AtomicPosition
from src.models.layer3 import (
    ManagedPosition,
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
    PositionStatus,
)
from src.money import Money, to_money
from src.money.currency import normalize_currency_code
from src.quantity import Quantity
from src.schemas.provenance import DataProvenance

logger = get_logger(__name__)

ASSET_QUANTITY_UNIT = "units"


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


@dataclass
class ValuationComponentItem:
    """Latest manual valuation component included in net worth views."""

    id: UUID
    component_type: str
    liquidity_class: str
    as_of_date: date
    value: Decimal
    currency: str
    source: str
    provenance: DataProvenance = "manual"


@dataclass
class ValuationComponentsResult:
    """Aggregated latest manual valuation components."""

    items: list[ValuationComponentItem]
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth_delta: Decimal


_DEFAULT_LIQUIDITY_CLASS: dict[ManualValuationComponentType, ManualValuationLiquidityClass] = {
    ManualValuationComponentType.PROPERTY_VALUE: ManualValuationLiquidityClass.ILLIQUID,
    ManualValuationComponentType.MORTGAGE_BALANCE: ManualValuationLiquidityClass.LIABILITY,
    ManualValuationComponentType.CPF_BALANCE: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.RETIREMENT_ACCOUNT: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.SOCIAL_SECURITY_PERSONAL_ACCOUNT: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.LONG_TERM_BENEFIT_ASSET: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.LONG_TERM_SAVINGS: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.TAX_PAYABLE: ManualValuationLiquidityClass.LIABILITY,
    ManualValuationComponentType.TAX_REFUND: ManualValuationLiquidityClass.LIQUID,
    ManualValuationComponentType.INSURANCE_CASH_VALUE: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.ESOP: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.RSU: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.STOCK_OPTIONS: ManualValuationLiquidityClass.RESTRICTED,
    ManualValuationComponentType.OTHER_ASSET: ManualValuationLiquidityClass.LIQUID,
    ManualValuationComponentType.OTHER_LIABILITY: ManualValuationLiquidityClass.LIABILITY,
}


def _valuation_key_query(
    user_id: UUID,
    *,
    component_type: ManualValuationComponentType,
    source: str,
    as_of_date: date,
) -> Select[tuple[ManualValuationSnapshot]]:
    """Base select for a manual-valuation version-chain key.

    Matches the partial unique index identity (user_id, component_type, source,
    as_of_date); callers append head/order/lock clauses.
    """
    return (
        select(ManualValuationSnapshot)
        .where(ManualValuationSnapshot.user_id == user_id)
        .where(ManualValuationSnapshot.component_type == component_type)
        .where(ManualValuationSnapshot.source == source)
        .where(ManualValuationSnapshot.as_of_date == as_of_date)
    )


class AssetService:
    """Service for managing asset positions."""

    async def create_valuation_snapshot(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        component_type: ManualValuationComponentType,
        as_of_date: date,
        value: Decimal,
        currency: str,
        source: str,
        valuation_basis: ManualValuationBasis | None = None,
        notes: str | None = None,
        liquidity_class: ManualValuationLiquidityClass | None = None,
        recurrence_days: int | None = None,
        reminder_date: date | None = None,
    ) -> ManualValuationSnapshot:
        """Record a manual valuation as an append-only versioned fact.

        Vision Axiom A: a recorded fact is never edited in place. If a current
        version already exists for the same (component_type, source, as_of_date),
        this appends a new version and supersedes the prior one instead of
        overwriting it, so the full correction history stays retrievable.
        """
        normalized_currency = currency.upper()
        head = await self._current_valuation_head(
            db,
            user_id,
            component_type=component_type,
            source=source,
            as_of_date=as_of_date,
        )

        snapshot = ManualValuationSnapshot(
            id=uuid4(),
            user_id=user_id,
            component_type=component_type,
            liquidity_class=liquidity_class or _DEFAULT_LIQUIDITY_CLASS[component_type],
            as_of_date=as_of_date,
            value=to_money(value),
            currency=normalized_currency,
            source=source,
            valuation_basis=valuation_basis,
            notes=notes,
            recurrence_days=recurrence_days,
            reminder_date=reminder_date,
            version=(head.version + 1) if head is not None else 1,
            # Park the new row under the prior head so there is never a moment with
            # two current heads for the same key (the partial unique index is
            # checked per statement). Promoted to head below once the prior head
            # has been demoted to point at it.
            superseded_by_id=head.id if head is not None else None,
        )
        db.add(snapshot)
        await db.flush()
        if head is not None:
            # Ordered hand-off, each flush valid under both the self-FK and the
            # partial unique index: demote the old head (0 heads), then promote
            # the new row (1 head).
            head.superseded_by_id = snapshot.id
            await db.flush()
            snapshot.superseded_by_id = None
            await db.flush()
        await db.refresh(snapshot)
        return snapshot

    async def _current_valuation_head(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        component_type: ManualValuationComponentType,
        source: str,
        as_of_date: date,
    ) -> ManualValuationSnapshot | None:
        """Return the current (non-superseded) version for a valuation key, if any.

        The key matches the partial unique index exactly
        (user_id, component_type, source, as_of_date) — currency is a corrigible
        attribute of the fact, not part of its version-chain identity.
        """
        result = await db.execute(
            _valuation_key_query(user_id, component_type=component_type, source=source, as_of_date=as_of_date)
            .where(ManualValuationSnapshot.superseded_by_id.is_(None))
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_valuation_versions(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        component_type: ManualValuationComponentType,
        source: str,
        as_of_date: date,
    ) -> Sequence[ManualValuationSnapshot]:
        """Return the full append-only version history for a valuation key, newest first.

        Keyed by the same identity as the head index
        (user_id, component_type, source, as_of_date), so a correction that also
        changes currency is still part of one history chain.
        """
        result = await db.execute(
            _valuation_key_query(user_id, component_type=component_type, source=source, as_of_date=as_of_date).order_by(
                ManualValuationSnapshot.version.desc()
            )
        )
        return result.scalars().all()

    async def list_valuation_snapshots(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        as_of_date: date | None = None,
        component_type: ManualValuationComponentType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Sequence[ManualValuationSnapshot], int]:
        """List manual valuation snapshots for a user."""
        # Only current heads (superseded_by_id IS NULL); superseded history rows
        # are reachable via list_valuation_versions, not the default listing.
        query = (
            select(ManualValuationSnapshot)
            .where(ManualValuationSnapshot.user_id == user_id)
            .where(ManualValuationSnapshot.superseded_by_id.is_(None))
        )
        count_query = (
            select(func.count())
            .select_from(ManualValuationSnapshot)
            .where(ManualValuationSnapshot.user_id == user_id)
            .where(ManualValuationSnapshot.superseded_by_id.is_(None))
        )
        if as_of_date is not None:
            query = query.where(ManualValuationSnapshot.as_of_date <= as_of_date)
            count_query = count_query.where(ManualValuationSnapshot.as_of_date <= as_of_date)
        if component_type is not None:
            query = query.where(ManualValuationSnapshot.component_type == component_type)
            count_query = count_query.where(ManualValuationSnapshot.component_type == component_type)

        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        result = await db.execute(
            query.order_by(ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total

    async def get_valuation_snapshot(
        self,
        db: AsyncSession,
        user_id: UUID,
        snapshot_id: UUID,
    ) -> ManualValuationSnapshot | None:
        """Get a manual valuation snapshot by id."""
        result = await db.execute(
            select(ManualValuationSnapshot)
            .where(ManualValuationSnapshot.user_id == user_id)
            .where(ManualValuationSnapshot.id == snapshot_id)
        )
        return result.scalar_one_or_none()

    async def update_valuation_snapshot(
        self,
        db: AsyncSession,
        user_id: UUID,
        snapshot_id: UUID,
        *,
        values: dict,
    ) -> ManualValuationSnapshot | None:
        """Update a manual valuation snapshot.

        Superseded versions are frozen history (vision Axiom A): a recorded fact is
        never edited in place. Editing one is rejected; corrections re-submit a new
        version via create_valuation_snapshot.
        """
        snapshot = await self.get_valuation_snapshot(db, user_id, snapshot_id)
        if not snapshot:
            return None
        if snapshot.superseded_by_id is not None:
            raise AssetServiceError("Cannot edit a superseded valuation version; submit a correction instead")

        if "component_type" in values and values["component_type"] is not None:
            snapshot.component_type = values["component_type"]
            if values.get("liquidity_class") is None:
                snapshot.liquidity_class = _DEFAULT_LIQUIDITY_CLASS[snapshot.component_type]
        if "liquidity_class" in values and values["liquidity_class"] is not None:
            snapshot.liquidity_class = values["liquidity_class"]
        if "as_of_date" in values and values["as_of_date"] is not None:
            snapshot.as_of_date = values["as_of_date"]
        if "value" in values and values["value"] is not None:
            snapshot.value = to_money(values["value"])
        if "currency" in values and values["currency"] is not None:
            snapshot.currency = values["currency"].upper()
        if "source" in values and values["source"] is not None:
            snapshot.source = values["source"]
        if "notes" in values:
            snapshot.notes = values["notes"]
        if "recurrence_days" in values:
            snapshot.recurrence_days = values["recurrence_days"]
        if "reminder_date" in values:
            snapshot.reminder_date = values["reminder_date"]

        await db.flush()
        await db.refresh(snapshot)
        return snapshot

    async def delete_valuation_snapshot(self, db: AsyncSession, user_id: UUID, snapshot_id: UUID) -> bool:
        """Delete a manual valuation snapshot by id."""
        snapshot = await self.get_valuation_snapshot(db, user_id, snapshot_id)
        if not snapshot:
            return False
        await db.delete(snapshot)
        await db.flush()
        return True

    async def get_latest_valuation_components(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        as_of_date: date,
        include_restricted: bool = True,
    ) -> ValuationComponentsResult:
        """Get latest manual valuation components for net worth aggregation."""
        latest_subquery = (
            select(
                ManualValuationSnapshot.id,
                func.row_number()
                .over(
                    partition_by=[
                        ManualValuationSnapshot.component_type,
                        ManualValuationSnapshot.source,
                        ManualValuationSnapshot.currency,
                    ],
                    order_by=[
                        ManualValuationSnapshot.as_of_date.desc(),
                        ManualValuationSnapshot.created_at.desc(),
                    ],
                )
                .label("rn"),
            )
            .where(ManualValuationSnapshot.user_id == user_id)
            .where(ManualValuationSnapshot.as_of_date <= as_of_date)
            .where(ManualValuationSnapshot.superseded_by_id.is_(None))
            .subquery()
        )

        result = await db.execute(
            select(ManualValuationSnapshot)
            .join(latest_subquery, ManualValuationSnapshot.id == latest_subquery.c.id)
            .where(latest_subquery.c.rn == 1)
            .order_by(ManualValuationSnapshot.component_type, ManualValuationSnapshot.source)
        )
        snapshots = result.scalars().all()

        total_assets = Decimal("0.00")
        total_liabilities = Decimal("0.00")
        items: list[ValuationComponentItem] = []

        for snapshot in snapshots:
            if not include_restricted and snapshot.liquidity_class in (
                ManualValuationLiquidityClass.RESTRICTED,
                ManualValuationLiquidityClass.ILLIQUID,
            ):
                continue

            value = to_money(snapshot.value)
            if snapshot.liquidity_class == ManualValuationLiquidityClass.LIABILITY:
                total_liabilities += value
            else:
                total_assets += value

            items.append(
                ValuationComponentItem(
                    id=snapshot.id,
                    component_type=snapshot.component_type.value,
                    liquidity_class=snapshot.liquidity_class.value,
                    as_of_date=snapshot.as_of_date,
                    value=value,
                    currency=snapshot.currency,
                    source=snapshot.source,
                    provenance="manual",
                )
            )

        total_assets = to_money(total_assets)
        total_liabilities = to_money(total_liabilities)
        return ValuationComponentsResult(
            items=items,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            net_worth_delta=to_money(total_assets - total_liabilities),
        )

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

            account = await self._get_or_create_broker_account(db, user_id, broker_name, snap.currency)

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
                quantity_changed = position.quantity != quantity
                # Money inequality compares amount AND currency in one go.
                valuation_changed = position.cost_basis_money != Money(snap.market_value, snap.currency)
                if quantity_changed or valuation_changed:
                    logger.info(
                        "Updating managed position from latest atomic snapshot",
                        asset=snap.asset_identifier,
                        old_qty=str(position.quantity),
                        new_qty=str(quantity),
                    )
                    position.quantity = quantity
                    position.cost_basis = snap.market_value
                    position.currency = snap.currency
                    position.position_metadata = {
                        **(position.position_metadata or {}),
                        "broker": snap.broker,
                        "latest_snapshot_date": snap.snapshot_date.isoformat(),
                    }

                if snapshot_quantity.is_zero():
                    position.status = PositionStatus.DISPOSED
                    position.disposal_date = snap.snapshot_date
                    result.disposed += 1
                else:
                    position.status = PositionStatus.ACTIVE
                    position.disposal_date = None
                    if quantity_changed or valuation_changed:
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
                        cost_basis=snap.market_value,
                        acquisition_date=snap.snapshot_date,
                        status=PositionStatus.ACTIVE,
                        currency=snap.currency,
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
                currency=normalize_currency_code(currency) or "USD",
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

        # Read cost via the money accessor; the depreciation math below is a
        # self-contained single-currency calculation (salvage_value carries no
        # currency), so it operates on the scalar amount.
        cost_basis = position.cost_basis_money.amount
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
            period_depreciation=to_money(period_depreciation),
            accumulated_depreciation=to_money(accumulated),
            book_value=to_money(book_value),
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
