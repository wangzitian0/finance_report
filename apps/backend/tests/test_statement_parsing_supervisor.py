"""Tests for parsing supervisor."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.database import create_session_maker_from_db
from src.models import BankStatement, BankStatementStatus
from src.services.statement_parsing_supervisor import (
    PARSING_STALE_THRESHOLD,
    reset_stale_parsing_jobs,
    run_parsing_supervisor,
)


@pytest.mark.asyncio
async def test_reset_stale_parsing_jobs_marks_rejected(db, test_user):
    """Stale parsing statements should be marked rejected."""
    stale_time = datetime.now(UTC) - PARSING_STALE_THRESHOLD - timedelta(minutes=1)
    statement = BankStatement(
        user_id=test_user.id,
        account_id=None,
        file_path="statements/test.pdf",
        file_hash="hash",
        original_filename="test.pdf",
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


@pytest.mark.asyncio
async def test_reset_stale_parsing_jobs_noop_for_recent(db, test_user):
    """Recent parsing statements should remain unchanged."""
    statement = BankStatement(
        user_id=test_user.id,
        account_id=None,
        file_path="statements/recent.pdf",
        file_hash="hash-recent",
        original_filename="recent.pdf",
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


@pytest.mark.asyncio
async def test_run_parsing_supervisor_stops(monkeypatch):
    """Supervisor exits when stop event is set."""
    stop_event = asyncio.Event()
    calls = []

    async def fake_reset():
        calls.append(1)
        stop_event.set()
        return 0

    monkeypatch.setattr(
        "src.services.statement_parsing_supervisor.reset_stale_parsing_jobs",
        fake_reset,
    )

    await run_parsing_supervisor(stop_event)
    assert calls == [1]
