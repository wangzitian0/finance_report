"""Tests for EPIC-003 orphaned storage object sweep behavior.

Verifies that sweep_orphaned_storage_objects correctly identifies S3 objects
that have no matching database record and deletes them.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.extraction import DocumentType, UploadedDocument
from src.runtime import StorageError
from src.runtime.extension.storage_sweep import (
    _list_storage_keys,
    run_storage_sweep,
    sweep_orphaned_storage_objects,
)


def _orphan_min_age() -> timedelta:
    """Configured grace period, read from settings at call time (issue #356)."""
    return timedelta(hours=settings.storage_sweep_grace_period_hours)


def _old_timestamp() -> datetime:
    """Return a timestamp older than the configured grace period."""
    return datetime.now(UTC) - _orphan_min_age() - timedelta(minutes=5)


def _recent_timestamp() -> datetime:
    """Return a timestamp newer than the configured grace period (still in flight)."""
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


async def test_sweep_deletes_orphaned_object(db: AsyncSession, test_user):
    """AC-extraction.8.1: Orphaned storage objects old enough for sweep are deleted."""
    orphan_key = "statements/user-1/orphan-id/orphan.pdf"
    mock_keys = [(orphan_key, _old_timestamp())]

    with (
        patch("src.runtime.extension.storage_sweep.StorageService") as MockStorage,
        patch("src.runtime.extension.storage_sweep._list_storage_keys", return_value=mock_keys),
    ):
        mock_storage_instance = MagicMock()
        MockStorage.return_value = mock_storage_instance

        # No DB statement has file_path = orphan_key, so it should be deleted
        deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))

    # Should have attempted to delete the orphaned object
    assert deleted == 1


async def test_sweep_skips_known_db_objects(db: AsyncSession, test_user):
    """AC-extraction.8.2: Storage objects with matching DB records are preserved."""
    known_key = "statements/user-1/known-id/statement.pdf"

    # Create a matching DB record (the kept ODS landing table keys storage objects)
    document = UploadedDocument(
        user_id=test_user.id,
        file_path=known_key,
        file_hash="known_hash_sweep_test",
        original_filename="statement.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.commit()

    mock_keys = [(known_key, _old_timestamp())]

    with (
        patch("src.runtime.extension.storage_sweep.StorageService") as MockStorage,
        patch("src.runtime.extension.storage_sweep._list_storage_keys", return_value=mock_keys),
    ):
        mock_storage_instance = MagicMock()
        MockStorage.return_value = mock_storage_instance

        deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))

    # Known object should NOT be deleted
    assert deleted == 0
    mock_storage_instance.delete_object.assert_not_called()


async def test_sweep_skips_recent_objects(db: AsyncSession, test_user):
    """AC-extraction.8.3: Recent storage objects are skipped as in-flight uploads."""
    recent_key = "statements/user-1/recent-id/recent.pdf"
    mock_keys = [(recent_key, _recent_timestamp())]

    with (
        patch("src.runtime.extension.storage_sweep.StorageService") as MockStorage,
        patch("src.runtime.extension.storage_sweep._list_storage_keys", return_value=mock_keys),
    ):
        mock_storage_instance = MagicMock()
        MockStorage.return_value = mock_storage_instance

        deleted = await sweep_orphaned_storage_objects()

    # Recent object should not be touched
    assert deleted == 0
    mock_storage_instance.delete_object.assert_not_called()


async def test_sweep_skips_when_no_bucket_configured():
    """AC-extraction.8.4: Storage sweep is a no-op when no S3 bucket is configured."""
    with patch("src.runtime.extension.storage_sweep.settings") as mock_settings:
        mock_settings.s3_bucket = None

        deleted = await sweep_orphaned_storage_objects()

    assert deleted == 0


async def test_sweep_returns_zero_when_no_objects():
    """AC-extraction.8.5: Storage sweep returns zero when no statement objects exist."""
    with (
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
        patch("src.runtime.extension.storage_sweep._list_storage_keys", return_value=[]),
        patch("src.runtime.extension.storage_sweep.StorageService"),
    ):
        mock_settings.s3_bucket = "test-bucket"

        deleted = await sweep_orphaned_storage_objects()

    assert deleted == 0


