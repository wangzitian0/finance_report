"""Journal entry management API router."""

from datetime import date as date_type
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth import get_current_user_id
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
    validate_fx_rates,
    void_journal_entry,
)

router = APIRouter(prefix="/journal-entries", tags=["journal-entries"])


@router.post("", response_model=JournalEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_journal_entry(
    entry_data: JournalEntryCreate,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> JournalEntryResponse:
    """Create a new journal entry in draft status."""
    # Create entry header
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_data.entry_date,
        memo=entry_data.memo,
        source_type=entry_data.source_type,
        source_id=entry_data.source_id,
    )
    db.add(entry)
    await db.flush()

    # Create journal lines
    lines: list[JournalLine] = []
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
        lines.append(line)

    try:
        validate_fx_rates(lines)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    for line in lines:
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
    user_id: UUID = Depends(get_current_user_id),
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
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(query)
    entries = result.scalars().all()

    items = [JournalEntryResponse.model_validate(e) for e in entries]
    return JournalEntryListResponse(items=items, total=total)


@router.get("/{entry_id}", response_model=JournalEntryResponse)
async def get_journal_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> JournalEntryResponse:
    """Get journal entry details."""
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id)
        .where(JournalEntry.user_id == user_id)
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
    user_id: UUID = Depends(get_current_user_id),
) -> JournalEntryResponse:
    """Post a journal entry (draft → posted)."""
    try:
        entry = await post_journal_entry(db, entry_id, user_id)
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
    user_id: UUID = Depends(get_current_user_id),
) -> JournalEntryResponse:
    """Void a posted journal entry by creating a reversal entry."""
    try:
        reversal_entry = await void_journal_entry(db, entry_id, void_request.reason, user_id)
        return JournalEntryResponse.model_validate(reversal_entry)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_journal_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> None:
    """Delete a draft journal entry."""
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id)
        .where(JournalEntry.user_id == user_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Journal entry {entry_id} not found",
        )

    if entry.status != JournalEntryStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only draft entries can be deleted",
        )

    await db.delete(entry)
    await db.commit()
