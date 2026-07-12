from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.pricing.orm.market_data import FxRate
from src.reporting import (
    ReportError,
    _aggregate_net_income_sql,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)


async def test_reporting_extreme_fallbacks_failure_reporting(db: AsyncSession, test_user_id):
    """Cover lines 270-277 and 426-433 where all FX fallbacks fail."""
    acc_usd = Account(user_id=test_user_id, name="USD Cash", type=AccountType.ASSET, currency="USD")
    acc_inc = Account(user_id=test_user_id, name="USD Income", type=AccountType.INCOME, currency="USD")
    db.add_all([acc_usd, acc_inc])
    await db.commit()
    await db.refresh(acc_usd)
    await db.refresh(acc_inc)

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Salary",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=acc_usd.id,
                direction=Direction.DEBIT,
                amount=Decimal("100"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=acc_inc.id,
                direction=Direction.CREDIT,
                amount=Decimal("100"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
        ]
    )
    await db.commit()

    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")

    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_income_statement(
            db,
            test_user_id,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            currency="SGD",
        )


async def test_reporting_trend_keys_coverage(db: AsyncSession, test_user_id):
    """Cover lines 585-593 in get_account_trend for different periods."""
    acc = Account(user_id=test_user_id, name="Bank", type=AccountType.ASSET, currency="SGD")
    db.add(acc)
    await db.commit()
    await db.refresh(acc)

    await get_account_trend(db, test_user_id, account_id=acc.id, period="weekly", currency="SGD")
    await get_account_trend(db, test_user_id, account_id=acc.id, period="monthly", currency="SGD")
    await get_account_trend(db, test_user_id, account_id=acc.id, period="daily", currency="SGD")


async def test_reporting_monthly_avg_fallback_coverage(db: AsyncSession, test_user_id):
    """Cover lines 448-454 in generate_income_statement."""
    acc_usd = Account(user_id=test_user_id, name="USD Cash", type=AccountType.ASSET, currency="USD")
    acc_inc = Account(user_id=test_user_id, name="USD Income", type=AccountType.INCOME, currency="USD")
    db.add_all([acc_usd, acc_inc])

    rate = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.3"),
        rate_date=date(2025, 1, 31),
        source="test",
    )
    db.add(rate)
    await db.commit()
    await db.refresh(acc_usd)
    await db.refresh(acc_inc)

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Salary",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=acc_usd.id,
                direction=Direction.DEBIT,
                amount=Decimal("100"),
                currency="USD",
                fx_rate=Decimal("1.30"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=acc_inc.id,
                direction=Direction.CREDIT,
                amount=Decimal("100"),
                currency="USD",
                fx_rate=Decimal("1.30"),
            ),
        ]
    )
    await db.commit()

    await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )


