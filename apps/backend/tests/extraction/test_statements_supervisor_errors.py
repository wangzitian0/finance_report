import asyncio
from datetime import date
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import UploadFile
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src import database
from src.database import create_session_maker_from_db
from src.extraction import BankStatementStatus, ParseJob, RetryableStatementIngestionError
from src.extraction.extension.service import ExtractionError
from src.extraction.extension.statement_parsing_supervisor import run_parsing_supervisor
from src.platform import DomainError
from src.reporting import ReportError
from src.request_context import RequestContext
from src.routers.reports import balance_sheet, cash_flow, income_statement
from src.routers.statements import create_statement_run, get_statement, upload_statement
from src.runtime import StorageError, StorageService
from src.schemas import StatementRunRequest
from tests.factories import StatementSummaryFactory, UploadedDocumentFactory
from tests.statement_ingestion import execute_statement_ingestion as parse_statement_background, run_for


async def test_create_session_maker_variants():
    mock_db, mock_async_engine, mock_engine, mock_obj = MagicMock(spec=AsyncSession), MagicMock(spec=AsyncEngine), MagicMock(spec=Engine), MagicMock()
    mock_engine._async_engine = mock_obj.async_engine = mock_async_engine
    for bind in (mock_async_engine, mock_engine, mock_obj):
        mock_db.bind = bind
        assert isinstance(create_session_maker_from_db(mock_db), async_sessionmaker)

    mock_db.bind, mock_db.get_bind.return_value, orig = MagicMock(), None, database.get_test_session_maker()
    database.set_test_session_maker(None)
    try:
        with pytest.raises(RuntimeError, match="Async engine unavailable"):
            create_session_maker_from_db(mock_db)
    finally:
        database.set_test_session_maker(orig)


@pytest.mark.parametrize(
    ("head_exc", "create_exc", "delete_exc", "match"),
    [
        (ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "head_bucket"), ClientError({"Error": {"Code": "500", "Message": "Error"}}, "create_bucket"), None, "Failed to create bucket"),
        (ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "head_bucket"), None, None, "Failed to access bucket"),
        (BotoCoreError(), None, None, "Failed to access bucket"),
        (None, None, BotoCoreError(), "Failed to delete"),
    ],
)
def test_storage_service_bucket_and_delete_errors(head_exc, create_exc, delete_exc, match):
    mock_s3 = MagicMock()
    StorageService._checked_buckets.clear()
    mock_s3.head_bucket.side_effect, mock_s3.head_bucket.return_value, mock_s3.create_bucket.side_effect, mock_s3.delete_object.side_effect = head_exc, {}, create_exc, delete_exc
    with patch("boto3.client", return_value=mock_s3), pytest.raises(StorageError, match=match):
        service = StorageService(bucket="err-bucket")
        service.delete_object("k") if delete_exc else service.upload_bytes(key="k", content=b"c")


