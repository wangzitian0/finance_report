"""Statement Stage-1 workflow contracts (EPIC-025 AC25.2.1 / #1158).

Service-level orchestration that owns the transaction boundary and the Stage-1
state transition for statement approval/rejection, so routers stay thin (HTTP
mapping + response shaping only). Behavior-preserving extraction of the inline
router sequences — same service calls, same commit point, same ordering.
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.database import async_session_maker, get_test_session_maker
from src.extraction.base.source_vocabulary import BankStatementStatus
from src.extraction.base.types import StatementPostingOutcome, StatementPostingStatus
from src.extraction.extension.statement_posting import (
    StatementPostingDependencies,
    auto_create_posted_entries_for_statement,
    reconcile_account_statement_chain,
    release_statement_ledger_effects,
    try_auto_post_statement_opening_balance,
)
from src.extraction.extension.statement_validation import (
    approve_statement,
    reject_statement,
)
from src.extraction.orm.statement_summary import StatementSummary
from src.observability import get_logger, safe_error_message

logger = get_logger(__name__)

TENANT_ANALYZE_TABLES: tuple[str, ...] = (
    "journal_entries",
    "journal_lines",
    "atomic_transactions",
    "reconciliation_matches",
    "trace_records",
    "statement_summaries",
)


# A refresh waits at most this long for a table lock, and runs at most this long (#2970).
TENANT_STATISTICS_LOCK_TIMEOUT = "2s"
TENANT_STATISTICS_STATEMENT_TIMEOUT = "20s"
# The background task waits this long after each run before it reads the request flag again.
TENANT_STATISTICS_MIN_GAP_SECONDS = 10.0

# The single background task of this process. The module holds it, so the event loop cannot drop it.
_refresh_task: asyncio.Task[None] | None = None
# Set by each request. The task clears it when a run starts, so one flag value stands for any number of requests.
_refresh_requested = False


async def analyze_tenant_tables(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Run one bounded ``ANALYZE`` of the core tenant tables in a session of its own (#2629, #2970).

    ``SET LOCAL`` ends the lock wait and the run at the two timeouts. A failure raises to the caller,
    which is the background task and not a request.
    """
    tables_sql = ", ".join(TENANT_ANALYZE_TABLES)
    async with session_maker() as session:
        await session.execute(text(f"SET LOCAL lock_timeout = '{TENANT_STATISTICS_LOCK_TIMEOUT}'"))
        await session.execute(text(f"SET LOCAL statement_timeout = '{TENANT_STATISTICS_STATEMENT_TIMEOUT}'"))
        await session.execute(text(f"ANALYZE {tables_sql}"))
        await session.commit()


async def _refresh_tenant_statistics() -> None:
    """Run refreshes while a request is pending, then end. A failure is logged and never raised."""
    global _refresh_task, _refresh_requested
    try:
        while _refresh_requested:
            _refresh_requested = False
            try:
                await analyze_tenant_tables(get_test_session_maker() or async_session_maker)
            except Exception as exc:
                logger.warning(
                    "statement.statistics_refresh.failed",
                    error_type=type(exc).__name__,
                    error=safe_error_message(exc),
                )
            await asyncio.sleep(TENANT_STATISTICS_MIN_GAP_SECONDS)
    finally:
        if _refresh_task is asyncio.current_task():
            _refresh_task = None


def request_tenant_statistics_refresh(db: AsyncSession) -> None:
    """Request a refresh of the planner statistics of the core tenant tables and return at once (#2629, #2970).

    Planner statistics of a newly loaded user are stale, so a statement can run 4,000 times slower
    until the next refresh. One background task per process runs the refreshes. A request that arrives
    during a run causes exactly one more run. The ``testing`` environment and other dialects than
    PostgreSQL make no request.
    """
    global _refresh_task, _refresh_requested
    if settings.environment == "testing" or os.environ.get("ENVIRONMENT") == "testing":
        return
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    _refresh_requested = True
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(_refresh_tenant_statistics())


async def approve_statement_workflow(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    *,
    dependencies: StatementPostingDependencies,
) -> StatementPostingOutcome:
    """Approve a PARSED statement and post its journal entries as one committed unit.

    Owns the PARSED→APPROVED transition, the auto-posting of journal entries, and
    the single ``commit`` that makes them durable together. The refresh of the planner statistics
    is requested after that commit and runs in the background (#2970). The posting account
    must already be resolved/bound by the caller within the same DB session.
    Domain errors (``ValueError``) propagate uncommitted so the caller can map
    them to HTTP 400 (and roll back the surrounding session). A completed
    economic plan returns ``POSTED``; an incomplete plan is committed back to
    pending review and returns ``REVIEW_REQUIRED``.
    """
    statement = await approve_statement(db, statement_id, user_id)
    outcome = await auto_create_posted_entries_for_statement(db, statement, user_id, dependencies=dependencies)
    if outcome.status is not StatementPostingStatus.REVIEW_REQUIRED:
        await try_auto_post_statement_opening_balance(db, statement, user_id, dependencies=dependencies)
    await db.commit()
    request_tenant_statistics_refresh(db)
    return outcome


async def reject_statement_workflow(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    *,
    reason: str | None = None,
    dependencies: StatementPostingDependencies | None = None,
) -> StatementSummary:
    """Reject a PARSED statement as one committed unit, returning the refreshed row.

    Owns the PARSED→REJECTED transition and its ``commit``. Re-parse queueing is a
    caller (router/background) concern and is intentionally excluded so the state
    transition stays a pure, committed unit.
    """
    # The reject changes the status, so the status before the reject decides which statements keep a shared row.
    # A missing statement gives None here, and ``reject_statement`` reports it.
    status_before = (
        await db.execute(
            select(StatementSummary.status)
            .where(StatementSummary.id == statement_id, StatementSummary.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    statement = await reject_statement(db, statement_id, user_id, reason=reason)
    # A reject of an APPROVED statement keeps a row only for another APPROVED statement.
    # Any other reject keeps a row for every statement that is not RETIRED and not REJECTED (#2888).
    await release_statement_ledger_effects(
        db,
        statement,
        user_id,
        was_approved=status_before == BankStatementStatus.APPROVED,
        reason=reason or "Statement rejected",
        dependencies=dependencies,
    )
    account_id = getattr(statement, "account_id", None)
    if account_id is not None:
        await reconcile_account_statement_chain(db, user_id=user_id, account_id=account_id, dependencies=dependencies)
    await db.commit()
    await db.refresh(statement)
    return statement
