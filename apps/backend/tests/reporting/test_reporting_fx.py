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
    _iter_periods,
    _quantize_money,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)
from src.reporting.extension import _core
from src.schemas.reporting import BalanceSheetResponse
from tests.reporting._report_fixtures import (
    make_entry,
    make_pair_entry,
    post_lines,
    post_pair,
    seed_accounts,
    seed_fx_rates,
)


@pytest.fixture
async def multi_currency_accounts(db: AsyncSession, test_user_id):
    return await seed_accounts(
        db,
        test_user_id,
        ("SGD Cash", AccountType.ASSET, "SGD"),
        ("USD Savings", AccountType.ASSET, "USD"),
        ("Capital", AccountType.EQUITY, "SGD"),
        ("Salary", AccountType.INCOME, "SGD"),
        ("Dining", AccountType.EXPENSE, "SGD"),
        commit=True,
    )


@pytest.fixture
async def fx_rates(db: AsyncSession):
    return await seed_fx_rates(db, ("USD", "SGD", "1.30", date(2025, 1, 1)), ("USD", "SGD", "1.40", date(2025, 1, 31)))


async def test_fx_unrealized_gain_and_comprehensive_income(
    db: AsyncSession, multi_currency_accounts, fx_rates, test_user_id
) -> None:
    sgd_cash, usd_savings, capital, salary, _ = multi_currency_accounts
    await post_lines(
        db,
        test_user_id,
        date(2025, 1, 1),
        "Init",
        [
            (usd_savings, Direction.DEBIT, "100.00", "USD", Decimal("1.30")),
            (capital, Direction.CREDIT, "130.00", "SGD", None),
        ],
    )
    await post_pair(db, test_user_id, date(2025, 1, 15), "Salary", sgd_cash, salary, "1000.00", commit=True)
    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
    assert (bs["total_assets"], bs["total_equity"], bs["unrealized_fx_gain_loss"], bs["is_balanced"]) == (
        Decimal("1140.00"),
        Decimal("130.00"),
        Decimal("10.00"),
        True,
    )
    inc = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert (inc["net_income"], inc["unrealized_fx_gain_loss"], inc["comprehensive_income"]) == (
        Decimal("1000.00"),
        Decimal("10.00"),
        Decimal("1010.00"),
    )


async def test_fx_liability_inversion_and_multi_currency_aggregation(
    db: AsyncSession, multi_currency_accounts, fx_rates, test_user_id
) -> None:
    sgd_cash, usd_savings, capital, *_ = multi_currency_accounts
    usd_debt, eur_savings = await seed_accounts(
        db,
        test_user_id,
        ("USD Debt", AccountType.LIABILITY, "USD"),
        ("EUR Savings", AccountType.ASSET, "EUR"),
        commit=True,
    )
    await seed_fx_rates(db, ("EUR", "SGD", "1.50", date(2025, 1, 1)))
    await post_lines(
        db,
        test_user_id,
        date(2025, 1, 1),
        "Open",
        [
            (usd_savings, Direction.DEBIT, "100.00", "USD", Decimal("1.30")),
            (eur_savings, Direction.DEBIT, "100.00", "EUR", Decimal("1.50")),
            (capital, Direction.CREDIT, "280.00", "SGD", None),
        ],
        commit=True,
    )
    bs_open = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 1), currency="SGD")
    assert (bs_open["total_assets"], bs_open["total_equity"], bs_open["unrealized_fx_gain_loss"]) == (
        Decimal("280.00"),
        Decimal("280.00"),
        Decimal("0.00"),
    )
    await post_lines(
        db,
        test_user_id,
        date(2025, 1, 1),
        "Borrow",
        [
            (sgd_cash, Direction.DEBIT, "130.00", "SGD", None),
            (usd_debt, Direction.CREDIT, "100.00", "USD", Decimal("1.30")),
        ],
        commit=True,
    )
    bs_end = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
    assert (bs_end["total_assets"], bs_end["total_liabilities"], bs_end["unrealized_fx_gain_loss"]) == (
        Decimal("420.00"),
        Decimal("140.00"),
        Decimal("0.00"),
    )


async def test_historical_vs_average_discrepancy_bridge_and_spot_fallbacks(
    db: AsyncSession, multi_currency_accounts, test_user_id
) -> None:
    _s, usd_savings, _c, salary, _d = multi_currency_accounts
    await seed_fx_rates(
        db,
        ("USD", "SGD", "1.30", date(2025, 1, 1)),
        ("USD", "SGD", "1.40", date(2025, 1, 15)),
        ("USD", "SGD", "1.50", date(2025, 1, 31)),
    )
    await post_pair(
        db,
        test_user_id,
        date(2025, 1, 15),
        "Salary",
        usd_savings,
        salary,
        "100.00",
        currency="USD",
        fx_rate=Decimal("1.40"),
        commit=True,
    )
    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
    assert (bs["total_assets"], bs["net_income"], bs["unrealized_fx_gain_loss"]) == (
        Decimal("150.00"),
        Decimal("140.00"),
        Decimal("10.00"),
    )
    assert (
        await generate_income_statement(
            db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
        )
    )["comprehensive_income"] == Decimal("150.00")


