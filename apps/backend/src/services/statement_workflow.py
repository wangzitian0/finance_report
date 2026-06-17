"""Statement Stage-1 workflow contracts (EPIC-025 AC25.2.1 / #1158).

Service-level orchestration that owns the transaction boundary and the Stage-1
state transition for statement approval/rejection, so routers stay thin (HTTP
mapping + response shaping only). Behavior-preserving extraction of the inline
router sequences — same service calls, same commit point, same ordering.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.statement_summary import StatementSummary
from src.services.statement_posting import auto_create_posted_entries_for_statement
from src.services.statement_validation import approve_statement, reject_statement


async def approve_statement_workflow(db: AsyncSession, statement_id: UUID, user_id: UUID) -> int:
    """Approve a PARSED statement and post its journal entries as one committed unit.

    Owns the PARSED→APPROVED transition, the auto-posting of journal entries, and
    the single ``commit`` that makes them durable together. The posting account
    must already be resolved/bound by the caller within the same DB session.
    Domain errors (``ValueError``) propagate uncommitted so the caller can map
    them to HTTP 400 (and roll back the surrounding session). Returns the number
    of journal entries created.
    """
    statement = await approve_statement(db, statement_id, user_id)
    created_count = await auto_create_posted_entries_for_statement(db, statement, user_id)
    await db.commit()
    return created_count


async def reject_statement_workflow(
    db: AsyncSession, statement_id: UUID, user_id: UUID, *, reason: str | None = None
) -> StatementSummary:
    """Reject a PARSED statement as one committed unit, returning the refreshed row.

    Owns the PARSED→REJECTED transition and its ``commit``. Re-parse queueing is a
    caller (router/background) concern and is intentionally excluded so the state
    transition stays a pure, committed unit.
    """
    statement = await reject_statement(db, statement_id, user_id, reason=reason)
    await db.commit()
    await db.refresh(statement)
    return statement
