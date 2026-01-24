from datetime import date
from decimal import Decimal
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
    generate_balance_sheet,
    generate_income_statement,
    get_account_trend,
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
