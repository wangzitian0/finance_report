"""Legacy opening-entry callers retain a monetary journal return contract."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from src.ledger import JournalEntry, ValidationError, list_opening_positions, post_opening_balance_entry
from tests.factories import AccountFactory


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-100")])
async def test_legacy_opening_entry_rejects_nonpositive_without_writes(db, test_user, amount):
    """AC-ledger.opening-position.9: legacy rejection never creates stock or journals."""
    account = await AccountFactory.create_async(db, user_id=test_user.id, currency="SGD")
    with pytest.raises(ValidationError, match="positive"):
        await post_opening_balance_entry(
            db,
            test_user.id,
            entry_date=date(2026, 1, 1),
            balances={account.id: amount},
            currency="SGD",
            base_currency="SGD",
        )
    assert await list_opening_positions(db, user_id=test_user.id, as_of=date.max) == ()
    assert (
        await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id)) == 0
    )
