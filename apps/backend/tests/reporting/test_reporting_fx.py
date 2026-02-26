"""Tests for multi-currency reporting and FX gain/loss calculation."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    Account,
    AccountType,
    Direction,
    FxRate,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from src.services.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)


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
async def test_fx_unrealized_gain_calculation(db: AsyncSession, multi_currency_accounts, fx_rates, test_user_id):
    """[AC5.1.2] Test that unrealized FX gain is correctly calculated in the balance sheet."""
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
    report = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")

    assert report["total_assets"] == Decimal("140.00")
    assert report["total_equity"] == Decimal("130.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("10.00")
    assert report["is_balanced"] is True


@pytest.mark.asyncio
async def test_income_statement_comprehensive_income(db: AsyncSession, multi_currency_accounts, fx_rates, test_user_id):
    """[AC5.2.2] Test that income statement includes both net income and unrealized FX change."""
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
async def test_fx_liability_inversion(db: AsyncSession, multi_currency_accounts, fx_rates, test_user_id):
    """Test that USD strengthening results in a LOSS for USD-denominated liabilities."""
    # Create a USD Liability account
    usd_debt = Account(user_id=test_user_id, name="USD Debt", type=AccountType.LIABILITY, currency="USD")
    db.add(usd_debt)
    sgd_cash = multi_currency_accounts[0]
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
    report = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")

    assert report["total_assets"] == Decimal("130.00")
    assert report["total_liabilities"] == Decimal("140.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("-10.00")


@pytest.mark.asyncio
async def test_multi_currency_aggregation(db: AsyncSession, multi_currency_accounts, test_user_id):
    """[AC5.1.3] Test aggregation of multiple foreign currencies (USD and EUR)."""
    sgd_cash, usd_savings, capital, *_ = multi_currency_accounts
    eur_savings = Account(user_id=test_user_id, name="EUR Savings", type=AccountType.ASSET, currency="EUR")
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

    report = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 1), currency="SGD")

    # USD 100 * 1.3 = 130
    # EUR 100 * 1.5 = 150
    # Total Assets = 280
    assert report["total_assets"] == Decimal("280.00")
    assert report["total_equity"] == Decimal("280.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("0.00")


@pytest.mark.asyncio
async def test_historical_vs_average_discrepancy_bridge(db: AsyncSession, multi_currency_accounts, test_user_id):
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
    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
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


@pytest.mark.asyncio
async def test_reporting_fx_fallbacks(db: AsyncSession, multi_currency_accounts, test_user_id):
    """[AC5.4.1] Test FX fallbacks when rates are missing for BS and IS."""
    sgd_cash, usd_savings, capital, salary, dining = multi_currency_accounts

    # Rate only on Jan 31
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.50"),
            rate_date=date(2025, 1, 31),
            source="test",
        )
    )
    await db.commit()

    # Entry on Jan 15 (Missing rate for Jan 15)
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

    # 1. Balance Sheet: Should NOT raise if prefetch fails but fallback works
    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
    # Assets: 100 USD * 1.50 = 150 SGD
    # Income: 100 USD * 1.50 (Fallback to spot) = 150 SGD
    # Unrealized = 150 - 150 = 0
    assert bs["total_assets"] == Decimal("150.00")
    assert bs["net_income"] == Decimal("150.00")
    assert bs["unrealized_fx_gain_loss"] == Decimal("0.00")

    # 2. Income Statement: Should fallback to spot rate at end_date
    is_report = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert is_report["total_income"] == Decimal("150.00")


@pytest.mark.asyncio
async def test_reporting_error_cases(db: AsyncSession, test_user_id):
    """Test error handling and edge cases in reporting."""
    # Start > End
    with pytest.raises(ReportError, match="start_date must be before end_date"):
        await generate_income_statement(db, test_user_id, start_date=date(2025, 1, 31), end_date=date(2025, 1, 1))

    # Missing account for trend
    with pytest.raises(ReportError, match="Account not found"):
        await get_account_trend(db, test_user_id, account_id=uuid4(), period="daily")

    # Invalid period for breakdown
    with pytest.raises(ReportError, match="Unsupported period"):
        await get_category_breakdown(db, test_user_id, breakdown_type=AccountType.INCOME, period="invalid")


@pytest.mark.asyncio
async def test_additional_reports_basic_coverage(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test trend, breakdown and cash flow reports for basic coverage."""
    sgd_cash, usd_savings, capital, salary, dining = multi_currency_accounts

    # Add some data
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Salary and Food",
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
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("1200.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=dining.id,
                direction=Direction.DEBIT,
                amount=Decimal("200.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    # Trend
    trend = await get_account_trend(db, test_user_id, account_id=sgd_cash.id, period="monthly", currency="SGD")
    assert isinstance(trend["points"], list)
    assert len(trend["points"]) > 0

    # Breakdown - need to use today's date or ensure data is within "monthly" start date
    # get_category_breakdown uses date.today() as end_date
    today = date.today()
    breakdown_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=today,
        memo="Today Income",
        status=JournalEntryStatus.POSTED,
    )
    db.add(breakdown_entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=breakdown_entry.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=breakdown_entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    breakdown = await get_category_breakdown(
        db, test_user_id, breakdown_type=AccountType.INCOME, period="monthly", currency="SGD"
    )
    assert isinstance(breakdown["items"], list)
    assert len(breakdown["items"]) >= 1
    assert any(item["category_name"] == "Salary" for item in breakdown["items"])

    # Cash Flow
    # Add cash keywords to sgd_cash name to ensure it's picked up
    sgd_cash.name = "SGD Cash Bank"
    db.add(sgd_cash)
    await db.commit()

    cf = await generate_cash_flow(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert isinstance(cf["summary"], dict)
    assert cf["summary"]["net_cash_flow"] == Decimal("1000.00")
    assert cf["summary"]["ending_cash"] == Decimal("1000.00")


@pytest.mark.asyncio
async def test_reporting_tags_filtering(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test filtering income statement by tags."""
    sgd_cash, _, _, salary, _ = multi_currency_accounts

    # Entry with tags
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Tagged Salary",
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
                amount=Decimal("500.00"),
                currency="SGD",
                tags={"work": "true"},
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("500.00"),
                currency="SGD",
                tags={"work": "true"},
            ),
        ]
    )
    await db.commit()

    # Filter by existing tag
    is_tagged = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        tags=["work"],
    )
    assert is_tagged["total_income"] == Decimal("500.00")

    # Filter by non-existent tag
    is_missing_tag = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        tags=["holiday"],
    )
    assert is_missing_tag["total_income"] == Decimal("0.00")


@pytest.mark.asyncio
async def test_reporting_fx_extreme_fallbacks(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test when ALL FX fallbacks fail for BS and IS."""
    sgd_cash, usd_savings, capital, salary, dining = multi_currency_accounts

    # No rates at all in DB

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

    # Balance Sheet should raise ReportError when fallback fails
    with pytest.raises(ReportError):
        await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")

    # Income Statement should raise ReportError when fallback fails
    with pytest.raises(ReportError):
        await generate_income_statement(
            db,
            test_user_id,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            currency="SGD",
        )


@pytest.mark.asyncio
async def test_reporting_trend_edge_cases(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test trend reporting edge cases (unsupported periods, daily/weekly)."""
    sgd_cash, *_ = multi_currency_accounts

    # Unsupported period
    with pytest.raises(ReportError, match="Unsupported period"):
        await get_account_trend(db, test_user_id, account_id=sgd_cash.id, period="yearly")

    # Daily trend
    trend_daily = await get_account_trend(db, test_user_id, account_id=sgd_cash.id, period="daily")
    assert isinstance(trend_daily["points"], list)
    assert len(trend_daily["points"]) > 0

    # Weekly trend
    trend_weekly = await get_account_trend(db, test_user_id, account_id=sgd_cash.id, period="weekly")
    assert isinstance(trend_weekly["points"], list)
    assert len(trend_weekly["points"]) > 0


@pytest.mark.asyncio
async def test_reporting_breakdown_income_expense_validation(db: AsyncSession, test_user_id):
    """Test that breakdown type must be income or expense."""
    with pytest.raises(ReportError, match="Breakdown type must be income or expense"):
        await get_category_breakdown(db, test_user_id, breakdown_type=AccountType.ASSET, period="monthly")


@pytest.mark.asyncio
async def test_reporting_cash_flow_edge_cases(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test cash flow with investing/financing activities and FX errors."""
    sgd_bank, usd_savings, capital, salary, dining = multi_currency_accounts
    sgd_bank.name = "Bank account"

    # Investing activity (Non-cash asset)
    equipment = Account(user_id=test_user_id, name="Equipment", type=AccountType.ASSET, currency="SGD")
    # Financing activity (Liability)
    loan = Account(user_id=test_user_id, name="Bank Loan", type=AccountType.LIABILITY, currency="SGD")
    db.add_all([equipment, loan, sgd_bank])
    await db.commit()

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Investing and Financing",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_bank.id,
                direction=Direction.DEBIT,
                amount=Decimal("5000"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=loan.id,
                direction=Direction.CREDIT,
                amount=Decimal("5000"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=equipment.id,
                direction=Direction.DEBIT,
                amount=Decimal("2000"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("2000"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    cf = await generate_cash_flow(db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31))
    summary = cf["summary"]
    assert isinstance(summary, dict)
    assert summary["financing_activities"] == Decimal("5000.00")
    assert summary["investing_activities"] == Decimal("2000.00")
    assert summary["net_cash_flow"] == Decimal("3000.00")


@pytest.mark.asyncio
async def test_reporting_remaining_branches(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Cover remaining small branches in reporting.py."""
    sgd_cash, _, _, salary, _ = multi_currency_accounts

    # 1. _quantize_money with int
    from src.services.reporting import _quantize_money

    assert _quantize_money(100) == Decimal("100.00")

    # 2. _iter_periods limit
    from src.services.reporting import _iter_periods

    spans = _iter_periods(date(2025, 1, 1), date(2030, 1, 1), "daily")
    assert len(spans) == 367  # MAX_TREND_POINTS + 1

    # 3. Income Statement with account_type filter
    is_income_only = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        account_type=AccountType.INCOME,
    )
    assert len(is_income_only["expenses"]) == 0

    # 4. Quarterly/Annual breakdowns
    await get_category_breakdown(db, test_user_id, breakdown_type=AccountType.INCOME, period="quarterly")
    await get_category_breakdown(db, test_user_id, breakdown_type=AccountType.INCOME, period="annual")

    # 5. Cash Flow start > end
    with pytest.raises(ReportError, match="start_date must be before end_date"):
        await generate_cash_flow(db, test_user_id, start_date=date(2025, 1, 31), end_date=date(2025, 1, 1))

    # 6. Trend invalid period
    with pytest.raises(ReportError, match="Unsupported period"):
        from src.services.reporting import _iter_periods

        _iter_periods(date(2025, 1, 1), date(2025, 1, 2), "invalid")


@pytest.mark.asyncio
async def test_reporting_cash_flow_before_fx_error(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test cash flow error when FX fails for 'before' period balances."""
    _, usd_savings, *_ = multi_currency_accounts

    # Entry BEFORE start_date
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2024, 12, 1),
        memo="Old Entry",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=usd_savings.id,
            direction=Direction.DEBIT,
            amount=Decimal("100"),
            currency="USD",
        )
    )
    await db.commit()

    # No rates in DB
    with pytest.raises(ReportError):
        await generate_cash_flow(db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31))


@pytest.mark.asyncio
async def test_reporting_cash_flow_fx_error_handling(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test cash flow error handling for FX conversion."""
    sgd_bank, usd_savings, *_ = multi_currency_accounts
    sgd_bank.name = "Bank account"

    # No rates in DB
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="FX CF Error",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=usd_savings.id,
            direction=Direction.DEBIT,
            amount=Decimal("100"),
            currency="USD",
        )
    )
    await db.commit()

    with pytest.raises(ReportError):
        await generate_cash_flow(db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31))


@pytest.mark.asyncio
async def test_reporting_breakdown_fx_error_handling(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test breakdown error handling for FX conversion."""
    _, _, _, salary, _ = multi_currency_accounts

    # No rates in DB
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="FX Breakdown Error",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=salary.id,
            direction=Direction.CREDIT,
            amount=Decimal("100"),
            currency="USD",
        )
    )
    await db.commit()

    with pytest.raises(ReportError):
        await get_category_breakdown(db, test_user_id, breakdown_type=AccountType.INCOME, period="monthly")


@pytest.mark.asyncio
async def test_reporting_trend_fx_error_handling(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test trend error handling for FX conversion."""
    _, usd_savings, *_ = multi_currency_accounts

    # No rates in DB
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="FX Trend Error",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=usd_savings.id,
            direction=Direction.DEBIT,
            amount=Decimal("100"),
            currency="USD",
        )
    )
    await db.commit()

    with pytest.raises(ReportError):
        await get_account_trend(db, test_user_id, account_id=usd_savings.id, period="daily")


@pytest.mark.asyncio
async def test_reporting_income_statement_period_fx_fallback_to_spot(
    db: AsyncSession, multi_currency_accounts, test_user_id
):
    """Test IS fallback from average rate to spot rate when average rate is missing."""
    _, _, _, salary, _ = multi_currency_accounts

    # Rate only at end_date
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.50"),
            rate_date=date(2025, 1, 31),
            source="test",
        )
    )
    await db.commit()

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Salary",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=salary.id,
            direction=Direction.CREDIT,
            amount=Decimal("100"),
            currency="USD",
        )
    )
    await db.commit()

    # Should fallback to spot at 2025-01-31
    report = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert report["total_income"] == Decimal("150.00")


@pytest.mark.asyncio
async def test_balance_sheet_net_income_fx_fallback(db: AsyncSession, multi_currency_accounts, test_user_id):
    """[AC5.4.2] Test balance sheet uses FX fallback (Rate Caching logic).

    This covers the fallback path in _aggregate_net_income_sql (lines 312-333).
    """
    sgd_cash, _, _, salary, expense = multi_currency_accounts

    # Only add FX rate at as_of_date (2025-01-31), NOT at entry_date (2025-01-10)
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=date(2025, 1, 31),
            source="test",
        )
    )
    await db.commit()

    # Create income entry on 2025-01-10 (no FX rate for this date)
    income_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 10),
        memo="USD Salary - no rate at entry date",
        status=JournalEntryStatus.POSTED,
    )
    db.add(income_entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
        ]
    )
    await db.commit()

    # Generate balance sheet at 2025-01-31 (has FX rate)
    # Should fallback to as_of_date rate for the income calculation
    report = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")

    # Net income should be 100 USD * 1.35 = 135 SGD
    assert report["net_income"] == Decimal("135.00")


@pytest.mark.asyncio
async def test_balance_sheet_net_income_no_fx_rate_error(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test balance sheet raises error when no FX rate available for income/expense.

    This covers the error path in _aggregate_net_income_sql (line 324-325).
    """
    sgd_cash, _, _, salary, _ = multi_currency_accounts

    # Create income entry with USD but NO FX rate at all
    income_entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 10),
        memo="USD Salary - no FX rate",
        status=JournalEntryStatus.POSTED,
    )
    db.add(income_entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
        ]
    )
    await db.commit()

    # Should raise ReportError because no USD/SGD rate exists
    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
