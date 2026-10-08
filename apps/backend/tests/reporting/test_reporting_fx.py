"""Tests for multi-currency reporting and FX gain/loss calculation."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import Account, AccountType, Direction
from src.pricing.orm.market_data import FxRate
from src.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)
from tests.reporting._report_fixtures import make_entry, make_pair_entry, seed_fx_rates


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
    return await seed_fx_rates(
        db,
        ("USD", "SGD", "1.30", date(2025, 1, 1)),
        ("USD", "SGD", "1.40", date(2025, 1, 31)),
    )


async def test_fx_unrealized_gain_calculation(db: AsyncSession, multi_currency_accounts, fx_rates, test_user_id):
    """AC-reporting.balance-sheet.2: [AC5.1.2] Test that unrealized FX gain is correctly calculated in the balance sheet."""
    sgd_cash, usd_savings, capital, *_ = multi_currency_accounts

    db.add(
        make_entry(
            test_user_id,
            date(2025, 1, 1),
            "Initial investment",
            [
                (usd_savings, Direction.DEBIT, "100.00", "USD", Decimal("1.30")),
                (capital, Direction.CREDIT, "130.00", "SGD", None),
            ],
        )
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")

    assert report["total_assets"] == Decimal("140.00")
    assert report["total_equity"] == Decimal("130.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("10.00")
    assert report["is_balanced"] is True


async def test_income_statement_comprehensive_income(db: AsyncSession, multi_currency_accounts, fx_rates, test_user_id):
    """AC-reporting.income-statement.2: [AC5.2.2] Test that income statement includes both net income and unrealized FX change."""
    sgd_cash, usd_savings, capital, salary, _ = multi_currency_accounts

    db.add_all(
        [
            make_entry(
                test_user_id,
                date(2025, 1, 1),
                "Opening",
                [
                    (usd_savings, Direction.DEBIT, "100.00", "USD", Decimal("1.30")),
                    (capital, Direction.CREDIT, "130.00", "SGD", None),
                ],
            ),
            make_pair_entry(test_user_id, date(2025, 1, 15), "Salary", sgd_cash, salary, "1000.00"),
        ]
    )
    await db.commit()

    report = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )

    assert report["net_income"] == Decimal("1000.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("10.00")
    assert report["comprehensive_income"] == Decimal("1010.00")


async def test_fx_liability_inversion(db: AsyncSession, multi_currency_accounts, fx_rates, test_user_id):
    """Test that USD strengthening results in a LOSS for USD-denominated liabilities."""
    usd_debt = Account(user_id=test_user_id, name="USD Debt", type=AccountType.LIABILITY, currency="USD")
    db.add(usd_debt)
    sgd_cash = multi_currency_accounts[0]
    await db.commit()
    await db.refresh(usd_debt)

    db.add(
        make_entry(
            test_user_id,
            date(2025, 1, 1),
            "Borrow",
            [
                (sgd_cash, Direction.DEBIT, "130.00", "SGD", None),
                (usd_debt, Direction.CREDIT, "100.00", "USD", Decimal("1.30")),
            ],
        )
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")

    assert report["total_assets"] == Decimal("130.00")
    assert report["total_liabilities"] == Decimal("140.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("-10.00")


async def test_multi_currency_aggregation(db: AsyncSession, multi_currency_accounts, test_user_id):
    """AC-reporting.balance-sheet.3: [AC5.1.3] Test aggregation of multiple foreign currencies (USD and EUR)."""
    sgd_cash, usd_savings, capital, *_ = multi_currency_accounts
    eur_savings = Account(user_id=test_user_id, name="EUR Savings", type=AccountType.ASSET, currency="EUR")
    db.add(eur_savings)

    await seed_fx_rates(
        db,
        ("USD", "SGD", "1.30", date(2025, 1, 1)),
        ("EUR", "SGD", "1.50", date(2025, 1, 1)),
    )

    db.add(
        make_entry(
            test_user_id,
            date(2025, 1, 1),
            "Opening",
            [
                (usd_savings, Direction.DEBIT, "100.00", "USD", Decimal("1.30")),
                (eur_savings, Direction.DEBIT, "100.00", "EUR", Decimal("1.50")),
                (capital, Direction.CREDIT, "280.00", "SGD", None),
            ],
        )
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 1), currency="SGD")

    assert report["total_assets"] == Decimal("280.00")
    assert report["total_equity"] == Decimal("280.00")
    assert report["unrealized_fx_gain_loss"] == Decimal("0.00")


async def test_historical_vs_average_discrepancy_bridge(db: AsyncSession, multi_currency_accounts, test_user_id):
    """
    Test that the system maintains A=L+E even when:
    - BS uses historical rates for Net Income (transaction date)
    - IS uses period-average rates for the same items
    """
    sgd_cash, usd_savings, capital, salary, _ = multi_currency_accounts

    await seed_fx_rates(
        db,
        ("USD", "SGD", "1.30", date(2025, 1, 1)),
        ("USD", "SGD", "1.40", date(2025, 1, 15)),
        ("USD", "SGD", "1.50", date(2025, 1, 31)),
    )

    db.add(
        make_pair_entry(
            test_user_id,
            date(2025, 1, 15),
            "Salary",
            usd_savings,
            salary,
            "100.00",
            currency="USD",
            fx_rate=Decimal("1.40"),
        )
    )
    await db.commit()

    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
    assert bs["total_assets"] == Decimal("150.00")
    assert bs["net_income"] == Decimal("140.00")
    assert bs["unrealized_fx_gain_loss"] == Decimal("10.00")

    is_report = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert is_report["comprehensive_income"] == Decimal("150.00")


async def test_reporting_fx_fallbacks(db: AsyncSession, multi_currency_accounts, test_user_id):
    """AC-reporting.fx.1: [AC5.4.1] Test FX fallbacks when rates are missing for BS and IS."""
    sgd_cash, usd_savings, capital, salary, dining = multi_currency_accounts

    await seed_fx_rates(db, ("USD", "SGD", "1.50", date(2025, 1, 31)))
    db.add(
        make_pair_entry(
            test_user_id,
            date(2025, 1, 15),
            "Salary",
            usd_savings,
            salary,
            "100.00",
            currency="USD",
            fx_rate=Decimal("1.50"),
        )
    )
    await db.commit()

    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
    assert bs["total_assets"] == Decimal("150.00")
    assert bs["net_income"] == Decimal("150.00")
    assert bs["unrealized_fx_gain_loss"] == Decimal("0.00")

    is_report = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert is_report["total_income"] == Decimal("150.00")


async def test_reporting_error_cases(db: AsyncSession, test_user_id):
    """Test error handling and edge cases in reporting."""
    with pytest.raises(ReportError, match="start_date must be before end_date"):
        await generate_income_statement(db, test_user_id, start_date=date(2025, 1, 31), end_date=date(2025, 1, 1))

    with pytest.raises(ReportError, match="Account not found"):
        await get_account_trend(db, test_user_id, account_id=uuid4(), period="daily")

    with pytest.raises(ReportError, match="Unsupported period"):
        await get_category_breakdown(db, test_user_id, breakdown_type=AccountType.INCOME, period="invalid")


async def test_additional_reports_basic_coverage(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test trend, breakdown and cash flow reports for basic coverage."""
    sgd_cash, usd_savings, capital, salary, dining = multi_currency_accounts

    db.add(
        make_entry(
            test_user_id,
            date(2025, 1, 15),
            "Salary and Food",
            [
                (sgd_cash, Direction.DEBIT, "1000.00", "SGD", None),
                (salary, Direction.CREDIT, "1200.00", "SGD", None),
                (dining, Direction.DEBIT, "200.00", "SGD", None),
            ],
        )
    )
    await db.commit()

    trend = await get_account_trend(db, test_user_id, account_id=sgd_cash.id, period="monthly", currency="SGD")
    assert isinstance(trend["points"], list)
    assert len(trend["points"]) > 0

    today = date.today()
    db.add(make_pair_entry(test_user_id, today, "Today Income", sgd_cash, salary, "100.00"))
    await db.commit()

    breakdown = await get_category_breakdown(
        db, test_user_id, breakdown_type=AccountType.INCOME, period="monthly", currency="SGD"
    )
    assert isinstance(breakdown["items"], list)
    assert len(breakdown["items"]) >= 1
    assert any(item["category_name"] == "Salary" for item in breakdown["items"])

    sgd_cash.name = "SGD Cash Bank"
    db.add(sgd_cash)
    await db.commit()

    cf = await generate_cash_flow(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert isinstance(cf["summary"], dict)
    assert cf["summary"]["net_cash_flow"] == Decimal("1000.00")
    assert cf["summary"]["ending_cash"] == Decimal("1000.00")


async def test_reporting_tags_filtering(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test filtering income statement by tags."""
    sgd_cash, _, _, salary, _ = multi_currency_accounts

    db.add(
        make_pair_entry(
            test_user_id, date(2025, 1, 15), "Tagged Salary", sgd_cash, salary, "500.00", tags={"work": "true"}
        )
    )
    await db.commit()

    is_tagged = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        tags=["work"],
    )
    assert is_tagged["total_income"] == Decimal("500.00")

    is_missing_tag = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        tags=["holiday"],
    )
    assert is_missing_tag["total_income"] == Decimal("0.00")


async def test_reporting_fx_extreme_fallbacks(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test when ALL FX fallbacks fail for BS and IS."""
    sgd_cash, usd_savings, capital, salary, dining = multi_currency_accounts

    # No rates at all in DB
    db.add(
        make_pair_entry(
            test_user_id,
            date(2025, 1, 15),
            "Salary",
            usd_savings,
            salary,
            "100.00",
            currency="USD",
            fx_rate=Decimal("1.00"),
        )
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


async def test_reporting_breakdown_income_expense_validation(db: AsyncSession, test_user_id):
    """Test that breakdown type must be income or expense."""
    with pytest.raises(ReportError, match="Breakdown type must be income or expense"):
        await get_category_breakdown(db, test_user_id, breakdown_type=AccountType.ASSET, period="monthly")


async def test_reporting_cash_flow_edge_cases(db: AsyncSession, multi_currency_accounts, test_user_id):
    """A mixed balance-sheet event stays in the bridge without guessed activity."""
    sgd_bank, usd_savings, capital, salary, dining = multi_currency_accounts
    sgd_bank.name = "Bank account"

    equipment = Account(user_id=test_user_id, name="Equipment", type=AccountType.ASSET, currency="SGD")
    loan = Account(user_id=test_user_id, name="Bank Loan", type=AccountType.LIABILITY, currency="SGD")
    db.add_all([equipment, loan, sgd_bank])
    await db.commit()

    db.add(
        make_entry(
            test_user_id,
            date(2025, 1, 15),
            "Investing and Financing",
            [
                (sgd_bank, Direction.DEBIT, "5000", "SGD"),
                (loan, Direction.CREDIT, "5000", "SGD"),
                (equipment, Direction.DEBIT, "2000", "SGD"),
                (sgd_bank, Direction.CREDIT, "2000", "SGD"),
            ],
        )
    )
    await db.commit()

    cf = await generate_cash_flow(db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31))
    summary = cf["summary"]
    assert isinstance(summary, dict)
    assert summary["financing_activities"] == Decimal("0.00")
    assert summary["investing_activities"] == Decimal("0.00")
    assert summary["net_cash_flow"] == Decimal("3000.00")
    assert cf["cash_bridge"]["unclassified_cash"] == Decimal("3000.00")
    assert cf["proof_state"] == "unproven"


async def test_reporting_remaining_branches(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Cover remaining small branches in reporting.py."""
    sgd_cash, _, _, salary, _ = multi_currency_accounts

    # 1. _quantize_money with int
    from src.reporting import _quantize_money

    assert _quantize_money(100) == Decimal("100.00")

    # 2. _iter_periods limit
    from src.reporting import _iter_periods

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
        from src.reporting import _iter_periods

        _iter_periods(date(2025, 1, 1), date(2025, 1, 2), "invalid")


async def test_reporting_cash_flow_before_fx_error(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test cash flow error when FX fails for 'before' period balances."""
    _, usd_savings, capital, *_ = multi_currency_accounts

    db.add(
        make_pair_entry(
            test_user_id,
            date(2024, 12, 1),
            "Old Entry",
            usd_savings,
            capital,
            "100",
            currency="USD",
            fx_rate=Decimal("1.00"),
        )
    )
    await db.commit()

    # No rates in DB
    with pytest.raises(ReportError):
        await generate_cash_flow(db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31))


async def test_reporting_cash_flow_fx_error_handling(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test cash flow error handling for FX conversion."""
    sgd_bank, usd_savings, capital, *_ = multi_currency_accounts
    sgd_bank.name = "Bank account"

    # No rates in DB
    db.add(
        make_pair_entry(
            test_user_id,
            date(2025, 1, 15),
            "FX CF Error",
            usd_savings,
            capital,
            "100",
            currency="USD",
            fx_rate=Decimal("1.00"),
        )
    )
    await db.commit()

    with pytest.raises(ReportError):
        await generate_cash_flow(db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31))


async def test_reporting_breakdown_fx_error_handling(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test breakdown error handling for FX conversion."""
    sgd_cash, _, _, salary, _ = multi_currency_accounts

    # No rates in DB
    db.add(
        make_pair_entry(
            test_user_id,
            date.today(),
            "FX Breakdown Error",
            sgd_cash,
            salary,
            "100",
            currency="USD",
            fx_rate=Decimal("1.00"),
        )
    )
    await db.commit()

    with pytest.raises(ReportError):
        await get_category_breakdown(db, test_user_id, breakdown_type=AccountType.INCOME, period="monthly")


async def test_reporting_trend_fx_error_handling(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test trend error handling for FX conversion."""
    _, usd_savings, capital, *_ = multi_currency_accounts

    # No rates in DB
    db.add(
        make_pair_entry(
            test_user_id,
            date.today(),
            "FX Trend Error",
            usd_savings,
            capital,
            "100",
            currency="USD",
            fx_rate=Decimal("1.00"),
        )
    )
    await db.commit()

    with pytest.raises(ReportError):
        await get_account_trend(db, test_user_id, account_id=usd_savings.id, period="daily")


async def test_reporting_income_statement_period_fx_fallback_to_spot(
    db: AsyncSession, multi_currency_accounts, test_user_id
):
    """Test IS fallback from average rate to spot rate when average rate is missing."""
    sgd_cash, _, _, salary, _ = multi_currency_accounts

    await seed_fx_rates(db, ("USD", "SGD", "1.50", date(2025, 1, 31)))

    db.add(
        make_pair_entry(
            test_user_id,
            date(2025, 1, 15),
            "Salary",
            sgd_cash,
            salary,
            "100",
            currency="USD",
            fx_rate=Decimal("1.50"),
        )
    )
    await db.commit()

    # Should fallback to spot at 2025-01-31
    report = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert report["total_income"] == Decimal("150.00")


async def test_balance_sheet_net_income_fx_fallback(db: AsyncSession, multi_currency_accounts, test_user_id):
    """AC-reporting.fx.2: [AC5.4.2] Test balance sheet uses FX fallback (Rate Caching logic).

    This covers the fallback path in _aggregate_net_income_sql (lines 312-333).
    """
    sgd_cash, _, _, salary, _ = multi_currency_accounts

    # Only add FX rate at as_of_date (2025-01-31), NOT at entry_date (2025-01-10)
    await seed_fx_rates(db, ("USD", "SGD", "1.35", date(2025, 1, 31)))

    db.add(
        make_pair_entry(
            test_user_id,
            date(2025, 1, 10),
            "USD Salary - no rate at entry date",
            sgd_cash,
            salary,
            "100.00",
            currency="USD",
            fx_rate=Decimal("1.35"),
        )
    )
    await db.commit()

    # Generate balance sheet at 2025-01-31 (has FX rate)
    # Should fallback to as_of_date rate for the income calculation
    report = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")

    # Net income should be 100 USD * 1.35 = 135 SGD
    assert report["net_income"] == Decimal("135.00")


async def test_reports_lazy_resolve_missing_hkd_sgd_from_bridge_rates(db: AsyncSession, test_user_id):
    """AC-reporting.fx.3: [AC5.4.3] Reports derive and persist a missing HKD/SGD rate from bridge rates."""
    hkd_cash = Account(user_id=test_user_id, name="HKD Cash", type=AccountType.ASSET, currency="HKD")
    hkd_salary = Account(user_id=test_user_id, name="HKD Salary", type=AccountType.INCOME, currency="HKD")
    db.add_all([hkd_cash, hkd_salary])
    await db.flush()

    await seed_fx_rates(
        db,
        ("USD", "HKD", "7.800000", date(2025, 6, 30)),
        ("USD", "SGD", "1.350000", date(2025, 6, 30)),
    )

    db.add(
        make_pair_entry(
            test_user_id,
            date(2025, 6, 30),
            "HKD salary",
            hkd_cash,
            hkd_salary,
            "780.00",
            currency="HKD",
            fx_rate=Decimal("0.173077"),
        )
    )
    await db.commit()

    income_statement = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 6, 1),
        end_date=date(2025, 6, 30),
        currency="SGD",
    )
    balance_sheet = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 6, 30), currency="SGD")

    assert income_statement["total_income"] == Decimal("135.00")
    assert balance_sheet["total_assets"] == Decimal("135.00")
    assert balance_sheet["net_income"] == Decimal("135.00")
    assert balance_sheet["is_balanced"] is True

    result = await db.execute(
        select(FxRate).where(
            FxRate.base_currency == "HKD",
            FxRate.quote_currency == "SGD",
            FxRate.rate_date == date(2025, 6, 30),
        )
    )
    derived_rate = result.scalar_one()
    assert derived_rate.rate == Decimal("0.173077")
    assert derived_rate.source == "derived:bridge:USD"


async def test_balance_sheet_net_income_no_fx_rate_error(db: AsyncSession, multi_currency_accounts, test_user_id):
    """Test balance sheet raises error when no FX rate available for income/expense.

    This covers the error path in _aggregate_net_income_sql (line 324-325).
    """
    sgd_cash, _, _, salary, _ = multi_currency_accounts

    # Create income entry with USD but NO FX rate at all
    db.add(
        make_pair_entry(
            test_user_id,
            date(2025, 1, 10),
            "USD Salary - no FX rate",
            sgd_cash,
            salary,
            "100.00",
            currency="USD",
            fx_rate=Decimal("1.00"),
        )
    )
    await db.commit()

    # Should raise ReportError because no USD/SGD rate exists
    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
