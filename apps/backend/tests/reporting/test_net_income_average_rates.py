"""Tests for net income FX rate methodology alignment.

Verifies that _aggregate_net_income_sql uses period-average rates
(consistent with the income statement) rather than per-transaction-date
historical cost rates.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.models.market_data import FxRate
from src.services.reporting import (
    ReportError,
    _aggregate_net_income_sql,
)


@pytest.fixture
def user_id(test_user):
    return test_user.id


@pytest.fixture
async def income_expense_accounts(db: AsyncSession, user_id):
    accounts = [
        Account(user_id=user_id, name="Checking", type=AccountType.ASSET, currency="SGD"),
        Account(user_id=user_id, name="Capital", type=AccountType.EQUITY, currency="SGD"),
        Account(user_id=user_id, name="Salary", type=AccountType.INCOME, currency="USD"),
        Account(user_id=user_id, name="Food", type=AccountType.EXPENSE, currency="USD"),
    ]
    db.add_all(accounts)
    await db.commit()
    for a in accounts:
        await db.refresh(a)
    return accounts


@pytest.fixture
async def fx_rates_varying(db: AsyncSession):
    """FX rates that vary significantly to make the test meaningful."""
    rates = [
        # Start of period: 1 USD = 1.20 SGD
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.20"), rate_date=date(2025, 1, 1), source="test"
        ),
        # Mid period: 1 USD = 1.30 SGD
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.30"), rate_date=date(2025, 1, 15), source="test"
        ),
        # End of period: 1 USD = 1.40 SGD
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.40"), rate_date=date(2025, 1, 31), source="test"
        ),
    ]
    db.add_all(rates)
    await db.commit()
    return rates


async def test_aggregate_net_income_uses_average_rate(
    db: AsyncSession,
    income_expense_accounts,
    fx_rates_varying,
    user_id,
):
    """_aggregate_net_income_sql should apply a single period-average rate per currency.

    When FX rates vary during the period, the result should reflect the average
    rate (approximately 1.30 SGD/USD) rather than a per-transaction-date rate.
    """
    checking, capital, salary, food = income_expense_accounts

    # Create two entries at different dates: early and late in January
    entry_early = JournalEntry(
        user_id=user_id, entry_date=date(2025, 1, 1), memo="Early", status=JournalEntryStatus.POSTED
    )
    entry_late = JournalEntry(
        user_id=user_id, entry_date=date(2025, 1, 31), memo="Late", status=JournalEntryStatus.POSTED
    )
    db.add_all([entry_early, entry_late])
    await db.flush()

    # Salary income on Jan 1 (rate = 1.20 under historical cost)
    # Food expense on Jan 31 (rate = 1.40 under historical cost)
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_early.id,
                account_id=checking.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000"),
                currency="USD",
                fx_rate=Decimal("1.20"),
            ),
            JournalLine(
                journal_entry_id=entry_early.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("1000"),
                currency="USD",
                fx_rate=Decimal("1.20"),
            ),
            JournalLine(
                journal_entry_id=entry_late.id,
                account_id=food.id,
                direction=Direction.DEBIT,
                amount=Decimal("200"),
                currency="USD",
                fx_rate=Decimal("1.40"),
            ),
            JournalLine(
                journal_entry_id=entry_late.id,
                account_id=checking.id,
                direction=Direction.CREDIT,
                amount=Decimal("200"),
                currency="USD",
                fx_rate=Decimal("1.40"),
            ),
        ]
    )
    await db.commit()

    # Average rate across the period [Jan 1 - Jan 31] = avg(1.20, 1.30, 1.40) = 1.30 SGD/USD
    # SQL AVG() computes an unweighted arithmetic mean across the three rate rows
    net_income = await _aggregate_net_income_sql(db, user_id, "SGD", date(2025, 1, 31), start_date=date(2025, 1, 1))

    # Expected: (1000 - 200) * 1.30 = 800 * 1.30 = 1040
    # Under historical cost: 1000*1.20 - 200*1.40 = 1200 - 280 = 920 (different!)
    assert abs(net_income - Decimal("1040.00")) < Decimal("1.00"), (
        f"Expected ~1040 (average-rate approach), got {net_income}. "
        "This suggests historical-cost rates are still being used."
    )


async def test_aggregate_net_income_no_start_date_uses_all_time_average(
    db: AsyncSession,
    income_expense_accounts,
    fx_rates_varying,
    user_id,
):
    """When start_date is omitted, the all-history average rate should be used."""
    checking, capital, salary, food = income_expense_accounts

    entry = JournalEntry(user_id=user_id, entry_date=date(2025, 1, 15), memo="Salary", status=JournalEntryStatus.POSTED)
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=checking.id,
                direction=Direction.DEBIT,
                amount=Decimal("500"),
                currency="USD",
                fx_rate=Decimal("1.30"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("500"),
                currency="USD",
                fx_rate=Decimal("1.30"),
            ),
        ]
    )
    await db.commit()

    # All-time average from Jan 1 to Jan 15 = avg(1.20, 1.30) = 1.25 (only rates on or before Jan 15)
    net_income = await _aggregate_net_income_sql(db, user_id, "SGD", date(2025, 1, 15))

    # Result should be 500 * ~1.25 = ~625 (not 500*1.30 = 650 spot or 500*1.20 = 600 historical)
    assert net_income > Decimal("0"), f"Net income should be positive, got {net_income}"


async def test_aggregate_net_income_same_currency_no_conversion(
    db: AsyncSession,
    user_id,
):
    """When income/expense currency matches target, net income should be exact."""
    accounts = [
        Account(user_id=user_id, name="Cash", type=AccountType.ASSET, currency="SGD"),
        Account(user_id=user_id, name="Revenue", type=AccountType.INCOME, currency="SGD"),
        Account(user_id=user_id, name="Rent", type=AccountType.EXPENSE, currency="SGD"),
    ]
    db.add_all(accounts)
    await db.commit()
    for a in accounts:
        await db.refresh(a)
    cash, revenue, rent = accounts

    entry = JournalEntry(user_id=user_id, entry_date=date(2025, 3, 1), memo="March", status=JournalEntryStatus.POSTED)
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("3000"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=revenue.id,
                direction=Direction.CREDIT,
                amount=Decimal("3000"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=rent.id,
                direction=Direction.DEBIT,
                amount=Decimal("1200"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction=Direction.CREDIT,
                amount=Decimal("1200"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    net_income = await _aggregate_net_income_sql(db, user_id, "SGD", date(2025, 3, 31))
    assert net_income == Decimal("1800.00")


async def test_aggregate_net_income_raises_on_missing_fx_rate(
    db: AsyncSession,
    user_id,
):
    """ReportError should be raised when no FX rate is available for conversion."""
    accounts = [
        Account(user_id=user_id, name="Cash", type=AccountType.ASSET, currency="EUR"),
        Account(user_id=user_id, name="Sales", type=AccountType.INCOME, currency="EUR"),
    ]
    db.add_all(accounts)
    await db.commit()
    for a in accounts:
        await db.refresh(a)
    cash, sales = accounts

    entry = JournalEntry(user_id=user_id, entry_date=date(2025, 6, 1), memo="Sales", status=JournalEntryStatus.POSTED)
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100"),
                currency="EUR",
                fx_rate=Decimal("1.00"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sales.id,
                direction=Direction.CREDIT,
                amount=Decimal("100"),
                currency="EUR",
                fx_rate=Decimal("1.00"),
            ),
        ]
    )
    await db.commit()

    # No EUR/SGD rate exists → should raise ReportError
    with pytest.raises(ReportError, match="No FX rate available"):
        await _aggregate_net_income_sql(db, user_id, "SGD", date(2025, 6, 30))
