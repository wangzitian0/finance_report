"""A memo that fills the memo column must not block later ledger operations (#2430)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntryStatus,
    post_journal_entry,
    void_journal_entry,
)
from tests.ledger._ledger_helpers import create_anchored_test_journal_entry as create_journal_entry


async def test_AC_ledger_void_memo_1_voiding_an_entry_with_a_full_memo_posts_a_cut_reversal_memo(
    db: AsyncSession, test_user
) -> None:
    """AC-ledger.void-memo.1: the reversal memo is 'VOID: ' plus the memo, cut to the column size."""
    user_id = test_user.id
    asset = Account(user_id=user_id, name="Memo Limit Cash", type=AccountType.ASSET, currency="SGD")
    equity = Account(user_id=user_id, name="Memo Limit Equity", type=AccountType.EQUITY, currency="SGD")
    db.add_all([asset, equity])
    await db.flush()

    memo = "M" * 500
    entry = await create_journal_entry(
        db,
        user_id,
        entry_date=date(2026, 1, 1),
        memo=memo,
        lines_data=[
            {"account_id": asset.id, "direction": Direction.DEBIT, "amount": Decimal("10.00"), "currency": "SGD"},
            {"account_id": equity.id, "direction": Direction.CREDIT, "amount": Decimal("10.00"), "currency": "SGD"},
        ],
        base_currency="SGD",
    )
    await post_journal_entry(db, entry.id, user_id, base_currency="SGD")
    entry_id = entry.id
    await db.commit()

    reversal = await void_journal_entry(db, entry_id, "Correction", user_id, base_currency="SGD")
    await db.commit()

    assert reversal.status == JournalEntryStatus.POSTED
    assert len(reversal.memo) == 500
    assert reversal.memo == ("VOID: " + memo)[:500]
