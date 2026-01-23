"""Tests for multi-currency reporting and FX gain/loss calculation."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    Direction,
    FxRate,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.services.reporting import generate_balance_sheet, generate_income_statement
from src.services.fx import clear_fx_cache


@pytest.fixture(autouse=True)
def cleanup_fx_cache():
    """Clear FX cache before each test to ensure isolation."""
    clear_fx_cache()
    yield
    clear_fx_cache()


@pytest.fixture
def test_user_id():
    return uuid4()


@pytest.fixture
async def multi_currency_accounts(db: AsyncSession, test_user_id):
    """Create accounts in different currencies."""
    accounts = [
        Account(user_id=test_user_id, name="SGD Cash", type=AccountType.ASSET, currency="SGD"),
        Account(user_id=test_user_id, name="USD Savings", type=AccountType.ASSET, currency="USD"),
        Account(user_id=test_user_id, name="Capital", type=AccountType.EQUITY, currency="SGD"),
        Account(user_id=test_user_id, name="Salary", type=AccountType.INCOME, currency="SGD"),
        Account(user_id=test_user_id, name="Dining", type=AccountType.EXPENSE, currency="SGD"),
    ]
    db.add_all(accounts)
    await db.commit()
    for account in accounts:
        await db.refresh(account)
    return accounts


@pytest.fixture
async def fx_rates(db: AsyncSession):
    """Setup historical FX rates."""
    rates = [
        # Rate at beginning of month: 1 USD = 1.30 SGD
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.30"),
            rate_date=date(2025, 1, 1),
            source="test",
        ),
        # Rate at end of month: 1 USD = 1.40 SGD (USD strengthened)
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.40"),
            rate_date=date(2025, 1, 31),
            source="test",
        ),
    ]
    db.add_all(rates)
    await db.commit()
    return rates


@pytest.mark.asyncio
async def test_fx_unrealized_gain_calculation(
    db: AsyncSession, multi_currency_accounts, fx_rates, test_user_id
):
    """Test that unrealized FX gain is correctly calculated in the balance sheet."""
    sgd_cash, usd_savings, capital, *_ = multi_currency_accounts

    # 1. Opening Entry: Invest 100 USD when rate is 1.30 (Historical Cost = 130 SGD)
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 1),
        memo="Initial investment",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_savings.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=capital.id,
                direction=Direction.CREDIT,
                amount=Decimal("130.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    # 2. At end of month, rate is 1.40.
    # Assets: 100 USD * 1.40 = 140 SGD
    # Equity: 130 SGD
    # Unrealized Gain = 140 - 130 = 10 SGD
    report = await generate_balance_sheet(
        db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD"
    )

    assert report["total_assets"] == Decimal("140.00")
    assert report["total_equity"] == Decimal("130.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("10.00")
    assert report["is_balanced"] is True


@pytest.mark.asyncio
async def test_income_statement_comprehensive_income(
    db: AsyncSession, multi_currency_accounts, fx_rates, test_user_id
):
    """Test that income statement includes both net income and unrealized FX change."""
    sgd_cash, usd_savings, capital, salary, _ = multi_currency_accounts

    # 1. Opening (already in USD)
    entry1 = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 1),
        memo="Opening",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry1)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry1.id,
                account_id=usd_savings.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
            JournalLine(
                journal_entry_id=entry1.id,
                account_id=capital.id,
                direction=Direction.CREDIT,
                amount=Decimal("130.00"),
                currency="SGD",
            ),
        ]
    )

    # 2. Income mid-month: 1000 SGD
    entry2 = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Salary",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry2)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry2.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry2.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    # Calculation:
    # Net Income = 1000 SGD
    # Unrealized FX Change = 10 SGD (from USD strengthening)
    # Comprehensive Income = 1010 SGD
    report = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )

    assert report["net_income"] == Decimal("1000.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("10.00")
    assert report["comprehensive_income"] == Decimal("1010.00")
