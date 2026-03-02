from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    Direction,
    FxRate,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from src.services.reporting import (
    ReportError,
    _aggregate_net_income_sql,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)


@pytest.fixture
def test_user_id():
    return uuid4()


@pytest.mark.asyncio
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
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=acc_inc.id,
                direction=Direction.CREDIT,
                amount=Decimal("100"),
                currency="USD",
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


@pytest.mark.asyncio
async def test_reporting_trend_keys_coverage(db: AsyncSession, test_user_id):
    """Cover lines 585-593 in get_account_trend for different periods."""
    acc = Account(user_id=test_user_id, name="Bank", type=AccountType.ASSET, currency="SGD")
    db.add(acc)
    await db.commit()
    await db.refresh(acc)

    await get_account_trend(db, test_user_id, account_id=acc.id, period="weekly", currency="SGD")
    await get_account_trend(db, test_user_id, account_id=acc.id, period="monthly", currency="SGD")
    await get_account_trend(db, test_user_id, account_id=acc.id, period="daily", currency="SGD")


@pytest.mark.asyncio
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
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=acc_inc.id,
                direction=Direction.CREDIT,
                amount=Decimal("100"),
                currency="USD",
            ),
        ]
    )
    await db.commit()

    await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )


@pytest.mark.asyncio
async def test_reporting_cash_flow_account_lookup_coverage(db: AsyncSession, test_user_id):
    """Cover lines 751-753 in generate_cash_flow."""
    from src.services.reporting import generate_cash_flow

    acc = Account(user_id=test_user_id, name="Bank Cash", type=AccountType.ASSET, currency="SGD")
    db.add(acc)
    await db.commit()
    await db.refresh(acc)

    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date(2024, 12, 1),
        memo="Old",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=acc.id,
            direction=Direction.DEBIT,
            amount=Decimal("100"),
            currency="SGD",
        )
    )
    await db.commit()

    await generate_cash_flow(db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31))


@pytest.mark.asyncio
async def test_net_income_sql_raises_when_fx_rate_missing(db: AsyncSession, test_user_id):
    account = Account(user_id=test_user_id, name="USD Income", type=AccountType.INCOME, currency="USD")
    db.add(account)
    await db.flush()
    entry = JournalEntry(
        user_id=test_user_id, entry_date=date(2025, 2, 1), memo="income", status=JournalEntryStatus.POSTED
    )
    db.add(entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.CREDIT,
            amount=Decimal("20"),
            currency="USD",
        )
    )
    await db.commit()

    with pytest.raises(ReportError, match="No FX rate available for USD/SGD"):
        await _aggregate_net_income_sql(db, test_user_id, "SGD", as_of_date=date(2025, 2, 1))


@pytest.mark.asyncio
async def test_net_income_sql_detects_missing_fx_map_row() -> None:
    fake_db = MagicMock()

    currency_dates_result = MagicMock()
    currency_dates_result.all.return_value = [("USD", date(2025, 1, 1))]

    rate_result = MagicMock()
    rate_result.scalar_one_or_none.return_value = Decimal("1.35")

    agg_result = MagicMock()
    agg_result.all.return_value = [
        SimpleNamespace(
            currency="USD",
            entry_date=date(2025, 1, 2),
            type=AccountType.INCOME,
            direction=Direction.CREDIT,
            total=Decimal("10"),
        )
    ]

    fake_db.execute = AsyncMock(side_effect=[currency_dates_result, rate_result, agg_result])

    with pytest.raises(ReportError, match="data consistency error"):
        await _aggregate_net_income_sql(fake_db, uuid4(), "SGD", as_of_date=date(2025, 1, 31))


@pytest.mark.asyncio
async def test_account_trend_raises_when_prefetched_rate_missing(db: AsyncSession, test_user_id):
    account = Account(user_id=test_user_id, name="USD Trend", type=AccountType.ASSET, currency="USD")
    db.add(account)
    await db.flush()
    entry = JournalEntry(user_id=test_user_id, entry_date=date.today(), memo="trend", status=JournalEntryStatus.POSTED)
    db.add(entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.DEBIT,
            amount=Decimal("5"),
            currency="USD",
        )
    )
    await db.commit()

    with (
        patch("src.services.reporting.PrefetchedFxRates.prefetch", new_callable=AsyncMock, return_value=None),
        patch("src.services.reporting.PrefetchedFxRates.get_rate", return_value=None),
    ):
        with pytest.raises(ReportError, match="No FX rate available for USD/SGD"):
            await get_account_trend(db, test_user_id, account_id=account.id, period="daily", currency="SGD")


@pytest.mark.asyncio
async def test_category_breakdown_raises_when_prefetched_rate_missing(db: AsyncSession, test_user_id):
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
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("7"),
                currency="USD",
            ),
        ]
    )
    await db.commit()

    with (
        patch("src.services.reporting.PrefetchedFxRates.prefetch", new_callable=AsyncMock, return_value=None),
        patch("src.services.reporting.PrefetchedFxRates.get_rate", return_value=None),
    ):
        with pytest.raises(ReportError, match="No FX rate available for USD/SGD"):
            await get_category_breakdown(
                db,
                test_user_id,
                breakdown_type=AccountType.EXPENSE,
                period="monthly",
                currency="SGD",
            )


@pytest.mark.asyncio
async def test_cash_flow_raises_when_start_date_rate_missing(db: AsyncSession, test_user_id):
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
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=offset.id,
                direction=Direction.CREDIT,
                amount=Decimal("10"),
                currency="USD",
            ),
        ]
    )
    await db.commit()

    with (
        patch("src.services.reporting.PrefetchedFxRates.prefetch", new_callable=AsyncMock, return_value=None),
        patch("src.services.reporting.PrefetchedFxRates.get_rate", return_value=None),
    ):
        with pytest.raises(ReportError, match="on 2025-01-01"):
            await generate_cash_flow(
                db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
            )


@pytest.mark.asyncio
async def test_cash_flow_raises_when_end_date_rate_missing(db: AsyncSession, test_user_id):
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
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=offset.id,
                direction=Direction.CREDIT,
                amount=Decimal("12"),
                currency="USD",
            ),
        ]
    )
    await db.commit()

    with (
        patch("src.services.reporting.PrefetchedFxRates.prefetch", new_callable=AsyncMock, return_value=None),
        patch("src.services.reporting.PrefetchedFxRates.get_rate", side_effect=[Decimal("1"), None]),
    ):
        with pytest.raises(ReportError, match="on 2025-01-31"):
            await generate_cash_flow(
                db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
            )
