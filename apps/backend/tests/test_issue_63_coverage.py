"""Tests to close coverage gaps for Issue #63."""

import asyncio
import logging
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.database import create_session_maker_from_db, init_db
from src.models.statement import BankStatement, BankStatementStatus, BankStatementTransaction
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
from src.services.statement_parsing_supervisor import reset_stale_parsing_jobs, run_parsing_supervisor
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
    
    # 4. Failure case
    mock_db.bind = MagicMock() # No async engine
    mock_db.get_bind.return_value = None
    with pytest.raises(RuntimeError, match="Async engine unavailable"):
        create_session_maker_from_db(mock_db)


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
                user_id=test_user.id
            )
        assert exc.value.status_code == 500
