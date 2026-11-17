from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.deps import Ctx, ReadCtx
from src.ledger import (
    JournalAuditLog,
    JournalEntry,
    JournalEntryStatus,
    post_journal_entry,
    submit_manual_journal_entry,
    void_journal_entry,
)
from src.observability import get_logger, log_financial_mutation
from src.platform import ValidationFailedError, get_owned_or_raise, paginate
from src.schemas import (
    JournalEntryCreate,
    JournalEntryListResponse,
    JournalEntryResponse,
    VoidJournalEntryRequest,
)
from src.schemas.journal import AuditTrailItem, AuditTrailResponse

router = APIRouter(prefix="/journal-entries", tags=["journal-entries"])
logger = get_logger(__name__)


@router.post("", response_model=JournalEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(
    entry_data: JournalEntryCreate,
    ctx: Ctx,
) -> JournalEntryResponse:
    """Create and post a balanced double-entry journal entry."""
    lines_data = [line.model_dump() for line in entry_data.lines]
    base_currency = await ctx.get_base_currency()
    entry = await submit_manual_journal_entry(
        db=ctx.db,
        user_id=ctx.user_id,
        entry_date=entry_data.entry_date,
        memo=entry_data.memo,
        lines_data=lines_data,
        rationale=entry_data.rationale,
        base_currency=base_currency,
    )
    await ctx.db.flush()
    await ctx.db.refresh(entry, ["lines"])
    return JournalEntryResponse.model_validate(entry)


@router.get("", response_model=JournalEntryListResponse)
async def list_journal_entries(
    status_filter: JournalEntryStatus | None = None,
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    limit: int = Query(50, ge=1, le=100, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    *,
    ctx: ReadCtx,
) -> JournalEntryListResponse:
    """List journal entries with pagination and filters."""
    query = select(JournalEntry).where(JournalEntry.user_id == ctx.user_id)

    if status_filter:
        query = query.where(JournalEntry.status == status_filter)
    if start_date:
        query = query.where(JournalEntry.entry_date >= start_date)
    if end_date:
        query = query.where(JournalEntry.entry_date <= end_date)

    entries, total = await paginate(
        ctx.db,
        query,
        limit=limit,
        offset=offset,
        options=[selectinload(JournalEntry.lines)],
        order_by=[JournalEntry.entry_date.desc(), JournalEntry.created_at.desc()],
    )

    items = [JournalEntryResponse.model_validate(e) for e in entries]
    return JournalEntryListResponse(items=items, total=total)


@router.get("/{entry_id}", response_model=JournalEntryResponse)
async def get_journal_entry(
    entry_id: UUID,
    *,
    ctx: ReadCtx,
) -> JournalEntryResponse:
    """Return one journal entry by id with its lines."""
    entry = await get_owned_or_raise(
        ctx.db,
        JournalEntry,
        entry_id,
        ctx.user_id,
        name="Journal entry",
        options=[selectinload(JournalEntry.lines)],
    )
    return JournalEntryResponse.model_validate(entry)


@router.post("/{entry_id}/postings", response_model=JournalEntryResponse)
async def post_entry(
    entry_id: UUID,
    *,
    ctx: Ctx,
) -> JournalEntryResponse:
    """Post a draft journal entry, making it immutable."""
    # `post_journal_entry` validates the draft under the base currency stored at its creation. The
    # effective value applies only to a draft written before revision 0067 (#2539).
    base_currency = await ctx.get_base_currency()
    await get_owned_or_raise(ctx.db, JournalEntry, entry_id, ctx.user_id, name="Journal entry")
    entry = await post_journal_entry(
        ctx.db,
        entry_id,
        ctx.user_id,
        base_currency=base_currency,
    )
    await ctx.db.flush()
    await ctx.db.refresh(entry, ["lines"])
    log_financial_mutation(
        logger,
        "journal.entry.posted",
        user_id=ctx.user_id,
        action="post",
        resource_type="journal_entry",
        resource_id=entry.id,
        status=entry.status.value,
    )
    return JournalEntryResponse.model_validate(entry)


@router.post("/{entry_id}/voidings", response_model=JournalEntryResponse)
async def void_entry(
    entry_id: UUID,
    void_request: VoidJournalEntryRequest,
    *,
    ctx: Ctx,
) -> JournalEntryResponse:
    """Void a posted journal entry with a reason."""
    base_currency = await ctx.get_base_currency()
    reversal_entry = await void_journal_entry(
        ctx.db,
        entry_id,
        void_request.reason,
        ctx.user_id,
        base_currency=base_currency,
    )
    await ctx.db.flush()
    await ctx.db.refresh(reversal_entry, ["lines"])
    log_financial_mutation(
        logger,
        "journal.entry.voided",
        user_id=ctx.user_id,
        action="void",
        resource_type="journal_entry",
        resource_id=entry_id,
        reversal_entry_id=str(reversal_entry.id),
        reason_length=len(void_request.reason or ""),
    )
    return JournalEntryResponse.model_validate(reversal_entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_journal_entry(
    entry_id: UUID,
    *,
    ctx: Ctx,
) -> None:
    """Delete a draft journal entry."""
    entry = await get_owned_or_raise(ctx.db, JournalEntry, entry_id, ctx.user_id, name="Journal entry")

    if entry.status != JournalEntryStatus.DRAFT:
        raise ValidationFailedError("Only draft entries can be deleted")

    await ctx.db.delete(entry)


@router.get("/{entry_id}/audit", response_model=AuditTrailResponse)
async def get_journal_entry_audit(
    entry_id: UUID,
    ctx: ReadCtx,
) -> AuditTrailResponse:
    """Return chronological audit trail entries for a journal entry."""
    await get_owned_or_raise(ctx.db, JournalEntry, entry_id, ctx.user_id, name="Journal entry")
    result = await ctx.db.execute(
        select(JournalAuditLog)
        .where(JournalAuditLog.entry_id == entry_id)
        .order_by(JournalAuditLog.created_at.asc())
    )
    logs = result.scalars().all()
    return AuditTrailResponse(items=[AuditTrailItem.model_validate(log) for log in logs])
