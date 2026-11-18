from __future__ import annotations

from datetime import date
from decimal import Decimal
import inspect
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from src.extraction import (
    BankStatementStatus,
    DocumentType,
    UploadedDocument,
    create_statement_account_from_confirmation,
    effective_statement_transaction_filter,
)
from src.extraction.extension import statement_pipeline
from src.extraction.extension.statement_parsing import handle_parse_failure
from src.extraction.extension.statement_posting import is_high_confidence_auto_approve_candidate
from src.extraction.orm.layer2 import AtomicTransaction
from src.identity import User
from src.routers import statements as statements_router
from tests.api._statement_router_fixtures import add_txn, build_statement

pytestmark = pytest.mark.asyncio


async def test_build_statement_storage_key_sanitizes_extension() -> None:
    statement_id = uuid4()
    assert (
        statements_router.build_statement_storage_key(
            statement_id=statement_id, file_hash="abcdef1234567890ffff", extension="PDF"
        )
        == f"statements/{statement_id}/abcdef1234567890.pdf"
    )
    assert (
        statements_router.build_statement_storage_key(
            statement_id=statement_id, file_hash="abcdef1234567890ffff", extension="exe"
        )
        == f"statements/{statement_id}/abcdef1234567890.bin"
    )
    statement_pipeline.PENDING_PARSE_TASKS.clear()
    await statement_pipeline.wait_for_parse_tasks()


async def test_is_high_confidence_auto_approve_candidate_requires_all_guards(test_user) -> None:
    statement = build_statement(test_user.id, "hash_candidate_true", 85)
    statement.status = BankStatementStatus.APPROVED
    assert is_high_confidence_auto_approve_candidate(statement) is True
    statement.confidence_score = 84
    assert is_high_confidence_auto_approve_candidate(statement) is False
    statement.confidence_score = 90
    statement.balance_validated = False
    assert is_high_confidence_auto_approve_candidate(statement) is False
    statement.balance_validated = True
    statement.status = BankStatementStatus.PARSED
    assert is_high_confidence_auto_approve_candidate(statement) is False


async def test_handle_parse_failure_inner_exception(db, test_user) -> None:
    statement = build_statement(test_user.id, "hash_inner_exc", 50)
    db.add(statement)
    await db.commit()
    statement_id = statement.id
    mock_session = AsyncMock(spec=db)
    mock_session.rollback = AsyncMock()
    mock_session.get = AsyncMock(side_effect=Exception("DB completely down"))
    mock_session.commit = AsyncMock()
    fake_stmt = MagicMock()
    fake_stmt.id = statement_id
    await handle_parse_failure(fake_stmt, mock_session, message="parse error")
    mock_session.get.assert_awaited_once()


async def test_handle_parse_failure_statement_not_found_after_rollback(db, test_user) -> None:
    mock_session = AsyncMock(spec=db)
    mock_session.rollback = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    fake_stmt = MagicMock()
    fake_stmt.id = uuid4()
    await handle_parse_failure(fake_stmt, mock_session, message="parse error")
    mock_session.get.assert_awaited_once()


async def test_handle_parse_failure_rollback_fails(db, test_user) -> None:
    statement = build_statement(test_user.id, "hash_rb_fail", 50)
    db.add(statement)
    await db.commit()
    statement_id = statement.id
    mock_session = AsyncMock(spec=db)
    mock_session.rollback = AsyncMock(side_effect=Exception("Rollback failed"))
    mock_session.get = AsyncMock(return_value=None)
    fake_stmt = MagicMock()
    fake_stmt.id = statement_id
    await handle_parse_failure(fake_stmt, mock_session, message="parse error")
    mock_session.rollback.assert_awaited_once()


async def test_rejected_statement_transactions_excluded_from_effective_filter(db, test_user) -> None:
    statement = build_statement(test_user.id, "hash_rejected_leak_test", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.flush()
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 15), description="Rejected statement transaction", amount=Decimal("50.00"), direction="IN"
    )
    await db.commit()
    scoped_txns = (
        await db.scalars(select(AtomicTransaction.id).where(effective_statement_transaction_filter(test_user.id, statement.id)))
    ).all()
    assert len(scoped_txns) == 0, f"Expected 0 transactions for rejected statement, got {len(scoped_txns)}"
    global_txns = (await db.scalars(select(AtomicTransaction.id).where(effective_statement_transaction_filter(test_user.id)))).all()
    assert txn.id not in global_txns, "Rejected statement transaction leaked into global effective filter"


async def test_resolve_uploaded_document_enforces_user_isolation(db, test_user) -> None:
    other_user = User(
        id=uuid4(), email=f"other_{uuid4().hex[:8]}@example.com", name="Other User", hashed_password="test_hashed_password"
    )
    db.add(other_user)
    await db.flush()
    other_doc = UploadedDocument(
        id=uuid4(),
        user_id=other_user.id,
        file_path="other_path.pdf",
        file_hash="other_hash_123",
        original_filename="other.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(other_doc)
    await db.flush()
    statement = build_statement(test_user.id, "statement_hash_456", 80)
    statement.uploaded_document_id = other_doc.id
    db.add(statement)
    await db.commit()
    resolved = await statement_pipeline.resolve_uploaded_document(db, statement, test_user.id)
    assert resolved is None, "Cross-user document must never be returned by resolve_uploaded_document"
    user_doc = UploadedDocument(
        id=uuid4(),
        user_id=test_user.id,
        file_path="user_path.pdf",
        file_hash="statement_hash_456",
        original_filename="user.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(user_doc)
    statement.uploaded_document_id = user_doc.id
    await db.commit()
    resolved_own = await statement_pipeline.resolve_uploaded_document(db, statement, test_user.id)
    assert resolved_own is not None
    assert resolved_own.id == user_doc.id


async def test_create_statement_account_from_confirmation_reuses_existing_active_account(db, test_user) -> None:
    first_stmt = build_statement(test_user.id, "hash_confirm_dedup_1", 80)
    first_stmt.account_id = None
    first_stmt.institution = "Standard Chartered Bank"
    first_stmt.account_last4 = None
    first_stmt.currency = "SGD"
    db.add(first_stmt)
    second_stmt = build_statement(test_user.id, "hash_confirm_dedup_2", 80)
    second_stmt.account_id = None
    second_stmt.institution = "Standard Chartered Bank"
    second_stmt.account_last4 = None
    second_stmt.currency = "SGD"
    db.add(second_stmt)
    await db.commit()
    first_account = await create_statement_account_from_confirmation(db, first_stmt, test_user.id)
    second_account = await create_statement_account_from_confirmation(db, second_stmt, test_user.id)
    assert first_account.name == "Standard Chartered Bank"
    assert second_account.id == first_account.id
    assert second_stmt.account_id == first_account.id


async def test_AC_extraction_2994_21_the_retry_flag_and_the_watchdog_are_gone() -> None:
    from src.extraction.extension import statement_parsing_supervisor as supervisor

    assert "reset_for_retry" not in inspect.signature(statements_router._queue_statement_reparse).parameters
    assert not hasattr(supervisor, "reset_stale_parsing_jobs")
    assert not hasattr(supervisor, "PARSING_STALE_THRESHOLD")
