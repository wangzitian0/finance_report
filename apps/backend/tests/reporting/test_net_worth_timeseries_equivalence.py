"""Net-worth time series equals one balance sheet per point (#2583 S0).

The series computes ledger balances with a running sum and reads the manual
valuations and positions once. These tests compare every point with
``generate_balance_sheet`` on the same date, which is how the series was
computed before #2583. The fixture holds the inputs that change a point
value: an opening balance before the range, several currencies with gaps in
the FX history, a currency without a rate, a foreign liability, excluded
entries (draft and FX revaluation), portfolio positions priced from
snapshots, synced prices and overrides, and current and superseded manual
valuations in two currencies.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.extraction.orm.layer2 import AssetType, AtomicPosition
from src.extraction.orm.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.pricing.orm.market_data import FxRate, StockPrice
from src.pricing.orm.market_data_override import MarketDataOverride, PriceSource
from src.reporting import ReportError, generate_balance_sheet, get_net_worth_timeseries

RANGE_START = date(2024, 12, 30)
RANGE_END = date(2025, 2, 14)


async def _reference_point(
    db: AsyncSession, user_id: UUID, point_date: date, currency: str, *, include_restricted: bool = True
) -> dict[str, Decimal]:
    """Compute one point the way the series did before #2583: one balance sheet per point."""
    sheet = await generate_balance_sheet(
        db,
        user_id,
        as_of_date=point_date,
        currency=currency,
        include_trust_signals=False,
        include_restricted=include_restricted,
    )
    total_assets = Decimal(str(sheet["total_assets"]))
    total_liabilities = Decimal(str(sheet["total_liabilities"]))
    return {
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": total_assets - total_liabilities,
    }


async def _stored_fx_rate_ids(db: AsyncSession) -> set[UUID]:
    return set((await db.execute(select(FxRate.id))).scalars().all())


async def _drop_fx_rates_except(db: AsyncSession, kept_ids: set[UUID]) -> None:
    """Delete the FX rows that a lazy FX fallback wrote, so the next computation starts from the seeded rates.

    The lazy fallback stores derived rates, and a stored rate changes later lookups.
    Without this reset, the reference would read the rates that the series stored.
    """
    await db.execute(delete(FxRate).where(FxRate.id.not_in(kept_ids)))
    await db.commit()


def _values(point: dict[str, object]) -> dict[str, object]:
    return {key: point[key] for key in ("total_assets", "total_liabilities", "net_worth")}


async def _account(db: AsyncSession, user_id: UUID, name: str, account_type: AccountType, currency: str) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency=currency)
    db.add(account)
    await db.flush()
    return account


async def _entry(
    db: AsyncSession,
    user_id: UUID,
    entry_date: date,
    debit: Account,
    credit: Account,
    amount: str,
    currency: str,
    *,
    status: JournalEntryStatus = JournalEntryStatus.POSTED,
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
) -> None:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo="net worth equivalence fixture",
        source_type=source_type,
        status=status,
    )
    db.add(entry)
    await db.flush()
    # The ledger requires a booking rate on non-base lines; reporting ignores it.
    booking_rate = None if currency == "SGD" else Decimal("1.33")
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=Decimal(amount),
                currency=currency,
                fx_rate=booking_rate,
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=Decimal(amount),
                currency=currency,
                fx_rate=booking_rate,
            ),
        ]
    )
    await db.flush()


def _position(
    user_id: UUID,
    account: Account,
    symbol: str,
    *,
    quantity: str,
    cost_basis: str,
    currency: str,
    acquired: date,
    disposed: date | None = None,
) -> ManagedPosition:
    return ManagedPosition(
        user_id=user_id,
        account_id=account.id,
        asset_identifier=symbol,
        quantity=Decimal(quantity),
        cost_basis=Decimal(cost_basis),
        currency=currency,
        acquisition_date=acquired,
        disposal_date=disposed,
        status=PositionStatus.DISPOSED if disposed else PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )


