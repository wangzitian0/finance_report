from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import AccountType
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass, PrefetchedFxRates
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.pricing.orm.market_data import FxRate
from src.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)
from src.reporting.extension.reporting_calc import MAX_TREND_POINTS, _iter_periods
from tests.reporting._report_fixtures import build_standard_chart_of_accounts, make_pair_entry


@pytest.fixture
async def chart_of_accounts(db: AsyncSession, test_user_id):
    return await build_standard_chart_of_accounts(db, test_user_id)


async def test_balance_sheet_equation_and_provenance(db: AsyncSession, chart_of_accounts, test_user_id) -> None:
    cash, _liab, equity, income, expense = chart_of_accounts
    mv = ManualValuationSnapshot(
        user_id=test_user_id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=date(2026, 1, 31),
        value=Decimal("900000.00"),
        currency="SGD",
        source="manual appraisal",
    )
    db.add_all(
        [
            make_pair_entry(
                test_user_id,
                date(2026, 1, 1),
                "Owner",
                cash,
                equity,
                "1000.00",
                source_type=JournalEntrySourceType.MANUAL,
            ),
            make_pair_entry(
                test_user_id,
                date(2026, 1, 15),
                "Salary",
                cash,
                income,
                "5000.00",
                source_type=JournalEntrySourceType.AUTO_PARSED,
            ),
            make_pair_entry(
                test_user_id,
                date(2026, 1, 20),
                "Fee",
                expense,
                cash,
                "120.00",
                source_type=JournalEntrySourceType.SYSTEM,
            ),
            mv,
        ]
    )
    await db.commit()
    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2026, 1, 31), currency="SGD")
    inc = await generate_income_statement(
        db, test_user_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), currency="SGD"
    )
    assert (
        bs["total_assets"],
        bs["total_liabilities"],
        bs["total_equity"],
        bs["equation_delta"],
        bs["is_balanced"],
    ) == (Decimal("905880.00"), Decimal("0.00"), Decimal("1000.00"), Decimal("0.00"), True)
    assert (inc["total_income"], inc["total_expenses"], inc["net_income"]) == (
        Decimal("5000.00"),
        Decimal("120.00"),
        Decimal("4880.00"),
    )
    asset_by_name = {line["name"]: line for line in bs["assets"]}
    assert (
        asset_by_name["Cash"]["provenance"],
        asset_by_name["Valuation: manual appraisal (property value)"]["provenance"],
    ) == ("derived", "manual")
    assert (inc["income"][0]["provenance"], inc["expenses"][0]["provenance"]) == ("imported", "derived")


