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
from src.pricing.orm.market_data import FxRate

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


def make_entry(
    user_id: UUID,
    entry_date: date,
    memo: str,
    lines: list[tuple],
    *,
    status: JournalEntryStatus = JournalEntryStatus.POSTED,
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    tags: dict[str, Any] | None = None,
) -> JournalEntry:
    """Create a posted journal entry with arbitrary debit/credit lines."""
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        source_type=source_type,
        status=status,
    )
    parsed_lines = []
    for item in lines:
        acc, direction, amt = item[0], item[1], item[2]
        curr = item[3] if len(item) > 3 else "SGD"
        fx = item[4] if len(item) > 4 else None
        parsed_lines.append(
            JournalLine(
                account_id=acc.id,
                direction=direction,
                amount=Decimal(str(amt)),
                currency=curr,
                fx_rate=fx,
                tags=tags,
            )
        )
    entry.lines = parsed_lines
    return entry


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
    return make_entry(
        user_id,
        entry_date,
        memo,
        [
            (debit_account, Direction.DEBIT, amount, currency, fx_rate),
            (credit_account, Direction.CREDIT, amount, currency, fx_rate),
        ],
        source_type=source_type,
        tags=tags,
    )


async def seed_fx_rates(db: AsyncSession, *rates: tuple[str, str, Decimal | str, date]) -> list[FxRate]:
    """Persist FX rate records for tests."""
    models = [
        FxRate(base_currency=b, quote_currency=q, rate=Decimal(str(r)), rate_date=d, source="test")
        for b, q, r, d in rates
    ]
    db.add_all(models)
    await db.commit()
    return models
