"""Background supervisor for stuck statement parsing jobs."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from src.database import async_session_maker
from src.models import BankStatement, BankStatementStatus

logger = logging.getLogger(__name__)

PARSING_STALE_THRESHOLD = timedelta(minutes=30)
PARSING_SUPERVISOR_INTERVAL_SECONDS = 300


async def reset_stale_parsing_jobs() -> int:
    """Mark stale parsing jobs as rejected so users can retry."""
    cutoff = datetime.now(UTC) - PARSING_STALE_THRESHOLD
    async with async_session_maker() as session:
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
                logger.warning("Reset %s stale parsing statements", count)
        except Exception:
            logger.exception("Failed to reset stale parsing statements")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=PARSING_SUPERVISOR_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue
