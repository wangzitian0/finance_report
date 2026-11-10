'EPIC-003'; import asyncio; from datetime import UTC, datetime, timedelta; from unittest.mock import MagicMock, patch; import pytest; from botocore.exceptions import ClientError; from sqlalchemy.ext.asyncio import AsyncSession; from src.config import settings; from src.extraction import DocumentType, UploadedDocument, get_known_storage_paths; from src.runtime import StorageError, register_known_storage_paths_provider; from src.runtime.extension.storage_sweep import _list_storage_keys, run_storage_sweep, sweep_orphaned_storage_objects
@pytest.fixture(autouse=True)
def _wire_known_storage_paths_provider() -> None: register_known_storage_paths_provider(get_known_storage_paths)
_orphan_min_age = lambda: timedelta(hours=settings.storage_sweep_grace_period_hours); _old_timestamp = lambda: datetime.now(UTC) - _orphan_min_age() - timedelta(minutes=5); _recent_timestamp = lambda: datetime.now(UTC) - timedelta(minutes=5)
def _make_db_sessionmaker(db: AsyncSession):
    def _sessionmaker():
        class _FakeCtx:
            async def __aenter__(self_): return db
            async def __aexit__(self_, *args): return False
        return _FakeCtx()
    return _sessionmaker
async def test_sweep_deletes_orphaned_object(db: AsyncSession, test_user):
    'AC-extraction.8.1'; orphan_key = 'statements/user-1/orphan-id/orphan.pdf'; mock_keys = [(orphan_key, _old_timestamp())]
    with patch('src.runtime.extension.storage_sweep.StorageService') as MockStorage, patch('src.runtime.extension.storage_sweep._list_storage_keys', return_value=mock_keys): mock_storage_instance = MagicMock(); MockStorage.return_value = mock_storage_instance; deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))
    assert deleted == 1
async def test_sweep_skips_known_db_objects(db: AsyncSession, test_user):
    'AC-extraction.8.2'; known_key = 'statements/user-1/known-id/statement.pdf'; document = UploadedDocument(user_id=test_user.id, file_path=known_key, file_hash='known_hash_sweep_test', original_filename='statement.pdf', document_type=DocumentType.BANK_STATEMENT); db.add(document); await db.commit(); mock_keys = [(known_key, _old_timestamp())]
    with patch('src.runtime.extension.storage_sweep.StorageService') as MockStorage, patch('src.runtime.extension.storage_sweep._list_storage_keys', return_value=mock_keys): mock_storage_instance = MagicMock(); MockStorage.return_value = mock_storage_instance; deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))
    assert deleted == 0; mock_storage_instance.delete_object.assert_not_called()
async def test_sweep_skips_recent_objects(db: AsyncSession, test_user):
    'AC-extraction.8.3'; recent_key = 'statements/user-1/recent-id/recent.pdf'; mock_keys = [(recent_key, _recent_timestamp())]
    with patch('src.runtime.extension.storage_sweep.StorageService') as MockStorage, patch('src.runtime.extension.storage_sweep._list_storage_keys', return_value=mock_keys): mock_storage_instance = MagicMock(); MockStorage.return_value = mock_storage_instance; deleted = await sweep_orphaned_storage_objects()
    assert deleted == 0; mock_storage_instance.delete_object.assert_not_called()
async def test_sweep_skips_when_no_bucket_configured():
    'AC-extraction.8.4'
    with patch('src.runtime.extension.storage_sweep.settings') as mock_settings: mock_settings.s3_bucket = None; deleted = await sweep_orphaned_storage_objects()
    assert deleted == 0
async def test_sweep_returns_zero_when_no_objects():
    'AC-extraction.8.5'
    with patch('src.runtime.extension.storage_sweep.settings') as mock_settings, patch('src.runtime.extension.storage_sweep._list_storage_keys', return_value=[]), patch('src.runtime.extension.storage_sweep.StorageService'): mock_settings.s3_bucket = 'test-bucket'; deleted = await sweep_orphaned_storage_objects()
    assert deleted == 0
