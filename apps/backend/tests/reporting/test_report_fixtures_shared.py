"""EPIC-025 AC25.4.1: shared reporting fixtures have a single source of truth."""

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.services.reporting import generate_balance_sheet
from tests.reporting._report_fixtures import (
    STANDARD_CHART_SPEC,
    build_standard_chart_of_accounts,
)


async def test_report_fixtures_shared(db: AsyncSession, test_user_id):
    """AC25.4.1: the shared chart-of-accounts builder and the shared `test_user_id`
    fixture (root conftest) replace the per-module duplicates without changing the
    accounts produced — five persisted SGD accounts in the canonical order, usable
    to generate a balanced balance sheet."""
    accounts = await build_standard_chart_of_accounts(db, test_user_id)

    # Single source of truth: builder output matches the declared spec exactly.
    assert [(a.name, a.type) for a in accounts] == list(STANDARD_CHART_SPEC)
    assert all(a.id is not None for a in accounts)  # persisted
    assert all(a.currency == "SGD" for a in accounts)
    assert [a.type for a in accounts] == [
        AccountType.ASSET,
        AccountType.LIABILITY,
        AccountType.EQUITY,
        AccountType.INCOME,
        AccountType.EXPENSE,
    ]

    # The shared fixtures still drive a balanced report (behavior preserved).
    cash, _liability, equity, *_rest = accounts
    entry = JournalEntry(
        user_id=test_user_id,
        entry_date=date.today(),
        memo="Owner contribution",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user_id, as_of_date=date.today(), currency="SGD")
    assert report["total_assets"] == Decimal("1000.00")
    assert report["total_equity"] == Decimal("1000.00")
    assert report["is_balanced"] is True