async def test_sweep_handles_storage_list_error():
    """AC-extraction.8.6: Storage sweep handles storage listing failures without deletions."""
    with (
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
        patch("src.runtime.extension.storage_sweep.StorageService"),
        patch(
            "src.runtime.extension.storage_sweep._list_storage_keys",
            side_effect=StorageError("connection error"),
        ),
    ):
        mock_settings.s3_bucket = "test-bucket"
        deleted = await sweep_orphaned_storage_objects()

    assert deleted == 0


async def test_sweep_handles_delete_error(db: AsyncSession):
    """AC-extraction.8.7: Storage sweep logs delete errors without incrementing deleted count."""
    orphan_key = "statements/user-1/orphan-id/orphan-del-err.pdf"
    mock_keys = [(orphan_key, _old_timestamp())]

    with (
        patch("src.runtime.extension.storage_sweep.StorageService") as MockStorage,
        patch("src.runtime.extension.storage_sweep._list_storage_keys", return_value=mock_keys),
    ):
        mock_storage_instance = MagicMock()
        mock_storage_instance.delete_object.side_effect = StorageError("Delete failed")
        MockStorage.return_value = mock_storage_instance

        deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))

    assert deleted == 0


def test_list_storage_keys_returns_paginated_keys_and_normalizes_timestamps():
    """AC-extraction.8.8: Storage key listing paginates and normalizes naive timestamps."""
    aware_modified = datetime(2026, 5, 29, 8, 0, tzinfo=UTC)
    naive_modified = datetime(2026, 5, 29, 9, 30)

    mock_storage = MagicMock()
    mock_storage.bucket = "test-bucket"
    mock_paginator = MagicMock()
    mock_storage.client.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {
            "Contents": [
                {
                    "Key": "statements/user-a/file-a.pdf",
                    "LastModified": aware_modified,
                }
            ]
        },
        {},
        {
            "Contents": [
                {
                    "Key": "statements/user-b/file-b.pdf",
                    "LastModified": naive_modified,
                }
            ]
        },
    ]

    assert _list_storage_keys(mock_storage) == [
        ("statements/user-a/file-a.pdf", aware_modified),
        ("statements/user-b/file-b.pdf", naive_modified.replace(tzinfo=UTC)),
    ]
    mock_storage.client.get_paginator.assert_called_once_with("list_objects_v2")
    mock_paginator.paginate.assert_called_once_with(Bucket="test-bucket", Prefix="statements/")


def test_list_storage_keys_raises_on_client_error():
    """AC-extraction.8.9: Storage key listing converts client errors to StorageError."""
    mock_storage = MagicMock()
    mock_paginator = MagicMock()
    mock_storage.client.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket", "Message": "The bucket does not exist"}},
        "ListObjectsV2",
    )

    with pytest.raises(StorageError, match="Failed to list storage objects"):
        _list_storage_keys(mock_storage)


async def test_run_storage_sweep_exits_on_stop_event():
    """AC-extraction.8.10: Storage sweep runner exits cleanly when stop_event is set."""
    stop_event = asyncio.Event()

    async def mock_sweep(*args, **kwargs):
        stop_event.set()
        return 0

    with (
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
        patch("src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects", side_effect=mock_sweep),
    ):
        mock_settings.enable_storage_sweep = True
        mock_settings.storage_sweep_interval_seconds = 86400
        await run_storage_sweep(stop_event)


async def test_run_storage_sweep_logs_when_objects_deleted():
    """AC-extraction.8.11: Storage sweep runner logs when orphaned objects are deleted."""
    stop_event = asyncio.Event()

    async def mock_sweep_with_deletions(*args, **kwargs):
        stop_event.set()
        return 5

    with (
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
        patch(
            "src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects",
            side_effect=mock_sweep_with_deletions,
        ),
    ):
        mock_settings.enable_storage_sweep = True
        mock_settings.storage_sweep_interval_seconds = 86400
        await run_storage_sweep(stop_event)


