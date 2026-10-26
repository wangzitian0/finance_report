"""Tests for net worth time-series reporting."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.pricing.orm.market_data import FxRate
from src.reporting import ReportError, get_net_worth_timeseries
from src.reporting.extension.reporting_calc import MAX_NET_WORTH_MONTHLY_POINTS


async def _account(db, user_id, name: str, account_type: AccountType, currency: str = "SGD") -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency=currency)
    db.add(account)
    await db.flush()
    return account


async def _entry(db, user_id, entry_date: date, lines: list[tuple[Account, Direction, Decimal, str]]) -> None:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo="timeseries fixture",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    for account, direction, amount, currency in lines:
        db.add(
            JournalLine(
                journal_entry_id=entry.id,
                account_id=account.id,
                direction=direction,
                amount=amount,
                currency=currency,
                fx_rate=Decimal("1.00") if currency.upper() != "SGD" else None,
            )
        )
    await db.flush()


async def test_net_worth_timeseries_daily_points(db, test_user):
    """AC5.7.1: Daily net worth time-series returns assets, liabilities, and net worth."""
    user_id = test_user.id
    cash = await _account(db, user_id, "Cash", AccountType.ASSET)
    equity = await _account(db, user_id, "Owner Equity", AccountType.EQUITY)
    expense = await _account(db, user_id, "Dining", AccountType.EXPENSE)
    await _entry(
        db,
        user_id,
        date(2026, 1, 1),
        [(cash, Direction.DEBIT, Decimal("1000.00"), "SGD"), (equity, Direction.CREDIT, Decimal("1000.00"), "SGD")],
    )
    await _entry(
        db,
        user_id,
        date(2026, 1, 3),
        [(expense, Direction.DEBIT, Decimal("200.00"), "SGD"), (cash, Direction.CREDIT, Decimal("200.00"), "SGD")],
    )
    await db.commit()

    report = await get_net_worth_timeseries(
        db,
        user_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        granularity="daily",
        currency="SGD",
    )

    assert report["currency"] == "SGD"
    assert [point["date"] for point in report["points"]] == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
    assert [point["net_worth"] for point in report["points"]] == [
        Decimal("1000.00"),
        Decimal("1000.00"),
        Decimal("800.00"),
    ]


async def test_net_worth_timeseries_uses_historical_fx_per_point(db, test_user):
    """AC-reporting.net-worth-timeseries.2: AC5.7.3: Each point uses the historical FX rate at that point's date."""
    user_id = test_user.id
    usd_cash = await _account(db, user_id, "USD Cash", AccountType.ASSET, currency="USD")
    equity = await _account(db, user_id, "Owner Equity", AccountType.EQUITY, currency="USD")
    await _entry(
        db,
        user_id,
        date(2026, 1, 1),
        [
            (usd_cash, Direction.DEBIT, Decimal("100.00"), "USD"),
            (equity, Direction.CREDIT, Decimal("100.00"), "USD"),
        ],
    )
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate_date=date(2026, 1, 1),
                rate=Decimal("1.30"),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate_date=date(2026, 1, 2),
                rate=Decimal("1.40"),
                source="test",
            ),
        ]
    )
    await db.commit()

    report = await get_net_worth_timeseries(
        db,
        user_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        granularity="daily",
        currency="SGD",
    )

    assert [point["net_worth"] for point in report["points"]] == [Decimal("130.00"), Decimal("140.00")]


async def test_net_worth_timeseries_daily_cap(db):
    """AC5.7.1: Daily net worth time-series is capped to prevent expensive scans."""
    with pytest.raises(ReportError, match="Daily net worth time-series is capped"):
        await get_net_worth_timeseries(
            db,
            uuid4(),
            start_date=date(2025, 1, 1),
            end_date=date(2026, 2, 1),
            granularity="daily",
            currency="SGD",
        )


async def test_net_worth_timeseries_rejects_reversed_dates(db):
    """AC5.7.1: Invalid date windows are rejected before scanning balances."""
    with pytest.raises(ReportError, match="from date must be before to date"):
        await get_net_worth_timeseries(
            db,
            uuid4(),
            start_date=date(2026, 2, 1),
            end_date=date(2026, 1, 1),
            granularity="monthly",
            currency="SGD",
        )


async def test_net_worth_timeseries_rejects_unknown_granularity(db):
    """AC5.7.1: Only daily and monthly net worth buckets are supported."""
    with pytest.raises(ReportError, match="Unsupported net worth granularity"):
        await get_net_worth_timeseries(
            db,
            uuid4(),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            granularity="weekly",
            currency="SGD",
        )


