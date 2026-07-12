"""Report package annualized income and long-term compensation schedule tests."""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.models.layer3 import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
)
from src.pricing.orm.market_data import FxRate
from src.reporting.extension.reporting_calc import income_bucket


def test_AC11_11_1_income_bucket_maps_report_package_income_accounts():
    """AC11.11.1: Schedule income bucket mapping covers report package income labels."""
    assert income_bucket("Salary Income") == "salary"
    assert income_bucket("Monthly Payroll") == "salary"
    assert income_bucket("Annual Bonus") == "bonus"
    assert income_bucket("Dividend Income") == "dividend"
    assert income_bucket("Consulting Income") is None


async def test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """AC11.11.1 AC11.11.2: Report package schedule includes income and restricted holdings."""
    salary = Account(user_id=test_user.id, name="Salary Income", type=AccountType.INCOME, currency="SGD")
    bonus = Account(user_id=test_user.id, name="Annual Bonus", type=AccountType.INCOME, currency="SGD")
    dividend = Account(user_id=test_user.id, name="Dividend Income", type=AccountType.INCOME, currency="SGD")
    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    db.add_all([salary, bonus, dividend, cash])
    await db.flush()

    income_entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 5, 1),
        memo="trailing income",
        status=JournalEntryStatus.POSTED,
    )
    db.add(income_entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("137400.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("120000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=bonus.id,
                direction=Direction.CREDIT,
                amount=Decimal("15000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=dividend.id,
                direction=Direction.CREDIT,
                amount=Decimal("2400.00"),
                currency="SGD",
            ),
        ]
    )
    db.add_all(
        [
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.RSU,
                liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
                as_of_date=date(2026, 5, 1),
                value=Decimal("12500.00"),
                currency="SGD",
                source="SHOP-RSU",
                notes="25% annual vesting",
                reminder_date=date(2027, 1, 1),
            ),
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.ESOP,
                liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
                as_of_date=date(2026, 4, 15),
                value=Decimal("85000.00"),
                currency="SGD",
                source="ACME ESOP",
                notes="4-year vesting",
                reminder_date=date(2028, 4, 15),
            ),
        ]
    )
    await db.commit()

    response = await client.get("/reports/package/annualized-income-schedule?as_of_date=2026-05-20")

    assert response.status_code == 200
    data = response.json()
    assert data["section_id"] == "annualized_income_long_term"
    assert data["as_of_date"] == "2026-05-20"
    assert data["trailing_period_start"] == "2025-05-20"
    assert data["trailing_period_end"] == "2026-05-20"
    assert data["trailing_period_days"] == 365
    assert data["income"] == {
        "annualized_salary": "120000.00",
        "annualized_bonus": "15000.00",
        "annualized_dividend": "2400.00",
        "annualized_total": "137400.00",
        "currency": "SGD",
        "calculation_basis": "posted_or_reconciled_income_journal_lines_trailing_12_months",
    }
    assert data["restricted_fair_value_total"] == "97500.00"
    assert data["net_worth_treatment"]["liquid_net_worth_default"] == "exclude_restricted_holdings"
    assert data["net_worth_treatment"]["restricted_wealth_basis"] == "manual_valuation_snapshot_fair_value"
    assert data["notes"] == [
        "Personal management report only; not tax advice.",
        "Restricted holdings are excluded from liquid net worth by default.",
    ]

    holdings = {holding["ticker"]: holding for holding in data["restricted_holdings"]}
    assert holdings["SHOP-RSU"] == {
        "ticker": "SHOP-RSU",
        "compensation_type": "rsu",
        "fair_value": "12500.00",
        "currency": "SGD",
        "valuation_basis": "unspecified",
        "vesting_schedule": "25% annual vesting",
        "unlock_date": "2027-01-01",
        "liquidity_class": "restricted",
        "net_worth_treatment": "excluded_from_liquid_net_worth_by_default",
    }


async def test_AC11_11_4_annualized_schedule_surfaces_structured_valuation_basis(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """AC11.11.4: A restricted holding surfaces its structured valuation_basis enum value.

    A snapshot captured with an explicit evidence basis must report that enum
    value in the schedule (not the hardcoded `manual_valuation_snapshot` literal);
    a snapshot with no basis must fall back to `unspecified`.
    """
    db.add_all(
        [
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.RSU,
                liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
                as_of_date=date(2026, 5, 1),
                value=Decimal("12500.00"),
                currency="SGD",
                source="GRANT-RSU",
                valuation_basis=ManualValuationBasis.EMPLOYER_GRANT_DOCUMENT,
                notes="25% annual vesting",
                reminder_date=date(2027, 1, 1),
            ),
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.ESOP,
                liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
                as_of_date=date(2026, 4, 15),
                value=Decimal("85000.00"),
                currency="SGD",
                source="LEGACY-ESOP",
                valuation_basis=None,
                notes="4-year vesting",
                reminder_date=date(2028, 4, 15),
            ),
        ]
    )
    await db.commit()

    response = await client.get("/reports/package/annualized-income-schedule?as_of_date=2026-05-20")

    assert response.status_code == 200
    holdings = {holding["ticker"]: holding for holding in response.json()["restricted_holdings"]}
    assert holdings["GRANT-RSU"]["valuation_basis"] == "employer_grant_document"
    assert holdings["LEGACY-ESOP"]["valuation_basis"] == "unspecified"


async def test_AC5_11_3_AC11_11_3_annualized_schedule_converts_mixed_currency_totals(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """AC-reporting.package-annualized.2: AC5.11.3/AC11.11.3: Annualized package totals use one reporting currency."""
    salary = Account(user_id=test_user.id, name="Salary Income", type=AccountType.INCOME, currency="SGD")
    dividend = Account(user_id=test_user.id, name="Dividend Income", type=AccountType.INCOME, currency="USD")
    sgd_cash = Account(user_id=test_user.id, name="SGD Cash", type=AccountType.ASSET, currency="SGD")
    usd_cash = Account(user_id=test_user.id, name="USD Cash", type=AccountType.ASSET, currency="USD")
    db.add_all([salary, dividend, sgd_cash, usd_cash])
    await db.flush()

    income_entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 5, 1),
        memo="mixed currency trailing income",
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
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=usd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("10.00"),
                currency="USD",
                fx_rate=Decimal("1.500000"),
            ),
            JournalLine(
                journal_entry_id=income_entry.id,
                account_id=dividend.id,
                direction=Direction.CREDIT,
                amount=Decimal("10.00"),
                currency="USD",
                fx_rate=Decimal("1.500000"),
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.500000"),
                rate_date=date(2026, 5, 1),
                source="test",
            ),
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.RSU,
                liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
                as_of_date=date(2026, 5, 1),
                value=Decimal("20.00"),
                currency="USD",
                source="USD-RSU",
            ),
        ]
    )
    await db.commit()

    response = await client.get("/reports/package/annualized-income-schedule?as_of_date=2026-05-20")

    assert response.status_code == 200
    data = response.json()
    assert data["income"] == {
        "annualized_salary": "100.00",
        "annualized_bonus": "0.00",
        "annualized_dividend": "15.00",
        "annualized_total": "115.00",
        "currency": "SGD",
        "calculation_basis": "posted_or_reconciled_income_journal_lines_trailing_12_months",
    }
    assert data["restricted_fair_value_total"] == "30.00"
    assert data["restricted_fair_value_total_currency"] == "SGD"
    assert data["restricted_holdings"][0]["fair_value"] == "20.00"
    assert data["restricted_holdings"][0]["currency"] == "USD"
