from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal
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
from src.extraction.extension import statement_parsing_supervisor as supervisor
from src.extraction.extension import statement_pipeline
from src.extraction.extension.statement_parsing import handle_parse_failure
from src.extraction.extension.statement_posting import is_high_confidence_auto_approve_candidate
from src.extraction.orm.layer2 import AtomicTransaction
from src.identity import User
from src.routers import statements as statements_router
from tests.api._statement_router_fixtures import add_txn, build_statement

pytestmark = pytest.mark.asyncio


async def test_build_statement_storage_key_and_high_confidence_guards(test_user) -> None:
    sid = uuid4()
    assert (
        statements_router.build_statement_storage_key(statement_id=sid, file_hash="abcdef1234567890ffff", extension="PDF"),
        statements_router.build_statement_storage_key(statement_id=sid, file_hash="abcdef1234567890ffff", extension="exe"),
    ) == (f"statements/{sid}/abcdef1234567890.pdf", f"statements/{sid}/abcdef1234567890.bin")
    statement_pipeline.PENDING_PARSE_TASKS.clear()
    await statement_pipeline.wait_for_parse_tasks()

    stmt = build_statement(test_user.id, "hash_candidate_true", 85)
    stmt.status = BankStatementStatus.APPROVED
    r1 = is_high_confidence_auto_approve_candidate(stmt)
    stmt.confidence_score = 84
    r2 = is_high_confidence_auto_approve_candidate(stmt)
    stmt.confidence_score, stmt.balance_validated = 90, False
    r3 = is_high_confidence_auto_approve_candidate(stmt)
    stmt.balance_validated, stmt.status = True, BankStatementStatus.PARSED
    r4 = is_high_confidence_auto_approve_candidate(stmt)
    assert (r1, r2, r3, r4) == (True, False, False, False)


@pytest.mark.parametrize(
    ("rb_exc", "get_kwargs", "expect_get"),
    [
        (None, {"side_effect": Exception("DB completely down")}, True),
        (None, {"return_value": None}, True),
        (Exception("Rollback failed"), {"return_value": None}, False),
    ],
)
async def test_handle_parse_failure_resilience(db, rb_exc, get_kwargs, expect_get) -> None:
    mock_session = AsyncMock(spec=db)
    mock_session.rollback = AsyncMock(side_effect=rb_exc)
    mock_session.get = AsyncMock(**get_kwargs)
    mock_session.commit = AsyncMock()
    await handle_parse_failure(MagicMock(id=uuid4()), mock_session, message="parse error")
    mock_session.rollback.assert_awaited_once()
    if expect_get:
        mock_session.get.assert_awaited_once()


async def test_rejected_statement_transactions_excluded_and_user_isolation(db, test_user) -> None:
    statement = build_statement(test_user.id, "hash_rejected_leak_test", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.flush()
    txn = await add_txn(db, statement, txn_date=date(2025, 1, 15), description="Rejected statement transaction", amount=Decimal("50.00"), direction="IN")
    await db.commit()
    scoped_txns = (await db.scalars(select(AtomicTransaction.id).where(effective_statement_transaction_filter(test_user.id, statement.id)))).all()
    global_txns = (await db.scalars(select(AtomicTransaction.id).where(effective_statement_transaction_filter(test_user.id)))).all()
    assert scoped_txns == [] and txn.id not in global_txns

    other_user = User(id=uuid4(), email=f"other_{uuid4().hex[:8]}@example.com", name="Other User", hashed_password="test_hashed_password")
    db.add(other_user)
    await db.flush()
    other_doc = UploadedDocument(id=uuid4(), user_id=other_user.id, file_path="other_path.pdf", file_hash="other_hash_123", original_filename="other.pdf", document_type=DocumentType.BANK_STATEMENT)
    db.add(other_doc)
    await db.flush()
    iso_stmt = build_statement(test_user.id, "statement_hash_456", 80)
    iso_stmt.uploaded_document_id = other_doc.id
    db.add(iso_stmt)
    await db.commit()
    assert await statement_pipeline.resolve_uploaded_document(db, iso_stmt, test_user.id) is None

    user_doc = UploadedDocument(id=uuid4(), user_id=test_user.id, file_path="user_path.pdf", file_hash="statement_hash_456", original_filename="user.pdf", document_type=DocumentType.BANK_STATEMENT)
    db.add(user_doc)
    iso_stmt.uploaded_document_id = user_doc.id
    await db.commit()
    resolved_own = await statement_pipeline.resolve_uploaded_document(db, iso_stmt, test_user.id)
    assert resolved_own is not None and resolved_own.id == user_doc.id


async def test_create_statement_account_dedup_and_watchdog_removed(db, test_user) -> None:
    s1, s2 = build_statement(test_user.id, "hash_confirm_dedup_1", 80), build_statement(test_user.id, "hash_confirm_dedup_2", 80)
    for s in (s1, s2):
        s.account_id, s.institution, s.account_last4, s.currency = None, "Standard Chartered Bank", None, "SGD"
    db.add_all([s1, s2])
    await db.commit()
    a1 = await create_statement_account_from_confirmation(db, s1, test_user.id)
    a2 = await create_statement_account_from_confirmation(db, s2, test_user.id)
    assert (a1.name, a2.id, s2.account_id) == ("Standard Chartered Bank", a1.id, a1.id)
    assert "reset_for_retry" not in inspect.signature(statements_router._queue_statement_reparse).parameters
    assert not hasattr(supervisor, "reset_stale_parsing_jobs") and not hasattr(supervisor, "PARSING_STALE_THRESHOLD")