async def test_sweep_handles_storage_list_error():
    'AC-extraction.8.6'
    with patch('src.runtime.extension.storage_sweep.settings') as mock_settings, patch('src.runtime.extension.storage_sweep.StorageService'), patch('src.runtime.extension.storage_sweep._list_storage_keys', side_effect=StorageError('connection error')): mock_settings.s3_bucket = 'test-bucket'; deleted = await sweep_orphaned_storage_objects()
    assert deleted == 0
async def test_sweep_handles_delete_error(db: AsyncSession):
    'AC-extraction.8.7'; orphan_key = 'statements/user-1/orphan-id/orphan-del-err.pdf'; mock_keys = [(orphan_key, _old_timestamp())]
    with patch('src.runtime.extension.storage_sweep.StorageService') as MockStorage, patch('src.runtime.extension.storage_sweep._list_storage_keys', return_value=mock_keys): mock_storage_instance = MagicMock(); mock_storage_instance.delete_object.side_effect = StorageError('Delete failed'); MockStorage.return_value = mock_storage_instance; deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))
    assert deleted == 0
def test_list_storage_keys_returns_paginated_keys_and_normalizes_timestamps(): 'AC-extraction.8.8'; aware_modified = datetime(2026, 5, 29, 8, 0, tzinfo=UTC); naive_modified = datetime(2026, 5, 29, 9, 30); mock_storage = MagicMock(); mock_storage.bucket = 'test-bucket'; mock_paginator = MagicMock(); mock_storage.client.get_paginator.return_value = mock_paginator; mock_paginator.paginate.return_value = [{'Contents': [{'Key': 'statements/user-a/file-a.pdf', 'LastModified': aware_modified}]}, {}, {'Contents': [{'Key': 'statements/user-b/file-b.pdf', 'LastModified': naive_modified}]}]; assert _list_storage_keys(mock_storage) == [('statements/user-a/file-a.pdf', aware_modified), ('statements/user-b/file-b.pdf', naive_modified.replace(tzinfo=UTC))]; mock_storage.client.get_paginator.assert_called_once_with('list_objects_v2'); mock_paginator.paginate.assert_called_once_with(Bucket='test-bucket', Prefix='statements/')
def test_list_storage_keys_raises_on_client_error():
    'AC-extraction.8.9'; mock_storage = MagicMock(); mock_paginator = MagicMock(); mock_storage.client.get_paginator.return_value = mock_paginator; mock_paginator.paginate.side_effect = ClientError({'Error': {'Code': 'NoSuchBucket', 'Message': 'The bucket does not exist'}}, 'ListObjectsV2')
    with pytest.raises(StorageError, match='Failed to list storage objects'): _list_storage_keys(mock_storage)
async def test_run_storage_sweep_exits_on_stop_event():
    'AC-extraction.8.10'; stop_event = asyncio.Event()
    async def mock_sweep(*args, **kwargs): stop_event.set(); return 0
    with patch('src.runtime.extension.storage_sweep.settings') as mock_settings, patch('src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects', side_effect=mock_sweep): mock_settings.enable_storage_sweep = True; mock_settings.storage_sweep_interval_seconds = 86400; await run_storage_sweep(stop_event)
async def test_run_storage_sweep_logs_when_objects_deleted():
    'AC-extraction.8.11'; stop_event = asyncio.Event()
    async def mock_sweep_with_deletions(*args, **kwargs): stop_event.set(); return 5
    with patch('src.runtime.extension.storage_sweep.settings') as mock_settings, patch('src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects', side_effect=mock_sweep_with_deletions): mock_settings.enable_storage_sweep = True; mock_settings.storage_sweep_interval_seconds = 86400; await run_storage_sweep(stop_event)
