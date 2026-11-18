from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Money
from src.ledger import AccountType, Direction
from src.pricing import PricingError
from src.reporting import (
    ReportError,
    _aggregate_balances_sql,
    _aggregate_net_income_sql,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)
from tests.reporting._report_fixtures import post_pair, seed_accounts, seed_fx_rates


@pytest.fixture
async def fx_accounts(db: AsyncSession, test_user):
    return await seed_accounts(
        db,
        test_user.id,
        ("SGD Cash", AccountType.ASSET, "SGD"),
        ("USD Savings", AccountType.ASSET, "USD"),
        ("Capital", AccountType.EQUITY, "SGD"),
        ("Salary", AccountType.INCOME, "SGD"),
        ("USD Income", AccountType.INCOME, "USD"),
        ("USD Equity", AccountType.EQUITY, "USD"),
        commit=True,
    )


async def test_aggregate_balances_and_net_income_start_date_and_missing_fx(
    db: AsyncSession, fx_accounts, test_user
) -> None:
    sgd_cash, usd_savings, capital, salary, usd_income, _ = fx_accounts
    await post_pair(
        db,
        test_user.id,
        date(2025, 1, 15),
        "USD open",
        usd_savings,
        capital,
        "100.00",
        currency="USD",
        fx_rate=Decimal("1.00"),
        commit=True,
    )

    warnings: list[dict[str, str]] = []
    assert (
        await _aggregate_balances_sql(
            db, test_user.id, (AccountType.ASSET,), "SGD", date(2025, 1, 31), fx_warnings=warnings, base_currency="SGD"
        )
        == {}
    )
    assert warnings == [
        {
            "type": "missing_fx_rate_partial_skip",
            "base_currency": "USD",
            "quote_currency": "SGD",
            "rate_date": "2025-01-31",
        }
    ]

    await post_pair(db, test_user.id, date(2025, 1, 1), "Before", sgd_cash, capital, "500.00")
    await post_pair(db, test_user.id, date(2025, 2, 1), "During", sgd_cash, capital, "300.00", commit=True)
    assert (
        await _aggregate_balances_sql(
            db, test_user.id, (AccountType.ASSET,), "SGD", date(2025, 3, 1), base_currency="SGD"
        )
    )[sgd_cash.id] == Decimal("800.00")
    assert (
        await _aggregate_balances_sql(
            db,
            test_user.id,
            (AccountType.ASSET,),
            "SGD",
            date(2025, 3, 1),
            start_date=date(2025, 1, 15),
            base_currency="SGD",
        )
    )[sgd_cash.id] == Decimal("300.00")

    await post_pair(db, test_user.id, date(2025, 1, 1), "Old inc", sgd_cash, salary, "1000.00")
    await post_pair(db, test_user.id, date(2025, 2, 15), "New inc", sgd_cash, salary, "500.00", commit=True)
    assert (await _aggregate_net_income_sql(db, test_user.id, "SGD", date(2025, 3, 1)))[0] == Decimal("1500.00")
    assert (await _aggregate_net_income_sql(db, test_user.id, "SGD", date(2025, 3, 1), start_date=date(2025, 2, 1)))[
        0
    ] == Decimal("500.00")

    await post_pair(
        db,
        test_user.id,
        date(2025, 2, 1),
        "No FX inc",
        usd_savings,
        usd_income,
        "20.00",
        currency="USD",
        fx_rate=Decimal("1.00"),
        commit=True,
    )
    with pytest.raises(ReportError, match="No FX rate available for USD/SGD"):
        await _aggregate_net_income_sql(db, test_user.id, "SGD", as_of_date=date(2025, 2, 1))


async def test_net_income_sql_period_average_and_missing_map_row(db: AsyncSession, fx_accounts, test_user) -> None:
    _, usd_savings, _, _, usd_income, _ = fx_accounts
    await seed_fx_rates(db, ("USD", "SGD", "1.30", date(2025, 1, 1)), ("USD", "SGD", "1.50", date(2025, 1, 31)))
    await post_pair(
        db,
        test_user.id,
        date(2025, 1, 15),
        "Sal Jan",
        usd_savings,
        usd_income,
        "100",
        currency="USD",
        fx_rate=Decimal("1.40"),
        commit=True,
    )
    assert (
        await _aggregate_net_income_sql(
            db, test_user.id, "SGD", as_of_date=date(2025, 1, 31), start_date=date(2025, 1, 1)
        )
    )[0] == Decimal("140.00")

    fake_db = MagicMock()
    r1, r2 = MagicMock(), MagicMock()
    r1.scalars.return_value.all.return_value = []
    r2.all.return_value = []
    r3, r4 = MagicMock(), MagicMock()
    r3.all.return_value = [("USD",)]
    r4.all.return_value = [
        SimpleNamespace(currency="EUR", type=AccountType.INCOME, direction=Direction.CREDIT, total=Decimal("10"))
    ]
    fake_db.execute = AsyncMock(side_effect=[r1, r2, r3, r4])
    with (
        patch("src.reporting.extension._core.get_average_rate", new_callable=AsyncMock, return_value=Decimal("1.35")),
        patch("src.reporting.extension._core.get_exchange_rate", new_callable=AsyncMock, return_value=Decimal("1.35")),
    ):
        with pytest.raises(ReportError, match="data consistency error"):
            await _aggregate_net_income_sql(fake_db, uuid4(), "SGD", as_of_date=date(2025, 1, 31))


