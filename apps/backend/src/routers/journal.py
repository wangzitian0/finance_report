from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.deps import CurrentUserId, DbSession
from src.models import JournalEntry, JournalEntryStatus
from src.schemas import (
    JournalEntryCreate,
    JournalEntryListResponse,
    JournalEntryResponse,
    VoidJournalEntryRequest,
)
from src.services import (
    ValidationError,
    create_journal_entry,
    post_journal_entry,
    void_journal_entry,
)
from src.utils import raise_bad_request, raise_not_found

router = APIRouter(prefix="/journal-entries", tags=["journal-entries"])


@router.post("", response_model=JournalEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(
    entry_data: JournalEntryCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> JournalEntryResponse:
    lines_data = [line.model_dump() for line in entry_data.lines]
    try:
        entry = await create_journal_entry(
            db=db,
            user_id=user_id,
            entry_date=entry_data.entry_date,
            memo=entry_data.memo,
            lines_data=lines_data,
            source_type=entry_data.source_type,
            source_id=entry_data.source_id,
        )
        await db.commit()
        await db.refresh(entry, ["lines"])
        return JournalEntryResponse.model_validate(entry)
    except ValidationError as e:
        raise_bad_request(str(e))


@router.get("", response_model=JournalEntryListResponse)
async def list_journal_entries(
    status_filter: JournalEntryStatus | None = None,
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    limit: int = Query(50, ge=1, le=100, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> JournalEntryListResponse:
    """List journal entries with pagination and filters."""
    query = select(JournalEntry).where(JournalEntry.user_id == user_id)

    if status_filter:
        query = query.where(JournalEntry.status == status_filter)
    if start_date:
        query = query.where(JournalEntry.entry_date >= start_date)
    if end_date:
        query = query.where(JournalEntry.entry_date <= end_date)

    # Get total count efficiently without loading data
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Apply pagination and eager load lines
    query = (
        query.options(selectinload(JournalEntry.lines))
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    entries = result.scalars().all()

    items = [JournalEntryResponse.model_validate(e) for e in entries]
    return JournalEntryListResponse(items=items, total=total)


@router.get("/{entry_id}", response_model=JournalEntryResponse)
async def get_journal_entry(
    entry_id: UUID,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> JournalEntryResponse:
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id)
        .where(JournalEntry.user_id == user_id)
        .options(selectinload(JournalEntry.lines))
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise_not_found("Journal entry")

    return JournalEntryResponse.model_validate(entry)


@router.post("/{entry_id}/post", response_model=JournalEntryResponse)
async def post_entry(
    entry_id: UUID,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> JournalEntryResponse:
    try:
        entry = await post_journal_entry(db, entry_id, user_id)
        await db.commit()
        await db.refresh(entry, ["lines"])
        return JournalEntryResponse.model_validate(entry)
    except ValidationError as e:
        raise_bad_request(str(e))


@router.post("/{entry_id}/void", response_model=JournalEntryResponse)
async def void_entry(
    entry_id: UUID,
    void_request: VoidJournalEntryRequest,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> JournalEntryResponse:
    try:
        reversal_entry = await void_journal_entry(db, entry_id, void_request.reason, user_id)
        await db.commit()
        return JournalEntryResponse.model_validate(reversal_entry)
    except ValidationError as e:
        raise_bad_request(str(e))


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_journal_entry(
    entry_id: UUID,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> None:
    result = await db.execute(
        select(JournalEntry).where(JournalEntry.id == entry_id).where(JournalEntry.user_id == user_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise_not_found("Journal entry")

    if entry.status != JournalEntryStatus.DRAFT:
        raise_bad_request("Only draft entries can be deleted")

    await db.delete(entry)
    await db.commit()
