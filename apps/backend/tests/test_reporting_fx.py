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


@pytest.mark.asyncio
async def test_fx_liability_inversion(
    db: AsyncSession, multi_currency_accounts, fx_rates, test_user_id
):
    """Test that USD strengthening results in a LOSS for USD-denominated liabilities."""
    # Create a USD Liability account
    usd_debt = Account(
        user_id=test_user_id, name="USD Debt", type=AccountType.LIABILITY, currency="USD"
    )
    db.add(usd_debt)
    sgd_cash = multi_currency_accounts[0]
    capital = multi_currency_accounts[2]
    await db.commit()
    await db.refresh(usd_debt)

    # 1. Borrow 100 USD when rate is 1.30 (Historical Liability = 130 SGD)
    # entry: Debit Cash 130 SGD, Credit USD Debt 100 USD (130 SGD)
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 1),
        memo="Borrow",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("130.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_debt.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
        ]
    )
    await db.commit()

    # 2. At end of month, rate is 1.40.
    # Liability: 100 USD * 1.40 = 140 SGD
    # Historical Net Income = 0
    # Equity = 0
    # Assets = 130 SGD
    # Equation: 130 = 140 + 0 + 0 + Unrealized
    # Unrealized = 130 - 140 = -10 SGD (Loss)
    report = await generate_balance_sheet(
        db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD"
    )

    assert report["total_assets"] == Decimal("130.00")
    assert report["total_liabilities"] == Decimal("140.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("-10.00")


@pytest.mark.asyncio
async def test_multi_currency_aggregation(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test aggregation of multiple foreign currencies (USD and EUR)."""
    sgd_cash, usd_savings, capital, *_ = multi_currency_accounts
    eur_savings = Account(
        user_id=test_user_id, name="EUR Savings", type=AccountType.ASSET, currency="EUR"
    )
    db.add(eur_savings)

    # Rates
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.30"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
            FxRate(
                base_currency="EUR",
                quote_currency="SGD",
                rate=Decimal("1.50"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
        ]
    )
    await db.commit()

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 1),
        memo="Opening",
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
                account_id=eur_savings.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="EUR",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=capital.id,
                direction=Direction.CREDIT,
                amount=Decimal("280.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    report = await generate_balance_sheet(
        db, test_user_id, as_of_date=date(2025, 1, 1), currency="SGD"
    )

    # USD 100 * 1.3 = 130
    # EUR 100 * 1.5 = 150
    # Total Assets = 280
    assert report["total_assets"] == Decimal("280.00")
    assert report["total_equity"] == Decimal("280.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("0.00")


@pytest.mark.asyncio
async def test_historical_vs_average_discrepancy_bridge(
    db: AsyncSession, multi_currency_accounts, test_user_id
):
    """
    Test that the system maintains A=L+E even when:
    - BS uses historical rates for Net Income (transaction date)
    - IS uses period-average rates for the same items
    """
    sgd_cash, usd_savings, capital, salary, _ = multi_currency_accounts

    # Rates
    # Date 1: 1 USD = 1.30 SGD
    # Date 15: 1 USD = 1.40 SGD (Income received)
    # Date 31: 1 USD = 1.50 SGD
    # Average for month: (1.3 + 1.4 + 1.5)/3 = 1.40 (Simplified)
    # Let's just put explicit average rate in DB if we want to be sure
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.30"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.40"),
                rate_date=date(2025, 1, 15),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.50"),
                rate_date=date(2025, 1, 31),
                source="test",
            ),
        ]
    )
    await db.commit()

    # 1. Earn 100 USD on Jan 15.
    # Spot rate: 1.40. Historical value = 140 SGD.
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Salary",
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
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
        ]
    )
    await db.commit()

    # 2. Check Balance Sheet on Jan 31.
    # Assets: 100 USD * 1.50 = 150 SGD
    # Net Income (Historical): 100 USD * 1.40 = 140 SGD
    # Unrealized Gain = 150 - 140 = 10 SGD
    bs = await generate_balance_sheet(
        db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD"
    )
    assert bs["total_assets"] == Decimal("150.00")
    assert bs["net_income"] == Decimal("140.00")
    assert bs["unrealized_fx_gain_loss"] == Decimal("10.00")

    # 3. Check Income Statement for Jan.
    # Income (Average): say average is 1.40 (matches spot on Jan 15 for this test)
    # If it uses average rate, it should match the historical cost in this case.
    # If it uses a DIFFERENT rate (e.g. monthly avg), the unrealized FX change will bridge it.
    is_report = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )

    # Net Income in IS might differ from BS if average rate != historical rate
    # But Comprehensive Income must equal the change in Net Assets.
    # Here Start Net Assets = 0. End Net Assets = 150. Change = 150.
    assert is_report["comprehensive_income"] == Decimal("150.00")
