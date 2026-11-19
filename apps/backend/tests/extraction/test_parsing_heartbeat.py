"""Parsing heartbeat (#2960, #2994)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update

from src.composition import compose_statement_posting_dependencies
from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    ParseJob,
    RunActorKind,
    RunHints,
    RunKind,
    RunTrigger,
    StatementIngestionUseCase,
    StatementSummary,
    claim_run,
    create_run,
    fail_run,
)
from src.extraction.extension import statement_parsing_supervisor as supervisor
from src.extraction.extension._base import ExtractionError
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing_supervisor import (
    PARSING_HEARTBEAT_INTERVAL_SECONDS,
    parsing_heartbeat,
    reap_stale_parsing_runs,
)
from src.extraction.extension.statement_runs import DEFAULT_STALE_AFTER, StaleRun
from src.extraction.orm.statement_run import StatementRun
from tests.factories import StatementSummaryFactory

STALE = DEFAULT_STALE_AFTER + timedelta(minutes=1)


async def _row(db, user, *, status=BankStatementStatus.PARSING, claim=True, heartbeat_age=STALE):
    statement = StatementSummaryFactory.build(
        id=uuid4(),
        user_id=user.id,
        account_id=None,
        file_hash=f"heartbeat-{uuid4()}",
        institution="DBS",
        status=status,
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
    if claim:
        await claim_run(db, run.id)
        await db.execute(
            update(StatementRun).where(StatementRun.id == run.id).values(heartbeat_at=datetime.now(UTC) - heartbeat_age)
        )
    await db.commit()
    return statement, run.id


async def _run_row(maker, run_id) -> StatementRun:
    async with maker() as session:
        return await session.get(StatementRun, run_id, populate_existing=True)


async def _wait_for_beat(maker, run_id, since: datetime, timeout: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while (await _run_row(maker, run_id)).heartbeat_at <= since:
        assert asyncio.get_running_loop().time() < deadline, "no heartbeat landed"
        await asyncio.sleep(0.05)


async def test_AC_extraction_2960_5_7_8_heartbeat_interval_protects_live_and_stops(db, test_user):
    assert PARSING_HEARTBEAT_INTERVAL_SECONDS * 3 <= DEFAULT_STALE_AFTER.total_seconds()
    statement, run_id = await _row(db, test_user)
    maker = create_session_maker_from_db(db)
    before = (await _run_row(maker, run_id)).heartbeat_at
    async with maker() as s:
        statement_updated_at = (await s.get(StatementSummary, statement.id, populate_existing=True)).updated_at
    async with parsing_heartbeat(run_id, maker, interval_seconds=0.05):
        await _wait_for_beat(maker, run_id, before)
        count = await reap_stale_parsing_runs(maker)
    after_block = (await _run_row(maker, run_id)).heartbeat_at
    await asyncio.sleep(0.4)
    await db.refresh(statement)
    assert (count, statement.status, statement.updated_at, (await _run_row(maker, run_id)).heartbeat_at) == (
        0,
        BankStatementStatus.PARSING,
        statement_updated_at,
        after_block,
    )


async def test_AC_extraction_2960_6_the_heartbeat_does_not_touch_a_row_that_left_parsing(db, test_user):
    _, failed_run_id = await _row(db, test_user, status=BankStatementStatus.REJECTED)
    await fail_run(db, failed_run_id, error_code="heartbeat_lost", error_message="No heartbeat.")
    await db.commit()
    _, live_run_id = await _row(db, test_user)
    maker = create_session_maker_from_db(db)
    failed_before, live_before = (
        (await _run_row(maker, failed_run_id)).heartbeat_at,
        (await _run_row(maker, live_run_id)).heartbeat_at,
    )
    async with parsing_heartbeat(live_run_id, maker, interval_seconds=0.05):
        await _wait_for_beat(maker, live_run_id, live_before)
    with pytest.raises(StaleRun):
        async with parsing_heartbeat(failed_run_id, maker, interval_seconds=0.05):
            await asyncio.sleep(5)
    assert (await _run_row(maker, failed_run_id)).heartbeat_at == failed_before


async def test_AC_extraction_2960_9_the_use_case_beats_while_parse_document_runs(db, test_user, monkeypatch):
    statement, run_id = await _row(db, test_user, claim=False)
    maker = create_session_maker_from_db(db)
    seen: dict[str, datetime] = {}

    async def slow_parse(*_args, **_kwargs):
        started_at = (await _run_row(maker, run_id)).started_at
        await _wait_for_beat(maker, run_id, started_at)
        seen["during"], seen["started"] = (await _run_row(maker, run_id)).heartbeat_at, started_at
        raise ExtractionError("stop after the heartbeat was observed")

    service = ExtractionService()
    service.parse_documents = slow_parse
    monkeypatch.setattr(supervisor, "PARSING_HEARTBEAT_INTERVAL_SECONDS", 0.05)

    async def no_router(**_kwargs) -> None:
        return None

    use_case = StatementIngestionUseCase(
        session_maker=maker,
        content_loader=lambda _k: asyncio.sleep(0, result=b"content"),
        extraction_service_factory=lambda: service,
        posting_dependencies=compose_statement_posting_dependencies(),
        brokerage_router=no_router,
        trace_emitter_factory=lambda _db: None,
        clock=lambda: 0.0,
        sleep=lambda _d: asyncio.sleep(0),
    )
    await use_case.execute(
        ParseJob(
            statement_id=statement.id,
            run_id=run_id,
            filename="statement.pdf",
            institution="DBS",
            user_id=test_user.id,
            account_id=None,
            file_hash=statement.file_hash,
            storage_key="uploads/statement.pdf",
            model=None,
            request_id="req-2960",
        ),
        content=b"content",
    )
    assert seen["during"] > seen["started"]
