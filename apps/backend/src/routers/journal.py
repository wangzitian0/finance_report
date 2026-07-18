from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.config_app import get_effective_base_currency
from src.deps import CurrentUserId, DbSession
from src.ledger import (
    DecisionAnchorError,
    JournalEntry,
    JournalEntryStatus,
    ValidationError,
    post_journal_entry,
    submit_manual_journal_entry,
    validate_manual_journal_entry_for_post,
    void_journal_entry,
)
from src.observability import get_logger, log_financial_mutation
from src.platform import get_owned_or_404, paginate, raise_bad_request
from src.schemas import (
    JournalEntryCreate,
    JournalEntryListResponse,
    JournalEntryResponse,
    VoidJournalEntryRequest,
)

router = APIRouter(prefix="/journal-entries", tags=["journal-entries"])
logger = get_logger(__name__)


@router.post("", response_model=JournalEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(
    entry_data: JournalEntryCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> JournalEntryResponse:
    lines_data = [line.model_dump() for line in entry_data.lines]
    try:
        base_currency = await get_effective_base_currency(db)
        entry = await submit_manual_journal_entry(
            db=db,
            user_id=user_id,
            entry_date=entry_data.entry_date,
            memo=entry_data.memo,
            lines_data=lines_data,
            rationale=entry_data.rationale,
            base_currency=base_currency,
        )
        await db.commit()
        await db.refresh(entry, ["lines"])
        return JournalEntryResponse.model_validate(entry)
    except (DecisionAnchorError, ValidationError) as e:
        raise_bad_request(str(e), cause=e)


@router.get("", response_model=JournalEntryListResponse)
async def list_journal_entries(
    status_filter: JournalEntryStatus | None = None,
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    limit: int = Query(50, ge=1, le=100, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> JournalEntryListResponse:
    """List journal entries with pagination and filters."""
    query = select(JournalEntry).where(JournalEntry.user_id == user_id)

    if status_filter:
        query = query.where(JournalEntry.status == status_filter)
    if start_date:
        query = query.where(JournalEntry.entry_date >= start_date)
    if end_date:
        query = query.where(JournalEntry.entry_date <= end_date)

    entries, total = await paginate(
        db,
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
    db: DbSession,
    user_id: CurrentUserId,
) -> JournalEntryResponse:
    entry = await get_owned_or_404(
        db,
        JournalEntry,
        entry_id,
        user_id,
        name="Journal entry",
        options=[selectinload(JournalEntry.lines)],
    )
    return JournalEntryResponse.model_validate(entry)


@router.post("/{entry_id}/postings", response_model=JournalEntryResponse)
async def post_entry(
    entry_id: UUID,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> JournalEntryResponse:
    try:
        base_currency = await get_effective_base_currency(db)
        draft = await get_owned_or_404(
            db,
            JournalEntry,
            entry_id,
            user_id,
            name="Journal entry",
            options=[selectinload(JournalEntry.lines)],
        )
        await validate_manual_journal_entry_for_post(
            db,
            user_id=user_id,
            entry=draft,
            base_currency=base_currency,
        )
        entry = await post_journal_entry(
            db,
            entry_id,
            user_id,
            base_currency=base_currency,
        )
        await db.commit()
        await db.refresh(entry, ["lines"])
        log_financial_mutation(
            logger,
            "journal.entry.posted",
            user_id=user_id,
            action="post",
            resource_type="journal_entry",
            resource_id=entry.id,
            status=entry.status.value,
        )
        return JournalEntryResponse.model_validate(entry)
    except (DecisionAnchorError, ValidationError) as e:
        raise_bad_request(str(e), cause=e)


@router.post("/{entry_id}/voidings", response_model=JournalEntryResponse)
async def void_entry(
    entry_id: UUID,
    void_request: VoidJournalEntryRequest,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> JournalEntryResponse:
    try:
        base_currency = await get_effective_base_currency(db)
        reversal_entry = await void_journal_entry(
            db,
            entry_id,
            void_request.reason,
            user_id,
            base_currency=base_currency,
        )
        await db.commit()
        await db.refresh(reversal_entry, ["lines"])
        log_financial_mutation(
            logger,
            "journal.entry.voided",
            user_id=user_id,
            action="void",
            resource_type="journal_entry",
            resource_id=entry_id,
            reversal_entry_id=str(reversal_entry.id),
            reason_length=len(void_request.reason or ""),
        )
        return JournalEntryResponse.model_validate(reversal_entry)
    except (DecisionAnchorError, ValidationError) as e:
        raise_bad_request(str(e), cause=e)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_journal_entry(
    entry_id: UUID,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    entry = await get_owned_or_404(db, JournalEntry, entry_id, user_id, name="Journal entry")

    if entry.status != JournalEntryStatus.DRAFT:
        raise_bad_request("Only draft entries can be deleted")

    await db.delete(entry)
    await db.commit()
