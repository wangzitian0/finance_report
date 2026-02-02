"""Tests to close coverage gaps for Issue #63."""

import asyncio
from datetime import date
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.database import create_session_maker_from_db
from src.models.statement import BankStatement, BankStatementStatus
from src.routers.statements import (
    _parse_statement_background,
    approve_statement,
    delete_statement,
    get_statement,
    list_statement_transactions,
    reject_statement,
    retry_statement_parsing,
    upload_statement,
)
from src.schemas import StatementDecisionRequest
from src.services.statement_parsing_supervisor import (
    run_parsing_supervisor,
)
from src.services.storage import StorageError, StorageService


def make_upload_file(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(content))


@pytest.mark.asyncio
async def test_create_session_maker_variants():
    """Test create_session_maker_from_db with various bind types."""
    mock_db = MagicMock(spec=AsyncSession)

    # 1. AsyncEngine directly
    mock_async_engine = MagicMock(spec=AsyncEngine)
    mock_db.bind = mock_async_engine
    maker = create_session_maker_from_db(mock_db)
    assert isinstance(maker, async_sessionmaker)

    # 2. Engine with _async_engine
    mock_engine = MagicMock(spec=Engine)
    mock_engine._async_engine = mock_async_engine
    mock_db.bind = mock_engine
    maker = create_session_maker_from_db(mock_db)
    assert isinstance(maker, async_sessionmaker)

    # 3. Object with async_engine attribute
    mock_obj = MagicMock()
    mock_obj.async_engine = mock_async_engine
    mock_db.bind = mock_obj
    maker = create_session_maker_from_db(mock_db)
    assert isinstance(maker, async_sessionmaker)

    # 4. Failure case - temporarily clear test session maker to test error path
    mock_db.bind = MagicMock()  # No async engine
    mock_db.get_bind.return_value = None

    from src import database

    original_test_maker = database.get_test_session_maker()
    database.set_test_session_maker(None)
    try:
        with pytest.raises(RuntimeError, match="Async engine unavailable"):
            create_session_maker_from_db(mock_db)
    finally:
        database.set_test_session_maker(original_test_maker)


@pytest.mark.asyncio
async def test_storage_service_errors():
    """Test StorageService error paths."""
    mock_s3 = MagicMock()
    StorageService._checked_buckets.clear()

    with patch("boto3.client", return_value=mock_s3):
        service = StorageService(bucket="err-bucket")

        # Bucket creation failure
        mock_s3.head_bucket.side_effect = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "head_bucket")
        mock_s3.create_bucket.side_effect = ClientError({"Error": {"Code": "500", "Message": "Error"}}, "create_bucket")
        with pytest.raises(StorageError, match="Failed to create bucket"):
            service.upload_bytes(key="k", content=b"c")

        # Access denied failure (not 404)
        StorageService._checked_buckets.clear()
        mock_s3.head_bucket.side_effect = ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "head_bucket")
        with pytest.raises(StorageError, match="Failed to access bucket"):
            service.upload_bytes(key="k", content=b"c")

        # BotoCoreError in head_bucket
        StorageService._checked_buckets.clear()
        mock_s3.head_bucket.side_effect = BotoCoreError()
        with pytest.raises(StorageError, match="Failed to access bucket"):
            service.upload_bytes(key="k", content=b"c")

        # Deletion error
        mock_s3.head_bucket.side_effect = None
        mock_s3.head_bucket.return_value = {}
        mock_s3.delete_object.side_effect = BotoCoreError()
        with pytest.raises(StorageError, match="Failed to delete"):
            service.delete_object("k")


