"""Tests for Reporting Snapshot Service."""

from datetime import date

import pytest

from src.models.layer3 import ClassificationRule, RuleType
from src.models.layer4 import ReportType
from src.services.reporting_snapshot import ReportingSnapshotService


@pytest.mark.asyncio
class TestReportingSnapshotService:
    """Tests for snapshot CRUD."""

    async def test_create_and_get_snapshot(self, db, test_user):
        """Test creating and retrieving a snapshot."""
        service = ReportingSnapshotService()

        # 1. Create Rule (Dependency)
        rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Test Rule",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={},
            created_by=test_user.id,
        )
        db.add(rule)
        await db.flush()

        # 2. Create Snapshot
        as_of_date = date(2024, 1, 31)
        report_data = {"assets": 1000, "liabilities": 500}

        snapshot = await service.create_snapshot(
            db,
            user_id=test_user.id,
            report_type=ReportType.BALANCE_SHEET,
            as_of_date=as_of_date,
            rule_version_id=rule.id,
            report_data=report_data,
        )

        assert snapshot.is_latest is True
        assert snapshot.report_data == report_data

        # 3. Get Snapshot
        fetched = await service.get_snapshot(
            db,
            user_id=test_user.id,
            report_type=ReportType.BALANCE_SHEET,
            as_of_date=as_of_date,
        )
        assert fetched.id == snapshot.id

        # 4. Create Newer Snapshot (Versioning)
        snapshot2 = await service.create_snapshot(
            db,
            user_id=test_user.id,
            report_type=ReportType.BALANCE_SHEET,
            as_of_date=as_of_date,
            rule_version_id=rule.id,
            report_data={"assets": 1100},
        )

        # Verify old snapshot is no longer latest
        await db.refresh(snapshot)
        assert snapshot.is_latest is False
        assert snapshot2.is_latest is True

        # Verify get_snapshot returns latest
        fetched_latest = await service.get_snapshot(
            db,
            user_id=test_user.id,
            report_type=ReportType.BALANCE_SHEET,
            as_of_date=as_of_date,
        )
        assert fetched_latest.id == snapshot2.id
