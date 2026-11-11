"""Parsing heartbeat (#2960).

Evidence of the run of 2026-11-11 on staging: a 100-row statement needs 340 s or more to
parse, and the watchdog rejects every row whose `updated_at` is older than 300 s. The
watchdog rejected live jobs. The late finish then wrote `parsed` over the rejected row.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.composition import compose_statement_posting_dependencies
from src.database import create_session_maker_from_db
from src.extraction import BankStatementStatus, ParseJob, StatementIngestionUseCase, StatementSummary
from src.extraction.extension import statement_parsing_supervisor as supervisor
from src.extraction.extension._base import ExtractionError
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing_supervisor import (
    PARSING_HEARTBEAT_INTERVAL_SECONDS,
    PARSING_STALE_THRESHOLD,
    parsing_heartbeat,
    reset_stale_parsing_jobs,
)
from tests.factories import StatementSummaryFactory


async def _row(db, user, *, status=BankStatementStatus.PARSING, age=PARSING_STALE_THRESHOLD + timedelta(minutes=1)):
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
    statement.updated_at = datetime.now(UTC) - age
    db.add(statement)
    await db.commit()
    return statement


async def _updated_at(maker, statement_id) -> datetime:
    async with maker() as session:
        return (await session.get(StatementSummary, statement_id)).updated_at


async def _wait_for_beat(maker, statement_id, since: datetime, timeout: float = 20.0) -> None:
    """Poll until a beat moved `updated_at` past `since`; a slow database cannot make a test pass vacuously."""
    deadline = asyncio.get_running_loop().time() + timeout
    while await _updated_at(maker, statement_id) <= since:
        assert asyncio.get_running_loop().time() < deadline, "no heartbeat landed"
        await asyncio.sleep(0.05)


async def test_AC_extraction_2960_5_a_running_parse_with_a_heartbeat_is_not_reset_by_the_watchdog(db, test_user):
    """AC-extraction.2960.5: The watchdog leaves a parsing row alone while the heartbeat runs."""
    statement = await _row(db, test_user)
    maker = create_session_maker_from_db(db)
    before = await _updated_at(maker, statement.id)
    async with parsing_heartbeat(statement.id, maker, interval_seconds=0.05):
        await _wait_for_beat(maker, statement.id, before)
        count = await reset_stale_parsing_jobs(sessionmaker=maker)
    await db.refresh(statement)
    assert count == 0
    assert statement.status == BankStatementStatus.PARSING


async def test_AC_extraction_2960_6_the_heartbeat_does_not_touch_a_row_that_left_parsing(db, test_user):
    """AC-extraction.2960.6: The heartbeat never changes a row that is no longer parsing."""
    rejected = await _row(db, test_user, status=BankStatementStatus.REJECTED)
    live = await _row(db, test_user)
    maker = create_session_maker_from_db(db)
    rejected_before = await _updated_at(maker, rejected.id)
    live_before = await _updated_at(maker, live.id)
    async with parsing_heartbeat(rejected.id, maker, interval_seconds=0.05):
        async with parsing_heartbeat(live.id, maker, interval_seconds=0.05):
            await _wait_for_beat(maker, live.id, live_before)
            await asyncio.sleep(0.2)
    assert await _updated_at(maker, rejected.id) == rejected_before


async def test_AC_extraction_2960_7_the_heartbeat_stops_when_the_parse_ends(db, test_user):
    """AC-extraction.2960.7: No beat is written after the parse leaves the heartbeat block."""
    statement = await _row(db, test_user)
    maker = create_session_maker_from_db(db)
    before = await _updated_at(maker, statement.id)
    async with parsing_heartbeat(statement.id, maker, interval_seconds=0.05):
        await _wait_for_beat(maker, statement.id, before)
    after_block = await _updated_at(maker, statement.id)
    await asyncio.sleep(0.4)
    assert await _updated_at(maker, statement.id) == after_block


def test_AC_extraction_2960_8_the_heartbeat_interval_fits_three_times_into_the_stale_threshold():
    """AC-extraction.2960.8: Two lost beats in a row do not make a live job stale."""
    assert PARSING_HEARTBEAT_INTERVAL_SECONDS * 3 <= PARSING_STALE_THRESHOLD.total_seconds()


async def test_AC_extraction_2960_9_the_use_case_beats_while_parse_document_runs(db, test_user, monkeypatch):
    """AC-extraction.2960.9: The ingestion use case runs the heartbeat around parse_document."""
    statement = await _row(db, test_user)
    maker = create_session_maker_from_db(db)
    before = await _updated_at(maker, statement.id)
    seen: dict[str, datetime] = {}

    async def slow_parse(*_args, **_kwargs):
        await _wait_for_beat(maker, statement.id, before)
        seen["during"] = await _updated_at(maker, statement.id)
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
    )
    job = ParseJob(
        statement_id=statement.id,
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
    assert seen["during"] > before + timedelta(minutes=5)
