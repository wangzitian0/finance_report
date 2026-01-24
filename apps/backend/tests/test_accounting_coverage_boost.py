"""Tests to increase coverage for accounting service."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from src.services.accounting import (
    ValidationError,
    calculate_account_balance,
    calculate_account_balances,
    post_journal_entry,
    verify_accounting_equation,
    void_journal_entry,
)


@pytest.fixture
async def test_user_id():
    return uuid4()


@pytest.mark.asyncio
async def test_calculate_account_balance_errors(db: AsyncSession, test_user_id):
    with pytest.raises(ValidationError, match="not found"):
        await calculate_account_balance(db, uuid4(), test_user_id)

    other_user_id = uuid4()
    account = Account(
        user_id=other_user_id,
        name="Other User Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    with pytest.raises(ValidationError, match="does not belong to user"):
        await calculate_account_balance(db, account.id, test_user_id)


@pytest.mark.asyncio
async def test_post_journal_entry_errors(db: AsyncSession, test_user_id):
    with pytest.raises(ValidationError, match="not found"):
        await post_journal_entry(db, uuid4(), test_user_id)

    other_user_id = uuid4()
    entry = JournalEntry(
        user_id=other_user_id,
        entry_date=date.today(),
        memo="Other user entry",
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    with pytest.raises(ValidationError, match="does not belong to user"):
        await post_journal_entry(db, entry.id, test_user_id)

    account = Account(
        user_id=test_user_id,
        name="Inactive Account",
        type=AccountType.ASSET,
        currency="SGD",
        is_active=False,
    )
    entry_inactive = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Inactive test",
        status=JournalEntryStatus.DRAFT,
    )
    db.add_all([account, entry_inactive])
    await db.flush()

    other_account = Account(
        user_id=test_user_id,
        name="Active Account",
        type=AccountType.INCOME,
        currency="SGD",
    )
    db.add(other_account)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_inactive.id,
                account_id=account.id,
                direction=Direction.DEBIT,
                amount=Decimal("100"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_inactive.id,
                account_id=other_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("100"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    with pytest.raises(ValidationError, match="is not active"):
        await post_journal_entry(db, entry_inactive.id, test_user_id)


@pytest.mark.asyncio
async def test_void_journal_entry_errors(db: AsyncSession, test_user_id):
    with pytest.raises(ValidationError, match="not found"):
        await void_journal_entry(db, uuid4(), "reason", test_user_id)

    other_user_id = uuid4()
    entry = JournalEntry(
        user_id=other_user_id,
        entry_date=date.today(),
        memo="Other user entry",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.commit()
    # Use select instead of refresh to avoid greenlet issues in some environments
    result = await db.execute(select(JournalEntry).where(JournalEntry.id == entry.id))
    entry = result.scalar_one()

    with pytest.raises(ValidationError, match="does not belong to user"):
        await void_journal_entry(db, entry.id, "reason", test_user_id)

    draft_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Draft entry",
        status=JournalEntryStatus.DRAFT,
    )
    db.add(draft_entry)
    await db.commit()
    result = await db.execute(select(JournalEntry).where(JournalEntry.id == draft_entry.id))
    draft_entry = result.scalar_one()

    with pytest.raises(ValidationError, match="Can only void posted entries"):
        await void_journal_entry(db, draft_entry.id, "reason", test_user_id)


@pytest.mark.asyncio
async def test_calculate_account_balances_other_types(db: AsyncSession, test_user_id):
    liability = Account(
        user_id=test_user_id,
        name="Credit Card",
        type=AccountType.LIABILITY,
        currency="SGD",
    )
    equity = Account(
        user_id=test_user_id,
        name="Opening Balance Equity",
        type=AccountType.EQUITY,
        currency="SGD",
    )
    db.add_all([liability, equity])
    await db.commit()
    await db.refresh(liability)
    await db.refresh(equity)

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Initial load",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=equity.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=liability.id,
                direction=Direction.CREDIT,
                amount=Decimal("1000"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    balances = await calculate_account_balances(db, [liability, equity], test_user_id)

    assert balances[liability.id] == Decimal("1000.00")
    assert balances[equity.id] == Decimal("-1000.00")


@pytest.mark.asyncio
async def test_post_journal_entry_success(db: AsyncSession, test_user_id):
    asset = Account(
        user_id=test_user_id,
        name="Cash",
        type=AccountType.ASSET,
        currency="SGD",
    )
    income = Account(
        user_id=test_user_id,
        name="Income",
        type=AccountType.INCOME,
        currency="SGD",
    )
    db.add_all([asset, income])
    await db.flush()

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Draft to Post",
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=asset.id,
                direction=Direction.DEBIT,
                amount=Decimal("100"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("100"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    posted_entry = await post_journal_entry(db, entry.id, test_user_id)
    assert posted_entry.status == JournalEntryStatus.POSTED


@pytest.mark.asyncio
async def test_void_journal_entry_success(db: AsyncSession, test_user_id):
    asset = Account(
        user_id=test_user_id,
        name="Cash for Void",
        type=AccountType.ASSET,
        currency="SGD",
    )
    income = Account(
        user_id=test_user_id,
        name="Income for Void",
        type=AccountType.INCOME,
        currency="SGD",
    )
    db.add_all([asset, income])
    await db.flush()

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Entry to Void",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=asset.id,
                direction=Direction.DEBIT,
                amount=Decimal("200"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("200"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    reversal = await void_journal_entry(db, entry.id, "Changed mind", test_user_id)

    assert reversal.status == JournalEntryStatus.POSTED
    assert len(reversal.lines) == 2

    result = await db.execute(select(JournalEntry).where(JournalEntry.id == entry.id))
    original = result.scalar_one()
    assert original.status == JournalEntryStatus.VOID
    assert original.void_reason == "Changed mind"


@pytest.mark.asyncio
async def test_verify_accounting_equation_success(db: AsyncSession, test_user_id):
    asset = Account(user_id=test_user_id, name="A", type=AccountType.ASSET, currency="SGD")
    liability = Account(user_id=test_user_id, name="L", type=AccountType.LIABILITY, currency="SGD")
    equity = Account(user_id=test_user_id, name="Eq", type=AccountType.EQUITY, currency="SGD")
    income = Account(user_id=test_user_id, name="I", type=AccountType.INCOME, currency="SGD")
    expense = Account(user_id=test_user_id, name="Ex", type=AccountType.EXPENSE, currency="SGD")

    db.add_all([asset, liability, equity, income, expense])
    await db.commit()

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Equation test",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=asset.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("100"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=liability.id,
                direction=Direction.CREDIT,
                amount=Decimal("200"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("300"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("600"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    assert await verify_accounting_equation(db, test_user_id) is True


@pytest.mark.asyncio
async def test_accounting_utils_coverage(db: AsyncSession, test_user_id):
    with pytest.raises(ValidationError, match="fx_rate required"):
        from src.services.accounting import validate_fx_rates

        line = JournalLine(currency="USD", fx_rate=None)
        validate_fx_rates([line])

    from src.services.accounting import calculate_account_balances

    assert await calculate_account_balances(db, [], test_user_id) == {}


@pytest.mark.asyncio
async def test_accounting_more_errors(db: AsyncSession, test_user_id):
    from src.services.accounting import validate_journal_balance

    with pytest.raises(ValidationError, match="at least 2 lines"):
        validate_journal_balance([JournalLine(amount=Decimal("100"))])

    with pytest.raises(ValidationError, match="not balanced"):
        validate_journal_balance(
            [
                JournalLine(direction=Direction.DEBIT, amount=Decimal("100")),
                JournalLine(direction=Direction.CREDIT, amount=Decimal("101")),
            ]
        )

    entry = JournalEntry(
        user_id=test_user_id,
        status=JournalEntryStatus.POSTED,
        entry_date=date.today(),
        memo="Posted Entry",
    )
    db.add(entry)
    await db.commit()
    with pytest.raises(ValidationError, match="Can only post draft entries"):
        await post_journal_entry(db, entry.id, test_user_id)

    asset = Account(user_id=test_user_id, name="Empty Account", type=AccountType.ASSET, currency="SGD")
    db.add(asset)
    await db.commit()
    balance = await calculate_account_balance(db, asset.id, test_user_id)
    assert balance == Decimal("0")


@pytest.mark.asyncio
async def test_calculate_account_balance_expense(db: AsyncSession, test_user_id):
    expense = Account(user_id=test_user_id, name="Food", type=AccountType.EXPENSE, currency="SGD")
    db.add(expense)
    await db.commit()

    liability = Account(user_id=test_user_id, name="Loan", type=AccountType.LIABILITY, currency="SGD")
    db.add(liability)
    await db.commit()
    balance = await calculate_account_balance(db, liability.id, test_user_id)
    assert balance == Decimal("0")
