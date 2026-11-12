"""The supervisor reaps stale runs and rejects the statements that they leave parsing."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    RunActorKind,
    RunHints,
    RunKind,
    RunTrigger,
    claim_run,
    create_run,
)
from src.extraction.extension.statement_parsing_supervisor import reap_stale_parsing_runs, run_parsing_supervisor
from src.extraction.extension.statement_runs import DEFAULT_STALE_AFTER
from src.extraction.orm.statement_run import StatementRun
from tests.factories import StatementSummaryFactory


async def _running_statement(db, user, *, file_hash, heartbeat_age):
    statement = StatementSummaryFactory.build(
        user_id=user.id,
        account_id=None,
        file_hash=file_hash,
        institution="DBS",
        status=BankStatementStatus.PARSING,
        confidence_score=None,
        balance_validated=None,
    )
    db.add(statement)
    await db.flush()
    run = await create_run(
        db,
        statement_id=statement.id,
        user_id=user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.SYSTEM,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(),
    )
    await claim_run(db, run.id)
    await db.execute(
        update(StatementRun).where(StatementRun.id == run.id).values(heartbeat_at=datetime.now(UTC) - heartbeat_age)
    )
    await db.commit()
    return statement


async def test_reap_stale_parsing_runs_marks_rejected(db, test_user):
    statement = await _running_statement(
        db, test_user, file_hash="hash", heartbeat_age=DEFAULT_STALE_AFTER + timedelta(minutes=1)
    )

    count = await reap_stale_parsing_runs(create_session_maker_from_db(db))

    await db.refresh(statement)
    assert count == 1
    assert statement.status == BankStatementStatus.REJECTED
    assert statement.validation_error == "Parsing timed out. Please retry."
    assert statement.confidence_score == 0
    assert statement.balance_validated is False


async def test_reap_stale_parsing_runs_noop_for_recent(db, test_user):
    statement = await _running_statement(db, test_user, file_hash="hash-recent", heartbeat_age=timedelta(seconds=10))

    count = await reap_stale_parsing_runs(create_session_maker_from_db(db))

    await db.refresh(statement)
    assert count == 0
    assert statement.status == BankStatementStatus.PARSING


async def test_run_parsing_supervisor_stops(monkeypatch):
    stop_event = asyncio.Event()
    calls = []

    async def fake_reap():
        calls.append(1)
        stop_event.set()
        return 0

    monkeypatch.setattr("src.extraction.extension.statement_parsing_supervisor.reap_stale_parsing_runs", fake_reap)
    await run_parsing_supervisor(stop_event)
    assert calls == [1]