async def test_run_storage_sweep_handles_exception():
    """AC-extraction.8.12: Storage sweep runner catches unexpected exceptions and continues."""
    stop_event = asyncio.Event()
    call_count = [0]

    async def maybe_raise(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("Unexpected error from sweep")
        stop_event.set()
        return 0

    with (
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
        patch("src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects", side_effect=maybe_raise),
    ):
        mock_settings.enable_storage_sweep = True
        mock_settings.storage_sweep_interval_seconds = 0.001
        await run_storage_sweep(stop_event)

    assert call_count[0] == 2


async def test_run_storage_sweep_disabled_by_feature_flag():
    """AC-extraction.8.13: Storage sweep runner exits immediately when disabled by feature flag."""
    stop_event = asyncio.Event()

    with (
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
        patch("src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects") as mock_sweep,
    ):
        mock_settings.enable_storage_sweep = False
        await run_storage_sweep(stop_event)

    # Should have returned without running any sweep (stop_event not set, sweep not called)
    assert not stop_event.is_set()
    mock_sweep.assert_not_called()


def test_grace_period_and_interval_defaults_match_issue_356(monkeypatch):
    """AC-extraction.8.14: Config defaults match issue #356 (24h grace, daily/86400s interval).

    Build a fresh ``Settings`` with the relevant env vars cleared and no env file,
    so this verifies the in-code defaults regardless of the dev/CI environment.
    """
    from src.config import Settings

    monkeypatch.delenv("STORAGE_SWEEP_GRACE_PERIOD_HOURS", raising=False)
    monkeypatch.delenv("STORAGE_SWEEP_INTERVAL_SECONDS", raising=False)

    defaults = Settings(_env_file=None)

    # Grace period: 24 hours by default (avoids racing with in-progress uploads).
    assert defaults.storage_sweep_grace_period_hours == 24
    # Interval: daily (86400 seconds) by default.
    assert defaults.storage_sweep_interval_seconds == 86400


async def test_sweep_reads_grace_period_from_config(db: AsyncSession, test_user):
    """AC-extraction.8.15: Sweep grace-period cutoff is read from config, not a hardcoded constant.

    An object older than the configured grace period must be swept; the same object
    is preserved when the configured grace period is widened past its age.
    """
    orphan_key = "statements/user-1/cfg-grace/orphan.pdf"
    # Object is ~2h old.
    obj_age_hours = 2
    mock_keys = [(orphan_key, datetime.now(UTC) - timedelta(hours=obj_age_hours, minutes=5))]

    # With a 1h grace period the 2h-old orphan is out of grace -> deleted.
    with (
        patch("src.runtime.extension.storage_sweep.StorageService") as MockStorage,
        patch("src.runtime.extension.storage_sweep._list_storage_keys", return_value=mock_keys),
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
    ):
        mock_settings.s3_bucket = "test-bucket"
        mock_settings.storage_sweep_grace_period_hours = 1
        mock_storage_instance = MagicMock()
        MockStorage.return_value = mock_storage_instance
        deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))
    assert deleted == 1

    # With a 24h grace period the same 2h-old orphan is within grace -> preserved.
    with (
        patch("src.runtime.extension.storage_sweep.StorageService") as MockStorage,
        patch("src.runtime.extension.storage_sweep._list_storage_keys", return_value=mock_keys),
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
    ):
        mock_settings.s3_bucket = "test-bucket"
        mock_settings.storage_sweep_grace_period_hours = 24
        mock_storage_instance = MagicMock()
        MockStorage.return_value = mock_storage_instance
        deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))
    assert deleted == 0
    mock_storage_instance.delete_object.assert_not_called()


async def test_run_storage_sweep_reads_interval_from_config():
    """AC-extraction.8.16: The sweep runner reads its wait interval from config."""
    stop_event = asyncio.Event()
    observed: dict[str, float] = {}

    async def fake_wait_for(_awaitable, timeout):
        observed["timeout"] = timeout
        stop_event.set()
        # Cancel the pending stop_event.wait() coroutine to avoid a warning.
        _awaitable.close()
        raise TimeoutError

    async def mock_sweep(*args, **kwargs):
        return 0

    with (
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
        patch("src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects", side_effect=mock_sweep),
        patch("src.runtime.extension.storage_sweep.asyncio.wait_for", side_effect=fake_wait_for),
    ):
        mock_settings.enable_storage_sweep = True
        mock_settings.storage_sweep_interval_seconds = 12345
        await run_storage_sweep(stop_event)

    assert observed["timeout"] == 12345