def _snapshot(user_id: UUID, symbol: str, snapshot_date: date, quantity: str, market_value: str, currency: str):
    return AtomicPosition(
        user_id=user_id,
        snapshot_date=snapshot_date,
        asset_identifier=symbol,
        broker="Moomoo",
        quantity=Decimal(quantity),
        market_value=Decimal(market_value),
        currency=currency,
        asset_type=AssetType.STOCK,
        sector="Technology",
        geography="US",
        dedup_hash=f"position-{uuid4().hex}",
        source_documents={},
    )


def _valuation(
    user_id: UUID,
    component_type: ManualValuationComponentType,
    source: str,
    liquidity_class: ManualValuationLiquidityClass,
    value: str,
    currency: str,
    as_of_date: date,
) -> ManualValuationSnapshot:
    return ManualValuationSnapshot(
        user_id=user_id,
        component_type=component_type,
        liquidity_class=liquidity_class,
        value=Decimal(value),
        currency=currency,
        as_of_date=as_of_date,
        source=source,
    )


async def _seed_mixed_household(db: AsyncSession, user_id: UUID) -> None:
    cash = await _account(db, user_id, "Cash", AccountType.ASSET, "SGD")
    usd_bank = await _account(db, user_id, "USD Bank", AccountType.ASSET, "USD")
    jpy_wallet = await _account(db, user_id, "JPY Wallet", AccountType.ASSET, "JPY")
    brokerage = await _account(db, user_id, "Moomoo", AccountType.ASSET, "SGD")
    card = await _account(db, user_id, "Credit Card", AccountType.LIABILITY, "SGD")
    usd_loan = await _account(db, user_id, "USD Loan", AccountType.LIABILITY, "USD")
    equity = await _account(db, user_id, "Owner Equity", AccountType.EQUITY, "SGD")
    salary = await _account(db, user_id, "Salary", AccountType.INCOME, "SGD")
    dining = await _account(db, user_id, "Dining", AccountType.EXPENSE, "SGD")

    # Opening balances before the range start.
    await _entry(db, user_id, date(2024, 12, 15), cash, equity, "5000.00", "SGD")
    await _entry(db, user_id, date(2024, 12, 20), usd_bank, equity, "1000.00", "USD")
    # Daily movements inside the range.
    for month, days in ((1, (3, 9, 17, 28)), (2, (3, 9))):
        await _entry(db, user_id, date(2025, month, 12), cash, salary, "3000.00", "SGD")
        for day in days:
            await _entry(db, user_id, date(2025, month, day), dining, card, f"{day * 3 + month}.37", "SGD")
        await _entry(db, user_id, date(2025, month, 13), card, cash, "150.00", "SGD")
    await _entry(db, user_id, date(2025, 1, 6), brokerage, cash, "1000.00", "SGD")
    await _entry(db, user_id, date(2025, 1, 8), jpy_wallet, equity, "10000.00", "JPY")
    await _entry(db, user_id, date(2025, 1, 20), usd_bank, usd_loan, "500.33", "USD")
    await _entry(db, user_id, date(2025, 2, 5), usd_loan, usd_bank, "120.11", "USD")
    # Entries the balance sheet excludes.
    await _entry(db, user_id, date(2025, 1, 22), cash, equity, "999.00", "SGD", status=JournalEntryStatus.DRAFT)
    await _entry(
        db,
        user_id,
        date(2025, 1, 31),
        usd_bank,
        equity,
        "77.00",
        "USD",
        source_type=JournalEntrySourceType.FX_REVALUATION,
    )

    # USD/SGD history with gaps; the first direct rate is after the range start.
    # Early dates resolve through the stored SGD/USD inverse. JPY has no rate.
    db.add_all(
        [
            FxRate(
                base_currency="SGD",
                quote_currency="USD",
                rate=Decimal("0.7462"),
                rate_date=date(2024, 12, 1),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.3311"),
                rate_date=date(2025, 1, 2),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.3507"),
                rate_date=date(2025, 1, 11),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.3109"),
                rate_date=date(2025, 1, 24),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.3613"),
                rate_date=date(2025, 2, 7),
                source="test",
            ),
        ]
    )

    # Portfolio: a held SGD position priced from snapshots, a synced price and
    # an override; a USD position that is disposed inside the range.
    db.add_all(
        [
            _position(
                user_id,
                brokerage,
                "AAPL",
                quantity="10",
                cost_basis="1000.00",
                currency="SGD",
                acquired=date(2025, 1, 6),
            ),
            _snapshot(user_id, "AAPL", date(2025, 1, 6), "10", "1000.00", "SGD"),
            _snapshot(user_id, "AAPL", date(2025, 1, 16), "10", "1210.00", "SGD"),
            StockPrice(
                symbol="AAPL", price=Decimal("118.250000"), currency="SGD", price_date=date(2025, 1, 23), source="test"
            ),
            MarketDataOverride(
                user_id=user_id,
                asset_identifier="AAPL",
                price_date=date(2025, 2, 3),
                price=Decimal("131.00"),
                currency="SGD",
                source=PriceSource.MANUAL,
            ),
            _position(
                user_id,
                brokerage,
                "TSLA",
                quantity="3",
                cost_basis="500.00",
                currency="USD",
                acquired=date(2025, 1, 19),
                disposed=date(2025, 2, 8),
            ),
            _snapshot(user_id, "TSLA", date(2025, 1, 19), "3", "612.00", "USD"),
        ]
    )

    # Manual valuations: two property values, a mortgage, a USD RSU grant and a
    # corrected CPF balance whose first version is superseded.
    property_jan = _valuation(
        user_id,
        ManualValuationComponentType.PROPERTY_VALUE,
        "Home",
        ManualValuationLiquidityClass.ILLIQUID,
        "500000.00",
        "SGD",
        date(2025, 1, 9),
    )
    db.add_all(
        [
            property_jan,
            _valuation(
                user_id,
                ManualValuationComponentType.PROPERTY_VALUE,
                "Home",
                ManualValuationLiquidityClass.ILLIQUID,
                "520000.00",
                "SGD",
                date(2025, 2, 1),
            ),
            _valuation(
                user_id,
                ManualValuationComponentType.MORTGAGE_BALANCE,
                "Home loan",
                ManualValuationLiquidityClass.LIABILITY,
                "300000.00",
                "SGD",
                date(2025, 1, 9),
            ),
            _valuation(
                user_id,
                ManualValuationComponentType.RSU,
                "Employer RSU",
                ManualValuationLiquidityClass.RESTRICTED,
                "1000.55",
                "USD",
                date(2025, 1, 18),
            ),
        ]
    )
    await db.flush()
    corrected_cpf = _valuation(
        user_id,
        ManualValuationComponentType.CPF_BALANCE,
        "CPF",
        ManualValuationLiquidityClass.RESTRICTED,
        "12000.00",
        "SGD",
        date(2025, 1, 4),
    )
    db.add(corrected_cpf)
    await db.flush()
    superseded_cpf = _valuation(
        user_id,
        ManualValuationComponentType.CPF_BALANCE,
        "CPF",
        ManualValuationLiquidityClass.RESTRICTED,
        "10000.00",
        "SGD",
        date(2025, 1, 4),
    )
    superseded_cpf.superseded_by_id = corrected_cpf.id
    db.add(superseded_cpf)
    await db.commit()


