from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

import src.reporting.extension.cash_flow as cf_mod
from src.ledger import AccountType
from src.reporting.extension.cash_flow import generate_cash_flow
from tests.reporting._report_fixtures import post_pair, seed_accounts, seed_fx_rates


async def test_multicurrency_cash_bridge_exposes_discrepancy_on_missing_activity(
    db: AsyncSession, test_user, monkeypatch
) -> None:
    p_start, p_end = date(2026, 1, 1), date(2026, 1, 31)
    usd_cash, usd_rev = await seed_accounts(
        db, test_user.id, ("USD Checking", AccountType.ASSET, "USD"), ("USD Consulting", AccountType.INCOME, "USD")
    )
    await seed_fx_rates(
        db,
        ("USD", "SGD", "1.30", p_start),
        ("USD", "SGD", "1.35", date(2026, 1, 15)),
        ("USD", "SGD", "1.40", p_end),
        commit=False,
    )
    await post_pair(
        db,
        test_user.id,
        date(2026, 1, 15),
        "Client USD",
        usd_cash,
        usd_rev,
        "100.00",
        currency="USD",
        fx_rate=Decimal("1.35"),
        commit=True,
    )

    rep = await generate_cash_flow(
        db, test_user.id, start_date=p_start, end_date=p_end, currency="SGD", cash_account_ids=frozenset([usd_cash.id])
    )
    assert rep["cash_bridge"] == {
        "classified_activity": Decimal("135.00"),
        "unclassified_cash": Decimal("0.00"),
        "opening_stock_adjustment": Decimal("0.00"),
        "fx_effect": Decimal("5.00"),
        "cash_delta": Decimal("140.00"),
        "discrepancy": Decimal("0.00"),
        "reconciles": True,
    }
    monkeypatch.setattr(cf_mod, "_line_total", lambda _items: Decimal("0.00"))
    bad = await generate_cash_flow(
        db, test_user.id, start_date=p_start, end_date=p_end, currency="SGD", cash_account_ids=frozenset([usd_cash.id])
    )
    assert (bad["cash_bridge"]["fx_effect"], bad["cash_bridge"]["discrepancy"], bad["cash_bridge"]["reconciles"]) == (
        Decimal("5.00"),
        Decimal("135.00"),
        False,
    )


async def test_multicurrency_cash_bridge_absorbs_per_line_fx_rounding_residue(db: AsyncSession, test_user) -> None:
    cny_cash, cny_exp = await seed_accounts(
        db,
        test_user.id,
        ("CNY Cash", AccountType.ASSET, "CNY", {"code": "1012"}),
        ("CNY Expense", AccountType.EXPENSE, "CNY", {"code": "5012"}),
    )
    await seed_fx_rates(
        db, ("CNY", "SGD", "0.188304", date(2024, 1, 15)), ("CNY", "SGD", "0.192490", date(2024, 2, 28)), commit=False
    )
    for idx in range(4):
        await post_pair(
            db,
            test_user.id,
            date(2024, 1, 15),
            f"CNY coffee {idx}",
            cny_exp,
            cny_cash,
            "10.00",
            currency="CNY",
            fx_rate=Decimal("0.188304"),
        )
    await db.commit()
    rep = await generate_cash_flow(
        db,
        test_user.id,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 28),
        currency="SGD",
        cash_account_ids=frozenset([cny_cash.id]),
    )
    assert rep["cash_bridge"] == {
        "classified_activity": Decimal("-7.52"),
        "unclassified_cash": Decimal("0.00"),
        "opening_stock_adjustment": Decimal("0.00"),
        "fx_effect": Decimal("-0.18"),
        "cash_delta": Decimal("-7.70"),
        "discrepancy": Decimal("0.00"),
        "reconciles": True,
    }
