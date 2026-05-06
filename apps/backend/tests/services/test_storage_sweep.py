"""Tests for orphaned storage object sweep service (Issue #6).

Verifies that sweep_orphaned_storage_objects correctly identifies S3 objects
that have no matching database record and deletes them.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import BankStatement, BankStatementStatus
from src.services import StorageError
from src.services.storage_sweep import (
    ORPHAN_MIN_AGE,
    _list_storage_keys,
    run_storage_sweep,
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


@pytest.mark.asyncio
async def test_sweep_handles_storage_list_error():
    """Sweep should return 0 and log when storage listing raises StorageError."""
    with (
        patch("src.services.storage_sweep.settings") as mock_settings,
        patch("src.services.storage_sweep.StorageService"),
        patch(
            "src.services.storage_sweep._list_storage_keys",
            side_effect=StorageError("connection error"),
        ),
    ):
        mock_settings.s3_bucket = "test-bucket"
        deleted = await sweep_orphaned_storage_objects()

    assert deleted == 0


@pytest.mark.asyncio
async def test_sweep_handles_delete_error(db: AsyncSession):
    """Delete errors should be logged but not increment the deleted count."""
    orphan_key = "statements/user-1/orphan-id/orphan-del-err.pdf"
    mock_keys = [(orphan_key, _old_timestamp())]

    with (
        patch("src.services.storage_sweep.StorageService") as MockStorage,
        patch("src.services.storage_sweep._list_storage_keys", return_value=mock_keys),
    ):
        mock_storage_instance = MagicMock()
        mock_storage_instance.delete_object.side_effect = StorageError("Delete failed")
        MockStorage.return_value = mock_storage_instance

        deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))

    assert deleted == 0


def test_list_storage_keys_raises_on_client_error():
    """_list_storage_keys converts ClientError to StorageError."""
    mock_storage = MagicMock()
    mock_paginator = MagicMock()
    mock_storage.client.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket", "Message": "The bucket does not exist"}},
        "ListObjectsV2",
    )

    with pytest.raises(StorageError, match="Failed to list storage objects"):
        _list_storage_keys(mock_storage)


@pytest.mark.asyncio
async def test_run_storage_sweep_exits_on_stop_event():
    """run_storage_sweep should exit cleanly when stop_event is set during a sweep."""
    stop_event = asyncio.Event()

    async def mock_sweep(*args, **kwargs):
        stop_event.set()
        return 0

    with (
        patch("src.services.storage_sweep.settings") as mock_settings,
        patch("src.services.storage_sweep.sweep_orphaned_storage_objects", side_effect=mock_sweep),
    ):
        mock_settings.enable_storage_sweep = True
        await run_storage_sweep(stop_event)


@pytest.mark.asyncio
async def test_run_storage_sweep_logs_when_objects_deleted():
    """run_storage_sweep should log when orphaned objects are deleted."""
    stop_event = asyncio.Event()

    async def mock_sweep_with_deletions(*args, **kwargs):
        stop_event.set()
        return 5

    with (
        patch("src.services.storage_sweep.settings") as mock_settings,
        patch(
            "src.services.storage_sweep.sweep_orphaned_storage_objects",
            side_effect=mock_sweep_with_deletions,
        ),
    ):
        mock_settings.enable_storage_sweep = True
        await run_storage_sweep(stop_event)


@pytest.mark.asyncio
async def test_run_storage_sweep_handles_exception():
    """run_storage_sweep should catch unexpected exceptions and continue looping."""
    stop_event = asyncio.Event()
    call_count = [0]

    async def maybe_raise(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("Unexpected error from sweep")
        stop_event.set()
        return 0

    with (
        patch("src.services.storage_sweep.settings") as mock_settings,
        patch("src.services.storage_sweep.sweep_orphaned_storage_objects", side_effect=maybe_raise),
        patch("src.services.storage_sweep.SWEEP_INTERVAL_SECONDS", 0.001),
    ):
        mock_settings.enable_storage_sweep = True
        await run_storage_sweep(stop_event)

    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_run_storage_sweep_disabled_by_feature_flag():
    """run_storage_sweep should exit immediately when ENABLE_STORAGE_SWEEP is False."""
    stop_event = asyncio.Event()

    with patch("src.services.storage_sweep.settings") as mock_settings:
        mock_settings.enable_storage_sweep = False
        await run_storage_sweep(stop_event)

    # Should have returned without running any sweep (stop_event not set)
    assert not stop_event.is_set()

