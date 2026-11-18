from datetime import UTC, date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.reporting import ReportingSnapshotService, ReportSnapshot, ReportType


class TestReportingSnapshotService:
    async def test_create_snapshot_lifecycle_scoping_and_ttl(self, db, test_user) -> None:
        svc = ReportingSnapshotService()
        d1, d2 = date(2024, 1, 31), date(2024, 2, 29)
        s1 = await svc.create_snapshot(
            db, user_id=test_user.id, report_type=ReportType.BALANCE_SHEET, as_of_date=d1, report_data={"assets": 1000}
        )
        assert s1.is_latest is True and s1.ttl is not None and s1.ttl.tzinfo == UTC
        s2 = await svc.create_snapshot(
            db, user_id=test_user.id, report_type=ReportType.BALANCE_SHEET, as_of_date=d1, report_data={"assets": 1100}
        )
        await db.refresh(s1)
        assert s1.is_latest is False and s2.is_latest is True
        latest_ids = (
            (
                await db.execute(
                    select(ReportSnapshot.id).where(
                        ReportSnapshot.user_id == test_user.id,
                        ReportSnapshot.as_of_date == d1,
                        ReportSnapshot.is_latest.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert latest_ids == [s2.id]
        s_feb = await svc.create_snapshot(
            db, user_id=test_user.id, report_type=ReportType.BALANCE_SHEET, as_of_date=d2, report_data={"month": "feb"}
        )
        await db.refresh(s2)
        assert s2.is_latest is True and s_feb.is_latest is True

    async def test_create_snapshot_exception_handling(self, db, test_user) -> None:
        with (
            patch.object(db, "flush", new_callable=AsyncMock, side_effect=RuntimeError("Database connection lost")),
            pytest.raises(RuntimeError, match="Database connection lost"),
        ):
            await ReportingSnapshotService().create_snapshot(
                db,
                user_id=test_user.id,
                report_type=ReportType.BALANCE_SHEET,
                as_of_date=date(2024, 1, 31),
                report_data={"test": "data"},
            )
