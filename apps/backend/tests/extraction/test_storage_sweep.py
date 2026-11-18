import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, settings
from src.extraction import DocumentType, UploadedDocument, get_known_storage_paths
from src.runtime import StorageError
from src.runtime.extension.storage_sweep import _list_storage_keys, run_storage_sweep, sweep_orphaned_storage_objects


def _old_ts(hours: int | None = None) -> datetime:
    offset = timedelta(hours=hours) if hours is not None else timedelta(hours=settings.storage_sweep_grace_period_hours)
    return datetime.now(UTC) - offset - timedelta(minutes=5)


def _make_db_sessionmaker(db: AsyncSession):
    class _FakeCtx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return False

    return lambda: _FakeCtx()


@pytest.mark.parametrize(
    ("case", "grace_hours", "expected_deleted", "expect_delete_call"),
    [
        ("orphan", None, 1, True),
        ("known", None, 0, False),
        ("recent", None, 0, False),
        ("delete_error", None, 0, True),
        ("grace_1h", 1, 1, True),
        ("grace_24h", 24, 0, False),
    ],
)
async def test_sweep_orphaned_objects_cases(db: AsyncSession, test_user, case, grace_hours, expected_deleted, expect_delete_call):
    key = f"statements/user-1/{case}/file.pdf"
    if case == "known":
        db.add(UploadedDocument(user_id=test_user.id, file_path=key, file_hash="known_hash_sweep_test", original_filename="s.pdf", document_type=DocumentType.BANK_STATEMENT))
        await db.commit()
    ts = datetime.now(UTC) - timedelta(minutes=5) if case == "recent" else datetime.now(UTC) - timedelta(hours=2, minutes=5) if grace_hours else _old_ts()
    mock_storage = MagicMock()
    if case == "delete_error":
        mock_storage.delete_object.side_effect = StorageError("Delete failed")
    with (
        patch("src.runtime.extension.storage_sweep.StorageService", return_value=mock_storage),
        patch("src.runtime.extension.storage_sweep._list_storage_keys", return_value=[(key, ts)]),
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
    ):
        mock_settings.environment = settings.environment
        mock_settings.s3_bucket = "test-bucket"
        mock_settings.storage_sweep_grace_period_hours = grace_hours or settings.storage_sweep_grace_period_hours
        assert await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db), known_paths_provider=get_known_storage_paths) == expected_deleted
    assert mock_storage.delete_object.called is expect_delete_call


@pytest.mark.parametrize(
    ("bucket", "list_kw"),
    [(None, {}), ("test-bucket", {"return_value": []}), ("test-bucket", {"side_effect": StorageError("connection error")})],
)
async def test_sweep_short_circuits_and_handles_list_errors(bucket, list_kw):
    with (
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
        patch("src.runtime.extension.storage_sweep.StorageService"),
        patch("src.runtime.extension.storage_sweep._list_storage_keys", **list_kw),
    ):
        mock_settings.s3_bucket = bucket
        assert await sweep_orphaned_storage_objects() == 0


def test_list_storage_keys_pagination_and_error():
    aware = datetime(2026, 5, 29, 8, 0, tzinfo=UTC)
    naive = datetime(2026, 5, 29, 9, 30)
    mock_storage, mock_paginator = MagicMock(bucket="test-bucket"), MagicMock()
    mock_storage.client.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [{"Contents": [{"Key": "statements/user-a/file-a.pdf", "LastModified": aware}]}, {}, {"Contents": [{"Key": "statements/user-b/file-b.pdf", "LastModified": naive}]}]
    assert _list_storage_keys(mock_storage) == [("statements/user-a/file-a.pdf", aware), ("statements/user-b/file-b.pdf", naive.replace(tzinfo=UTC))]
    mock_storage.client.get_paginator.assert_called_once_with("list_objects_v2")
    mock_paginator.paginate.assert_called_once_with(Bucket="test-bucket", Prefix="statements/")

    mock_paginator.paginate.side_effect = ClientError({"Error": {"Code": "NoSuchBucket", "Message": "missing"}}, "ListObjectsV2")
    with pytest.raises(StorageError, match="Failed to list storage objects"):
        _list_storage_keys(mock_storage)


@pytest.mark.parametrize(("enabled", "fail_first", "deleted_count"), [(True, False, 0), (True, False, 5), (True, True, 0), (False, False, 0)])
async def test_run_storage_sweep_loop(enabled, fail_first, deleted_count):
    stop_event, calls = asyncio.Event(), [0]

    async def fake_sweep(*_args, **_kwargs):
        calls[0] += 1
        if fail_first and calls[0] == 1:
            raise RuntimeError("Unexpected error")
        stop_event.set()
        return deleted_count

    with patch("src.runtime.extension.storage_sweep.settings") as mock_settings, patch("src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects", side_effect=fake_sweep) as mock_sweep:
        mock_settings.enable_storage_sweep, mock_settings.storage_sweep_interval_seconds = enabled, 0.001
        await run_storage_sweep(stop_event)
    if enabled:
        assert calls[0] == (2 if fail_first else 1)
    else:
        assert not stop_event.is_set()
        mock_sweep.assert_not_called()


async def test_run_storage_sweep_config_defaults_and_interval(monkeypatch):
    monkeypatch.delenv("STORAGE_SWEEP_GRACE_PERIOD_HOURS", raising=False)
    monkeypatch.delenv("STORAGE_SWEEP_INTERVAL_SECONDS", raising=False)
    defaults = Settings(_env_file=None)
    assert (defaults.storage_sweep_grace_period_hours, defaults.storage_sweep_interval_seconds) == (24, 86400)

    stop_event, observed = asyncio.Event(), {}

    async def fake_wait_for(awaitable, timeout):
        observed["timeout"] = timeout
        stop_event.set()
        awaitable.close()
        raise TimeoutError

    with (
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
        patch("src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects", return_value=0),
        patch("src.runtime.extension.storage_sweep.asyncio.wait_for", side_effect=fake_wait_for),
    ):
        mock_settings.enable_storage_sweep, mock_settings.storage_sweep_interval_seconds = True, 12345
        await run_storage_sweep(stop_event)
    assert observed["timeout"] == 12345


@pytest.mark.parametrize("preview_env", ["preview", "branch-main", "pr-42"])
async def test_storage_sweep_skipped_in_preview_environment(preview_env: str):
    stop_event = asyncio.Event()
    with (
        patch("src.runtime.extension.storage_sweep.settings") as mock_settings,
        patch("src.runtime.extension.storage_sweep.StorageService") as mock_storage,
        patch("src.runtime.extension.storage_sweep._list_storage_keys") as mock_list,
    ):
        mock_settings.environment, mock_settings.enable_storage_sweep, mock_settings.s3_bucket = preview_env, True, "finance-report-staging"
        assert await sweep_orphaned_storage_objects() == 0
        await run_storage_sweep(stop_event)
    assert not stop_event.is_set()
    mock_storage.assert_not_called()
    mock_list.assert_not_called()