async def test_AC_reporting_net_worth_timeseries_3_daily_points_equal_balance_sheets(db: AsyncSession, test_user):
    """AC-reporting.net-worth-timeseries.3: every daily point equals the balance sheet on its date."""
    await _seed_mixed_household(db, test_user.id)
    seeded_fx_rates = await _stored_fx_rate_ids(db)

    for currency in ("SGD", "USD"):
        await _drop_fx_rates_except(db, seeded_fx_rates)
        report = await get_net_worth_timeseries(
            db, test_user.id, start_date=RANGE_START, end_date=RANGE_END, granularity="daily", currency=currency
        )
        points = report["points"]
        assert [point["date"] for point in points] == [
            RANGE_START + timedelta(days=offset) for offset in range((RANGE_END - RANGE_START).days + 1)
        ]
        await _drop_fx_rates_except(db, seeded_fx_rates)
        mismatches = []
        for point in points:
            expected = await _reference_point(db, test_user.id, point["date"], currency)
            if _values(point) != expected:
                mismatches.append((point["date"], _values(point), expected))
        assert mismatches == [], f"{currency}: {len(mismatches)} of {len(points)} points differ: {mismatches[:3]}"

    # The fixture moves the inputs that a point depends on.
    sgd = await get_net_worth_timeseries(
        db, test_user.id, start_date=RANGE_START, end_date=RANGE_END, granularity="daily", currency="SGD"
    )
    by_date = {point["date"]: point for point in sgd["points"]}
    # Only the USD/SGD rate changes from 10 to 11 January.
    assert by_date[date(2025, 1, 11)]["net_worth"] != by_date[date(2025, 1, 10)]["net_worth"]
    # The property valuation starts on 9 January; the AAPL override applies on 3 February only.
    assert by_date[date(2025, 1, 9)]["total_assets"] - by_date[date(2025, 1, 8)]["total_assets"] == Decimal("500000.00")
    assert by_date[date(2025, 2, 3)]["total_assets"] != by_date[date(2025, 2, 4)]["total_assets"]