async def test_run_storage_sweep_handles_exception():
    'AC-extraction.8.12'; stop_event = asyncio.Event(); call_count = [0]
    async def maybe_raise(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1: raise RuntimeError('Unexpected error from sweep')
        stop_event.set(); return 0
    with patch('src.runtime.extension.storage_sweep.settings') as mock_settings, patch('src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects', side_effect=maybe_raise): mock_settings.enable_storage_sweep = True; mock_settings.storage_sweep_interval_seconds = 0.001; await run_storage_sweep(stop_event)
    assert call_count[0] == 2
async def test_run_storage_sweep_disabled_by_feature_flag():
    'AC-extraction.8.13'; stop_event = asyncio.Event()
    with patch('src.runtime.extension.storage_sweep.settings') as mock_settings, patch('src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects') as mock_sweep: mock_settings.enable_storage_sweep = False; await run_storage_sweep(stop_event)
    assert not stop_event.is_set(); mock_sweep.assert_not_called()
def test_grace_period_and_interval_defaults_match_issue_356(monkeypatch): 'AC-extraction.8.14'; from src.config import Settings; monkeypatch.delenv('STORAGE_SWEEP_GRACE_PERIOD_HOURS', raising=False); monkeypatch.delenv('STORAGE_SWEEP_INTERVAL_SECONDS', raising=False); defaults = Settings(_env_file=None); assert defaults.storage_sweep_grace_period_hours == 24; assert defaults.storage_sweep_interval_seconds == 86400
async def test_sweep_reads_grace_period_from_config(db: AsyncSession, test_user):
    'AC-extraction.8.15'; orphan_key = 'statements/user-1/cfg-grace/orphan.pdf'; obj_age_hours = 2; mock_keys = [(orphan_key, datetime.now(UTC) - timedelta(hours=obj_age_hours, minutes=5))]
    with patch('src.runtime.extension.storage_sweep.StorageService') as MockStorage, patch('src.runtime.extension.storage_sweep._list_storage_keys', return_value=mock_keys), patch('src.runtime.extension.storage_sweep.settings') as mock_settings: mock_settings.s3_bucket = 'test-bucket'; mock_settings.storage_sweep_grace_period_hours = 1; mock_storage_instance = MagicMock(); MockStorage.return_value = mock_storage_instance; deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))
    assert deleted == 1
    with patch('src.runtime.extension.storage_sweep.StorageService') as MockStorage, patch('src.runtime.extension.storage_sweep._list_storage_keys', return_value=mock_keys), patch('src.runtime.extension.storage_sweep.settings') as mock_settings: mock_settings.s3_bucket = 'test-bucket'; mock_settings.storage_sweep_grace_period_hours = 24; mock_storage_instance = MagicMock(); MockStorage.return_value = mock_storage_instance; deleted = await sweep_orphaned_storage_objects(sessionmaker=_make_db_sessionmaker(db))
    assert deleted == 0; mock_storage_instance.delete_object.assert_not_called()
async def test_run_storage_sweep_reads_interval_from_config():
    'AC-extraction.8.16'; stop_event = asyncio.Event(); observed: dict[str, float] = {}
    async def fake_wait_for(_awaitable, timeout): observed['timeout'] = timeout; stop_event.set(); _awaitable.close(); raise TimeoutError
    async def mock_sweep(*args, **kwargs): return 0
    with patch('src.runtime.extension.storage_sweep.settings') as mock_settings, patch('src.runtime.extension.storage_sweep.sweep_orphaned_storage_objects', side_effect=mock_sweep), patch('src.runtime.extension.storage_sweep.asyncio.wait_for', side_effect=fake_wait_for): mock_settings.enable_storage_sweep = True; mock_settings.storage_sweep_interval_seconds = 12345; await run_storage_sweep(stop_event)
    assert observed['timeout'] == 12345
@pytest.mark.parametrize('preview_env', ['preview', 'branch-main', 'pr-42'])
async def test_storage_sweep_skipped_in_preview_environment(preview_env: str):
    'AC-extraction.8.13'; stop_event = asyncio.Event()
    with patch('src.runtime.extension.storage_sweep.settings') as mock_settings, patch('src.runtime.extension.storage_sweep.StorageService') as MockStorage, patch('src.runtime.extension.storage_sweep._list_storage_keys') as mock_list: mock_settings.environment = preview_env; mock_settings.enable_storage_sweep = True; mock_settings.s3_bucket = 'finance-report-staging'; deleted = await sweep_orphaned_storage_objects(); assert deleted == 0; MockStorage.assert_not_called(); mock_list.assert_not_called(); await run_storage_sweep(stop_event); assert not stop_event.is_set(); MockStorage.assert_not_called()
