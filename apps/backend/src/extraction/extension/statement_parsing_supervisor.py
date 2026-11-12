"""Background supervisor for statement parsing runs (#2994)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database import async_session_maker
from src.extraction.base.run_vocabulary import ACTIVE_RUN_STATES, RunKind
from src.extraction.base.source_vocabulary import BankStatementStatus
from src.extraction.extension.statement_runs import DEFAULT_STALE_AFTER, heartbeat_run, reap_stale_runs
from src.extraction.orm.statement_run import StatementRun
from src.extraction.orm.statement_summary import StatementSummary
from src.observability import get_logger

logger = get_logger(__name__)

PARSING_SUPERVISOR_INTERVAL_SECONDS = 60
PARSING_HEARTBEAT_INTERVAL_SECONDS = 30
PARSING_TIMEOUT_MESSAGE = "Parsing timed out. Please retry."


@asynccontextmanager
async def parsing_heartbeat(
    run_id: UUID,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    *,
    interval_seconds: float | None = None,
) -> AsyncIterator[None]:
    """Refresh `heartbeat_at` of a running run while the parse runs.

    The reaper fails a running run whose heartbeat is older than the stale threshold. A long statement
    needs more time than that threshold, so a live parse must show it is alive.
    """
    interval = PARSING_HEARTBEAT_INTERVAL_SECONDS if interval_seconds is None else interval_seconds
    session_factory = sessionmaker or async_session_maker

    async def beat() -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                async with session_factory() as session:
                    await heartbeat_run(session, run_id)
                    await session.commit()
            except Exception:
                logger.warning("statement.parsing.heartbeat_failed", run_id=str(run_id), exc_info=True)

    task = asyncio.create_task(beat())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def reap_stale_parsing_runs(
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    *,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    now: datetime | None = None,
) -> int:
    """Fail the runs that have no worker. Reject each statement that is parsing and has no active run.

    A reaped extract run leaves its statement without an active run. So does a last retry attempt that
    failed. Return the number of failed runs plus the number of other statements that this call rejected.
    A statement that is no longer parsing keeps its status.
    """
    session_factory = sessionmaker or async_session_maker
    moment = now or datetime.now(UTC)
    async with session_factory() as session:
        failed_ids = await reap_stale_runs(session, stale_after=stale_after, now=moment)
        reaped_extract_runs = (
            (
                await session.execute(
                    select(StatementRun).where(StatementRun.id.in_(failed_ids), StatementRun.kind == RunKind.EXTRACT)
                )
            )
            .scalars()
            .all()
            if failed_ids
            else []
        )
        has_active_run = (
            select(StatementRun.id)
            .where(StatementRun.statement_id == StatementSummary.id, StatementRun.state.in_(ACTIVE_RUN_STATES))
            .exists()
        )
        rejected = set(
            (
                await session.execute(
                    update(StatementSummary)
                    .where(StatementSummary.status == BankStatementStatus.PARSING, ~has_active_run)
                    .values(
                        status=BankStatementStatus.REJECTED,
                        validation_error=PARSING_TIMEOUT_MESSAGE,
                        confidence_score=0,
                        balance_validated=False,
                    )
                    .returning(StatementSummary.id)
                )
            ).scalars()
        )
        await session.commit()
    reaped_statements = {run.statement_id for run in reaped_extract_runs}
    for run in reaped_extract_runs:
        if run.statement_id in rejected:
            last_sign = run.heartbeat_at or run.requested_at
            logger.warning(
                "statement.parsing.watchdog_timeout",
                run_id=str(run.id),
                statement_id=str(run.statement_id),
                error_code=run.error_code,
                threshold_seconds=int(stale_after.total_seconds()),
                age_seconds=int((moment - last_sign).total_seconds()),
            )
    others = rejected - reaped_statements
    for statement_id in others:
        logger.warning("statement.parsing.no_active_run", statement_id=str(statement_id))
    return len(failed_ids) + len(others)


async def run_parsing_supervisor(stop_event: asyncio.Event) -> None:
    """Run periodic checks until stop_event is set."""
    while not stop_event.is_set():
        try:
            count = await reap_stale_parsing_runs()
            if count:
                logger.warning("Reaped stale statement runs", count=count)
        except Exception:
            logger.exception("Failed to reap stale statement runs")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=PARSING_SUPERVISOR_INTERVAL_SECONDS)
        except TimeoutError:
            continue
