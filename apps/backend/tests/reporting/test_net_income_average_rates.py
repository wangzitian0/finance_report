from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import AccountType
from src.reporting import ReportError, _aggregate_net_income_sql
from tests.reporting._report_fixtures import post_pair, seed_accounts, seed_fx_rates


async def test_aggregate_net_income_average_rate_all_time_and_same_currency(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    checking, salary, food, sgd_cash, sgd_rev, sgd_rent = await seed_accounts(
        db,
        uid,
        ("Checking", AccountType.ASSET, "SGD"),
        ("Salary", AccountType.INCOME, "USD"),
        ("Food", AccountType.EXPENSE, "USD"),
        ("Cash", AccountType.ASSET, "SGD"),
        ("Revenue", AccountType.INCOME, "SGD"),
        ("Rent", AccountType.EXPENSE, "SGD"),
    )
    await seed_fx_rates(
        db,
        ("USD", "SGD", "1.20", date(2025, 1, 1)),
        ("USD", "SGD", "1.30", date(2025, 1, 15)),
        ("USD", "SGD", "1.40", date(2025, 1, 31)),
        commit=False,
    )
    await post_pair(
        db, uid, date(2025, 1, 1), "Early", checking, salary, "1000", currency="USD", fx_rate=Decimal("1.20")
    )
    await post_pair(
        db, uid, date(2025, 1, 31), "Late", food, checking, "200", currency="USD", fx_rate=Decimal("1.40"), commit=True
    )
    net_avg, _ = await _aggregate_net_income_sql(db, uid, "SGD", date(2025, 1, 31), start_date=date(2025, 1, 1))
    assert abs(net_avg - Decimal("1040.00")) < Decimal("1.00")
    assert (await _aggregate_net_income_sql(db, uid, "SGD", date(2025, 1, 15)))[0] > Decimal("0")

    await post_pair(db, uid, date(2025, 3, 1), "Rev", sgd_cash, sgd_rev, "3000", currency="SGD")
    await post_pair(db, uid, date(2025, 3, 1), "Rent", sgd_rent, sgd_cash, "1200", currency="SGD", commit=True)
    assert (await _aggregate_net_income_sql(db, uid, "SGD", date(2025, 3, 31), start_date=date(2025, 3, 1)))[
        0
    ] == Decimal("1800.00")


async def test_aggregate_net_income_raises_on_missing_fx_rate(db: AsyncSession, test_user) -> None:
    cash, sales = await seed_accounts(
        db, test_user.id, ("Cash", AccountType.ASSET, "EUR"), ("Sales", AccountType.INCOME, "EUR")
    )
    await post_pair(
        db,
        test_user.id,
        date(2025, 6, 1),
        "Sales",
        cash,
        sales,
        "100",
        currency="EUR",
        fx_rate=Decimal("1.00"),
        commit=True,
    )
    with pytest.raises(ReportError, match="No FX rate available"):
        await _aggregate_net_income_sql(db, test_user.id, "SGD", date(2025, 6, 30))
