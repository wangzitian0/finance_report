"""Tests for reporting service."""

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
from src.services.reporting import generate_balance_sheet, generate_income_statement


@pytest.fixture
async def test_user_id():
    """Test user ID."""
    return uuid4()


@pytest.fixture
async def chart_of_accounts(db: AsyncSession, test_user_id):
    """Create a minimal chart of accounts for reporting."""
    accounts = [
        Account(
            user_id=test_user_id,
            name="Cash",
            type=AccountType.ASSET,
            currency="SGD",
        ),
        Account(
            user_id=test_user_id,
            name="Credit Card",
            type=AccountType.LIABILITY,
            currency="SGD",
        ),
        Account(
            user_id=test_user_id,
            name="Owner Equity",
            type=AccountType.EQUITY,
            currency="SGD",
        ),
        Account(
            user_id=test_user_id,
            name="Salary",
            type=AccountType.INCOME,
            currency="SGD",
        ),
        Account(
            user_id=test_user_id,
            name="Dining",
            type=AccountType.EXPENSE,
            currency="SGD",
        ),
    ]
    db.add_all(accounts)
    await db.commit()
    for account in accounts:
        await db.refresh(account)
    return accounts


@pytest.mark.asyncio
async def test_balance_sheet_equation(
    db: AsyncSession, chart_of_accounts, test_user_id
):
    """Balance sheet should satisfy Assets = Liabilities + Equity."""
    cash, _liability, equity, *_rest = chart_of_accounts

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Owner contribution",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    report = await generate_balance_sheet(
        db,
        test_user_id,
        as_of_date=date.today(),
        currency="SGD",
    )

    assert report["total_assets"] == Decimal("1000.00")
    assert report["total_liabilities"] == Decimal("0.00")
    assert report["total_equity"] == Decimal("1000.00")
    assert report["equation_delta"] == Decimal("0.00")
    assert report["is_balanced"] is True


@pytest.mark.asyncio
async def test_income_statement_calculation(
    db: AsyncSession, chart_of_accounts, test_user_id
):
    """Income statement should satisfy Net Income = Income - Expenses."""
    cash, _liability, _equity, income, expense = chart_of_accounts

    salary_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Salary",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(salary_entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=salary_entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("5000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=salary_entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("5000.00"),
                currency="SGD",
            ),
        ]
    )

    expense_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 20),
        memo="Dinner",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(expense_entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=expense_entry.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("200.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=expense_entry.id,
                account_id=cash.id,
                direction=Direction.CREDIT,
                amount=Decimal("200.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    report = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
    )

    assert report["total_income"] == Decimal("5000.00")
    assert report["total_expenses"] == Decimal("200.00")
    assert report["net_income"] == Decimal("4800.00")
