"""Tests for Reporting Snapshot Service."""

from datetime import UTC, date

import pytest
from sqlalchemy import select

from src.reporting import ReportingSnapshotService, ReportSnapshot, ReportType


class TestReportingSnapshotService:
    """Tests for snapshot CRUD."""

    async def test_create_snapshot_retires_previous_latest(self, db, test_user):
        """A second snapshot for the same report date becomes the only latest one."""
        service = ReportingSnapshotService()

        as_of_date = date(2024, 1, 31)
        report_data = {"assets": 1000, "liabilities": 500}

        snapshot = await service.create_snapshot(
            db,
            user_id=test_user.id,
            report_type=ReportType.BALANCE_SHEET,
            as_of_date=as_of_date,
            report_data=report_data,
        )

        assert snapshot.is_latest is True
        assert snapshot.report_data == report_data

        snapshot2 = await service.create_snapshot(
            db,
            user_id=test_user.id,
            report_type=ReportType.BALANCE_SHEET,
            as_of_date=as_of_date,
            report_data={"assets": 1100},
        )

        await db.refresh(snapshot)
        assert snapshot.is_latest is False
        assert snapshot2.is_latest is True
        latest_ids = (
            (
                await db.execute(
                    select(ReportSnapshot.id)
                    .where(ReportSnapshot.user_id == test_user.id)
                    .where(ReportSnapshot.as_of_date == as_of_date)
                    .where(ReportSnapshot.is_latest.is_(True))
                )
            )
            .scalars()
            .all()
        )
        assert latest_ids == [snapshot2.id]

    async def test_create_snapshot_exception_handling(self, db, test_user):
        """
        GIVEN create_snapshot encounters a database error
        WHEN the exception occurs
        THEN it should log error details and re-raise the exception
        """
        from unittest.mock import AsyncMock, patch

        service = ReportingSnapshotService()

        with patch.object(db, "flush", new_callable=AsyncMock) as mock_flush:
            mock_flush.side_effect = RuntimeError("Database connection lost")

            with pytest.raises(RuntimeError, match="Database connection lost"):
                await service.create_snapshot(
                    db,
                    user_id=test_user.id,
                    report_type=ReportType.BALANCE_SHEET,
                    as_of_date=date(2024, 1, 31),
                    report_data={"test": "data"},
                )

    async def test_create_snapshot_scopes_latest_to_same_report_date(self, db, test_user):
        """Creating a new snapshot only retires the latest snapshot for the same report date."""
        service = ReportingSnapshotService()

        january = await service.create_snapshot(
            db,
            user_id=test_user.id,
            report_type=ReportType.BALANCE_SHEET,
            as_of_date=date(2024, 1, 31),
            report_data={"month": "jan"},
        )
        february = await service.create_snapshot(
            db,
            user_id=test_user.id,
            report_type=ReportType.BALANCE_SHEET,
            as_of_date=date(2024, 2, 29),
            report_data={"month": "feb"},
        )
        await db.refresh(january)
        await db.refresh(february)

        assert january.is_latest is True
        assert february.is_latest is True

    async def test_create_snapshot_ttl_is_utc_aware(self, db, test_user):
        """AC-reporting.snapshot.1: snapshot.ttl must be timezone-aware with UTC timezone."""
        service = ReportingSnapshotService()
        snapshot = await service.create_snapshot(
            db,
            user_id=test_user.id,
            report_type=ReportType.BALANCE_SHEET,
            as_of_date=date(2024, 1, 31),
            report_data={"assets": 1000},
        )
        assert snapshot.ttl is not None
        assert snapshot.ttl.tzinfo is not None, "snapshot.ttl must be timezone-aware"
        assert snapshot.ttl.tzinfo == UTC, f"snapshot.ttl timezone must be UTC, got {snapshot.ttl.tzinfo}"
