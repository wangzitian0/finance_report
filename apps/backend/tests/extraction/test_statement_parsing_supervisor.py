"""The supervisor reaps stale runs and rejects the statements that they leave parsing."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from src.database import create_session_maker_from_db
from src.extraction import BankStatementStatus, RunActorKind, RunHints, RunKind, RunTrigger, claim_run, create_run
from src.extraction.extension.statement_parsing_supervisor import reap_stale_parsing_runs, run_parsing_supervisor
from src.extraction.extension.statement_runs import DEFAULT_STALE_AFTER
from src.extraction.orm.statement_run import StatementRun
from tests.factories import StatementSummaryFactory


async def _running_statement(db, user, *, file_hash, heartbeat_age):
    statement = StatementSummaryFactory.build(user_id=user.id, account_id=None, file_hash=file_hash, institution="DBS", status=BankStatementStatus.PARSING, confidence_score=None, balance_validated=None)
    db.add(statement)
    await db.flush()
    run = await create_run(db, statement_id=statement.id, user_id=user.id, kind=RunKind.EXTRACT, actor_kind=RunActorKind.SYSTEM, trigger=RunTrigger.UPLOAD, hints=RunHints())
    await claim_run(db, run.id)
    await db.execute(update(StatementRun).where(StatementRun.id == run.id).values(heartbeat_at=datetime.now(UTC) - heartbeat_age))
    await db.commit()
    return statement


@pytest.mark.parametrize(
    ("file_hash", "age", "stale_after", "expected_count", "expected_status", "msg_sub"),
    [
        ("hash", DEFAULT_STALE_AFTER + timedelta(minutes=1), None, 1, BankStatementStatus.REJECTED, "parsing timed out"),
        ("hash-recent", timedelta(seconds=10), None, 0, BankStatementStatus.PARSING, None),
        ("hash-stuck", timedelta(seconds=200), timedelta(seconds=180), 1, BankStatementStatus.REJECTED, "timed out"),
        ("hash-fresh", timedelta(seconds=30), timedelta(seconds=180), 0, BankStatementStatus.PARSING, None),
    ],
)
async def test_reap_stale_parsing_runs_thresholds(db, test_user, file_hash, age, stale_after, expected_count, expected_status, msg_sub):
    statement = await _running_statement(db, test_user, file_hash=file_hash, heartbeat_age=age)
    kw = {"stale_after": stale_after} if stale_after is not None else {}
    count = await reap_stale_parsing_runs(create_session_maker_from_db(db), **kw)
    await db.refresh(statement)
    assert (count, statement.status) == (expected_count, expected_status)
    if msg_sub is not None:
        assert (statement.confidence_score, statement.balance_validated) == (0, False) and msg_sub in (statement.validation_error or "").lower()


async def test_run_parsing_supervisor_stops(monkeypatch):
    stop_event, calls = asyncio.Event(), []

    async def fake_reap():
        calls.append(1)
        stop_event.set()
        return 0

    monkeypatch.setattr("src.extraction.extension.statement_parsing_supervisor.reap_stale_parsing_runs", fake_reap)
    await run_parsing_supervisor(stop_event)
    assert calls == [1]
