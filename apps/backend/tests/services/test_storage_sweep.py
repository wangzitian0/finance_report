"""Tests for orphaned storage object sweep service (Issue #6).

Verifies that sweep_orphaned_storage_objects correctly identifies S3 objects
that have no matching database record and deletes them.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import BankStatement, BankStatementStatus
from src.services.storage_sweep import (
    ORPHAN_MIN_AGE,
    sweep_orphaned_storage_objects,
)


def _old_timestamp() -> datetime:
    """Return a timestamp older than ORPHAN_MIN_AGE."""
    return datetime.now(UTC) - ORPHAN_MIN_AGE - timedelta(minutes=5)


def _recent_timestamp() -> datetime:
    """Return a timestamp newer than ORPHAN_MIN_AGE (still in flight)."""
    return datetime.now(UTC) - timedelta(minutes=5)


def _make_db_sessionmaker(db: AsyncSession):
    """Return a synchronous callable that yields the test DB session as an async context manager."""

    def _sessionmaker():
        class _FakeCtx:
            async def __aenter__(self_):
                return db

            async def __aexit__(self_, *args):
                return False

        return _FakeCtx()

    return _sessionmaker


@pytest.mark.asyncio
async def test_sweep_deletes_orphaned_object(db: AsyncSession, test_user):
    """Orphaned storage objects (no DB record, old enough) should be deleted."""
    orphan_key = "statements/user-1/orphan-id/orphan.pdf"
    mock_keys = [(orphan_key, _old_timestamp())]

    with (
        patch("src.services.storage_sweep.StorageService") as MockStorage,
        patch("src.services.storage_sweep._list_storage_keys", return_value=mock_keys),
    ):
        mock_storage_instance = MagicMock()
        MockStorage.return_value = mock_storage_instance

        # No DB statement has file_path = orphan_key, so it should be deleted
        deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))

    # Should have attempted to delete the orphaned object
    assert deleted == 1


@pytest.mark.asyncio
async def test_sweep_skips_known_db_objects(db: AsyncSession, test_user):
    """Objects with a matching DB record should NOT be deleted."""
    known_key = "statements/user-1/known-id/statement.pdf"

    # Create a matching DB record
    statement = BankStatement(
        user_id=test_user.id,
        file_path=known_key,
        file_hash="known_hash_sweep_test",
        original_filename="statement.pdf",
        institution="TestBank",
        status=BankStatementStatus.PARSED,
    )
    db.add(statement)
    await db.commit()

    mock_keys = [(known_key, _old_timestamp())]

    with (
        patch("src.services.storage_sweep.StorageService") as MockStorage,
        patch("src.services.storage_sweep._list_storage_keys", return_value=mock_keys),
    ):
        mock_storage_instance = MagicMock()
        MockStorage.return_value = mock_storage_instance

        deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))

    # Known object should NOT be deleted
    assert deleted == 0
    mock_storage_instance.delete_object.assert_not_called()


@pytest.mark.asyncio
async def test_sweep_skips_recent_objects(db: AsyncSession, test_user):
    """Objects newer than ORPHAN_MIN_AGE should be skipped (in-flight uploads)."""
    recent_key = "statements/user-1/recent-id/recent.pdf"
    mock_keys = [(recent_key, _recent_timestamp())]

    with (
        patch("src.services.storage_sweep.StorageService") as MockStorage,
        patch("src.services.storage_sweep._list_storage_keys", return_value=mock_keys),
    ):
        mock_storage_instance = MagicMock()
        MockStorage.return_value = mock_storage_instance

        deleted = await sweep_orphaned_storage_objects()

    # Recent object should not be touched
    assert deleted == 0
    mock_storage_instance.delete_object.assert_not_called()


@pytest.mark.asyncio
async def test_sweep_skips_when_no_bucket_configured():
    """Sweep should be a no-op when S3 bucket is not configured."""
    with patch("src.services.storage_sweep.settings") as mock_settings:
        mock_settings.s3_bucket = None

        deleted = await sweep_orphaned_storage_objects()

    assert deleted == 0


@pytest.mark.asyncio
async def test_sweep_returns_zero_when_no_objects():
    """Sweep should return 0 when storage has no objects under the statements prefix."""
    with (
        patch("src.services.storage_sweep.settings") as mock_settings,
        patch("src.services.storage_sweep._list_storage_keys", return_value=[]),
        patch("src.services.storage_sweep.StorageService"),
    ):
        mock_settings.s3_bucket = "test-bucket"

        deleted = await sweep_orphaned_storage_objects()

    assert deleted == 0