@pytest.mark.parametrize(("rate", "expected_total"), [("1.50", "150.00"), ("1.35", "135.00")])
async def test_reporting_fx_spot_fallback_for_income_statement_and_balance_sheet(
    db: AsyncSession, multi_currency_accounts, test_user_id, rate: str, expected_total: str
) -> None:
    sgd_cash, _, _, salary, _ = multi_currency_accounts
    await seed_fx_rates(db, ("USD", "SGD", rate, date(2025, 1, 31)))
    await post_pair(
        db,
        test_user_id,
        date(2025, 1, 10),
        "Spot fallback",
        sgd_cash,
        salary,
        "100.00",
        currency="USD",
        fx_rate=Decimal(rate),
        commit=True,
    )
    assert (
        await generate_income_statement(
            db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
        )
    )["total_income"] == Decimal(expected_total)
    assert (await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD"))[
        "net_income"
    ] == Decimal(expected_total)


@pytest.mark.parametrize(
    ("fn_name", "entry_dt", "d_idx", "c_idx", "kwargs"),
    [
        ("generate_balance_sheet", date(2025, 1, 10), 0, 3, {"as_of_date": date(2025, 1, 31)}),
        (
            "generate_income_statement",
            date(2025, 1, 15),
            1,
            3,
            {"start_date": date(2025, 1, 1), "end_date": date(2025, 1, 31)},
        ),
        (
            "generate_cash_flow",
            date(2024, 12, 1),
            1,
            2,
            {"start_date": date(2025, 1, 1), "end_date": date(2025, 1, 31)},
        ),
        (
            "generate_cash_flow",
            date(2025, 1, 15),
            1,
            2,
            {"start_date": date(2025, 1, 1), "end_date": date(2025, 1, 31)},
        ),
        ("get_category_breakdown", date.today(), 0, 3, {"breakdown_type": AccountType.INCOME, "period": "monthly"}),
        ("get_account_trend", date.today(), 1, 2, {"use_usd": True, "period": "daily"}),
    ],
)
async def test_reporting_fx_missing_rate_raises(
    db: AsyncSession,
    multi_currency_accounts,
    test_user_id,
    fn_name: str,
    entry_dt: date,
    d_idx: int,
    c_idx: int,
    kwargs: dict,
) -> None:
    await post_pair(
        db,
        test_user_id,
        entry_dt,
        "FX Err",
        multi_currency_accounts[d_idx],
        multi_currency_accounts[c_idx],
        "100",
        currency="USD",
        fx_rate=Decimal("1.00"),
        commit=True,
    )
    kw = dict(kwargs)
    if kw.pop("use_usd", False):
        kw["account_id"] = multi_currency_accounts[1].id
    with pytest.raises(ReportError):
        await globals()[fn_name](db, test_user_id, currency="SGD", **kw)