async def test_reporting_cash_flow_account_lookup_coverage(db: AsyncSession, test_user_id):
    """Cover lines 751-753 in generate_cash_flow."""
    from src.reporting import generate_cash_flow

    acc = Account(user_id=test_user_id, name="Bank Cash", type=AccountType.ASSET, currency="SGD")
    offset = Account(user_id=test_user_id, name="Owner Equity", type=AccountType.EQUITY, currency="SGD")
    db.add_all([acc, offset])
    await db.commit()
    await db.refresh(acc)
    await db.refresh(offset)

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2024, 12, 1),
        memo="Old",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=acc.id,
                direction=Direction.DEBIT,
                amount=Decimal("100"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=offset.id,
                direction=Direction.CREDIT,
                amount=Decimal("100"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    await generate_cash_flow(db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31))


async def test_net_income_sql_raises_when_fx_rate_missing(db: AsyncSession, test_user_id):
    """AC5.6.7: Net income FX aggregation raises when source FX rates are unavailable."""
    account = Account(user_id=test_user_id, name="USD Income", type=AccountType.INCOME, currency="USD")
    asset = Account(user_id=test_user_id, name="USD Cash", type=AccountType.ASSET, currency="USD")
    db.add_all([account, asset])
    await db.flush()
    entry = JournalEntry(
        user_id=test_user_id, entry_date=date(2025, 2, 1), memo="income", status=JournalEntryStatus.POSTED
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=asset.id,
                direction=Direction.DEBIT,
                amount=Decimal("20"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=account.id,
                direction=Direction.CREDIT,
                amount=Decimal("20"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
        ]
    )
    await db.commit()

    with pytest.raises(ReportError, match="No FX rate available for USD/SGD"):
        await _aggregate_net_income_sql(db, test_user_id, "SGD", as_of_date=date(2025, 2, 1))


async def test_net_income_sql_uses_period_average_rate(db: AsyncSession, test_user_id):
    """_aggregate_net_income_sql uses period-average FX rate, not spot rate.

    With two FX rates in the period (1.30 and 1.50), the average is 1.40.
    Net income of 100 USD should be converted at 1.40, yielding 140 SGD.
    The old spot-rate behavior (rate on entry date 2025-01-15 = 1.30) would give 130 SGD.
    """
    income_acc = Account(user_id=test_user_id, name="USD Salary", type=AccountType.INCOME, currency="USD")
    asset_acc = Account(user_id=test_user_id, name="USD Cash", type=AccountType.ASSET, currency="USD")
    db.add_all([income_acc, asset_acc])
    await db.flush()

    # Two FX rates within the period — average is (1.30 + 1.50) / 2 = 1.40
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.30"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.50"),
                rate_date=date(2025, 1, 31),
                source="test",
            ),
        ]
    )

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2025, 1, 15),
        memo="Salary Jan",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=asset_acc.id,
                direction=Direction.DEBIT,
                amount=Decimal("100"),
                currency="USD",
                fx_rate=Decimal("1.40"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income_acc.id,
                direction=Direction.CREDIT,
                amount=Decimal("100"),
                currency="USD",
                fx_rate=Decimal("1.40"),
            ),
        ]
    )
    await db.commit()

    net_income = await _aggregate_net_income_sql(
        db,
        test_user_id,
        "SGD",
        as_of_date=date(2025, 1, 31),
        start_date=date(2025, 1, 1),
    )

    # Period-average rate: (1.30 + 1.50) / 2 = 1.40 → 100 USD × 1.40 = 140 SGD
    assert net_income == Decimal("140.00")


async def test_net_income_sql_detects_missing_fx_map_row() -> None:
    """AC5.6.7: Net income FX aggregation detects missing FX map row (data consistency).

    Simulates a data race where the aggregation query returns a currency that
    was not present when the currency list was first fetched.
    """
    fake_db = MagicMock()

    # First execute: distinct currency query → returns ["USD"]
    currency_result = MagicMock()
    currency_result.all.return_value = [("USD",)]

    # Second execute (aggregation): returns a row with "EUR" – NOT in fx_rate_map for "USD" only
    agg_result = MagicMock()
    agg_result.all.return_value = [
        SimpleNamespace(
            currency="EUR",
            type=AccountType.INCOME,
            direction=Direction.CREDIT,
            total=Decimal("10"),
        )
    ]

    # _aggregate_net_income_sql first loads internal-transfer FxConversion rows
    # (#1123 AC3 live wiring); none in this race scenario, so the adjustment is a no-op.
    transfer_result = MagicMock()
    transfer_result.scalars.return_value.all.return_value = []

    # Then it auto-discovers transfer legs from the raw ledger (#1123 AC2 live):
    # the asset-line query returns nothing here, so discovery is a no-op too.
    discovery_result = MagicMock()
    discovery_result.all.return_value = []

    fake_db.execute = AsyncMock(side_effect=[transfer_result, discovery_result, currency_result, agg_result])

    # Patch get_average_rate so we don't need to mock DB FX queries; USD gets a rate
    with patch("src.reporting.extension._core.get_average_rate", new_callable=AsyncMock) as mock_avg:
        mock_avg.return_value = Decimal("1.35")
        with pytest.raises(ReportError, match="data consistency error"):
            await _aggregate_net_income_sql(fake_db, uuid4(), "SGD", as_of_date=date(2025, 1, 31))


async def test_account_trend_raises_when_prefetched_rate_missing(db: AsyncSession, test_user_id):
    """AC-reporting.kpis.4: AC5.6.8: Account trend raises when prefetched non-base FX rate is missing."""
    account = Account(user_id=test_user_id, name="USD Trend", type=AccountType.ASSET, currency="USD")
    offset = Account(user_id=test_user_id, name="USD Equity", type=AccountType.EQUITY, currency="USD")
    db.add_all([account, offset])
    await db.flush()
    entry = JournalEntry(user_id=test_user_id, entry_date=date.today(), memo="trend", status=JournalEntryStatus.POSTED)
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=account.id,
                direction=Direction.DEBIT,
                amount=Decimal("5"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=offset.id,
                direction=Direction.CREDIT,
                amount=Decimal("5"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
        ]
    )
    await db.commit()

    with (
        patch(
            "src.reporting.extension.fx_gateway.PrefetchedFxRates.prefetch", new_callable=AsyncMock, return_value=None
        ),
        patch("src.reporting.extension.fx_gateway.PrefetchedFxRates.get_rate", return_value=None),
    ):
        with pytest.raises(ReportError, match="No FX rate available for USD/SGD"):
            await get_account_trend(db, test_user_id, account_id=account.id, period="daily", currency="SGD")


