"""Layer 4: Reporting Snapshot Service."""

from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.reporting.orm import ReportSnapshot, ReportType


class ReportingSnapshotService:
    """Service for managing financial report snapshots (Layer 4)."""

    async def get_snapshot(
        self,
        db: AsyncSession,
        user_id: UUID,
        report_type: ReportType,
        as_of_date: date,
        start_date: date | None = None,
        rule_version_id: UUID | None = None,
    ) -> ReportSnapshot | None:
        """Get an existing snapshot.

        If rule_version_id is provided, gets that specific version.
        Otherwise, gets the latest version for that date.
        """
        query = (
            select(ReportSnapshot)
            .where(ReportSnapshot.user_id == user_id)
            .where(ReportSnapshot.report_type == report_type)
            .where(ReportSnapshot.as_of_date == as_of_date)
        )
        if start_date is None:
            query = query.where(ReportSnapshot.start_date.is_(None))
        else:
            query = query.where(ReportSnapshot.start_date == start_date)

        if rule_version_id is not None:
            query = query.where(ReportSnapshot.rule_version_id == rule_version_id)
        else:
            query = query.where(ReportSnapshot.is_latest == True)  # noqa: E712

        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def create_snapshot(
        self,
        db: AsyncSession,
        user_id: UUID,
        report_type: ReportType,
        as_of_date: date,
        rule_version_id: UUID | None,
        report_data: dict,
        start_date: date | None = None,
        ttl_seconds: int = 3600,
        snapshot_id: UUID | None = None,
    ) -> ReportSnapshot:
        """Create a new report snapshot and mark it as latest."""
        try:
            existing_query = (
                select(ReportSnapshot)
                .where(ReportSnapshot.user_id == user_id)
                .where(ReportSnapshot.report_type == report_type)
                .where(ReportSnapshot.as_of_date == as_of_date)
                .where(ReportSnapshot.is_latest == True)  # noqa: E712
            )
            if start_date is None:
                existing_query = existing_query.where(ReportSnapshot.start_date.is_(None))
            else:
                existing_query = existing_query.where(ReportSnapshot.start_date == start_date)
            existing = (await db.execute(existing_query)).scalars().all()
            for snap in existing:
                snap.is_latest = False

            ttl = datetime.now() + timedelta(seconds=ttl_seconds)
            snapshot = ReportSnapshot(
                user_id=user_id,
                report_type=report_type,
                as_of_date=as_of_date,
                start_date=start_date,
                rule_version_id=rule_version_id,
                report_data=report_data,
                is_latest=True,
                ttl=ttl,
            )
            # Package assembly pre-allocates its UUID so the frozen document can
            # bind its immutable identity before persistence. Other snapshots
            # must leave the field unset for UUIDMixin's default to generate it.
            if snapshot_id is not None:
                snapshot.id = snapshot_id
            db.add(snapshot)
            await db.flush()
            return snapshot

        except Exception as e:
            from src.observability import get_logger

            logger = get_logger(__name__)
            logger.error(
                "Failed to create report snapshot",
                user_id=str(user_id),
                report_type=report_type.value,
                as_of_date=str(as_of_date),
                error=str(e),
                error_type=type(e).__name__,
            )
            raise
