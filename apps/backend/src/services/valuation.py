"""Valuation snapshot service."""

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.valuation import ValuationSnapshot
from src.schemas.valuation import ValuationSnapshotCreate


class ValuationService:
    """Service for managing net worth valuation snapshots."""

    async def create_snapshot(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        payload: ValuationSnapshotCreate,
    ) -> ValuationSnapshot:
        """Create a new valuation snapshot."""
        snapshot = ValuationSnapshot(
            user_id=user_id,
            component_type=payload.component_type,
            component_name=payload.component_name.strip(),
            side=payload.side,
            value=payload.value,
            currency=payload.currency.upper(),
            as_of_date=payload.as_of_date,
            source=payload.source,
            confidence=payload.confidence,
            stale_after_days=payload.stale_after_days,
            include_in_total_net_worth=payload.include_in_total_net_worth,
            include_in_liquid_net_worth=payload.include_in_liquid_net_worth,
            restricted_until=payload.restricted_until,
            notes=payload.notes,
            snapshot_metadata=payload.snapshot_metadata,
        )
        db.add(snapshot)
        await db.flush()
        await db.refresh(snapshot)
        return snapshot

    async def list_snapshots(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        as_of_date: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ValuationSnapshot], int]:
        """List valuation snapshots for a user."""
        stmt = select(ValuationSnapshot).where(ValuationSnapshot.user_id == user_id)
        count_stmt = select(func.count()).select_from(ValuationSnapshot).where(ValuationSnapshot.user_id == user_id)
        if as_of_date is not None:
            stmt = stmt.where(ValuationSnapshot.as_of_date <= as_of_date)
            count_stmt = count_stmt.where(ValuationSnapshot.as_of_date <= as_of_date)

        total_result = await db.execute(count_stmt)
        total = total_result.scalar_one()

        result = await db.execute(
            stmt.order_by(ValuationSnapshot.as_of_date.desc(), ValuationSnapshot.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total)

    async def latest_components(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        as_of_date: date,
    ) -> list[ValuationSnapshot]:
        """Return the latest snapshot per component as of the requested date."""
        result = await db.execute(
            select(ValuationSnapshot)
            .where(ValuationSnapshot.user_id == user_id)
            .where(ValuationSnapshot.as_of_date <= as_of_date)
            .order_by(
                ValuationSnapshot.component_type.asc(),
                ValuationSnapshot.component_name.asc(),
                ValuationSnapshot.as_of_date.desc(),
                ValuationSnapshot.created_at.desc(),
            )
        )
        latest: dict[tuple[str, str], ValuationSnapshot] = {}
        for snapshot in result.scalars().all():
            key = (snapshot.component_type.value, snapshot.component_name)
            latest.setdefault(key, snapshot)
        return list(latest.values())
