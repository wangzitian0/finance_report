"""Layer 4: Reporting Snapshot Service."""

from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.layer4 import ReportSnapshot, ReportType


class ReportingSnapshotService:
    """Service for managing financial report snapshots (Layer 4)."""

    async def get_snapshot(
        self,
        db: AsyncSession,
        user_id: UUID,
        report_type: ReportType,
        as_of_date: date,
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

        if rule_version_id:
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
        rule_version_id: UUID,
        report_data: dict,
        ttl_seconds: int = 3600,
    ) -> ReportSnapshot:
        """Create a new report snapshot and mark it as latest."""
        # 1. Mark existing snapshots for this date as not latest
        existing_query = (
            select(ReportSnapshot)
            .where(ReportSnapshot.user_id == user_id)
            .where(ReportSnapshot.report_type == report_type)
            .where(ReportSnapshot.as_of_date == as_of_date)
            .where(ReportSnapshot.is_latest == True)  # noqa: E712
        )
        existing = (await db.execute(existing_query)).scalars().all()
        for snap in existing:
            snap.is_latest = False

        # 2. Create new snapshot
        ttl = datetime.now() + timedelta(seconds=ttl_seconds)
        snapshot = ReportSnapshot(
            user_id=user_id,
            report_type=report_type,
            as_of_date=as_of_date,
            rule_version_id=rule_version_id,
            report_data=report_data,
            is_latest=True,
            ttl=ttl,
        )
        db.add(snapshot)
        await db.flush()
        return snapshot
