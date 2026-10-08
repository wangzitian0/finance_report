"""AC-reporting.net-worth-components.1: Tests for Net Worth metric alignment between Balance Sheet and Net Worth Allocation."""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine


async def test_balance_sheet_and_net_worth_allocation_are_coherent(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """Net assets from balance-sheet must equal net_worth from net-worth-allocation."""
    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    loan = Account(user_id=test_user.id, name="Bank Loan", type=AccountType.LIABILITY, currency="SGD")
    equity = Account(user_id=test_user.id, name="Opening Equity", type=AccountType.EQUITY, currency="SGD")
    db.add_all([cash, loan, equity])
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2025, 4, 15),
        memo="initial positions",
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
                amount=Decimal("50000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=loan.id,
                direction=Direction.CREDIT,
                amount=Decimal("10000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("40000.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    bs_resp = await client.get("/reports/balance-sheet?as_of_date=2025-04-15&currency=SGD&include_restricted=true")
    assert bs_resp.status_code == 200
    bs_data = bs_resp.json()
    net_assets = Decimal(str(bs_data["total_assets"])) - Decimal(str(bs_data["total_liabilities"]))

    alloc_resp = await client.get(
        "/reports/net-worth/allocation?as_of_date=2025-04-15&currency=SGD&include_restricted=true"
    )
    assert alloc_resp.status_code == 200
    alloc_data = alloc_resp.json()
    net_worth = Decimal(str(alloc_data["net_worth"]))

    assert net_assets == net_worth
    assert net_worth == Decimal("40000.00")
