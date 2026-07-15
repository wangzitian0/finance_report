"""Transaction audit trail endpoints."""

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from src.audit.base.types.audit import AuditTrailItem, AuditTrailResponse
from src.deps import CurrentUserId, DbSession
from src.ledger import JournalAuditLog, JournalEntry
from src.platform import raise_not_found

router = APIRouter(prefix="/transactions", tags=["audit"])


@router.get("/{transaction_id}/audit", response_model=AuditTrailResponse)
async def get_transaction_audit(
    transaction_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> AuditTrailResponse:
    """Return chronological audit records for a user-owned transaction."""
    entry_result = await db.execute(
        select(JournalEntry.id).where(JournalEntry.id == transaction_id).where(JournalEntry.user_id == user_id)
    )
    if entry_result.scalar_one_or_none() is None:
        raise_not_found("Transaction")

    result = await db.execute(
        select(JournalAuditLog)
        .where(JournalAuditLog.entry_id == transaction_id)
        .order_by(JournalAuditLog.created_at.asc())
    )
    logs = result.scalars().all()
    return AuditTrailResponse(items=[AuditTrailItem.model_validate(log) for log in logs])
