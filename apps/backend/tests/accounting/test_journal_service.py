"""Direct tests for journal router functions.

These tests validate the journal service layer functions including
journal entry creation, listing, posting, and voiding.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntryStatus
from src.routers.journal import (
    create_entry,
    get_journal_entry,
    list_journal_entries,
    post_entry,
    void_entry,
)
from src.schemas.journal import (
    JournalEntryCreate,
    JournalLineCreate,
    VoidJournalEntryRequest,
)


@pytest.mark.asyncio
async def test_journal_router_direct(db: AsyncSession, test_user) -> None:
    user_id = test_user.id
    bank = Account(
        user_id=user_id,
        name="Bank",
        type=AccountType.ASSET,
        currency="SGD",
    )
    revenue = Account(
        user_id=user_id,
        name="Revenue",
        type=AccountType.INCOME,
        currency="SGD",
    )
    db.add_all([bank, revenue])
    await db.commit()
    await db.refresh(bank)
    await db.refresh(revenue)

    entry_data = JournalEntryCreate(
        entry_date=date.today(),
        memo="Direct entry",
        lines=[
            JournalLineCreate(
                account_id=bank.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLineCreate(
                account_id=revenue.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ],
    )
    created = await create_entry(entry_data, db, user_id=user_id)
    assert created.status == JournalEntryStatus.DRAFT

    older_entry_data = JournalEntryCreate(
        entry_date=date.today() - timedelta(days=7),
        memo="Older entry",
        lines=[
            JournalLineCreate(
                account_id=bank.id,
                direction=Direction.DEBIT,
                amount=Decimal("50.00"),
                currency="SGD",
            ),
            JournalLineCreate(
                account_id=revenue.id,
                direction=Direction.CREDIT,
                amount=Decimal("50.00"),
                currency="SGD",
            ),
        ],
    )
    older = await create_entry(older_entry_data, db, user_id=user_id)

    listed = await list_journal_entries(
        status_filter=JournalEntryStatus.DRAFT,
        start_date=date.today(),
        limit=50,
        offset=0,
        db=db,
        user_id=user_id,
    )
    assert any(item.id == created.id for item in listed.items)
    assert all(item.entry_date >= date.today() for item in listed.items)

    older_list = await list_journal_entries(
        end_date=older.entry_date,
        limit=50,
        offset=0,
        db=db,
        user_id=user_id,
    )
    assert any(item.id == older.id for item in older_list.items)

    fetched = await get_journal_entry(created.id, db, user_id=user_id)
    assert fetched.id == created.id

    with pytest.raises(HTTPException):
        await get_journal_entry(uuid4(), db, user_id=user_id)

    posted = await post_entry(created.id, db, user_id=user_id)
    assert posted.status == JournalEntryStatus.POSTED

    voided = await void_entry(
        created.id,
        VoidJournalEntryRequest(reason="Test void"),
        db,
        user_id=user_id,
    )
    assert voided.status == JournalEntryStatus.POSTED

    with pytest.raises(HTTPException):
        await post_entry(uuid4(), db, user_id=user_id)

    with pytest.raises(HTTPException):
        await void_entry(uuid4(), VoidJournalEntryRequest(reason="Missing"), db, user_id=user_id)
