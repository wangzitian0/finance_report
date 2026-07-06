"""Tests for parsing supervisor."""

import asyncio
from datetime import UTC, datetime, timedelta

from src.database import create_session_maker_from_db
from src.models.statement_enums import BankStatementStatus
from src.extraction.extension.statement_parsing_supervisor import (
    PARSING_STALE_THRESHOLD,
    reset_stale_parsing_jobs,
    run_parsing_supervisor,
)
from tests.factories import StatementSummaryFactory


async def test_reset_stale_parsing_jobs_marks_rejected(db, test_user):
    """Stale parsing statements should be marked rejected."""
    stale_time = datetime.now(UTC) - PARSING_STALE_THRESHOLD - timedelta(minutes=1)
    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=None,
        file_hash="hash",
        institution="DBS",
        status=BankStatementStatus.PARSING,
        confidence_score=None,
        balance_validated=None,
    )
    statement.updated_at = stale_time
    db.add(statement)
    await db.commit()

    session_maker = create_session_maker_from_db(db)
    count = await reset_stale_parsing_jobs(sessionmaker=session_maker)
    await db.refresh(statement)

    assert count == 1
    assert statement.status == BankStatementStatus.REJECTED
    assert statement.validation_error == "Parsing timed out. Please retry."
    assert statement.confidence_score == 0
    assert statement.balance_validated is False


async def test_reset_stale_parsing_jobs_noop_for_recent(db, test_user):
    """Recent parsing statements should remain unchanged."""
    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=None,
        file_hash="hash-recent",
        institution="DBS",
        status=BankStatementStatus.PARSING,
        confidence_score=None,
        balance_validated=None,
    )
    db.add(statement)
    await db.commit()

    session_maker = create_session_maker_from_db(db)
    count = await reset_stale_parsing_jobs(sessionmaker=session_maker)
    await db.refresh(statement)

    assert count == 0
    assert statement.status == BankStatementStatus.PARSING


async def test_run_parsing_supervisor_stops(monkeypatch):
    """Supervisor exits when stop event is set."""
    stop_event = asyncio.Event()
    calls = []

    async def fake_reset():
        calls.append(1)
        stop_event.set()
        return 0

    monkeypatch.setattr(
        "src.extraction.extension.statement_parsing_supervisor.reset_stale_parsing_jobs",
        fake_reset,
    )

    await run_parsing_supervisor(stop_event)
    assert calls == [1]
