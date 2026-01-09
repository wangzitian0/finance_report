"""Integration tests for accounting service with database."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.services.accounting import (
    ValidationError,
    calculate_account_balance,
    post_journal_entry,
    verify_accounting_equation,
    void_journal_entry,
)


@pytest.fixture
async def test_user_id():
    """Test user ID."""
    return uuid4()


@pytest.fixture
async def bank_account(db: AsyncSession, test_user_id):
    """Create a test bank account."""
    account = Account(
        user_id=test_user_id,
        name="Test Bank Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@pytest.fixture
async def salary_account(db: AsyncSession, test_user_id):
    """Create a test salary income account."""
    account = Account(
        user_id=test_user_id,
        name="Test Salary Income",
        type=AccountType.INCOME,
        currency="SGD",
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@pytest.fixture
async def expense_account(db: AsyncSession, test_user_id):
    """Create a test expense account."""
    account = Account(
        user_id=test_user_id,
        name="Test Expense",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@pytest.mark.asyncio
async def test_calculate_balance_for_asset_account(
    db: AsyncSession, bank_account, salary_account, test_user_id
):
    """Test balance calculation for asset account with salary income."""
    # Create and post journal entry: Debit Bank 5000, Credit Salary 5000
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Test salary deposit",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    line1 = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank_account.id,
        direction=Direction.DEBIT,
        amount=Decimal("5000.00"),
        currency="SGD",
    )
    line2 = JournalLine(
        journal_entry_id=entry.id,
        account_id=salary_account.id,
        direction=Direction.CREDIT,
        amount=Decimal("5000.00"),
        currency="SGD",
    )
    db.add(line1)
    db.add(line2)
    await db.commit()

    # Check bank account balance (should be +5000 for asset account)
    balance = await calculate_account_balance(db, bank_account.id, test_user_id)
    assert balance == Decimal("5000.00")


@pytest.mark.asyncio
async def test_calculate_balance_for_income_account(
    db: AsyncSession, bank_account, salary_account, test_user_id
):
    """Test balance calculation for income account."""
    # Create and post journal entry
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Test salary income",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    line1 = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank_account.id,
        direction=Direction.DEBIT,
        amount=Decimal("3000.00"),
        currency="SGD",
    )
    line2 = JournalLine(
        journal_entry_id=entry.id,
        account_id=salary_account.id,
        direction=Direction.CREDIT,
        amount=Decimal("3000.00"),
        currency="SGD",
    )
    db.add(line1)
    db.add(line2)
    await db.commit()

    # Check salary account balance (should be +3000 for income account)
    balance = await calculate_account_balance(db, salary_account.id, test_user_id)
    assert balance == Decimal("3000.00")


@pytest.mark.asyncio
async def test_post_journal_entry_success(
    db: AsyncSession, bank_account, salary_account, test_user_id
):
    """Test posting a draft journal entry."""
    # Create draft entry
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Test draft entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()

    line1 = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank_account.id,
        direction=Direction.DEBIT,
        amount=Decimal("1000.00"),
        currency="SGD",
    )
    line2 = JournalLine(
        journal_entry_id=entry.id,
        account_id=salary_account.id,
        direction=Direction.CREDIT,
        amount=Decimal("1000.00"),
        currency="SGD",
    )
    db.add(line1)
    db.add(line2)
    await db.commit()

    # Post the entry
    posted_entry = await post_journal_entry(db, entry.id, test_user_id)

    assert posted_entry.status == JournalEntryStatus.POSTED
    assert posted_entry.id == entry.id


@pytest.mark.asyncio
async def test_post_journal_entry_already_posted_fails(
    db: AsyncSession, bank_account, salary_account, test_user_id
):
    """Test that posting an already posted entry fails."""
    # Create already posted entry
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Already posted",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    line1 = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank_account.id,
        direction=Direction.DEBIT,
        amount=Decimal("100.00"),
        currency="SGD",
    )
    line2 = JournalLine(
        journal_entry_id=entry.id,
        account_id=salary_account.id,
        direction=Direction.CREDIT,
        amount=Decimal("100.00"),
        currency="SGD",
    )
    db.add(line1)
    db.add(line2)
    await db.commit()

    # Try to post again - should fail
    with pytest.raises(ValidationError, match="Can only post draft entries"):
        await post_journal_entry(db, entry.id, test_user_id)


@pytest.mark.asyncio
async def test_void_journal_entry_creates_reversal(
    db: AsyncSession, bank_account, salary_account, test_user_id
):
    """Test that voiding an entry creates a reversal entry."""
    # Create and post entry
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Entry to void",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    line1 = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank_account.id,
        direction=Direction.DEBIT,
        amount=Decimal("2000.00"),
        currency="SGD",
    )
    line2 = JournalLine(
        journal_entry_id=entry.id,
        account_id=salary_account.id,
        direction=Direction.CREDIT,
        amount=Decimal("2000.00"),
        currency="SGD",
    )
    db.add(line1)
    db.add(line2)
    await db.commit()

    # Void the entry
    reversal = await void_journal_entry(db, entry.id, "Test void", test_user_id)

    # Check reversal entry
    assert reversal.status == JournalEntryStatus.POSTED
    assert len(reversal.lines) == 2
    assert "VOID" in reversal.memo

    # Check original entry is voided
    await db.refresh(entry)
    assert entry.status == JournalEntryStatus.VOID
    assert entry.void_reason == "Test void"
    assert entry.void_reversal_entry_id == reversal.id

    # Check reversal lines have opposite directions
    reversal_lines = {line.account_id: line for line in reversal.lines}
    assert reversal_lines[bank_account.id].direction == Direction.CREDIT
    assert reversal_lines[salary_account.id].direction == Direction.DEBIT


@pytest.mark.asyncio
async def test_accounting_equation_holds(
    db: AsyncSession, bank_account, salary_account, expense_account, test_user_id
):
    """Test that the accounting equation holds after multiple transactions."""
    # Transaction 1: Salary income 5000
    entry1 = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Salary",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry1)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry1.id,
            account_id=bank_account.id,
            direction=Direction.DEBIT,
            amount=Decimal("5000.00"),
            currency="SGD",
        )
    )
    db.add(
        JournalLine(
            journal_entry_id=entry1.id,
            account_id=salary_account.id,
            direction=Direction.CREDIT,
            amount=Decimal("5000.00"),
            currency="SGD",
        )
    )

    # Transaction 2: Expense 1000
    entry2 = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Expense",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry2)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry2.id,
            account_id=expense_account.id,
            direction=Direction.DEBIT,
            amount=Decimal("1000.00"),
            currency="SGD",
        )
    )
    db.add(
        JournalLine(
            journal_entry_id=entry2.id,
            account_id=bank_account.id,
            direction=Direction.CREDIT,
            amount=Decimal("1000.00"),
            currency="SGD",
        )
    )
    await db.commit()

    # Verify accounting equation
    result = await verify_accounting_equation(db, test_user_id)
    assert result is True


@pytest.mark.asyncio
async def test_draft_entries_not_included_in_balance(
    db: AsyncSession, bank_account, salary_account, test_user_id
):
    """Test that draft entries don't affect balance calculation."""
    # Create draft entry
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Draft entry",
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()

    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=bank_account.id,
            direction=Direction.DEBIT,
            amount=Decimal("9999.00"),
            currency="SGD",
        )
    )
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=salary_account.id,
            direction=Direction.CREDIT,
            amount=Decimal("9999.00"),
            currency="SGD",
        )
    )
    await db.commit()

    # Balance should be zero (draft not counted)
    balance = await calculate_account_balance(db, bank_account.id, test_user_id)
    assert balance == Decimal("0")
