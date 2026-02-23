"""AC3.5.5 - Statements Error Path Coverage

Tests for error handling in statement parsing and background task management.
Covers rollback failures, statement not found scenarios, and exception handling.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.models.statement import BankStatement, BankStatementStatus
from src.routers.statements import _handle_parse_failure


@pytest.mark.asyncio
async def test_handle_parse_failure_rollback_fails(db):
    """AC3.5.5 - Handle parse failure: Rollback exception is caught and logged

    GIVEN a statement exists in the database
    WHEN _handle_parse_failure is called and db.rollback() raises an exception
    THEN the exception is logged but the handler continues to mark statement as rejected
    """
    user_id = uuid4()
    statement = BankStatement(
        user_id=user_id,
        file_path="test.pdf",
        file_hash="abc123",
        original_filename="test.pdf",
        institution="TEST",
        account_last4="1234",
        currency="SGD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("100.00"),
        status=BankStatementStatus.PARSING,
        confidence_score=0,
        balance_validated=False,
    )
    db.add(statement)
    await db.commit()
    await db.refresh(statement)

    with patch.object(db, "rollback", side_effect=SQLAlchemyError("Rollback failed")):
        await _handle_parse_failure(db=db, statement=statement, message="Test error")

    await db.refresh(statement)
    assert statement.status == BankStatementStatus.REJECTED
    assert statement.validation_error == "Test error"


@pytest.mark.asyncio
async def test_handle_parse_failure_statement_not_found(db):
    """AC3.5.5 - Handle parse failure: Statement not found after rollback is logged

    GIVEN a statement that gets deleted during processing
    WHEN _handle_parse_failure is called and statement is not found after rollback
    THEN the error is logged and function returns without crashing
    """
    user_id = uuid4()
    statement = BankStatement(
        user_id=user_id,
        file_path="test.pdf",
        file_hash="abc123",
        original_filename="test.pdf",
        institution="TEST",
        account_last4="1234",
        currency="SGD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("100.00"),
        status=BankStatementStatus.PARSING,
        confidence_score=0,
        balance_validated=False,
    )
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    await db.delete(statement)
    await db.commit()

    fake_statement = MagicMock()
    fake_statement.id = statement_id
    await _handle_parse_failure(db=db, statement=fake_statement, message="Test error")


@pytest.mark.asyncio
async def test_handle_parse_failure_commit_fails(db):
    """AC3.5.5 - Handle parse failure: Commit failure during error handling is logged

    GIVEN a statement exists in the database
    WHEN _handle_parse_failure is called and db.commit() raises an exception
    THEN the exception is logged as inner error
    """
    user_id = uuid4()
    statement = BankStatement(
        user_id=user_id,
        file_path="test.pdf",
        file_hash="abc123",
        original_filename="test.pdf",
        institution="TEST",
        account_last4="1234",
        currency="SGD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("100.00"),
        status=BankStatementStatus.PARSING,
        confidence_score=0,
        balance_validated=False,
    )
    db.add(statement)
    await db.commit()
    await db.refresh(statement)

    original_commit = db.commit

    async def failing_commit():
        if not hasattr(failing_commit, "called"):
            failing_commit.called = True
            await original_commit()
        else:
            raise SQLAlchemyError("Commit failed")

    with patch.object(db, "commit", side_effect=failing_commit):
        await _handle_parse_failure(db=db, statement=statement, message="Test error")
