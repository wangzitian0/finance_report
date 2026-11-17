"""Journal entry audit trail endpoints."""

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from src.deps import CurrentUserId, ReadDbSession
from src.ledger import JournalAuditLog, JournalEntry
from src.platform import raise_not_found
from src.schemas.audit import AuditTrailItem, AuditTrailResponse

router = APIRouter(prefix="/journal-entries", tags=["audit"])


@router.get("/{entry_id}/audit", response_model=AuditTrailResponse)
async def get_journal_entry_audit(
    entry_id: UUID,
    db: ReadDbSession,
    user_id: CurrentUserId,
) -> AuditTrailResponse:
    """Return chronological audit records for a user-owned journal entry."""
    entry_result = await db.execute(
        select(JournalEntry.id).where(JournalEntry.id == entry_id).where(JournalEntry.user_id == user_id)
    )
    if entry_result.scalar_one_or_none() is None:
        raise_not_found("Journal entry")

    result = await db.execute(
        select(JournalAuditLog)
        .where(JournalAuditLog.entry_id == entry_id)
        .order_by(JournalAuditLog.created_at.asc())
    )
    logs = result.scalars().all()
    return AuditTrailResponse(items=[AuditTrailItem.model_validate(log) for log in logs])
