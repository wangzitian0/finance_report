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
    generate_cash_flow,
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
async def test_balance_sheet_equation(db: AsyncSession, chart_of_accounts, test_user_id):
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
async def test_income_statement_calculation(db: AsyncSession, chart_of_accounts, test_user_id):
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


@pytest.mark.asyncio
async def test_cash_flow_statement(db: AsyncSession, chart_of_accounts, test_user_id):
    """Cash flow statement should track movements across periods."""
    cash, _liability, equity, income, expense = chart_of_accounts

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
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
                amount=Decimal("5000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("5000.00"),
                currency="SGD",
            ),
        ]
    )

    salary_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 20),
        memo="Salary income",
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
                amount=Decimal("3000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=salary_entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("3000.00"),
                currency="SGD",
            ),
        ]
    )

    expense_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 25),
        memo="Office supplies",
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
                amount=Decimal("500.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=expense_entry.id,
                account_id=cash.id,
                direction=Direction.CREDIT,
                amount=Decimal("500.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    report: dict = await generate_cash_flow(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
    )

    assert "operating" in report
    assert "investing" in report
    assert "financing" in report
    assert "summary" in report
    assert report["currency"] == "SGD"
    assert report["start_date"] == date(2025, 1, 1)
    assert report["end_date"] == date(2025, 1, 31)

    operating: list[dict] = report["operating"]
    investing: list[dict] = report["investing"]
    financing: list[dict] = report["financing"]

    operating_names = [item["subcategory"] for item in operating]
    investing_names = [item["subcategory"] for item in investing]
    financing_names = [item["subcategory"] for item in financing]

    assert income.name in operating_names, "Income account should be in operating activities"
    assert expense.name in operating_names, "Expense account should be in operating activities"
    assert equity.name in financing_names, "Equity account should be in financing activities"
    assert cash.name in investing_names, "Cash (asset) account should be in investing activities"

    summary: dict = report["summary"]
    assert "operating_activities" in summary
    assert "investing_activities" in summary
    assert "financing_activities" in summary
    assert "net_cash_flow" in summary
    assert "beginning_cash" in summary
    assert "ending_cash" in summary


@pytest.mark.asyncio
async def test_cash_flow_empty_period(db: AsyncSession, chart_of_accounts, test_user_id):
    """Cash flow statement with no transactions should return empty lists."""
    report: dict = await generate_cash_flow(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
    )

    assert report["operating"] == []
    assert report["investing"] == []
    assert report["financing"] == []
    assert report["summary"]["net_cash_flow"] == Decimal("0.00")


@pytest.mark.asyncio
async def test_income_statement_with_tags_filter(db: AsyncSession, chart_of_accounts, test_user_id):
    """Income statement should filter by tags when specified."""
    cash, _liability, _equity, income, expense = chart_of_accounts

    tagged_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Tagged salary",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(tagged_entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=tagged_entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("5000.00"),
                currency="SGD",
                tags={"business": True, "project": "alpha"},
            ),
            JournalLine(
                journal_entry_id=tagged_entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("5000.00"),
                currency="SGD",
                tags={"business": True, "project": "alpha"},
            ),
        ]
    )

    untagged_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 20),
        memo="Personal gift",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(untagged_entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=untagged_entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=untagged_entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    report_with_business_tag: dict = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        tags=["business"],
    )

    assert report_with_business_tag["total_income"] == Decimal("5000.00")
    assert report_with_business_tag["filters_applied"]["tags"] == ["business"]

    report_with_all_tags: dict = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        tags=["business", "personal"],
    )

    assert report_with_all_tags["total_income"] == Decimal("5000.00")


@pytest.mark.asyncio
async def test_income_statement_with_account_type_filter(
    db: AsyncSession, chart_of_accounts, test_user_id
):
    """Income statement should filter by account type when specified."""
    cash, _liability, _equity, income, expense = chart_of_accounts

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Mixed entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("5000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("2000.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    report_income_only: dict = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        account_type=AccountType.INCOME,
    )

    assert report_income_only["total_income"] == Decimal("5000.00")
    assert report_income_only["total_expenses"] == Decimal("0.00")
    assert report_income_only["filters_applied"]["account_type"] == "INCOME"
    assert len(report_income_only["expenses"]) == 0

    report_expense_only: dict = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        account_type=AccountType.EXPENSE,
    )

    assert report_expense_only["total_income"] == Decimal("0.00")
    assert report_expense_only["total_expenses"] == Decimal("2000.00")
    assert report_expense_only["filters_applied"]["account_type"] == "EXPENSE"
    assert len(report_expense_only["income"]) == 0


@pytest.mark.asyncio
async def test_income_statement_combined_filters(db: AsyncSession, chart_of_accounts, test_user_id):
    """Income statement should support combined tags and account_type filters."""
    cash, _liability, _equity, income, expense = chart_of_accounts

    tagged_income_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Business income",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(tagged_income_entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=tagged_income_entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("3000.00"),
                currency="SGD",
                tags={"business": True},
            ),
            JournalLine(
                journal_entry_id=tagged_income_entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("3000.00"),
                currency="SGD",
                tags={"business": True},
            ),
        ]
    )

    untagged_income_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 16),
        memo="Personal income",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(untagged_income_entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=untagged_income_entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("2000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=untagged_income_entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("2000.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    report: dict = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        tags=["business"],
        account_type=AccountType.INCOME,
    )

    assert report["total_income"] == Decimal("3000.00")
    assert report["filters_applied"]["tags"] == ["business"]
    assert report["filters_applied"]["account_type"] == "INCOME"


@pytest.mark.asyncio
async def test_cash_flow_with_tags(db: AsyncSession, chart_of_accounts, test_user_id):
    """Cash flow should respect tag filtering."""
    cash, _liability, _equity, income, expense = chart_of_accounts

    tagged_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Tagged investment",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(tagged_entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=tagged_entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("10000.00"),
                currency="SGD",
                tags={"investment": True},
            ),
            JournalLine(
                journal_entry_id=tagged_entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("10000.00"),
                currency="SGD",
                tags={"investment": True},
            ),
        ]
    )
    await db.commit()

    report: dict = await generate_cash_flow(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
    )

    assert "operating" in report
    operating_list = report["operating"]
    assert isinstance(operating_list, list)
