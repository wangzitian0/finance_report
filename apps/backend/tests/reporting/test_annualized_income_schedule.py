from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import AccountType, Direction
from src.platform import ValidationFailedError
from src.pricing import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    PrefetchedFxRates,
    PricingError,
    list_current_manual_valuation_facts,
)
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.reporting import generate_annualized_income_schedule
from src.reporting.extension.framework_policy import framework_policy_facts_for_user
from src.reporting.extension.reporting_calc import income_bucket
from tests.reporting._report_fixtures import post_lines, seed_accounts, seed_fx_rates


def test_AC11_11_1_income_bucket_maps_report_package_income_accounts() -> None:
    assert income_bucket("Salary Income") == "salary" and income_bucket("Monthly Payroll") == "salary"
    assert income_bucket("Annual Bonus") == "bonus" and income_bucket("Dividend Income") == "dividend"
    assert income_bucket("Consulting Income") is None


async def test_AC11_11_annualized_schedule_income_basis_and_mixed_currency(db: AsyncSession, test_user) -> None:
    salary, bonus, dividend, sgd_cash, usd_cash, usd_div = await seed_accounts(
        db,
        test_user.id,
        ("Salary Income", AccountType.INCOME),
        ("Annual Bonus", AccountType.INCOME),
        ("Dividend Income", AccountType.INCOME),
        ("Cash", AccountType.ASSET),
        ("USD Cash", AccountType.ASSET, "USD"),
        ("Dividend Income", AccountType.INCOME, "USD"),
    )
    await seed_fx_rates(db, ("USD", "SGD", "1.500000", date(2026, 5, 1)), commit=False)
    await post_lines(
        db,
        test_user.id,
        date(2026, 5, 1),
        "trailing",
        [
            (sgd_cash, Direction.DEBIT, "137400.00", "SGD"),
            (salary, Direction.CREDIT, "120000.00", "SGD"),
            (bonus, Direction.CREDIT, "15000.00", "SGD"),
            (dividend, Direction.CREDIT, "2400.00", "SGD"),
            (usd_cash, Direction.DEBIT, "10.00", "USD", Decimal("1.500000")),
            (usd_div, Direction.CREDIT, "10.00", "USD", Decimal("1.500000")),
        ],
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
                source="ACME ESOP",
                valuation_basis=None,
                notes="4-year vesting",
                reminder_date=date(2028, 4, 15),
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
    data = (
        await generate_annualized_income_schedule(db, test_user.id, as_of_date=date(2026, 5, 20), currency="SGD")
    ).model_dump(mode="json")
    assert (
        data["section_id"],
        data["as_of_date"],
        data["trailing_period_start"],
        data["trailing_period_end"],
        data["trailing_period_days"],
    ) == ("annualized_income_long_term", "2026-05-20", "2025-05-20", "2026-05-20", 365)
    assert data["income"] == {
        "annualized_salary": "120000.00",
        "annualized_bonus": "15000.00",
        "annualized_dividend": "2415.00",
        "annualized_total": "137415.00",
        "currency": "SGD",
        "calculation_basis": "posted_or_reconciled_income_journal_lines_trailing_12_months",
    }
    assert (data["restricted_fair_value_total"], data["restricted_fair_value_total_currency"]) == ("97530.00", "SGD")
    assert (
        data["net_worth_treatment"]["liquid_net_worth_default"],
        data["net_worth_treatment"]["restricted_wealth_basis"],
    ) == ("exclude_restricted_holdings", "manual_valuation_snapshot_fair_value")
    assert data["notes"] == [
        "Personal management report only; not tax advice.",
        "Restricted holdings are excluded from liquid net worth by default.",
    ]
    holdings = {h["ticker"]: h for h in data["restricted_holdings"]}
    assert (
        holdings["SHOP-RSU"]["valuation_basis"],
        holdings["ACME ESOP"]["valuation_basis"],
        holdings["USD-RSU"]["fair_value"],
        holdings["USD-RSU"]["currency"],
    ) == ("employer_grant_document", "unspecified", "20.00", "USD")


async def test_AC5_32_3_annualized_schedule_falls_back_to_account_currency_and_skips_restricted(
    db: AsyncSession, test_user
) -> None:
    assert ManualValuationComponentType.restricted_compensation_types() == (
        ManualValuationComponentType.ESOP,
        ManualValuationComponentType.RSU,
        ManualValuationComponentType.STOCK_OPTIONS,
    )
    usd_div, usd_cash = await seed_accounts(
        db, test_user.id, ("Dividend Income", AccountType.INCOME, "USD"), ("USD Cash", AccountType.ASSET, "USD")
    )
    await seed_fx_rates(db, ("USD", "SGD", "1.500000", date(2026, 5, 1)), commit=False)
    await post_lines(
        db,
        test_user.id,
        date(2026, 5, 1),
        "fallback",
        [
            (usd_cash, Direction.DEBIT, "20.00", "", Decimal("1.500000")),
            (usd_div, Direction.CREDIT, "20.00", "", Decimal("1.500000")),
        ],
    )
    db.add_all(
        [
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.RSU,
                liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
                as_of_date=date(2026, 1, 1),
                value=Decimal("10.00"),
                currency="USD",
                source="MULTI-CCY-RSU",
            ),
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.RSU,
                liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
                as_of_date=date(2026, 5, 1),
                value=Decimal("25.00"),
                currency="USD",
                source="MULTI-CCY-RSU",
            ),
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.RSU,
                liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
                as_of_date=date(2026, 5, 10),
                value=Decimal("40.00"),
                currency="SGD",
                source="MULTI-CCY-RSU",
            ),
        ]
    )
    await db.commit()
    sched = await generate_annualized_income_schedule(
        db, test_user.id, as_of_date=None, include_restricted_holdings=False, currency="SGD"
    )
    assert (
        sched.as_of_date,
        sched.income.annualized_dividend,
        sched.income.annualized_total,
        sched.restricted_holdings,
        sched.restricted_fair_value_total,
    ) == (date(2026, 5, 1), Decimal("30.00"), Decimal("30.00"), [], Decimal("0.00"))
    assert [
        (f.source, f.currency, f.value)
        for f in await list_current_manual_valuation_facts(db, test_user.id, as_of_date=date(2026, 5, 20))
    ] == [("MULTI-CCY-RSU", "SGD", Decimal("40.00")), ("MULTI-CCY-RSU", "USD", Decimal("25.00"))]
    pf = await framework_policy_facts_for_user(
        db,
        test_user.id,
        as_of_date=date(2026, 5, 20),
        report_period_start=date(2026, 1, 1),
        report_period_end=date(2026, 5, 20),
    )
    assert {(f.currency, f.amount) for f in pf if f.fact_id.startswith("manual_valuation_snapshot:")} == {
        ("USD", Decimal("25.00")),
        ("SGD", Decimal("40.00")),
    }
    with (
        patch.object(PrefetchedFxRates, "prefetch", new=AsyncMock(side_effect=PricingError("Missing FX rate"))),
        pytest.raises(ValidationFailedError) as exc,
    ):
        await generate_annualized_income_schedule(db, test_user.id, as_of_date=date(2026, 5, 20), currency="JPY")
    assert exc.value.status_code == 400
