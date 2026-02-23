"""AC2.10 - AC2.1: Additional coverage tests for accounts router.
These tests cover edge cases and error paths for the accounts router
that are not covered in the main test files.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalLine


@pytest.mark.asyncio
class TestAccountsRouterCoverage:
    """Additional tests for accounts router coverage."""

    async def test_delete_account_with_transactions(self, client, db, test_user):
        """AC2.10.2: Delete account with transactions

        GIVEN an account with existing transactions
        WHEN attempting to delete it
        THEN it should return 400 error
        """
        # Create account
        account = Account(
            user_id=test_user.id,
            name="Cash",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        # Create a journal entry with a line referencing this account
        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date(2024, 1, 1),
            memo="Test transaction",
        )
        db.add(entry)
        await db.flush()

        line = JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="USD",
        )
        db.add(line)
        await db.commit()
        await db.refresh(account)

        # Attempt to delete account
        response = await client.delete(f"/accounts/{account.id}")
        assert response.status_code == 400
        assert "transactions" in response.json()["detail"].lower()