async def test_AC_reporting_net_worth_timeseries_3_liquid_scope_points_equal_balance_sheets(
    db: AsyncSession, test_user
):
    """AC-reporting.net-worth-timeseries.3: in the scope without restricted holdings, each daily point equals
    the balance sheet of that scope on its date (#2645).

    The fixture holds an illiquid property with its mortgage, a restricted RSU and a
    restricted CPF balance. The scope leaves all four out, so a liquid point differs
    from a full point by their net.
    """
    await _seed_mixed_household(db, test_user.id)
    seeded_fx_rates = await _stored_fx_rate_ids(db)

    for currency in ("SGD", "USD"):
        await _drop_fx_rates_except(db, seeded_fx_rates)
        liquid = await get_net_worth_timeseries(
            db,
            test_user.id,
            start_date=RANGE_START,
            end_date=RANGE_END,
            granularity="daily",
            currency=currency,
            include_restricted=False,
        )
        await _drop_fx_rates_except(db, seeded_fx_rates)
        mismatches = []
        for point in liquid["points"]:
            expected = await _reference_point(db, test_user.id, point["date"], currency, include_restricted=False)
            if _values(point) != expected:
                mismatches.append((point["date"], _values(point), expected))
        assert mismatches == [], f"{currency}: {len(mismatches)} points differ: {mismatches[:3]}"

    await _drop_fx_rates_except(db, seeded_fx_rates)
    full = await get_net_worth_timeseries(
        db, test_user.id, start_date=RANGE_END, end_date=RANGE_END, granularity="daily", currency="SGD"
    )
    liquid = await get_net_worth_timeseries(
        db,
        test_user.id,
        start_date=RANGE_END,
        end_date=RANGE_END,
        granularity="daily",
        currency="SGD",
        include_restricted=False,
    )
    # On the last day the property is 520,000.00 and the mortgage 300,000.00: the liquid
    # point has neither, and it also has no RSU or CPF value.
    assert full["points"][-1]["total_liabilities"] - liquid["points"][-1]["total_liabilities"] == Decimal("300000.00")
    assert full["points"][-1]["total_assets"] - liquid["points"][-1]["total_assets"] > Decimal("532000.00")


