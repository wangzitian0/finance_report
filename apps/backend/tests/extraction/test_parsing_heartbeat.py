"""Parsing heartbeat (#2960, #2994).

Evidence of the run of 2026-11-11 on staging: a 100-row statement needs 340 s or more to
parse, and the watchdog rejected every row whose `updated_at` was older than 300 s. The
watchdog rejected live jobs. The late finish then wrote `parsed` over the rejected row.
The heartbeat now writes `statement_runs.heartbeat_at` and the reaper reads it.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
from src.extraction.extension.statement_runs import DEFAULT_STALE_AFTER
from src.extraction.orm.statement_run import StatementRun
from tests.factories import StatementSummaryFactory

STALE = DEFAULT_STALE_AFTER + timedelta(minutes=1)


async def _no_sleep(_delay: float) -> None:
    return None


async def _row(db, user, *, status=BankStatementStatus.PARSING, claim=True, heartbeat_age=STALE):
    """Return a statement and its run. A claimed run has a heartbeat that is `heartbeat_age` old."""
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
            update(StatementRun)
            .where(StatementRun.id == run.id)
            .values(heartbeat_at=datetime.now(UTC) - heartbeat_age)
        )
    await db.commit()
    return statement, run.id


async def _run_row(maker, run_id) -> StatementRun:
    async with maker() as session:
        return await session.get(StatementRun, run_id, populate_existing=True)


async def _statement_updated_at(maker, statement_id) -> datetime:
    async with maker() as session:
        return (await session.get(StatementSummary, statement_id, populate_existing=True)).updated_at


async def _wait_for_beat(maker, run_id, since: datetime, timeout: float = 20.0) -> None:
    """Poll until a beat moved `heartbeat_at` past `since`; a slow database cannot make a test pass vacuously."""
    deadline = asyncio.get_running_loop().time() + timeout
    while (await _run_row(maker, run_id)).heartbeat_at <= since:
        assert asyncio.get_running_loop().time() < deadline, "no heartbeat landed"
        await asyncio.sleep(0.05)


async def test_AC_extraction_2960_5_a_running_parse_with_a_heartbeat_is_not_reset_by_the_watchdog(db, test_user):
    """AC-extraction.2960.5: The reaper leaves a running run alone while the heartbeat runs."""
    statement, run_id = await _row(db, test_user)
    maker = create_session_maker_from_db(db)
    before = (await _run_row(maker, run_id)).heartbeat_at
    statement_updated_at = await _statement_updated_at(maker, statement.id)
    async with parsing_heartbeat(run_id, maker, interval_seconds=0.05):
        await _wait_for_beat(maker, run_id, before)
        count = await reap_stale_parsing_runs(maker)
    await db.refresh(statement)
    assert count == 0
    assert statement.status == BankStatementStatus.PARSING
    assert statement.updated_at == statement_updated_at, "the heartbeat must not write the statement row"


async def test_AC_extraction_2960_6_the_heartbeat_does_not_touch_a_row_that_left_parsing(db, test_user):
    """AC-extraction.2960.6: The heartbeat never changes a run that is no longer running."""
    failed_statement, failed_run_id = await _row(db, test_user, status=BankStatementStatus.REJECTED)
    await fail_run(db, failed_run_id, error_code="heartbeat_lost", error_message="No heartbeat.")
    await db.commit()
    _live_statement, live_run_id = await _row(db, test_user)
    maker = create_session_maker_from_db(db)
    failed_before = (await _run_row(maker, failed_run_id)).heartbeat_at
    live_before = (await _run_row(maker, live_run_id)).heartbeat_at
    async with parsing_heartbeat(failed_run_id, maker, interval_seconds=0.05):
        async with parsing_heartbeat(live_run_id, maker, interval_seconds=0.05):
            await _wait_for_beat(maker, live_run_id, live_before)
            await asyncio.sleep(0.2)
    assert (await _run_row(maker, failed_run_id)).heartbeat_at == failed_before


async def test_AC_extraction_2960_7_the_heartbeat_stops_when_the_parse_ends(db, test_user):
    """AC-extraction.2960.7: No beat is written after the parse leaves the heartbeat block."""
    _statement, run_id = await _row(db, test_user)
    maker = create_session_maker_from_db(db)
    before = (await _run_row(maker, run_id)).heartbeat_at
    async with parsing_heartbeat(run_id, maker, interval_seconds=0.05):
        await _wait_for_beat(maker, run_id, before)
    after_block = (await _run_row(maker, run_id)).heartbeat_at
    await asyncio.sleep(0.4)
    assert (await _run_row(maker, run_id)).heartbeat_at == after_block


def test_AC_extraction_2960_8_the_heartbeat_interval_fits_three_times_into_the_stale_threshold():
    """AC-extraction.2960.8: Two lost beats in a row do not make a live job stale."""
    assert PARSING_HEARTBEAT_INTERVAL_SECONDS * 3 <= DEFAULT_STALE_AFTER.total_seconds()


async def test_AC_extraction_2960_9_the_use_case_beats_while_parse_document_runs(db, test_user, monkeypatch):
    """AC-extraction.2960.9: The ingestion use case runs the heartbeat around parse_document."""
    statement, run_id = await _row(db, test_user, claim=False)
    maker = create_session_maker_from_db(db)
    seen: dict[str, datetime] = {}

    async def slow_parse(*_args, **_kwargs):
        started_at = (await _run_row(maker, run_id)).started_at
        await _wait_for_beat(maker, run_id, started_at)
        seen["during"] = (await _run_row(maker, run_id)).heartbeat_at
        seen["started"] = started_at
        raise ExtractionError("stop after the heartbeat was observed")

    service = ExtractionService()
    service.parse_document = slow_parse

    async def no_router(**_kwargs) -> None:
        return None

    monkeypatch.setattr(supervisor, "PARSING_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    use_case = StatementIngestionUseCase(
        session_maker=maker,
        content_loader=lambda _key: asyncio.sleep(0, result=b"content"),
        extraction_service_factory=lambda: service,
        posting_dependencies=compose_statement_posting_dependencies(),
        brokerage_router=no_router,
        trace_emitter_factory=lambda _db: None,
        clock=lambda: 0.0,
        sleep=_no_sleep,
    )
    job = ParseJob(
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
    )
    await use_case.execute(job, content=b"content")
    assert seen["during"] > seen["started"]
