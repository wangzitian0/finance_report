"""Regression tests for user deletion racing an in-flight statement parse (#1256).

Two defects are covered here (the third, the 409 deletion guard, lives in
``api/test_users_router.py``):

- AC13.23.2: the parse-failure lineage write must re-check user existence and
  skip the FK-violating ``uploaded_documents.user_id`` insert when the owning
  user has been deleted mid-parse.
- AC13.23.3: ``handle_parse_failure`` must roll back BEFORE reading any expired
  ORM attribute (using a plain cached ``statement_id``), so an already-failed
  session does not raise ``PendingRollbackError`` and mask the original error;
  the original error must still be logged.

All identifiers are synthetic (generated UUIDs / sequence-based factory values).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import structlog
from sqlalchemy import delete, select
from sqlalchemy.exc import PendingRollbackError

from src.identity import User
from src.models.layer1 import UploadedDocument
from src.models.statement_enums import BankStatementStatus
from src.models.statement_summary import StatementSummary
from src.services.statement_parsing import _ensure_failed_document_lineage, handle_parse_failure
from tests.factories import StatementSummaryFactory

pytestmark = pytest.mark.asyncio


async def test_AC13_23_2_failed_lineage_skips_when_user_deleted(db, test_user):
    """AC13.23.2: when the owning user is deleted mid-parse, the failure-handler
    lineage write must NOT attempt the FK-violating UploadedDocument insert.

    Reproduces #1256 defect 1: the background parse captured ``user_id`` before
    deletion; after the user (and its cascade) is gone, persisting failed lineage
    would insert ``uploaded_documents.user_id`` pointing at a missing ``users.id``
    and PostgreSQL rejects it with a FK IntegrityError. The handler must detect
    the user is gone and skip gracefully instead.
    """
    statement = await StatementSummaryFactory.create_async(db, user_id=test_user.id, status=BankStatementStatus.PARSING)
    await db.commit()
    file_hash = statement.file_hash

    # The background parse holds the StatementSummary ORM object (with its captured
    # user_id) in memory; meanwhile the owning user is deleted. We detach the
    # statement from the session and delete the user so the in-memory row's user_id
    # now points at a missing users.id — exactly the #1256 race. Persisting failed
    # lineage for it would hit the uploaded_documents.user_id FK.
    db.expunge(statement)
    await db.execute(delete(StatementSummary).where(StatementSummary.user_id == test_user.id))
    await db.execute(delete(User).where(User.id == test_user.id))
    await db.commit()

    # Must not raise an FK IntegrityError; the lineage write re-checks user existence
    # and skips gracefully.
    await _ensure_failed_document_lineage(
        db,
        statement,
        file_hash=file_hash,
        storage_key="statements/synthetic/synthetic.pdf",
        original_filename="synthetic.pdf",
    )

    # No orphan document row was created for the deleted user.
    leftover = (
        await db.execute(select(UploadedDocument).where(UploadedDocument.file_hash == file_hash))
    ).scalar_one_or_none()
    assert leftover is None


async def test_AC13_23_3_failure_handler_rolls_back_before_reading_orm(db, test_user):
    """AC13.23.3: the handler rolls back BEFORE any ORM attribute read, and never
    needs a live ORM read at all when the caller passes the plain ``statement_id``.

    Reproduces #1256 defect 2: the old handler read ``statement.id`` off the
    (possibly expired) ORM row *before* ``db.rollback()``; on an already-failed
    session that access raises ``PendingRollbackError`` and masks the original
    error. We assert ``rollback`` is invoked before any ``statement.id`` access by
    poisoning the attribute, and that the handler completes and marks the statement
    rejected using the plain id (the production caller's value).
    """
    statement = await StatementSummaryFactory.create_async(db, user_id=test_user.id, status=BankStatementStatus.PARSING)
    await db.commit()
    real_id = statement.id

    order: list[str] = []
    original_rollback = db.rollback

    async def _tracking_rollback():
        order.append("rollback")
        await original_rollback()

    # A lightweight stand-in for the (possibly expired) ORM row passed to the
    # handler: touching ``.id`` is the #1256 hazard, so it raises unless rollback
    # already ran. Because the production caller now passes the plain
    # ``statement_id``, the handler must never read this attribute pre-rollback.
    class _PoisonedStatement:
        user_id = statement.user_id

        @property
        def id(self):
            if "rollback" not in order:
                raise PendingRollbackError("statement.id read before rollback")
            return real_id

    with patch.object(db, "rollback", _tracking_rollback):
        # Must NOT raise: rollback runs first; the plain statement_id is used so no
        # live ORM read on the expired row is needed before rollback.
        await handle_parse_failure(
            _PoisonedStatement(),
            db,
            message="Finalize failed: original boom",
            statement_id=real_id,
        )

    assert order == ["rollback"]
    refreshed = await db.get(StatementSummary, real_id)
    assert refreshed.status == BankStatementStatus.REJECTED


async def test_AC13_23_3_original_error_not_masked(db, test_user):
    """AC13.23.3: a failure during the rejection write must not swallow the
    original error — the original message stays logged even if the inner write
    raises (e.g. PendingRollbackError from a poisoned session)."""
    statement = await StatementSummaryFactory.create_async(db, user_id=test_user.id, status=BankStatementStatus.PARSING)
    await db.commit()

    original_message = "Parsing failed: synthetic original FK violation"

    # Force the post-rollback rejection write to fail the way a still-broken
    # session would; the handler must log the original error, not hide it.
    with (
        patch.object(db, "get", new=AsyncMock(side_effect=PendingRollbackError("session still dirty"))),
        structlog.testing.capture_logs() as logs,
    ):
        await handle_parse_failure(statement, db, message=original_message)

    # The original error context is preserved in the logs (not masked away).
    assert any(original_message in str(entry.values()) for entry in logs)
