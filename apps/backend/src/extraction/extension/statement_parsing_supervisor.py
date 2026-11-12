"""Background supervisor for stuck statement parsing jobs."""

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
from src.extraction.base.source_vocabulary import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.observability import get_logger

logger = get_logger(__name__)

PARSING_STALE_THRESHOLD = timedelta(minutes=5)
PARSING_SUPERVISOR_INTERVAL_SECONDS = 60
PARSING_HEARTBEAT_INTERVAL_SECONDS = 30
_PARSING_STATUSES = [BankStatementStatus.PARSING, BankStatementStatus.PARSING.value]


@asynccontextmanager
async def parsing_heartbeat(
    statement_id: UUID,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    *,
    interval_seconds: float | None = None,
) -> AsyncIterator[None]:
    """Refresh `updated_at` of a parsing row while the parse runs.

    The watchdog resets rows whose `updated_at` is older than the stale threshold. A long
    statement needs more time than that threshold, so a live parse must show it is alive.
    """
    interval = PARSING_HEARTBEAT_INTERVAL_SECONDS if interval_seconds is None else interval_seconds
    session_factory = sessionmaker or async_session_maker

    async def beat() -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                async with session_factory() as session:
                    await session.execute(
                        update(StatementSummary)
                        .where(StatementSummary.id == statement_id, StatementSummary.status.in_(_PARSING_STATUSES))
                        .values(updated_at=datetime.now(UTC))
                    )
                    await session.commit()
            except Exception:
                logger.warning("statement.parsing.heartbeat_failed", statement_id=str(statement_id), exc_info=True)

    task = asyncio.create_task(beat())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def reset_stale_parsing_jobs(
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    *,
    stale_threshold: timedelta | None = None,
) -> int:
    """Mark stale parsing jobs as rejected so users can retry."""
    threshold = stale_threshold or PARSING_STALE_THRESHOLD
    cutoff = datetime.now(UTC) - threshold
    session_factory = sessionmaker or async_session_maker
    async with session_factory() as session:
        result = await session.execute(
            select(StatementSummary)
            .where(StatementSummary.status.in_(_PARSING_STATUSES))
            .where(StatementSummary.updated_at < cutoff)
        )
        stale_statements = result.scalars().all()

        for statement in stale_statements:
            updated_at = statement.updated_at.replace(tzinfo=statement.updated_at.tzinfo or UTC)
            statement.status = BankStatementStatus.REJECTED
            statement.validation_error = "Parsing timed out. Please retry."
            statement.confidence_score = 0
            statement.balance_validated = False
            logger.warning(
                "statement.parsing.watchdog_timeout",
                statement_id=str(statement.id),
                threshold_seconds=int(threshold.total_seconds()),
                updated_at=str(statement.updated_at),
                age_seconds=int((datetime.now(UTC) - updated_at).total_seconds()),
            )

        if stale_statements:
            await session.commit()
        return len(stale_statements)


async def run_parsing_supervisor(stop_event: asyncio.Event) -> None:
    """Run periodic checks until stop_event is set."""
    while not stop_event.is_set():
        try:
            count = await reset_stale_parsing_jobs()
            if count:
                logger.warning("Reset stale parsing statements", count=count)
        except Exception:
            logger.exception("Failed to reset stale parsing statements")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=PARSING_SUPERVISOR_INTERVAL_SECONDS)
        except TimeoutError:
            continue
