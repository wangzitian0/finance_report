"""Statement Stage-1 workflow contracts (EPIC-025 AC25.2.1 / #1158).

Service-level orchestration that owns the transaction boundary and the Stage-1
state transition for statement approval/rejection, so routers stay thin (HTTP
mapping + response shaping only). Behavior-preserving extraction of the inline
router sequences — same service calls, same commit point, same ordering.
"""

from __future__ import annotations

import os
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.extraction.base.types import StatementPostingOutcome, StatementPostingStatus
from src.extraction.extension.statement_posting import (
    StatementPostingDependencies,
    auto_create_posted_entries_for_statement,
    reconcile_account_statement_chain,
    try_auto_post_statement_opening_balance,
    void_statement_posted_entries,
)
from src.extraction.extension.statement_validation import (
    approve_statement,
    reject_statement,
)
from src.extraction.orm.statement_summary import StatementSummary

TENANT_ANALYZE_TABLES: tuple[str, ...] = (
    "journal_entries",
    "journal_lines",
    "atomic_transactions",
    "reconciliation_matches",
    "trace_records",
    "statement_summaries",
)


async def analyze_tenant_tables(db: AsyncSession) -> None:
    """Refresh PostgreSQL planner statistics on core tenant tables after bulk statement approval (#2629)."""
    if settings.environment == "testing" or os.environ.get("ENVIRONMENT") == "testing":
        return
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        tables_sql = ", ".join(TENANT_ANALYZE_TABLES)
        await db.execute(text(f"ANALYZE {tables_sql}"))


async def approve_statement_workflow(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    *,
    dependencies: StatementPostingDependencies,
) -> StatementPostingOutcome:
    """Approve a PARSED statement and post its journal entries as one committed unit.

    Owns the PARSED→APPROVED transition, the auto-posting of journal entries, and
    the single ``commit`` that makes them durable together. The posting account
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
    await analyze_tenant_tables(db)
    return outcome


async def reject_statement_workflow(
    db: AsyncSession, statement_id: UUID, user_id: UUID, *, reason: str | None = None
) -> StatementSummary:
    """Reject a PARSED statement as one committed unit, returning the refreshed row.

    Owns the PARSED→REJECTED transition and its ``commit``. Re-parse queueing is a
    caller (router/background) concern and is intentionally excluded so the state
    transition stays a pure, committed unit.
    """
    statement = await reject_statement(db, statement_id, user_id, reason=reason)
    await void_statement_posted_entries(db, statement, user_id, reason=reason or "Statement rejected")
    account_id = getattr(statement, "account_id", None)
    if account_id is not None:
        await reconcile_account_statement_chain(db, user_id=user_id, account_id=account_id)
    await db.commit()
    await db.refresh(statement)
    return statement
