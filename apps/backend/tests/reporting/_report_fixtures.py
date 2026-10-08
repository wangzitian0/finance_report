"""Shared reporting-test builders (EPIC-025 AC25.4.1 / #1158).

Single source of truth for the standard chart of accounts that reporting tests
previously re-declared per module. Behavior-preserving: the produced accounts
are identical (name, type, currency, order) to the inlined originals.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine

# The standard 5-account SGD chart used across reporting tests, in a stable
# order: (Cash ASSET, Credit Card LIABILITY, Owner Equity EQUITY, Salary INCOME,
# Dining EXPENSE).
STANDARD_CHART_SPEC: tuple[tuple[str, AccountType], ...] = (
    ("Cash", AccountType.ASSET),
    ("Credit Card", AccountType.LIABILITY),
    ("Owner Equity", AccountType.EQUITY),
    ("Salary", AccountType.INCOME),
    ("Dining", AccountType.EXPENSE),
)


async def build_standard_chart_of_accounts(db: AsyncSession, user_id: UUID, *, currency: str = "SGD") -> list[Account]:
    """Create and persist the standard chart of accounts, returning them in spec order."""
    accounts = [
        Account(user_id=user_id, name=name, type=acct_type, currency=currency)
        for name, acct_type in STANDARD_CHART_SPEC
    ]
    db.add_all(accounts)
    await db.commit()
    for account in accounts:
        await db.refresh(account)
    return accounts


def make_pair_entry(
    user_id: UUID,
    entry_date: date,
    memo: str,
    debit_account: Account,
    credit_account: Account,
    amount: Decimal | str,
    *,
    currency: str = "SGD",
    fx_rate: Decimal | None = None,
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    tags: dict[str, Any] | None = None,
) -> JournalEntry:
    """Create a balanced two-line posted journal entry."""
    amt = Decimal(str(amount))
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        source_type=source_type,
        status=JournalEntryStatus.POSTED,
    )
    entry.lines = [
        JournalLine(
            account_id=debit_account.id,
            direction=Direction.DEBIT,
            amount=amt,
            currency=currency,
            fx_rate=fx_rate,
            tags=tags,
        ),
        JournalLine(
            account_id=credit_account.id,
            direction=Direction.CREDIT,
            amount=amt,
            currency=currency,
            fx_rate=fx_rate,
            tags=tags,
        ),
    ]
    return entry
