"""AC2.7: Journal router error path coverage.

These tests cover API error handling from EPIC-002:
 AC2.7.1: GET entry returns 404 for non-existent ID
 AC2.7.2: POST entry returns 400 for non-existent ID
 AC2.7.3: VOID entry returns 400 for non-existent ID
 AC2.7.4: Validation error (422) for malformed request
 AC2.7.5: DELETE draft entry success (204)
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine


@pytest.mark.asyncio
class TestJournalRouterAdditionalCoverage:
    """Test additional journal router paths for coverage."""

    async def test_get_entry_not_found(self, client, test_user):
        """
        GIVEN a non-existent journal entry ID
        WHEN getting entry details
        THEN it should return 404
        """
        fake_id = uuid4()
        response = await client.get(f"/journal-entries/{fake_id}")
        assert response.status_code == 404

    async def test_post_entry_not_found(self, client, test_user):
        """
        GIVEN a non-existent journal entry ID
        WHEN posting entry
        THEN it should return 400
        """
        fake_id = uuid4()
        response = await client.post(f"/journal-entries/{fake_id}/post")
        assert response.status_code == 400

    async def test_void_entry_not_found(self, client, test_user):
        """
        GIVEN a non-existent journal entry ID
        WHEN voiding entry
        THEN it should return 400
        """
        fake_id = uuid4()
        response = await client.post(
            f"/journal-entries/{fake_id}/void",
            json={"reason": "Test void"},
        )
        assert response.status_code == 400

    async def test_create_entry_validation_error(self, client, test_user):
        """
        GIVEN entry with invalid data structure
        WHEN creating entry
        THEN it should return 422 from Pydantic validation
        """
        response = await client.post(
            "/journal-entries",
            json={
                "entry_date": "2024-01-01",
                "description": "Test",
                "lines": "invalid_structure",
            },
        )
        assert response.status_code == 422

    async def test_delete_draft_entry_success(self, client, db, test_user):
        """
        GIVEN a draft journal entry exists
        WHEN deleting the entry
        THEN it should return 204 and remove from database
        """
        from sqlalchemy import select

        cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="USD")
        revenue = Account(user_id=test_user.id, name="Revenue", type=AccountType.INCOME, currency="USD")
        db.add_all([cash, revenue])
        await db.flush()

        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date(2024, 1, 1),
            memo="Test Entry",
            status=JournalEntryStatus.DRAFT,
        )
        db.add(entry)
        await db.flush()

        line1 = JournalLine(
            journal_entry_id=entry.id, account_id=cash.id, direction=Direction.DEBIT, amount=Decimal("100.00")
        )
        line2 = JournalLine(
            journal_entry_id=entry.id, account_id=revenue.id, direction=Direction.CREDIT, amount=Decimal("100.00")
        )
        db.add_all([line1, line2])
        await db.commit()

        entry_id = entry.id

        response = await client.delete(f"/journal-entries/{entry_id}")
        assert response.status_code == 204

        result = await db.execute(select(JournalEntry).where(JournalEntry.id == entry_id))
        assert result.scalar_one_or_none() is None
