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
from src.services import reporting as reporting_service
from src.services.reporting import (
    generate_balance_sheet,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)


@pytest.fixture
def test_user_id():
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


@pytest.mark.asyncio
async def test_account_trend_monthly(
    db: AsyncSession, chart_of_accounts, test_user_id, monkeypatch
):
    """Account trend should bucket entries by month."""
    cash, _liability, _equity, income, expense = chart_of_accounts

    class FixedDate(date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2025, 3, 15)

    monkeypatch.setattr(reporting_service, "date", FixedDate)

    entry_one = JournalEntry(
        user_id=test_user_id,
        entry_date=FixedDate(2024, 12, 10),
        memo="Salary",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry_one)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_one.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_one.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ]
    )

    entry_two = JournalEntry(
        user_id=test_user_id,
        entry_date=FixedDate(2025, 2, 5),
        memo="Dinner",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry_two)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_two.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("40.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_two.id,
                account_id=cash.id,
                direction=Direction.CREDIT,
                amount=Decimal("40.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    report = await get_account_trend(
        db,
        test_user_id,
        account_id=cash.id,
        period="monthly",
        currency="SGD",
    )

    points = {point["period_start"]: point["amount"] for point in report["points"]}
    assert points[FixedDate(2024, 12, 1)] == Decimal("100.00")
    assert points[FixedDate(2025, 2, 1)] == Decimal("-40.00")


@pytest.mark.asyncio
async def test_category_breakdown_quarterly(
    db: AsyncSession, chart_of_accounts, test_user_id, monkeypatch
):
    """Category breakdown should aggregate within the selected period."""
    cash, _liability, _equity, _income, expense = chart_of_accounts

    class FixedDate(date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2025, 3, 15)

    monkeypatch.setattr(reporting_service, "date", FixedDate)

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=FixedDate(2025, 2, 10),
        memo="Expense",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("120.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction=Direction.CREDIT,
                amount=Decimal("120.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    report = await get_category_breakdown(
        db,
        test_user_id,
        breakdown_type=AccountType.EXPENSE,
        period="quarterly",
        currency="SGD",
    )

    assert report["items"][0]["total"] == Decimal("120.00")