@pytest.mark.asyncio
async def test_parsing_supervisor_error_path(monkeypatch):
    """Test supervisor generic exception handling."""
    stop_event = asyncio.Event()

    call_count = 0

    async def failing_reset(sessionmaker=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Coverage test failure")
        stop_event.set()
        return 0

    monkeypatch.setattr("src.services.statement_parsing_supervisor.reset_stale_parsing_jobs", failing_reset)

    # Use a small timeout to avoid hanging
    patch_target = "src.services.statement_parsing_supervisor.PARSING_SUPERVISOR_INTERVAL_SECONDS"
    with patch(patch_target, 0.01):
        await run_parsing_supervisor(stop_event)

    assert call_count >= 2


@pytest.mark.asyncio
async def test_statement_router_error_cases(db, test_user, monkeypatch):
    """Test 404s and error handlers in statements router."""
    sid = uuid4()
    uid = test_user.id

    # 404s
    with pytest.raises(HTTPException) as exc:
        await get_statement(sid, db, uid)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await list_statement_transactions(sid, db, uid)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await approve_statement(sid, StatementDecisionRequest(notes=""), db, uid)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await reject_statement(sid, StatementDecisionRequest(notes=""), db, uid)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await delete_statement(sid, db, uid)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        from src.schemas import RetryParsingRequest

        await retry_statement_parsing(sid, RetryParsingRequest(model=None), db, uid)
    assert exc.value.status_code == 404

    # Retry invalid status
    from src.models.statement import BankStatementStatus

    statement = BankStatement(
        id=sid,
        user_id=uid,
        status=BankStatementStatus.UPLOADED,  # Not in allowed list for retry
        file_path="p",
        file_hash="h_err",
        original_filename="f.pdf",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value
        mock_storage.get_object.return_value = b"content"
        with pytest.raises(HTTPException) as exc:
            await retry_statement_parsing(sid, RetryParsingRequest(model=None), db, uid)
        assert exc.value.status_code == 400

    # Background parsing not found
    session_maker = create_session_maker_from_db(db)
    await _parse_statement_background(
        statement_id=uuid4(),
        filename="f",
        institution="i",
        user_id=uid,
        account_id=None,
        file_hash="h",
        storage_key="k",
        content=b"",
        model=None,
        session_maker=session_maker,
    )

    # Delete statement storage error (should continue to DB delete)
    # Already created sid in DB above
    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value
        mock_storage.delete_object.side_effect = StorageError("Failed")
        await delete_statement(sid, db, uid)
        # Verify it was deleted from DB
        result = await db.get(BankStatement, sid)
        assert result is None


@pytest.mark.asyncio
async def test_upload_statement_db_commit_failure(db, test_user, monkeypatch):
    """Test upload_statement cleanup logic when DB commit fails."""
    from src.config import settings

    # Mock commit to fail
    monkeypatch.setattr(db, "commit", AsyncMock(side_effect=Exception("DB Fail")))

    # Mock storage cleanup to also fail (to cover line 243)
    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value
        mock_storage.delete_object.side_effect = StorageError("Storage Fail")

        upload_file = make_upload_file("test.pdf", b"content")
        # Provide primary_model to pass validation
        with pytest.raises(HTTPException) as exc:
            await upload_statement(
                file=upload_file,
                institution="DBS",
                model=settings.primary_model,
                db=db,
                user_id=test_user.id,
            )
        assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_parse_statement_background_error_paths(db, test_user):
    """Test background parsing error handlers."""
    sid = uuid4()
    uid = test_user.id

    # Setup a statement in DB
    statement = BankStatement(
        id=sid,
        user_id=uid,
        status=BankStatementStatus.PARSING,
        file_path="p",
        file_hash="h2",
        original_filename="f.pdf",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    session_maker = create_session_maker_from_db(db)

    # 1. StorageError in background (presigned URL failure)
    # Presigned URL failure now rejects PDFs without a public URL.
    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value
        mock_storage.generate_presigned_url.side_effect = StorageError("S3 Fail")

        await _parse_statement_background(
            statement_id=sid,
            filename="f",
            institution="i",
            user_id=uid,
            account_id=None,
            file_hash="h2",
            storage_key="k",
            content=b"",
            model=None,
            session_maker=session_maker,
        )

        await db.refresh(statement)
        assert statement.status == BankStatementStatus.REJECTED
        # Flexible check for failure reason
        error_msg = statement.validation_error.lower()
        assert "public url" in error_msg

    # 2. ExtractionError in background
    statement.status = BankStatementStatus.PARSING
    await db.commit()
    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value
        mock_storage.generate_presigned_url.return_value = "http://url"

        from src.services.extraction import ExtractionError

        with patch("src.routers.statements.ExtractionService") as mock_ext_cls:
            mock_ext = mock_ext_cls.return_value
            mock_ext.parse_document.side_effect = ExtractionError("Parse Fail")

            await _parse_statement_background(
                statement_id=sid,
                filename="f",
                institution="i",
                user_id=uid,
                account_id=None,
                file_hash="h2",
                storage_key="k",
                content=b"",
                model=None,
                session_maker=session_maker,
            )

            await db.refresh(statement)
            assert statement.status == BankStatementStatus.REJECTED
            assert "Parse Fail" in statement.validation_error

    # 3. Generic Exception in background
    statement.status = BankStatementStatus.PARSING
    await db.commit()
    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value
        mock_storage.generate_presigned_url.return_value = "http://url"

        with patch("src.routers.statements.ExtractionService") as mock_ext_cls:
            mock_ext = mock_ext_cls.return_value
            mock_ext.parse_document.side_effect = Exception("Unknown")

            await _parse_statement_background(
                statement_id=sid,
                filename="f",
                institution="i",
                user_id=uid,
                account_id=None,
                file_hash="h2",
                storage_key="k",
                content=b"",
                model=None,
                session_maker=session_maker,
            )

            await db.refresh(statement)
            assert statement.status == BankStatementStatus.REJECTED
            assert "Unknown" in statement.validation_error


@pytest.mark.asyncio
async def test_retry_statement_parsing_error_paths(db, test_user):
    """Test retry endpoint error handlers."""
    sid = uuid4()
    uid = test_user.id

    # Setup a statement in DB (must be PARSED or REJECTED to retry)
    statement = BankStatement(
        id=sid,
        user_id=uid,
        status=BankStatementStatus.PARSED,
        file_path="p",
        file_hash="h3",
        original_filename="f.pdf",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    # 1. StorageError in retry
    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value
        mock_storage.get_object.side_effect = StorageError("S3 Fail")

        from src.schemas import RetryParsingRequest

        with pytest.raises(HTTPException) as exc:
            await retry_statement_parsing(sid, RetryParsingRequest(model=None), db, uid)
        assert exc.value.status_code == 503

    # 2. ExtractionError in retry
    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value
        mock_storage.get_object.return_value = b"content"

        # Note: retry now uses background task, so it returns 200/PARSING
        # unless it fails BEFORE starting the task.
        # To test pre-task failures, we can mock something earlier.
        # But wait, retry_statement_parsing now returns 200 if task starts.
        # Let's adjust expectations.
        resp = await retry_statement_parsing(sid, RetryParsingRequest(model=None), db, uid)
        assert resp.status == BankStatementStatus.PARSING


@pytest.mark.asyncio
async def test_report_router_error_handlers(db, test_user, monkeypatch):
    """Test HTTPException wrappers for ReportError in reports router."""
    from src.routers.reports import (
        account_trend,
        balance_sheet,
        cash_flow,
        category_breakdown,
        income_statement,
    )
    from src.schemas.reporting import BreakdownPeriod, BreakdownType, TrendPeriod
    from src.services.reporting import ReportError

    uid = test_user.id

    # Mock services to raise ReportError
    async def mock_fail(*args, **kwargs):
        raise ReportError("Report Fail")

    monkeypatch.setattr("src.routers.reports.generate_balance_sheet", mock_fail)
    monkeypatch.setattr("src.routers.reports.generate_income_statement", mock_fail)
    monkeypatch.setattr("src.routers.reports.generate_cash_flow", mock_fail)
    monkeypatch.setattr("src.routers.reports.get_account_trend", mock_fail)
    monkeypatch.setattr("src.routers.reports.get_category_breakdown", mock_fail)

    with pytest.raises(HTTPException) as exc:
        await balance_sheet(db=db, user_id=uid)
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        await income_statement(start_date=date.today(), end_date=date.today(), db=db, user_id=uid)
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        await cash_flow(start_date=date.today(), end_date=date.today(), db=db, user_id=uid)
    assert exc.value.status_code == 400

    # Provide values explicitly to avoid Query object attribute errors
    with pytest.raises(HTTPException) as exc:
        await account_trend(account_id=uuid4(), period=TrendPeriod.MONTHLY, db=db, user_id=uid)
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        await category_breakdown(
            breakdown_type=BreakdownType.EXPENSE,
            period=BreakdownPeriod.MONTHLY,
            db=db,
            user_id=uid,
        )
    assert exc.value.status_code == 400