async def test_category_breakdown_raises_when_prefetched_rate_missing(db: AsyncSession, test_user_id):
    """AC-reporting.kpis.5: AC5.6.9: Category breakdown raises when prefetched non-base FX rate is missing."""
    expense = Account(user_id=test_user_id, name="USD Expense", type=AccountType.EXPENSE, currency="USD")
    bank = Account(user_id=test_user_id, name="USD Bank", type=AccountType.ASSET, currency="USD")
    db.add_all([expense, bank])
    await db.flush()
    entry = JournalEntry(
        user_id=test_user_id, entry_date=date.today(), memo="breakdown", status=JournalEntryStatus.POSTED
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("7"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("7"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
        ]
    )
    await db.commit()

    with (
        patch(
            "src.reporting.extension.fx_gateway.PrefetchedFxRates.prefetch", new_callable=AsyncMock, return_value=None
        ),
        patch("src.reporting.extension.fx_gateway.PrefetchedFxRates.get_rate", return_value=None),
    ):
        with pytest.raises(ReportError, match="No FX rate available for USD/SGD"):
            await get_category_breakdown(
                db,
                test_user_id,
                breakdown_type=AccountType.EXPENSE,
                period="monthly",
                currency="SGD",
            )


async def test_cash_flow_raises_when_start_date_rate_missing(db: AsyncSession, test_user_id):
    """AC-reporting.kpis.6: AC5.6.10: Cash flow raises when start-date non-base FX rate is missing."""
    bank = Account(user_id=test_user_id, name="USD Cash Before", type=AccountType.ASSET, currency="USD")
    offset = Account(user_id=test_user_id, name="USD Equity Before", type=AccountType.EQUITY, currency="USD")
    db.add_all([bank, offset])
    await db.flush()
    entry = JournalEntry(
        user_id=test_user_id, entry_date=date(2024, 12, 20), memo="before", status=JournalEntryStatus.POSTED
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.DEBIT,
                amount=Decimal("10"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=offset.id,
                direction=Direction.CREDIT,
                amount=Decimal("10"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
        ]
    )
    await db.commit()

    with (
        patch(
            "src.reporting.extension.fx_gateway.PrefetchedFxRates.prefetch", new_callable=AsyncMock, return_value=None
        ),
        patch("src.reporting.extension.fx_gateway.PrefetchedFxRates.get_rate", return_value=None),
    ):
        with pytest.raises(ReportError, match="on 2025-01-01"):
            await generate_cash_flow(
                db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
            )


async def test_cash_flow_raises_when_end_date_rate_missing(db: AsyncSession, test_user_id):
    """AC-reporting.kpis.7: AC5.6.10 AC5.6.11: Cash flow raises when end-date rate missing; PricingError propagated."""
    bank = Account(user_id=test_user_id, name="USD Cash During", type=AccountType.ASSET, currency="USD")
    offset = Account(user_id=test_user_id, name="USD Equity During", type=AccountType.EQUITY, currency="USD")
    db.add_all([bank, offset])
    await db.flush()
    entry = JournalEntry(
        user_id=test_user_id, entry_date=date(2025, 1, 20), memo="during", status=JournalEntryStatus.POSTED
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.DEBIT,
                amount=Decimal("12"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=offset.id,
                direction=Direction.CREDIT,
                amount=Decimal("12"),
                currency="USD",
                fx_rate=Decimal("1.00"),
            ),
        ]
    )
    await db.commit()

    with (
        patch(
            "src.reporting.extension.fx_gateway.PrefetchedFxRates.prefetch", new_callable=AsyncMock, return_value=None
        ),
        patch("src.reporting.extension.fx_gateway.PrefetchedFxRates.get_rate", side_effect=[Decimal("1"), None]),
    ):
        with pytest.raises(ReportError, match="on 2025-01-31"):
            await generate_cash_flow(
                db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
            )
