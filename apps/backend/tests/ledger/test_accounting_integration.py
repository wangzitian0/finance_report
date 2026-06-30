"""AC-ledger.2.6 AC-ledger.3.1 AC-ledger.4.3 AC-ledger.5.3: Integration tests for accounting service with database.

These tests cover:
 AC2.3.x: Journal entry posting and voiding
 AC2.4.x: Balance calculation
 AC2.5.x: Accounting equation verification
 AC-ledger.7.1: Transaction boundary handling (flush vs commit)
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.ledger import (
    ValidationError,
    calculate_account_balance,
    calculate_account_balances,
    create_journal_entry,
    post_journal_entry,
    validate_journal_posting_invariants,
    validate_line_account_ownership,
    verify_accounting_equation,
    void_journal_entry,
)
from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from tests.factories import UserFactory


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


async def test_AC2_13_1_create_journal_entry_rejects_cross_user_account(
    db: AsyncSession,
    bank_account,
    salary_account,
    test_user_id,
):
    """AC-ledger.13.1: Manual journal creation rejects lines using another user's account."""
    other_user_id = (await UserFactory.create_async(db)).id
    other_account = Account(
        user_id=other_user_id,
        name="Other User Cash",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(other_account)
    await db.commit()
    await db.refresh(other_account)

    with pytest.raises(ValidationError, match="Account does not belong to user"):
        await create_journal_entry(
            db=db,
            user_id=test_user_id,
            entry_date=date.today(),
            memo="Cross-user attempt",
            lines_data=[
                {"account_id": other_account.id, "direction": Direction.DEBIT, "amount": Decimal("10.00")},
                {"account_id": salary_account.id, "direction": Direction.CREDIT, "amount": Decimal("10.00")},
            ],
        )


async def test_AC2_13_1_line_account_ownership_accepts_empty_line_set(
    db: AsyncSession,
    test_user_id,
):
    """AC-ledger.13.1: Empty line account sets short-circuit without a database lookup."""
    accounts = await validate_line_account_ownership(db, test_user_id, set())

    assert accounts == {}


async def test_AC2_13_1_line_account_ownership_rejects_missing_account(
    db: AsyncSession,
    test_user_id,
):
    """AC-ledger.13.1: Journal lines cannot reference nonexistent accounts."""
    missing_account_id = uuid4()

    with pytest.raises(ValidationError, match=f"Account {missing_account_id} not found"):
        await validate_line_account_ownership(db, test_user_id, {missing_account_id})


async def test_AC2_13_2_journal_lines_reject_cross_user_account_at_db_boundary(
    db: AsyncSession,
    bank_account,
    salary_account,
    test_user_id,
):
    """AC-ledger.13.2: Database invariants reject line accounts outside the entry owner."""
    other_user_id = (await UserFactory.create_async(db)).id
    other_account = Account(
        user_id=other_user_id,
        name="Other User Asset",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(other_account)
    await db.flush()

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Cross-user draft",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=other_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("25.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("25.00"),
                currency="SGD",
            ),
        ]
    )

    with pytest.raises(IntegrityError, match="cannot reference cross-user account"):
        await db.flush()
    await db.rollback()


async def test_AC2_13_2_posting_invariants_reject_line_with_missing_account_relationship(
    test_user_id,
):
    """AC-ledger.13.2: Posting invariants require every line to resolve to an account."""
    missing_account_id = uuid4()
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Missing account",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.DRAFT,
    )
    entry.lines = [
        JournalLine(
            journal_entry_id=uuid4(),
            account_id=missing_account_id,
            direction=Direction.DEBIT,
            amount=Decimal("25.00"),
            currency="SGD",
        ),
        JournalLine(
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.CREDIT,
            amount=Decimal("25.00"),
            currency="SGD",
        ),
    ]

    with pytest.raises(ValidationError, match=f"Account {missing_account_id} not found"):
        validate_journal_posting_invariants(entry)


async def test_AC2_13_3_balance_queries_ignore_cross_user_entry_headers(
    db: AsyncSession,
    bank_account,
    salary_account,
    test_user_id,
):
    """AC-ledger.13.3: Balance aggregation requires account and entry ownership to match."""
    other_user_id = (await UserFactory.create_async(db)).id
    other_account = Account(
        user_id=other_user_id,
        name="Other User Cash",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(other_account)
    await db.flush()

    polluted_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Pollution attempt",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(polluted_entry)
    await db.flush()
    try:
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        db.add_all(
            [
                JournalLine(
                    journal_entry_id=polluted_entry.id,
                    account_id=other_account.id,
                    direction=Direction.DEBIT,
                    amount=Decimal("99.00"),
                    currency="SGD",
                ),
                JournalLine(
                    journal_entry_id=polluted_entry.id,
                    account_id=salary_account.id,
                    direction=Direction.CREDIT,
                    amount=Decimal("99.00"),
                    currency="SGD",
                ),
            ]
        )
        await db.flush()
    finally:
        await db.execute(text("SET LOCAL session_replication_role = DEFAULT"))
    await db.commit()

    balances = await calculate_account_balances(db, [other_account], other_user_id)

    assert balances[other_account.id] == Decimal("0")


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
        # Legacy raw 'bank_statement' (retired from the enum in 0040, #896) is
        # still accepted on write and normalized to auto_parsed.
        source_type="bank_statement",
        source_id=source_id,
    )

    assert entry.source_type == JournalEntrySourceType.AUTO_PARSED
    assert entry.source_id == source_id
    await db.commit()


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


async def test_create_journal_entry_default_currency_uses_configured_base_currency(
    db: AsyncSession, bank_account, salary_account, test_user_id, monkeypatch: pytest.MonkeyPatch
):
    """AC-ledger.2.7: Missing line currency defaults to the configured base currency."""
    monkeypatch.setattr(settings, "base_currency", "usd")
    lines_data = [
        {"account_id": bank_account.id, "direction": Direction.DEBIT, "amount": Decimal("500.00")},
        {"account_id": salary_account.id, "direction": Direction.CREDIT, "amount": Decimal("500.00")},
    ]

    entry = await create_journal_entry(
        db=db,
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Test configured default currency",
        lines_data=lines_data,
    )

    assert {line.currency for line in entry.lines} == {"USD"}
    await db.commit()


async def test_create_journal_entry_rejects_unbalanced_draft(
    db: AsyncSession, bank_account, salary_account, test_user_id
):
    """AC-ledger.2.2: Service-layer draft creation rejects unbalanced debit/credit lines."""
    lines_data = [
        {"account_id": bank_account.id, "direction": Direction.DEBIT, "amount": Decimal("100.00")},
        {"account_id": salary_account.id, "direction": Direction.CREDIT, "amount": Decimal("90.00")},
    ]

    with pytest.raises(ValidationError, match="Journal entry not balanced"):
        await create_journal_entry(
            db=db,
            user_id=test_user_id,
            entry_date=date.today(),
            memo="Unbalanced draft",
            lines_data=lines_data,
        )


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
        {"account_id": salary_account.id, "direction": Direction.CREDIT, "amount": Decimal("135.00")},
    ]

    with pytest.raises(ValidationError, match="fx_rate required for currency USD"):
        await create_journal_entry(
            db=db,
            user_id=test_user_id,
            entry_date=date.today(),
            memo="Test FX validation",
            lines_data=lines_data,
        )


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
        {"account_id": salary_account.id, "direction": Direction.CREDIT, "amount": Decimal("135.00")},
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
