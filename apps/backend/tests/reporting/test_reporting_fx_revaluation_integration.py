from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import AccountType, Direction
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass, get_average_rate
from src.reporting import generate_balance_sheet, generate_income_statement
from src.reporting.extension._core import _aggregate_balances_sql
from tests.reporting._report_fixtures import post_lines, post_pair, seed_accounts, seed_fx_rates, seed_valuations


async def test_balance_sheet_fx_revaluation_is_calculated_and_excludes_reval_entries(
    db: AsyncSession, test_user
) -> None:
    rep_date = date(2025, 1, 31)
    usd_cash, equity, fx_acct = await seed_accounts(
        db,
        test_user.id,
        ("USD Cash", AccountType.ASSET, "USD"),
        ("Owner Equity", AccountType.EQUITY, "SGD"),
        ("Unrealized FX", AccountType.EQUITY, "SGD", {"code": "SYS-FX-REVAL"}),
    )
    await seed_fx_rates(db, ("USD", "SGD", "1.35", rep_date), commit=False)
    await post_lines(
        db,
        test_user.id,
        date(2025, 1, 15),
        "USD deposit",
        [
            (usd_cash, Direction.DEBIT, "1000.00", "USD", Decimal("1.30")),
            (equity, Direction.CREDIT, "1300.00", "SGD", Decimal("1")),
        ],
    )
    await post_lines(
        db,
        test_user.id,
        rep_date,
        "FX Reval",
        [
            (usd_cash, Direction.DEBIT, "50.00", "SGD", Decimal("1")),
            (fx_acct, Direction.CREDIT, "50.00", "SGD", Decimal("1")),
        ],
        source_type=JournalEntrySourceType.FX_REVALUATION,
    )
    await seed_valuations(
        db,
        test_user.id,
        (
            ManualValuationComponentType.OTHER_ASSET,
            ManualValuationLiquidityClass.LIQUID,
            "200.00",
            "SGD",
            rep_date,
            "Manual asset",
        ),
        commit=True,
    )

    balances = await _aggregate_balances_sql(
        db,
        test_user.id,
        (AccountType.ASSET, AccountType.EQUITY),
        target_currency="SGD",
        as_of_date=rep_date,
        base_currency="SGD",
    )
    assert (balances.get(usd_cash.id), balances.get(fx_acct.id, Decimal("0.00"))) == (
        Decimal("1350.00"),
        Decimal("0.00"),
    )
    rep = await generate_balance_sheet(db, test_user.id, as_of_date=rep_date, currency="SGD")
    assert (
        rep["total_assets"],
        rep["total_equity"],
        rep["unrealized_fx_gain_loss"],
        rep["net_worth_adjustment_gain_loss"],
        rep["equation_delta"],
        rep["is_balanced"],
    ) == (Decimal("1550.00"), Decimal("1300.00"), Decimal("50.00"), Decimal("200.00"), Decimal("0.00"), True)


async def test_income_statement_includes_average_rate_fallback_warning(db: AsyncSession, test_user) -> None:
    s_date, e_date = date(2025, 1, 1), date(2025, 1, 31)
    cash, income = await seed_accounts(
        db, test_user.id, ("USD Cash", AccountType.ASSET, "USD"), ("USD Salary", AccountType.INCOME, "USD")
    )
    await seed_fx_rates(db, ("USD", "SGD", "1.50", date(2024, 12, 31)), commit=False)
    await post_pair(
        db,
        test_user.id,
        date(2025, 1, 15),
        "USD salary",
        cash,
        income,
        "100.00",
        currency="USD",
        fx_rate=Decimal("1.50"),
        commit=True,
    )
    assert await get_average_rate(db, "USD", "SGD", s_date, e_date) == Decimal("1.50")
    rep = await generate_income_statement(db, test_user.id, start_date=s_date, end_date=e_date, currency="SGD")
    assert rep["net_income"] == Decimal("150.00") and rep["fx_warnings"] == [
        {
            "type": "average_rate_fallback",
            "base_currency": "USD",
            "quote_currency": "SGD",
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
        }
    ]
