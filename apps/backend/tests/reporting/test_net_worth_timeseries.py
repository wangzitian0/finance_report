from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.ledger import AccountType, Direction
from src.reporting import ReportError, get_net_worth_timeseries
from src.reporting.extension.reporting_calc import MAX_NET_WORTH_MONTHLY_POINTS
from tests.reporting._report_fixtures import post_lines, seed_accounts, seed_fx_rates


async def test_net_worth_timeseries_daily_and_fx(db, test_user) -> None:
    cash, eq, exp, usd_cash, usd_eq = await seed_accounts(
        db,
        test_user.id,
        ("Cash", AccountType.ASSET),
        ("Owner Equity", AccountType.EQUITY),
        ("Dining", AccountType.EXPENSE),
        ("USD Cash", AccountType.ASSET, "USD"),
        ("USD Equity", AccountType.EQUITY, "USD"),
    )
    await post_lines(
        db,
        test_user.id,
        date(2026, 1, 1),
        "Init",
        [(cash, Direction.DEBIT, "1000.00", "SGD"), (eq, Direction.CREDIT, "1000.00", "SGD")],
    )
    await post_lines(
        db,
        test_user.id,
        date(2026, 1, 3),
        "Din",
        [(exp, Direction.DEBIT, "200.00", "SGD"), (cash, Direction.CREDIT, "200.00", "SGD")],
    )
    await post_lines(
        db,
        test_user.id,
        date(2026, 1, 1),
        "USD",
        [
            (usd_cash, Direction.DEBIT, "100.00", "USD", Decimal("1.00")),
            (usd_eq, Direction.CREDIT, "100.00", "USD", Decimal("1.00")),
        ],
    )
    await seed_fx_rates(db, ("USD", "SGD", "1.30", date(2026, 1, 1)), ("USD", "SGD", "1.40", date(2026, 1, 2)))
    rep = await get_net_worth_timeseries(
        db, test_user.id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 3), granularity="daily", currency="SGD"
    )
    assert rep["currency"] == "SGD" and [p["date"] for p in rep["points"]] == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]
    assert [p["net_worth"] for p in rep["points"]] == [Decimal("1130.00"), Decimal("1140.00"), Decimal("940.00")]


@pytest.mark.parametrize(
    ("start", "end", "gran", "match"),
    [
        (date(2025, 1, 1), date(2026, 2, 1), "daily", "Daily net worth time-series is capped"),
        (date(2026, 2, 1), date(2026, 1, 1), "monthly", "from date must be before to date"),
        (date(2026, 1, 1), date(2026, 1, 31), "weekly", "Unsupported net worth granularity"),
    ],
)
async def test_net_worth_timeseries_validation_errors(db, start: date, end: date, gran: str, match: str) -> None:
    with pytest.raises(ReportError, match=match):
        await get_net_worth_timeseries(db, uuid4(), start_date=start, end_date=end, granularity=gran, currency="SGD")


async def test_net_worth_timeseries_monthly_series_and_router(client, db, test_user) -> None:
    empty = await get_net_worth_timeseries(
        db, test_user.id, start_date=date(1970, 1, 1), end_date=date(2026, 6, 10), granularity="monthly", currency="SGD"
    )
    assert [(p["date"], p["net_worth"]) for p in empty["points"]] == [(date(2026, 6, 10), Decimal("0.00"))]

    usd_cash, usd_card, eq = await seed_accounts(
        db,
        test_user.id,
        ("USD Cash", AccountType.ASSET, "USD"),
        ("USD Card", AccountType.LIABILITY, "USD"),
        ("Owner Equity", AccountType.EQUITY, "USD"),
    )
    await post_lines(
        db,
        test_user.id,
        date(2026, 1, 20),
        "Init",
        [
            (usd_cash, Direction.DEBIT, "1000.00", "USD", Decimal("1.00")),
            (eq, Direction.CREDIT, "1000.00", "USD", Decimal("1.00")),
        ],
    )
    await post_lines(
        db,
        test_user.id,
        date(2026, 2, 1),
        "Card",
        [
            (eq, Direction.DEBIT, "250.00", "USD", Decimal("1.00")),
            (usd_card, Direction.CREDIT, "250.00", "USD", Decimal("1.00")),
        ],
        commit=True,
    )
    rep = await get_net_worth_timeseries(
        db, test_user.id, start_date=date(2026, 1, 15), end_date=date(2026, 2, 2), granularity="monthly", currency="usd"
    )
    assert rep["currency"] == "USD" and [(p["date"], p["currency"], p["net_worth"]) for p in rep["points"]] == [
        (date(2026, 1, 31), "USD", Decimal("1000.00")),
        (date(2026, 2, 2), "USD", Decimal("750.00")),
    ]

    hist = await get_net_worth_timeseries(
        db, test_user.id, start_date=date(1970, 1, 1), end_date=date(2057, 6, 10), granularity="monthly", currency="USD"
    )
    assert len(hist["points"]) == MAX_NET_WORTH_MONTHLY_POINTS and (
        hist["points"][0]["date"],
        hist["points"][-1]["date"],
    ) == (date(2027, 1, 31), date(2057, 6, 10))

    assert (
        await client.get(
            "/reports/net-worth/timeseries",
            params={"from": "2026-01-01", "to": "2026-01-31", "granularity": "monthly", "currency": "SGD"},
        )
    ).json()["granularity"] == "monthly"
    assert (
        await client.get(
            "/reports/net-worth/timeseries",
            params={"from": "2026-02-01", "to": "2026-01-01", "granularity": "monthly", "currency": "SGD"},
        )
    ).status_code == 400