async def test_AC_reporting_net_worth_timeseries_3_monthly_points_equal_balance_sheets(db: AsyncSession, test_user):
    """AC-reporting.net-worth-timeseries.3: every monthly point equals the balance sheet on its month end."""
    await _seed_mixed_household(db, test_user.id)
    seeded_fx_rates = await _stored_fx_rate_ids(db)

    report = await get_net_worth_timeseries(
        db, test_user.id, start_date=date(2024, 10, 1), end_date=RANGE_END, granularity="monthly", currency="SGD"
    )
    await _drop_fx_rates_except(db, seeded_fx_rates)

    # October and November hold no data, so the series starts in December.
    # The last point is the end date, not the month end.
    assert [point["date"] for point in report["points"]] == [date(2024, 12, 31), date(2025, 1, 31), RANGE_END]
    for point in report["points"]:
        assert _values(point) == await _reference_point(db, test_user.id, point["date"], "SGD")
    for empty_month_end in (date(2024, 10, 31), date(2024, 11, 30)):
        assert await _reference_point(db, test_user.id, empty_month_end, "SGD") == {
            "total_assets": Decimal("0.00"),
            "total_liabilities": Decimal("0.00"),
            "net_worth": Decimal("0.00"),
        }


async def test_AC_reporting_net_worth_timeseries_3_point_on_today_equals_balance_sheet(db: AsyncSession, test_user):
    """AC-reporting.net-worth-timeseries.3: the point on today uses the same portfolio date as the balance sheet."""
    await _seed_mixed_household(db, test_user.id)
    today = date.today()
    db.add(_snapshot(test_user.id, "AAPL", today + timedelta(days=3), "10", "1555.00", "SGD"))
    await db.commit()
    seeded_fx_rates = await _stored_fx_rate_ids(db)

    report = await get_net_worth_timeseries(
        db, test_user.id, start_date=today - timedelta(days=4), end_date=today, granularity="daily", currency="SGD"
    )
    await _drop_fx_rates_except(db, seeded_fx_rates)

    assert report["points"][-1]["date"] == today
    for point in report["points"]:
        assert _values(point) == await _reference_point(db, test_user.id, point["date"], "SGD")


async def test_AC_reporting_net_worth_timeseries_3_income_fx_miss_does_not_fail_the_series(db: AsyncSession, test_user):
    """AC-reporting.net-worth-timeseries.3: the series does not compute net income. An FX miss on an expense
    line fails the balance sheet, but the series returns its points and skips the line as the balance sheet does."""
    cash = await _account(db, test_user.id, "Cash", AccountType.ASSET, "SGD")
    jpy_wallet = await _account(db, test_user.id, "JPY Wallet", AccountType.ASSET, "JPY")
    equity = await _account(db, test_user.id, "Owner Equity", AccountType.EQUITY, "SGD")
    jpy_equity = await _account(db, test_user.id, "JPY Equity", AccountType.EQUITY, "JPY")
    travel = await _account(db, test_user.id, "Travel", AccountType.EXPENSE, "JPY")
    await _entry(db, test_user.id, date(2025, 3, 1), cash, equity, "800.00", "SGD")
    await _entry(db, test_user.id, date(2025, 3, 1), jpy_wallet, jpy_equity, "50000.00", "JPY")
    await _entry(db, test_user.id, date(2025, 3, 10), travel, jpy_wallet, "12000.00", "JPY")
    await db.commit()

    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_balance_sheet(db, test_user.id, as_of_date=date(2025, 3, 10), currency="SGD")
    report = await get_net_worth_timeseries(
        db, test_user.id, start_date=date(2025, 3, 9), end_date=date(2025, 3, 11), granularity="daily", currency="SGD"
    )

    assert [point["net_worth"] for point in report["points"]] == [Decimal("800.00")] * 3