async def test_net_worth_timeseries_monthly_uses_period_end_and_normalizes_currency(db, test_user):
    """AC5.7.1: Monthly net worth points use month-end dates and normalized currency."""
    user_id = test_user.id
    usd_cash = await _account(db, user_id, "USD Cash", AccountType.ASSET, currency="USD")
    usd_card = await _account(db, user_id, "USD Card", AccountType.LIABILITY, currency="USD")
    equity = await _account(db, user_id, "Owner Equity", AccountType.EQUITY, currency="USD")
    await _entry(
        db,
        user_id,
        date(2026, 1, 20),
        [(usd_cash, Direction.DEBIT, Decimal("1000.00"), "USD"), (equity, Direction.CREDIT, Decimal("1000.00"), "USD")],
    )
    await _entry(
        db,
        user_id,
        date(2026, 2, 1),
        [(equity, Direction.DEBIT, Decimal("250.00"), "USD"), (usd_card, Direction.CREDIT, Decimal("250.00"), "USD")],
    )
    await db.commit()

    report = await get_net_worth_timeseries(
        db,
        user_id,
        start_date=date(2026, 1, 15),
        end_date=date(2026, 2, 2),
        granularity="monthly",
        currency="usd",
    )

    assert report["currency"] == "USD"
    assert [point["date"] for point in report["points"]] == [date(2026, 1, 31), date(2026, 2, 2)]
    assert [point["currency"] for point in report["points"]] == ["USD", "USD"]
    assert [point["net_worth"] for point in report["points"]] == [Decimal("1000.00"), Decimal("750.00")]


async def test_AC_reporting_net_worth_timeseries_5_monthly_series_starts_at_first_month_with_value(db, test_user):
    """AC-reporting.net-worth-timeseries.5: a monthly series from 1970 starts at the first month with a
    non-zero total, keeps at most 366 months, and keeps the latest months."""
    user_id = test_user.id
    cash = await _account(db, user_id, "Cash", AccountType.ASSET)
    equity = await _account(db, user_id, "Owner Equity", AccountType.EQUITY)
    await _entry(
        db,
        user_id,
        date(2026, 3, 9),
        [(cash, Direction.DEBIT, Decimal("500.00"), "SGD"), (equity, Direction.CREDIT, Decimal("500.00"), "SGD")],
    )
    await db.commit()

    report = await get_net_worth_timeseries(
        db, user_id, start_date=date(1970, 1, 1), end_date=date(2026, 6, 10), granularity="monthly", currency="SGD"
    )

    assert [point["date"] for point in report["points"]] == [
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
        date(2026, 6, 10),
    ]
    assert {point["net_worth"] for point in report["points"]} == {Decimal("500.00")}

    long_history = await get_net_worth_timeseries(
        db, user_id, start_date=date(1970, 1, 1), end_date=date(2057, 6, 10), granularity="monthly", currency="SGD"
    )
    assert len(long_history["points"]) == MAX_NET_WORTH_MONTHLY_POINTS
    assert long_history["points"][0]["date"] == date(2027, 1, 31)
    assert long_history["points"][-1]["date"] == date(2057, 6, 10)


async def test_AC_reporting_net_worth_timeseries_5_empty_monthly_series_keeps_its_last_point(db, test_user):
    """AC-reporting.net-worth-timeseries.5: a monthly series without data keeps only its last point."""
    report = await get_net_worth_timeseries(
        db, test_user.id, start_date=date(1970, 1, 1), end_date=date(2026, 6, 10), granularity="monthly"
    )

    assert [point["date"] for point in report["points"]] == [date(2026, 6, 10)]
    assert report["points"][0]["net_worth"] == Decimal("0.00")


async def test_net_worth_timeseries_router(client):
    """AC-reporting.net-worth-timeseries.1: AC5.7.1: Router exposes the net worth time-series contract."""
    response = await client.get(
        "/reports/net-worth/timeseries",
        params={"from": "2026-01-01", "to": "2026-01-31", "granularity": "monthly", "currency": "SGD"},
    )

    assert response.status_code == 200
    assert response.json()["granularity"] == "monthly"
    assert response.json()["points"]


async def test_net_worth_timeseries_router_returns_bad_request_for_invalid_window(client):
    """AC5.7.1: Router maps net worth time-series validation errors to 400 responses."""
    response = await client.get(
        "/reports/net-worth/timeseries",
        params={"from": "2026-02-01", "to": "2026-01-01", "granularity": "monthly", "currency": "SGD"},
    )

    assert response.status_code == 400