@pytest.mark.parametrize(
    ("target", "exc", "match"),
    [
        (
            "_aggregate_net_income_sql",
            ReportError("Missing FX rate for USD/SGD on 2025-01-15 - data consistency error"),
            "data consistency error",
        ),
        ("_aggregate_balances_sql", SQLAlchemyError("DB connection lost"), "DB connection lost"),
        (
            "_aggregate_net_income_sql",
            SQLAlchemyError("Timeout during net income calc"),
            "Timeout during net income calc",
        ),
    ],
)
async def test_balance_sheet_sql_and_consistency_errors(
    db: AsyncSession, fx_accounts, test_user, target: str, exc: Exception, match: str
) -> None:
    with patch(f"src.reporting.extension.balance_sheet.{target}", new_callable=AsyncMock, side_effect=exc):
        with pytest.raises(ReportError, match=match):
            await generate_balance_sheet(db, test_user.id, as_of_date=date(2025, 1, 31), currency="SGD")


@pytest.mark.parametrize("all_fail", [False, True])
async def test_income_statement_fx_average_to_spot_fallback(
    db: AsyncSession, fx_accounts, test_user, all_fail: bool
) -> None:
    sgd_cash, _, _, salary, _, _ = fx_accounts
    await seed_fx_rates(db, ("USD", "SGD", "1.35", date(2025, 1, 31)))
    await post_pair(
        db,
        test_user.id,
        date(2025, 1, 15),
        "USD Inc",
        sgd_cash,
        salary,
        "100.00",
        currency="USD",
        fx_rate=Decimal("1.35"),
        commit=True,
    )

    async def mock_convert(_db, money, target_ccy, _d, **kw):
        if all_fail or kw.get("average_start") is not None:
            raise PricingError("No rate")
        return Money(money.amount * Decimal("1.35"), target_ccy)

    with (
        patch("src.reporting.extension.income_statement.PrefetchedFxRates") as mock_pf,
        patch("src.reporting.extension.income_statement.convert_money", side_effect=mock_convert),
    ):
        mock_pf.return_value = MagicMock(prefetch=AsyncMock(), get_rate=lambda *_a, **_kw: None)
        if all_fail:
            with pytest.raises(ReportError, match="FX conversion failed"):
                await generate_income_statement(
                    db, test_user.id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
                )
        else:
            rep = await generate_income_statement(
                db, test_user.id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
            )
            assert rep["total_income"] == Decimal("135.00")


@pytest.mark.parametrize(
    ("mod", "fn_name", "kwargs"),
    [
        ("net_worth", "get_account_trend", {"use_cash": True, "period": "daily"}),
        ("net_worth", "get_category_breakdown", {"breakdown_type": AccountType.INCOME, "period": "monthly"}),
        ("cash_flow", "generate_cash_flow", {"start_date": date(2025, 1, 1), "end_date": date(2025, 1, 31)}),
    ],
)
async def test_same_currency_rate_none_fallback(
    db: AsyncSession, fx_accounts, test_user, mod: str, fn_name: str, kwargs: dict
) -> None:
    sgd_cash, _, capital, salary, _, _ = fx_accounts
    sgd_cash.name = "SGD Bank Cash"
    await post_pair(db, test_user.id, date(2024, 12, 15), "Before", sgd_cash, capital, "500.00")
    await post_pair(db, test_user.id, date(2025, 1, 15), "During", sgd_cash, salary, "300.00", commit=True)
    kw = dict(kwargs)
    if kw.pop("use_cash", False):
        kw["account_id"] = sgd_cash.id
    with patch(f"src.reporting.extension.{mod}.PrefetchedFxRates") as mock_pf:
        mock_pf.return_value = MagicMock(prefetch=AsyncMock(), get_rate=lambda *_a, **_kw: None)
        res = await globals()[fn_name](db, test_user.id, currency="SGD", **kw)
        assert res is not None
        mock_pf.assert_called()


@pytest.mark.parametrize(
    ("fn_name", "entry_dt", "d_idx", "c_idx", "kwargs", "match", "side_effect"),
    [
        (
            "get_account_trend",
            date.today(),
            1,
            5,
            {"use_usd": True, "period": "daily"},
            "No FX rate available for USD/SGD",
            None,
        ),
        (
            "get_category_breakdown",
            date.today(),
            4,
            1,
            {"breakdown_type": AccountType.INCOME, "period": "monthly"},
            "No FX rate available for USD/SGD",
            None,
        ),
        (
            "generate_cash_flow",
            date(2024, 12, 20),
            1,
            5,
            {"start_date": date(2025, 1, 1), "end_date": date(2025, 1, 31)},
            "on 2025-01-01",
            None,
        ),
        (
            "generate_cash_flow",
            date(2025, 1, 20),
            1,
            5,
            {"start_date": date(2025, 1, 1), "end_date": date(2025, 1, 31)},
            "on 2025-01-31",
            lambda _s, _t, rd: None if rd == date(2025, 1, 31) else Decimal("1"),
        ),
    ],
)
async def test_prefetched_rate_missing_raises(
    db: AsyncSession,
    fx_accounts,
    test_user,
    fn_name: str,
    entry_dt: date,
    d_idx: int,
    c_idx: int,
    kwargs: dict,
    match: str,
    side_effect,
) -> None:
    await post_pair(
        db,
        test_user.id,
        entry_dt,
        "Missing PF",
        fx_accounts[d_idx],
        fx_accounts[c_idx],
        "10",
        currency="USD",
        fx_rate=Decimal("1.00"),
        commit=True,
    )
    kw = dict(kwargs)
    if kw.pop("use_usd", False):
        kw["account_id"] = fx_accounts[1].id
    get_rate_kw = {"side_effect": side_effect} if side_effect else {"return_value": None}
    with (
        patch("src.pricing.PrefetchedFxRates.prefetch", new_callable=AsyncMock, return_value=None),
        patch("src.pricing.PrefetchedFxRates.get_rate", **get_rate_kw),
        pytest.raises(ReportError, match=match),
    ):
        await globals()[fn_name](db, test_user.id, currency="SGD", **kw)