async def test_reporting_fx_additional_coverage_and_edge_cases(
    db: AsyncSession, multi_currency_accounts, test_user_id
) -> None:
    sgd_cash, _, _, salary, dining = multi_currency_accounts
    equipment, loan = await seed_accounts(
        db, test_user_id, ("Equipment", AccountType.ASSET), ("Bank Loan", AccountType.LIABILITY), commit=True
    )
    db.add(
        make_entry(
            test_user_id,
            date(2025, 1, 15),
            "Inv+Fin",
            [
                (sgd_cash, Direction.DEBIT, "5000", "SGD"),
                (loan, Direction.CREDIT, "5000", "SGD"),
                (equipment, Direction.DEBIT, "2000", "SGD"),
                (sgd_cash, Direction.CREDIT, "2000", "SGD"),
            ],
        )
    )
    sgd_cash.name = "Bank account"
    await db.commit()
    cf = await generate_cash_flow(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )
    assert (
        cf["summary"]["financing_activities"],
        cf["summary"]["investing_activities"],
        cf["summary"]["net_cash_flow"],
        cf["cash_bridge"]["unclassified_cash"],
        cf["proof_state"],
    ) == (Decimal("0.00"), Decimal("0.00"), Decimal("3000.00"), Decimal("3000.00"), "unproven")

    db.add(
        make_entry(
            test_user_id,
            date(2025, 1, 15),
            "Sal+Food",
            [
                (sgd_cash, Direction.DEBIT, "1000.00", "SGD"),
                (salary, Direction.CREDIT, "1200.00", "SGD"),
                (dining, Direction.DEBIT, "200.00", "SGD"),
            ],
            tags={"work": "true"},
        )
    )
    db.add(make_pair_entry(test_user_id, date.today(), "Today", sgd_cash, salary, "100.00"))
    await db.commit()

    assert (
        await generate_income_statement(
            db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD", tags=["work"]
        )
    )["total_income"] == Decimal("1200.00")
    assert (
        await generate_income_statement(
            db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD", tags=["holiday"]
        )
    )["total_income"] == Decimal("0.00")
    assert (
        await generate_income_statement(
            db,
            test_user_id,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            account_type=AccountType.INCOME,
            currency="SGD",
        )
    )["expenses"] == []
    assert (await get_account_trend(db, test_user_id, account_id=sgd_cash.id, period="daily", currency="SGD"))["points"]
    assert (await get_account_trend(db, test_user_id, account_id=sgd_cash.id, period="weekly", currency="SGD"))[
        "points"
    ]
    assert any(
        i["category_name"] == "Salary"
        for i in (
            await get_category_breakdown(
                db, test_user_id, breakdown_type=AccountType.INCOME, period="monthly", currency="SGD"
            )
        )["items"]
    )
    await get_category_breakdown(
        db, test_user_id, breakdown_type=AccountType.INCOME, period="quarterly", currency="SGD"
    )
    await get_category_breakdown(db, test_user_id, breakdown_type=AccountType.INCOME, period="annual", currency="SGD")
    assert (
        _quantize_money(100) == Decimal("100.00")
        and len(_iter_periods(date(2025, 1, 1), date(2030, 1, 1), "daily")) == 367
    )


async def test_reports_lazy_resolve_missing_hkd_sgd_from_bridge_rates(db: AsyncSession, test_user_id) -> None:
    hkd_cash, hkd_salary = await seed_accounts(
        db, test_user_id, ("HKD Cash", AccountType.ASSET, "HKD"), ("HKD Salary", AccountType.INCOME, "HKD")
    )
    await seed_fx_rates(
        db, ("USD", "HKD", "7.800000", date(2025, 6, 30)), ("USD", "SGD", "1.350000", date(2025, 6, 30))
    )
    await post_pair(
        db,
        test_user_id,
        date(2025, 6, 30),
        "HKD salary",
        hkd_cash,
        hkd_salary,
        "780.00",
        currency="HKD",
        fx_rate=Decimal("0.173077"),
        commit=True,
    )
    inc = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 6, 1), end_date=date(2025, 6, 30), currency="SGD"
    )
    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 6, 30), currency="SGD")
    assert (inc["total_income"], bs["total_assets"], bs["net_income"], bs["is_balanced"]) == (
        Decimal("135.00"),
        Decimal("135.00"),
        Decimal("135.00"),
        True,
    )
    derived = (
        await db.execute(
            select(FxRate).where(
                FxRate.base_currency == "HKD", FxRate.quote_currency == "SGD", FxRate.rate_date == date(2025, 6, 30)
            )
        )
    ).scalar_one()
    assert (derived.rate, derived.source) == (Decimal("0.173077"), "derived:bridge:USD")


async def test_AC_reporting_2728_1_balance_sheet_exposes_native_amount_when_fx_rate_missing(
    db: AsyncSession, test_user_id
) -> None:
    cmb, equity = await seed_accounts(
        db,
        test_user_id,
        ("China Merchants Bank ••7788", AccountType.ASSET, "CNY"),
        ("Opening Balances", AccountType.EQUITY, "CNY"),
    )
    await post_pair(
        db,
        test_user_id,
        date(2026, 1, 15),
        "CNY opening",
        cmb,
        equity,
        "47939.43",
        currency="CNY",
        fx_rate=Decimal("1.00"),
        commit=True,
    )
    rep = await generate_balance_sheet(db, test_user_id, as_of_date=date(2026, 1, 31), currency="SGD")
    ser = BalanceSheetResponse.model_validate(rep).model_dump(mode="json")
    line = next(item for item in ser["assets"] if item["account_id"] == str(cmb.id))
    assert (line["amount"], line["source_currency"], line["native_amount"]) == ("0.00", "CNY", "47939.43")
    assert any(
        w.get("type") == "missing_fx_rate_partial_skip" and w.get("base_currency") == "CNY" for w in ser["fx_warnings"]
    )
    assert not hasattr(_core, "_REPORT_STATUSES")
