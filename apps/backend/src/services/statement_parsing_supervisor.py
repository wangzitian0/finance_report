"""Background supervisor for stuck statement parsing jobs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database import async_session_maker
from src.logger import get_logger
from src.models import BankStatement, BankStatementStatus

logger = get_logger(__name__)

PARSING_STALE_THRESHOLD = timedelta(minutes=5)
PARSING_SUPERVISOR_INTERVAL_SECONDS = 300


async def reset_stale_parsing_jobs(
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Mark stale parsing jobs as rejected so users can retry."""
    cutoff = datetime.now(UTC) - PARSING_STALE_THRESHOLD
    session_factory = sessionmaker or async_session_maker
    async with session_factory() as session:
        result = await session.execute(
            select(BankStatement)
            .where(BankStatement.status == BankStatementStatus.PARSING)
            .where(BankStatement.updated_at < cutoff)
        )
        stale_statements = result.scalars().all()

        for statement in stale_statements:
            statement.status = BankStatementStatus.REJECTED
            statement.validation_error = "Parsing timed out. Please retry."
            statement.confidence_score = 0
            statement.balance_validated = False

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
