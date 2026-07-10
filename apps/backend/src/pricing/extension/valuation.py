"""Manual-valuation snapshot service (split from services/assets.py, #1677/#1610).

Valuation snapshots and their versioned read models are pricing-owned facts
(#1610 ruling 2); the position/depreciation half lives in
``src.portfolio.extension.positions``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import to_money
from src.models.layer3 import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
)
from src.observability import get_logger
from src.schemas.provenance import DataProvenance

logger = get_logger(__name__)

ASSET_QUANTITY_UNIT = "units"


class ValuationServiceError(Exception):
    """Valuation service failure (was ValuationServiceError, #1677)."""


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


class ValuationService:
    """Manual-valuation snapshot operations (was AssetService's valuation half)."""

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
            raise ValuationServiceError("Cannot edit a superseded valuation version; submit a correction instead")

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
