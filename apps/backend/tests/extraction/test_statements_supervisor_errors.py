import asyncio; from datetime import date; from io import BytesIO; from unittest.mock import AsyncMock, MagicMock, patch; from uuid import uuid4; import pytest; from botocore.exceptions import BotoCoreError, ClientError; from fastapi import HTTPException, UploadFile; from sqlalchemy.engine import Engine; from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker; from src.database import create_session_maker_from_db; from src.extraction import BankStatementStatus, ParseJob, RetryableStatementIngestionError; from src.extraction.extension.statement_parsing_supervisor import run_parsing_supervisor; from src.extraction.orm.statement_summary import StatementSummary; from src.routers.statements import delete_statement, get_statement, list_statement_transactions, retry_statement_parsing, upload_statement; from src.runtime import StorageError, StorageService; from tests.factories import StatementSummaryFactory; from tests.statement_ingestion import execute_statement_ingestion as parse_statement_background; make_upload_file = lambda name, content: UploadFile(filename=name, file=BytesIO(content))
from tests.statement_ingestion import run_for
async def test_create_session_maker_variants():
    mock_db = MagicMock(spec=AsyncSession); mock_async_engine = MagicMock(spec=AsyncEngine); mock_db.bind = mock_async_engine; maker = create_session_maker_from_db(mock_db); assert isinstance(maker, async_sessionmaker); mock_engine = MagicMock(spec=Engine); mock_engine._async_engine = mock_async_engine; mock_db.bind = mock_engine; maker = create_session_maker_from_db(mock_db); assert isinstance(maker, async_sessionmaker); mock_obj = MagicMock(); mock_obj.async_engine = mock_async_engine; mock_db.bind = mock_obj; maker = create_session_maker_from_db(mock_db); assert isinstance(maker, async_sessionmaker); mock_db.bind = MagicMock(); mock_db.get_bind.return_value = None; from src import database; original_test_maker = database.get_test_session_maker(); database.set_test_session_maker(None)
    try:
        with pytest.raises(RuntimeError, match='Async engine unavailable'): create_session_maker_from_db(mock_db)
    finally: database.set_test_session_maker(original_test_maker)
    _m1_mock_s3 = MagicMock(); StorageService._checked_buckets.clear()
    with patch('boto3.client', return_value=_m1_mock_s3):
        _m1_service = StorageService(bucket='err-bucket'); _m1_mock_s3.head_bucket.side_effect = ClientError({'Error': {'Code': '404', 'Message': 'Not Found'}}, 'head_bucket'); _m1_mock_s3.create_bucket.side_effect = ClientError({'Error': {'Code': '500', 'Message': 'Error'}}, 'create_bucket')
        with pytest.raises(StorageError, match='Failed to create bucket'): _m1_service.upload_bytes(key='k', content=b'c')
        StorageService._checked_buckets.clear(); _m1_mock_s3.head_bucket.side_effect = ClientError({'Error': {'Code': '403', 'Message': 'Forbidden'}}, 'head_bucket')
        with pytest.raises(StorageError, match='Failed to access bucket'): _m1_service.upload_bytes(key='k', content=b'c')
        StorageService._checked_buckets.clear(); _m1_mock_s3.head_bucket.side_effect = BotoCoreError()
        with pytest.raises(StorageError, match='Failed to access bucket'): _m1_service.upload_bytes(key='k', content=b'c')
        _m1_mock_s3.head_bucket.side_effect = None; _m1_mock_s3.head_bucket.return_value = {}; _m1_mock_s3.delete_object.side_effect = BotoCoreError()
        with pytest.raises(StorageError, match='Failed to delete'): _m1_service.delete_object('k')