async def test_reporting_dashboard_fixture_exact_totals(db: AsyncSession, chart_of_accounts, test_user_id) -> None:
    cash, liability, equity, income, expense = chart_of_accounts
    db.add_all(
        [
            make_pair_entry(test_user_id, date(2025, 1, 1), "Owner", cash, equity, "1000.00"),
            make_pair_entry(test_user_id, date(2025, 1, 10), "Salary", cash, income, "500.00"),
            make_pair_entry(test_user_id, date(2025, 1, 15), "Rent", expense, cash, "200.00"),
            make_pair_entry(test_user_id, date(2025, 1, 20), "Card", cash, liability, "300.00"),
        ]
    )
    await db.commit()
    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
    inc = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    cf = await generate_cash_flow(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert (
        bs["total_assets"],
        bs["total_liabilities"],
        bs["total_equity"],
        bs["net_income"],
        bs["unrealized_fx_gain_loss"],
        bs["net_worth_adjustment_gain_loss"],
        bs["equation_delta"],
        bs["is_balanced"],
    ) == (
        Decimal("1600.00"),
        Decimal("300.00"),
        Decimal("1000.00"),
        Decimal("300.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        True,
    )
    assert bs["assets"] == [
        {
            "account_id": cash.id,
            "name": "Cash",
            "type": AccountType.ASSET,
            "parent_id": None,
            "amount": Decimal("1600.00"),
            "provenance": "manual",
            "source_currency": "SGD",
            "native_amount": Decimal("1600.00"),
            "allocation_asset_class": "cash",
            "allocation_liquidity_class": "liquid",
            "allocation_source_type": "ledger_account",
        }
    ]
    assert bs["liabilities"] == [
        {
            "account_id": liability.id,
            "name": "Credit Card",
            "type": AccountType.LIABILITY,
            "parent_id": None,
            "amount": Decimal("300.00"),
            "provenance": "manual",
            "source_currency": "SGD",
            "native_amount": Decimal("300.00"),
            "allocation_asset_class": "liability",
            "allocation_liquidity_class": "liability",
            "allocation_source_type": "ledger_account",
        }
    ]
    assert any(w.get("type") == "missing_opening_balance" for w in bs["opening_balance_warnings"])
    assert (
        inc["total_income"],
        inc["total_expenses"],
        inc["net_income"],
        inc["unrealized_fx_gain_loss"],
        inc["comprehensive_income"],
    ) == (Decimal("500.00"), Decimal("200.00"), Decimal("300.00"), Decimal("0.00"), Decimal("300.00"))
    assert inc["trends"] == [
        {
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 1, 31),
            "total_income": Decimal("500.00"),
            "total_expenses": Decimal("200.00"),
            "net_income": Decimal("300.00"),
        }
    ]
    assert cf["operating"] == [
        {
            "category": "Operating",
            "subcategory": "Salary",
            "amount": Decimal("500.00"),
            "description": "Inflow - Salary",
            "account_id": income.id,
        },
        {
            "category": "Operating",
            "subcategory": "Dining",
            "amount": Decimal("-200.00"),
            "description": "Outflow - Dining",
            "account_id": expense.id,
        },
    ]
    assert (
        cf["investing"] == cf["financing"] == []
        and cf["proof_state"] == "unproven"
        and cf["cash_bridge"]["unclassified_cash"] == Decimal("1300.00")
    )
    assert cf["summary"] == {
        "operating_activities": Decimal("300.00"),
        "investing_activities": Decimal("0.00"),
        "financing_activities": Decimal("0.00"),
        "net_cash_flow": Decimal("1600.00"),
        "beginning_cash": Decimal("0.00"),
        "ending_cash": Decimal("1600.00"),
    }


@pytest.mark.parametrize(
    ("fn_name", "kwargs", "match"),
    [
        (
            "generate_income_statement",
            {"start_date": date(2025, 2, 1), "end_date": date(2025, 1, 1), "currency": "SGD"},
            "start_date must be before end_date",
        ),
        ("get_account_trend", {"account_id": uuid4(), "period": "monthly", "currency": "SGD"}, "Account not found"),
        ("get_account_trend", {"use_cash": True, "period": "yearly", "currency": "SGD"}, "Unsupported period"),
        (
            "get_category_breakdown",
            {"breakdown_type": AccountType.ASSET, "period": "monthly", "currency": "SGD"},
            "Breakdown type must be income or expense",
        ),
        (
            "get_category_breakdown",
            {"breakdown_type": AccountType.INCOME, "period": "weekly", "currency": "SGD"},
            "Unsupported period",
        ),
        (
            "generate_cash_flow",
            {"start_date": date(2025, 2, 1), "end_date": date(2025, 1, 1), "currency": "SGD"},
            "start_date must be before end_date",
        ),
    ],
)
async def test_reporting_validation_errors(
    db: AsyncSession, chart_of_accounts, test_user_id, fn_name: str, kwargs: dict, match: str
) -> None:
    fn = globals()[fn_name]
    kw = dict(kwargs)
    if kw.pop("use_cash", False):
        kw["account_id"] = chart_of_accounts[0].id
    with pytest.raises(ReportError, match=match):
        await fn(db, test_user_id, **kw)


@pytest.mark.parametrize(
    ("fn_name", "entry_dt", "debit_idx", "credit_idx", "extra"),
    [
        (
            "generate_income_statement",
            date(2025, 1, 15),
            0,
            3,
            {"start_date": date(2025, 1, 1), "end_date": date(2025, 1, 31)},
        ),
        ("get_account_trend", date.today(), 0, 2, {"use_cash": True, "period": "monthly"}),
        ("get_category_breakdown", date.today(), 4, 0, {"breakdown_type": AccountType.EXPENSE, "period": "monthly"}),
        ("generate_cash_flow", date(2025, 1, 1), 0, 2, {"start_date": date(2025, 2, 1), "end_date": date(2025, 2, 28)}),
        (
            "generate_cash_flow",
            date(2025, 2, 10),
            0,
            2,
            {"start_date": date(2025, 2, 1), "end_date": date(2025, 2, 28)},
        ),
    ],
)
async def test_reporting_missing_fx_errors(
    db: AsyncSession,
    chart_of_accounts,
    test_user_id,
    fn_name: str,
    entry_dt: date,
    debit_idx: int,
    credit_idx: int,
    extra: dict,
) -> None:
    db.add(
        make_pair_entry(
            test_user_id,
            entry_dt,
            "FX",
            chart_of_accounts[debit_idx],
            chart_of_accounts[credit_idx],
            "10.00",
            currency="USD",
            fx_rate=Decimal("1.00"),
        )
    )
    await db.commit()
    kw = dict(extra)
    if kw.pop("use_cash", False):
        kw["account_id"] = chart_of_accounts[0].id
    with pytest.raises(ReportError, match="No FX rate available"):
        await globals()[fn_name](db, test_user_id, currency="SGD", **kw)


async def test_balance_sheet_fx_error_partial_skip(db: AsyncSession, chart_of_accounts, test_user_id) -> None:
    db.add(
        make_pair_entry(
            test_user_id,
            date.today(),
            "FX entry",
            chart_of_accounts[0],
            chart_of_accounts[2],
            "100.00",
            currency="USD",
            fx_rate=Decimal("1.00"),
        )
    )
    await db.commit()
    rep = await generate_balance_sheet(db, test_user_id, as_of_date=date.today(), currency="SGD")
    assert rep["total_assets"] == Decimal("0.00") and any(
        w["type"] == "missing_fx_rate_partial_skip" for w in rep["fx_warnings"]
    )


async def test_trends_breakdown_and_cash_flow_periods(
    db: AsyncSession, chart_of_accounts, test_user_id, monkeypatch
) -> None:
    cash, _l, equity, income, expense = chart_of_accounts
    assert (await get_account_trend(db, test_user_id, account_id=cash.id, period="daily", currency="SGD"))[
        "period"
    ] == "daily"
    assert (await get_account_trend(db, test_user_id, account_id=cash.id, period="weekly", currency="SGD"))[
        "period"
    ] == "weekly"
    assert (
        cast(
            date,
            (
                await get_category_breakdown(
                    db, test_user_id, breakdown_type=AccountType.INCOME, period="annual", currency="SGD"
                )
            )["period_start"],
        ).year
        == date.today().year
    )
    empty_cf = await generate_cash_flow(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert empty_cf["operating"] == empty_cf["investing"] == empty_cf["financing"] == [] and empty_cf["summary"][
        "net_cash_flow"
    ] == Decimal("0.00")

    class FixedDate(date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2025, 3, 15)

    monkeypatch.setattr("src.reporting.extension.net_worth.date", FixedDate)
    db.add_all(
        [
            make_pair_entry(test_user_id, FixedDate(2024, 12, 10), "Sal", cash, income, "100.00"),
            make_pair_entry(test_user_id, FixedDate(2025, 2, 5), "Din", expense, cash, "40.00"),
        ]
    )
    await db.commit()
    pts = {
        p["period_start"]: p["amount"]
        for p in (await get_account_trend(db, test_user_id, account_id=cash.id, period="monthly", currency="SGD"))[
            "points"
        ]
    }
    assert (pts[FixedDate(2024, 12, 1)], pts[FixedDate(2025, 2, 1)]) == (Decimal("100.00"), Decimal("-40.00"))
    q_rep = await get_category_breakdown(
        db, test_user_id, breakdown_type=AccountType.EXPENSE, period="quarterly", currency="SGD"
    )
    assert q_rep["items"][0]["total"] == Decimal("40.00")

    db.add(make_pair_entry(test_user_id, date(2025, 1, 15), "Before", cash, equity, "20.00"))
    await db.commit()
    assert "summary" in await generate_cash_flow(
        db, test_user_id, start_date=date(2025, 2, 1), end_date=date(2025, 2, 28), currency="SGD"
    )


async def test_income_statement_filters_and_fallback_rate(
    db: AsyncSession, chart_of_accounts, test_user_id, monkeypatch
) -> None:
    cash, _l, _e, income, expense = chart_of_accounts
    db.add_all(
        [
            make_pair_entry(
                test_user_id, date(2025, 1, 15), "Tagged", cash, income, "3000.00", tags={"business": True}
            ),
            make_pair_entry(test_user_id, date(2025, 1, 16), "Personal", cash, income, "2000.00"),
            make_pair_entry(test_user_id, date(2025, 1, 17), "Exp", expense, cash, "1500.00"),
        ]
    )
    await db.commit()
    assert (
        await generate_income_statement(
            db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD", tags=["business"]
        )
    )["total_income"] == Decimal("3000.00")
    assert (
        await generate_income_statement(
            db,
            test_user_id,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            currency="SGD",
            tags=["business"],
            account_type=AccountType.INCOME,
        )
    )["total_income"] == Decimal("3000.00")
    exp_only = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        account_type=AccountType.EXPENSE,
    )
    assert (exp_only["total_income"], exp_only["total_expenses"], exp_only["income"]) == (
        Decimal("0.00"),
        Decimal("1500.00"),
        [],
    )

    db.add(
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.35"), rate_date=date(2025, 1, 31), source="test"
        )
    )
    db.add(
        make_pair_entry(
            test_user_id, date(2025, 1, 15), "USD", cash, income, "100.00", currency="USD", fx_rate=Decimal("1.35")
        )
    )
    await db.commit()
    monkeypatch.setattr(PrefetchedFxRates, "get_rate", lambda self, *a, **kw: None)
    rep = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert rep["total_income"] == Decimal("5135.00")


def test_iter_periods_daily_limit() -> None:
    assert len(_iter_periods(date(2020, 1, 1), date(2020, 1, 1) + timedelta(days=999), "daily")) == MAX_TREND_POINTS + 1
