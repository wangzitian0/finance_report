"""Shared reporting-test builders (EPIC-025 AC25.4.1 / #1158).

Single source of truth for the standard chart of accounts that reporting tests
previously re-declared per module. Behavior-preserving: the produced accounts
are identical (name, type, currency, order) to the inlined originals.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType

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