async def test_parsing_supervisor_and_router_error_paths(db, test_user, monkeypatch):
    stop_event, call_count = asyncio.Event(), 0

    async def failing_reset(sessionmaker=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Coverage test failure")
        stop_event.set()
        return 0

    monkeypatch.setattr("src.extraction.extension.statement_parsing_supervisor.reap_stale_parsing_runs", failing_reset)
    with patch("src.extraction.extension.statement_parsing_supervisor.PARSING_SUPERVISOR_INTERVAL_SECONDS", 0.01):
        await run_parsing_supervisor(stop_event)
    assert call_count >= 2

    with pytest.raises(DomainError) as exc:
        await get_statement(uuid4(), RequestContext(db, test_user.id))
    assert exc.value.status_code == 404

    with monkeypatch.context() as mp:
        mp.setattr(db, "commit", AsyncMock(side_effect=Exception("DB Fail")))
        with patch("src.routers.statements.StorageService") as mock_storage_cls, pytest.raises(DomainError) as exc2:
            mock_storage_cls.return_value.delete_object.side_effect = StorageError("Storage Fail")
            await upload_statement(file=UploadFile(filename="test.pdf", file=BytesIO(b"content")), institution="DBS", model=None, ctx=RequestContext(db, test_user.id))
        assert exc2.value.status_code == 500


@pytest.mark.parametrize(
    ("s3_error", "parse_exc", "expected_status", "expected_err"),
    [(True, None, BankStatementStatus.REJECTED, True), (False, ExtractionError("Parse Fail"), BankStatementStatus.REJECTED, "Parse Fail"), (False, Exception("Unknown"), BankStatementStatus.PARSING, None)],
)
async def test_parse_statement_background_error_paths(db, test_user, monkeypatch, s3_error, parse_exc, expected_status, expected_err):
    sid = uuid4()
    statement = StatementSummaryFactory.build(id=sid, user_id=test_user.id, status=BankStatementStatus.PARSING, file_hash=f"h-{sid.hex[:8]}", institution="DBS")
    db.add(statement)
    await db.commit()
    job = ParseJob(statement_id=sid, run_id=await run_for(db, sid), filename="f", institution="i", user_id=test_user.id, account_id=None, file_hash=statement.file_hash, storage_key="k", model=None)
    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        if s3_error:
            mock_storage_cls.return_value.generate_presigned_url.side_effect = StorageError("S3 Fail")
        else:
            mock_storage_cls.return_value.generate_presigned_url.return_value = "http://url"
            monkeypatch.setattr("src.extraction.extension.statement_parsing.ExtractionService.parse_document", AsyncMock(side_effect=parse_exc))
        if expected_status is BankStatementStatus.PARSING:
            with pytest.raises(RetryableStatementIngestionError, match="Unknown"):
                await parse_statement_background(job=job, content=b"", session_maker=create_session_maker_from_db(db))
        else:
            await parse_statement_background(job=job, content=b"", session_maker=create_session_maker_from_db(db))
    await db.refresh(statement)
    assert statement.status == expected_status and ((statement.validation_error is not None) if expected_err is True else (statement.validation_error is None if expected_err is None else expected_err in statement.validation_error))


async def test_create_statement_run_and_report_error_handlers(db, test_user, monkeypatch):
    sid, uid = uuid4(), test_user.id
    document = await UploadedDocumentFactory.create_async(db, uid, file_hash="h3")
    statement = StatementSummaryFactory.build(id=sid, user_id=uid, uploaded_document_id=document.id, status=BankStatementStatus.PARSED, file_hash="h3", institution="DBS")
    db.add(statement)
    await db.commit()
    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage_cls.return_value.get_object.side_effect = StorageError("S3 Fail")
        with pytest.raises(DomainError) as exc:
            await create_statement_run(sid, StatementRunRequest(model=None), ctx=RequestContext(db, uid))
        assert exc.value.status_code == 503
        mock_storage_cls.return_value.get_object.side_effect, mock_storage_cls.return_value.get_object.return_value = None, b"content"
        resp = await create_statement_run(sid, StatementRunRequest(model=None), ctx=RequestContext(db, uid))
    await db.refresh(statement)
    assert resp.state in ("requested", "running") and statement.status == BankStatementStatus.PARSING

    async def mock_fail(*_args, **_kwargs):
        raise ReportError("Report Fail")

    for name in ("generate_balance_sheet", "generate_income_statement", "generate_cash_flow"):
        monkeypatch.setattr(f"src.routers.reports.{name}", mock_fail)
    ctx = RequestContext(db, uid)
    for call in (balance_sheet(ctx=ctx), income_statement(start_date=date.today(), end_date=date.today(), ctx=ctx), cash_flow(start_date=date.today(), end_date=date.today(), ctx=ctx)):
        with pytest.raises(DomainError) as exc:
            await call
        assert exc.value.status_code == 400
