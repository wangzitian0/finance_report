"""Journal entry management API router."""

from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.models import JournalEntry, JournalEntryStatus, JournalLine
from src.schemas import (
    JournalEntryCreate,
    JournalEntryListResponse,
    JournalEntryResponse,
    VoidJournalEntryRequest,
)
from src.services import (
    ValidationError,
    post_journal_entry,
    void_journal_entry,
)

router = APIRouter(prefix="/api/journal-entries", tags=["journal-entries"])

# Mock user_id for now (will be replaced with auth)
MOCK_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


@router.post("", response_model=JournalEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_journal_entry(
    entry_data: JournalEntryCreate,
    db: AsyncSession = Depends(get_db),
) -> JournalEntryResponse:
    """Create a new journal entry in draft status."""
    # Create entry header
    entry = JournalEntry(
        user_id=MOCK_USER_ID,
        entry_date=entry_data.entry_date,
        memo=entry_data.memo,
        source_type=entry_data.source_type,
        source_id=entry_data.source_id,
    )
    db.add(entry)
    await db.flush()

    # Create journal lines
    for line_data in entry_data.lines:
        line = JournalLine(
            journal_entry_id=entry.id,
            account_id=line_data.account_id,
            direction=line_data.direction,
            amount=line_data.amount,
            currency=line_data.currency,
            fx_rate=line_data.fx_rate,
            event_type=line_data.event_type,
            tags=line_data.tags,
        )
        db.add(line)

    await db.commit()
    await db.refresh(entry, ["lines"])

    return JournalEntryResponse.model_validate(entry)


@router.get("", response_model=JournalEntryListResponse)
async def list_journal_entries(
    status_filter: JournalEntryStatus | None = None,
    start_date: date_type | None = None,
    end_date: date_type | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> JournalEntryListResponse:
    """List journal entries with pagination and filters."""
    query = (
        select(JournalEntry)
        .where(JournalEntry.user_id == MOCK_USER_ID)
        .options(selectinload(JournalEntry.lines))
    )

    if status_filter:
        query = query.where(JournalEntry.status == status_filter)
    if start_date:
        query = query.where(JournalEntry.entry_date >= start_date)
    if end_date:
        query = query.where(JournalEntry.entry_date <= end_date)

    query = query.order_by(JournalEntry.entry_date.desc(), JournalEntry.created_at.desc())

    # Get total count
    count_result = await db.execute(query)
    total = len(count_result.scalars().all())

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    entries = result.scalars().all()

    items = [JournalEntryResponse.model_validate(e) for e in entries]
    return JournalEntryListResponse(items=items, total=total)


@router.get("/{entry_id}", response_model=JournalEntryResponse)
async def get_journal_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JournalEntryResponse:
    """Get journal entry details."""
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id)
        .where(JournalEntry.user_id == MOCK_USER_ID)
        .options(selectinload(JournalEntry.lines))
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Journal entry {entry_id} not found",
        )

    return JournalEntryResponse.model_validate(entry)


@router.post("/{entry_id}/post", response_model=JournalEntryResponse)
async def post_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JournalEntryResponse:
    """Post a journal entry (draft → posted)."""
    try:
        entry = await post_journal_entry(db, entry_id, MOCK_USER_ID)
        await db.refresh(entry, ["lines"])
        return JournalEntryResponse.model_validate(entry)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/{entry_id}/void", response_model=JournalEntryResponse)
async def void_entry(
    entry_id: UUID,
    void_request: VoidJournalEntryRequest,
    db: AsyncSession = Depends(get_db),
) -> JournalEntryResponse:
    """Void a posted journal entry by creating a reversal entry."""
    try:
        reversal_entry = await void_journal_entry(
            db, entry_id, void_request.reason, MOCK_USER_ID
        )
        return JournalEntryResponse.model_validate(reversal_entry)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