async def test_parsing_supervisor_error_path(monkeypatch):
    stop_event = asyncio.Event(); call_count = 0
    async def failing_reset(sessionmaker=None):
        nonlocal call_count; call_count += 1
        if call_count == 1: raise Exception('Coverage test failure')
        stop_event.set(); return 0
    monkeypatch.setattr('src.extraction.extension.statement_parsing_supervisor.reap_stale_parsing_runs', failing_reset); patch_target = 'src.extraction.extension.statement_parsing_supervisor.PARSING_SUPERVISOR_INTERVAL_SECONDS'
    with patch(patch_target, 0.01): await run_parsing_supervisor(stop_event)
    assert call_count >= 2
async def test_statement_router_error_cases(db, test_user, monkeypatch):
    sid = uuid4(); uid = test_user.id
    with pytest.raises(HTTPException) as exc: await get_statement(sid, db, uid)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc: await list_statement_transactions(sid, db, uid)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc: await delete_statement(sid, db, uid)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc: from src.schemas import RetryParsingRequest; await retry_statement_parsing(sid, RetryParsingRequest(model=None), db=db, user_id=uid)
    assert exc.value.status_code == 404; statement = StatementSummaryFactory.build(id=sid, user_id=uid, status=BankStatementStatus.UPLOADED, file_hash='h_err', institution='DBS'); db.add(statement); await db.commit()
    with patch('src.routers.statements.StorageService') as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value; mock_storage.get_object.return_value = b'content'
        with pytest.raises(HTTPException) as exc: await retry_statement_parsing(sid, RetryParsingRequest(model=None), db=db, user_id=uid)
        assert exc.value.status_code == 400
    session_maker = create_session_maker_from_db(db); await parse_statement_background(job=ParseJob(statement_id=uuid4(), run_id=uuid4(), filename='f', institution='i', user_id=uid, account_id=None, file_hash='h', storage_key='k', model=None), content=b'', session_maker=session_maker)
    with patch('src.routers.statements.StorageService') as mock_storage_cls: mock_storage = mock_storage_cls.return_value; mock_storage.delete_object.side_effect = StorageError('Failed'); await delete_statement(sid, db, uid); mock_storage.delete_object.assert_not_called(); result = await db.get(StatementSummary, sid); assert result is not None; assert result.status is BankStatementStatus.RETIRED
async def test_upload_statement_db_commit_failure(db, test_user, monkeypatch):
    monkeypatch.setattr(db, 'commit', AsyncMock(side_effect=Exception('DB Fail')))
    with patch('src.routers.statements.StorageService') as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value; mock_storage.delete_object.side_effect = StorageError('Storage Fail'); upload_file = make_upload_file('test.pdf', b'content')
        with pytest.raises(HTTPException) as exc: await upload_statement(file=upload_file, institution='DBS', model=None, db=db, user_id=test_user.id)
        assert exc.value.status_code == 500
