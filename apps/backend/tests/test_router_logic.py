"""Direct tests for router functions."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, AccountType, Direction, JournalEntryStatus
from src.routers.accounts import (
    create_account,
    get_account,
    list_accounts,
    update_account,
)
from src.routers.journal import (
    create_journal_entry,
    get_journal_entry,
    list_journal_entries,
    post_entry,
    void_entry,
)
from src.schemas.account import AccountCreate, AccountUpdate
from src.schemas.journal import (
    JournalEntryCreate,
    JournalLineCreate,
    VoidJournalEntryRequest,
)


async def test_account_router_direct(db: AsyncSession) -> None:
    created = await create_account(
        AccountCreate(name="Cash", type=AccountType.ASSET, currency="SGD"),
        db,
    )
    assert created.balance is not None

    listed = await list_accounts(include_balance=False, db=db)
    assert listed.total >= 1

    listed_with_balance = await list_accounts(include_balance=True, db=db)
    assert listed_with_balance.items[0].balance is not None

    filtered = await list_accounts(
        account_type=AccountType.ASSET,
        is_active=True,
        db=db,
    )
    assert filtered.total >= 1

    fetched = await get_account(created.id, db)
    assert fetched.id == created.id

    updated = await update_account(
        created.id,
        AccountUpdate(
            name="Cash Updated",
            code="1001",
            description="Updated account",
            is_active=False,
        ),
        db,
    )
    assert updated.name == "Cash Updated"
    assert updated.is_active is False

    with pytest.raises(HTTPException):
        await get_account(uuid4(), db)

    with pytest.raises(HTTPException):
        await update_account(uuid4(), AccountUpdate(name="Missing"), db)


async def test_journal_router_direct(db: AsyncSession) -> None:
    bank = Account(
        user_id=uuid4(),
        name="Bank",
        type=AccountType.ASSET,
        currency="SGD",
    )
    revenue = Account(
        user_id=uuid4(),
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
    created = await create_journal_entry(entry_data, db)
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
    older = await create_journal_entry(older_entry_data, db)

    listed = await list_journal_entries(
        status_filter=JournalEntryStatus.DRAFT,
        start_date=date.today(),
        page=1,
        page_size=50,
        db=db,
    )
    assert any(item.id == created.id for item in listed.items)
    assert all(item.entry_date >= date.today() for item in listed.items)

    older_list = await list_journal_entries(
        end_date=older.entry_date,
        page=1,
        page_size=50,
        db=db,
    )
    assert any(item.id == older.id for item in older_list.items)

    fetched = await get_journal_entry(created.id, db)
    assert fetched.id == created.id

    with pytest.raises(HTTPException):
        await get_journal_entry(uuid4(), db)

    posted = await post_entry(created.id, db)
    assert posted.status == JournalEntryStatus.POSTED

    voided = await void_entry(
        created.id,
        VoidJournalEntryRequest(reason="Test void"),
        db,
    )
    assert voided.status == JournalEntryStatus.POSTED

    with pytest.raises(HTTPException):
        await post_entry(uuid4(), db)

    with pytest.raises(HTTPException):
        await void_entry(uuid4(), VoidJournalEntryRequest(reason="Missing"), db)
