"""AC5.10: Financial statement logic audit tests."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.reporting import generate_cash_flow


async def _add_entry(
    db: AsyncSession,
    *,
    user_id,
    entry_date: date,
    memo: str,
    lines: list[tuple[Account, Direction, Decimal]],
) -> None:
    entry = JournalEntry(user_id=user_id, entry_date=entry_date, memo=memo, status=JournalEntryStatus.POSTED)
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=account.id,
                direction=direction,
                amount=amount,
                currency="SGD",
            )
            for account, direction, amount in lines
        ]
    )
    await db.flush()


@pytest.fixture
async def cash_flow_accounts(db: AsyncSession, test_user):
    user_id = test_user.id
    cash = Account(user_id=user_id, name="Cash", type=AccountType.ASSET, currency="SGD")
    equity = Account(user_id=user_id, name="Owner Equity", type=AccountType.EQUITY, currency="SGD")
    rent = Account(user_id=user_id, name="Rent Expense", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([cash, equity, rent])
    await db.flush()
    return user_id, cash, equity, rent


async def test_AC5_10_1_cash_flow_uses_cumulative_cash_balances(db: AsyncSession, cash_flow_accounts):
    """AC-reporting.logic-audit.1: AC5.10.1: Cash-flow beginning/ending cash are cumulative balances."""
    user_id, cash, equity, rent = cash_flow_accounts
    await _add_entry(
        db,
        user_id=user_id,
        entry_date=date(2025, 12, 31),
        memo="Opening capital",
        lines=[(cash, Direction.DEBIT, Decimal("1000.00")), (equity, Direction.CREDIT, Decimal("1000.00"))],
    )
    await _add_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 15),
        memo="January rent",
        lines=[(rent, Direction.DEBIT, Decimal("100.00")), (cash, Direction.CREDIT, Decimal("100.00"))],
    )

    report = await generate_cash_flow(db, user_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))

    assert report["summary"]["beginning_cash"] == Decimal("1000.00")
    assert report["summary"]["ending_cash"] == Decimal("900.00")
    assert report["summary"]["net_cash_flow"] == Decimal("-100.00")


async def test_AC5_10_2_cash_flow_activity_totals_preserve_signs(db: AsyncSession, cash_flow_accounts):
    """AC-reporting.logic-audit.2: AC5.10.2: Cash-flow activities preserve outflow signs."""
    user_id, cash, equity, rent = cash_flow_accounts
    await _add_entry(
        db,
        user_id=user_id,
        entry_date=date(2025, 12, 31),
        memo="Opening capital",
        lines=[(cash, Direction.DEBIT, Decimal("1000.00")), (equity, Direction.CREDIT, Decimal("1000.00"))],
    )
    await _add_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 15),
        memo="January rent",
        lines=[(rent, Direction.DEBIT, Decimal("100.00")), (cash, Direction.CREDIT, Decimal("100.00"))],
    )

    report = await generate_cash_flow(db, user_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))

    assert report["summary"]["operating_activities"] == Decimal("-100.00")
    assert report["operating"][0]["amount"] == Decimal("-100.00")