async def test_parse_statement_background_error_paths(db, test_user, monkeypatch):
    sid = uuid4(); uid = test_user.id; statement = StatementSummaryFactory.build(id=sid, user_id=uid, status=BankStatementStatus.PARSING, file_hash='h2', institution='DBS'); db.add(statement); await db.commit(); session_maker = create_session_maker_from_db(db)
    with patch('src.routers.statements.StorageService') as mock_storage_cls: mock_storage = mock_storage_cls.return_value; mock_storage.generate_presigned_url.side_effect = StorageError('S3 Fail'); await parse_statement_background(job=ParseJob(statement_id=sid, run_id=await run_for(db, sid), filename='f', institution='i', user_id=uid, account_id=None, file_hash='h2', storage_key='k', model=None), content=b'', session_maker=session_maker); await db.refresh(statement); assert statement.status == BankStatementStatus.REJECTED; assert statement.validation_error is not None
    statement.status = BankStatementStatus.PARSING; await db.commit()
    with patch('src.routers.statements.StorageService') as mock_storage_cls: mock_storage = mock_storage_cls.return_value; mock_storage.generate_presigned_url.return_value = 'http://url'; from src.extraction.extension.service import ExtractionError; mock_parse = AsyncMock(side_effect=ExtractionError('Parse Fail')); monkeypatch.setattr('src.extraction.extension.statement_parsing.ExtractionService.parse_document', mock_parse); await parse_statement_background(job=ParseJob(statement_id=sid, run_id=await run_for(db, sid), filename='f', institution='i', user_id=uid, account_id=None, file_hash='h2', storage_key='k', model=None), content=b'', session_maker=session_maker); await db.refresh(statement); assert statement.status == BankStatementStatus.REJECTED; assert 'Parse Fail' in statement.validation_error
    statement.status = BankStatementStatus.PARSING; statement.validation_error = None; await db.commit()
    with patch('src.routers.statements.StorageService') as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value; mock_storage.generate_presigned_url.return_value = 'http://url'; mock_parse = AsyncMock(side_effect=Exception('Unknown')); monkeypatch.setattr('src.extraction.extension.statement_parsing.ExtractionService.parse_document', mock_parse)
        with pytest.raises(RetryableStatementIngestionError, match='Unknown'): await parse_statement_background(job=ParseJob(statement_id=sid, run_id=await run_for(db, sid), filename='f', institution='i', user_id=uid, account_id=None, file_hash='h2', storage_key='k', model=None), content=b'', session_maker=session_maker)
        await db.refresh(statement); assert statement.status == BankStatementStatus.PARSING; assert statement.validation_error is None
async def test_retry_statement_parsing_error_paths(db, test_user):
    sid = uuid4(); uid = test_user.id; from tests.factories import UploadedDocumentFactory; document = await UploadedDocumentFactory.create_async(db, uid, file_hash='h3'); statement = StatementSummaryFactory.build(id=sid, user_id=uid, uploaded_document_id=document.id, status=BankStatementStatus.PARSED, file_hash='h3', institution='DBS'); db.add(statement); await db.commit()
    with patch('src.routers.statements.StorageService') as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value; mock_storage.get_object.side_effect = StorageError('S3 Fail'); from src.schemas import RetryParsingRequest
        with pytest.raises(HTTPException) as exc: await retry_statement_parsing(sid, RetryParsingRequest(model=None), db=db, user_id=uid)
        assert exc.value.status_code == 503
    with patch('src.routers.statements.StorageService') as mock_storage_cls: mock_storage = mock_storage_cls.return_value; mock_storage.get_object.return_value = b'content'; resp = await retry_statement_parsing(sid, RetryParsingRequest(model=None), db=db, user_id=uid); assert resp.status == BankStatementStatus.PARSING
async def test_report_router_error_handlers(db, test_user, monkeypatch):
    from src.reporting import ReportError; from src.routers.reports import account_trend, balance_sheet, cash_flow, category_breakdown, income_statement; from src.schemas.reporting import BreakdownPeriod, BreakdownType, TrendPeriod; uid = test_user.id
    async def mock_fail(*args, **kwargs): raise ReportError('Report Fail')
    monkeypatch.setattr('src.routers.reports.generate_balance_sheet', mock_fail); monkeypatch.setattr('src.routers.reports.generate_income_statement', mock_fail); monkeypatch.setattr('src.routers.reports.generate_cash_flow', mock_fail); monkeypatch.setattr('src.routers.reports.get_account_trend', mock_fail); monkeypatch.setattr('src.routers.reports.get_category_breakdown', mock_fail)
    with pytest.raises(HTTPException) as exc: await balance_sheet(db=db, user_id=uid)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc: await income_statement(start_date=date.today(), end_date=date.today(), db=db, user_id=uid)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc: await cash_flow(start_date=date.today(), end_date=date.today(), db=db, user_id=uid)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc: await account_trend(account_id=uuid4(), period=TrendPeriod.MONTHLY, db=db, user_id=uid)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc: await category_breakdown(breakdown_type=BreakdownType.EXPENSE, period=BreakdownPeriod.MONTHLY, db=db, user_id=uid)
    assert exc.value.status_code == 400
