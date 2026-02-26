"""AC2.3 - AC2.5: Integration tests for accounting service with database.

These tests cover:
 AC2.3.x: Journal entry posting and voiding
 AC2.4.x: Balance calculation
 AC2.5.x: Accounting equation verification
 AC2.7.1: Transaction boundary handling (flush vs commit)
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy.orm import selectinload\nfrom sqlalchemy.orm import selectinload

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
    create_journal_entry,
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
async def test_calculate_balance_for_asset_account(db: AsyncSession, bank_account, salary_account, test_user_id):
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
async def test_calculate_balance_for_income_account(db: AsyncSession, bank_account, salary_account, test_user_id):
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
async def test_post_journal_entry_success(db: AsyncSession, bank_account, salary_account, test_user_id):
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
async def test_post_journal_entry_already_posted_fails(db: AsyncSession, bank_account, salary_account, test_user_id):
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
async def test_post_unbalanced_journal_entry_fails(db: AsyncSession, bank_account, salary_account, test_user_id):
    """Test that posting an unbalanced journal entry fails with ValidationError."""
    # Create draft entry with unbalanced lines (debit 1000 != credit 500)
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Unbalanced entry",
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
        amount=Decimal("500.00"),  # Intentionally unbalanced
        currency="SGD",
    )
    db.add(line1)
    db.add(line2)
    await db.commit()

    # Try to post - should fail due to unbalanced entry
    with pytest.raises(ValidationError, match="Journal entry not balanced"):
        await post_journal_entry(db, entry.id, test_user_id)


@pytest.mark.asyncio
async def test_void_journal_entry_creates_reversal(db: AsyncSession, bank_account, salary_account, test_user_id):
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
async def test_accounting_equation_holds(db: AsyncSession, bank_account, salary_account, expense_account, test_user_id):
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
async def test_draft_entries_not_included_in_balance(db: AsyncSession, bank_account, salary_account, test_user_id):
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


@pytest.mark.asyncio
async def test_create_journal_entry_basic(db: AsyncSession, bank_account, salary_account, test_user_id):
    """Test basic journal entry creation with balanced debit/credit."""
    lines_data = [
        {
            "account_id": bank_account.id,
            "direction": Direction.DEBIT,
            "amount": Decimal("1500.00"),
        },
        {
            "account_id": salary_account.id,
            "direction": Direction.CREDIT,
            "amount": Decimal("1500.00"),
        },
    ]

    entry = await create_journal_entry(
        db=db,
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Test salary deposit",
        lines_data=lines_data,
    )

    assert entry.id is not None
    assert entry.user_id == test_user_id
    assert entry.memo == "Test salary deposit"
    assert entry.entry_date == date.today()
    assert entry.status == JournalEntryStatus.DRAFT
    assert len(entry.lines) == 2
    await db.commit()


@pytest.mark.asyncio
async def test_create_journal_entry_default_source_type(db: AsyncSession, bank_account, salary_account, test_user_id):
    """Test that source_type defaults to MANUAL."""
    lines_data = [
        {"account_id": bank_account.id, "direction": Direction.DEBIT, "amount": Decimal("100.00")},
        {"account_id": salary_account.id, "direction": Direction.CREDIT, "amount": Decimal("100.00")},
    ]

    entry = await create_journal_entry(
        db=db,
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Test default source type",
        lines_data=lines_data,
    )

    assert entry.source_type == JournalEntrySourceType.MANUAL
    await db.commit()


@pytest.mark.asyncio
async def test_create_journal_entry_custom_source_type(db: AsyncSession, bank_account, salary_account, test_user_id):
    """Test journal entry with custom source_type and source_id."""
    source_id = uuid4()
    lines_data = [
        {"account_id": bank_account.id, "direction": Direction.DEBIT, "amount": Decimal("200.00")},
        {"account_id": salary_account.id, "direction": Direction.CREDIT, "amount": Decimal("200.00")},
    ]

    entry = await create_journal_entry(
        db=db,
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Bank statement entry",
        lines_data=lines_data,
        source_type=JournalEntrySourceType.BANK_STATEMENT,
        source_id=source_id,
    )

    assert entry.source_type == JournalEntrySourceType.BANK_STATEMENT
    assert entry.source_id == source_id
    await db.commit()


@pytest.mark.asyncio
async def test_create_journal_entry_default_currency_sgd(db: AsyncSession, bank_account, salary_account, test_user_id):
    """Test that line currency defaults to SGD when not specified."""
    lines_data = [
        {"account_id": bank_account.id, "direction": Direction.DEBIT, "amount": Decimal("500.00")},
        {"account_id": salary_account.id, "direction": Direction.CREDIT, "amount": Decimal("500.00")},
    ]

    entry = await create_journal_entry(
        db=db,
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Test default currency",
        lines_data=lines_data,
    )

    for line in entry.lines:
        assert line.currency == "SGD"
    await db.commit()


@pytest.mark.asyncio
async def test_create_journal_entry_fx_rate_required_for_foreign_currency(
    db: AsyncSession, bank_account, salary_account, test_user_id
):
    """Test that fx_rate is required for non-SGD currencies."""
    lines_data = [
        {
            "account_id": bank_account.id,
            "direction": Direction.DEBIT,
            "amount": Decimal("100.00"),
            "currency": "USD",
        },
        {"account_id": salary_account.id, "direction": Direction.CREDIT, "amount": Decimal("100.00")},
    ]

    with pytest.raises(ValidationError, match="fx_rate required for currency USD"):
        await create_journal_entry(
            db=db,
            user_id=test_user_id,
            entry_date=date.today(),
            memo="Test FX validation",
            lines_data=lines_data,
        )


@pytest.mark.asyncio
async def test_create_journal_entry_with_fx_rate(db: AsyncSession, bank_account, salary_account, test_user_id):
    """Test journal entry with foreign currency and valid fx_rate."""
    lines_data = [
        {
            "account_id": bank_account.id,
            "direction": Direction.DEBIT,
            "amount": Decimal("100.00"),
            "currency": "USD",
            "fx_rate": Decimal("1.35"),
        },
        {"account_id": salary_account.id, "direction": Direction.CREDIT, "amount": Decimal("100.00")},
    ]

    entry = await create_journal_entry(
        db=db,
        user_id=test_user_id,
        entry_date=date.today(),
        memo="USD transaction",
        lines_data=lines_data,
    )

    usd_line = next(line for line in entry.lines if line.currency == "USD")
    assert usd_line.fx_rate == Decimal("1.35")
    await db.commit()


@pytest.mark.asyncio
async def test_create_journal_entry_with_optional_fields(db: AsyncSession, bank_account, salary_account, test_user_id):
    """Test journal entry with optional event_type and tags."""
    lines_data = [
        {
            "account_id": bank_account.id,
            "direction": Direction.DEBIT,
            "amount": Decimal("300.00"),
            "event_type": "DEPOSIT",
            "tags": ["salary", "monthly"],
        },
        {
            "account_id": salary_account.id,
            "direction": Direction.CREDIT,
            "amount": Decimal("300.00"),
            "event_type": "INCOME",
            "tags": ["employment"],
        },
    ]

    entry = await create_journal_entry(
        db=db,
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Tagged entry",
        lines_data=lines_data,
    )

    bank_line = next(line for line in entry.lines if line.account_id == bank_account.id)
    salary_line = next(line for line in entry.lines if line.account_id == salary_account.id)

    assert bank_line.event_type == "DEPOSIT"
    assert bank_line.tags == ["salary", "monthly"]
    assert salary_line.event_type == "INCOME"
    assert salary_line.tags == ["employment"]
    await db.commit()


@pytest.mark.asyncio
async def test_create_journal_entry_uses_flush_not_commit(db: AsyncSession, bank_account, salary_account, test_user_id):
    """Test that create_journal_entry uses flush() not commit() - allows transaction control."""
    lines_data = [
        {"account_id": bank_account.id, "direction": Direction.DEBIT, "amount": Decimal("100.00")},
        {"account_id": salary_account.id, "direction": Direction.CREDIT, "amount": Decimal("100.00")},
    ]

    entry = await create_journal_entry(
        db=db,
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Flush test",
        lines_data=lines_data,
    )

    assert entry.id is not None
    await db.rollback()

    from sqlalchemy import select

    result = await db.execute(select(JournalEntry).where(JournalEntry.id == entry.id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_post_unbalanced_entry_rejected(db: AsyncSession, bank_account, salary_account, test_user_id):
    """
    CRITICAL: Verify that posting an unbalanced entry is rejected.

    This test ensures the constraint:
    "NEVER skip entry balance validation or post entries without accounting equation check"

    The system MUST reject posting entries with unbalanced debit/credit amounts.
    """
    # Create an entry with unbalanced amounts: DEBIT 100, CREDIT 90
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Unbalanced entry should be rejected",
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()

    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=bank_account.id,
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="SGD",
        )
    )
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=salary_account.id,
            direction=Direction.CREDIT,
            amount=Decimal("90.00"),  # Intentionally unbalanced
            currency="SGD",
        )
    )
    await db.commit()

    # Attempting to post an unbalanced entry should fail with ValidationError
    with pytest.raises(ValidationError, match="not balanced"):
        await post_journal_entry(db, entry.id, test_user_id)

    # Verify entry remains in DRAFT status
    await db.refresh(entry)
    assert entry.status == JournalEntryStatus.DRAFT


@pytest.mark.asyncio
async def test_post_single_line_entry_rejected(db: AsyncSession, bank_account, test_user_id):
    """
    CRITICAL: Verify that posting a single-line entry is rejected.

    This test ensures the constraint:
    "NEVER skip entry balance validation or post entries without accounting equation check"

    Double-entry bookkeeping requires at least 2 lines (one debit, one credit).
    """
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Single line entry should be rejected",
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()

    # Only add a single DEBIT line
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=bank_account.id,
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="SGD",
        )
    )
    await db.commit()

    # Attempting to post a single-line entry should fail
    with pytest.raises(ValidationError, match="at least 2 lines"):
        await post_journal_entry(db, entry.id, test_user_id)

    # Verify entry remains in DRAFT status
    await db.refresh(entry)
    assert entry.status == JournalEntryStatus.DRAFT
