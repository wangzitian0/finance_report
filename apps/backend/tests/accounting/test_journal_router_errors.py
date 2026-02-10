"""AC2.7.2 - AC2.7.2: Journal Router Error Handling Tests

These tests validate journal router error handling for various scenarios including
validation errors, posting restrictions, voiding constraints, and deletion protection.
"""

from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.models.account import Account, AccountType
from src.models.journal import JournalEntry, JournalEntryStatus
from src.services.accounting import ValidationError


@pytest.mark.asyncio
class TestJournalRouterErrors:
    """Test error handling in journal router endpoints."""

    async def test_create_entry_validation_error(self, client, db, test_user):
        """
        GIVEN invalid journal entry data (unbalanced)
        WHEN creating a journal entry
        THEN it should return 422 with validation error
        """
        cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="USD")
        revenue = Account(user_id=test_user.id, name="Revenue", type=AccountType.INCOME, currency="USD")
        db.add_all([cash, revenue])
        await db.commit()
        await db.refresh(cash)
        await db.refresh(revenue)

        entry_data = {
            "entry_date": str(date.today()),
            "memo": "Unbalanced test",
            "lines": [
                {
                    "account_id": str(cash.id),
                    "direction": "DEBIT",
                    "amount": "100.00",
                    "currency": "USD",
                },
                {
                    "account_id": str(revenue.id),
                    "direction": "CREDIT",
                    "amount": "200.00",
                    "currency": "USD",
                },
            ],
        }

        response = await client.post("/journal-entries", json=entry_data)
        assert response.status_code == 422
        response_data = response.json()
        assert "detail" in response_data
        error_msg = str(response_data).lower()
        assert "balance" in error_msg or "debit" in error_msg or "credit" in error_msg

    async def test_post_entry_validation_error(self, client, db, test_user):
        """
        GIVEN a draft journal entry that fails validation on posting
        WHEN posting the entry
        THEN it should return 400 with validation error
        """
        # Create a draft entry
        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date.today(),
            memo="Test",
            status=JournalEntryStatus.DRAFT,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

        # Mock the post_journal_entry service to raise ValidationError
        with patch("src.routers.journal.post_journal_entry", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = ValidationError("Entry has no lines")

            response = await client.post(f"/journal-entries/{entry.id}/post")
            assert response.status_code == 400
            assert "no lines" in response.json()["detail"].lower()

    async def test_void_entry_validation_error(self, client, db, test_user):
        """
        GIVEN a journal entry that cannot be voided
        WHEN attempting to void the entry
        THEN it should return 400 with validation error
        """
        # Create a draft entry (can't void draft entries)
        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date.today(),
            memo="Test",
            status=JournalEntryStatus.DRAFT,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

        # Mock the void_journal_entry service to raise ValidationError
        with patch("src.routers.journal.void_journal_entry", new_callable=AsyncMock) as mock_void:
            mock_void.side_effect = ValidationError("Cannot void draft entry")

            response = await client.post(
                f"/journal-entries/{entry.id}/void",
                json={"reason": "Test void"},
            )
            assert response.status_code == 400
            assert "draft" in response.json()["detail"].lower()

    async def test_delete_posted_entry_fails(self, client, db, test_user):
        """
        GIVEN a posted journal entry
        WHEN attempting to delete it
        THEN it should return 400 error
        """
        # Create accounts
        cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="USD")
        revenue = Account(user_id=test_user.id, name="Revenue", type=AccountType.INCOME, currency="USD")
        db.add_all([cash, revenue])
        await db.flush()

        # Create a posted entry
        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date.today(),
            memo="Posted entry",
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

        response = await client.delete(f"/journal-entries/{entry.id}")
        assert response.status_code == 400
        assert "draft" in response.json()["detail"].lower()

    async def test_delete_nonexistent_entry(self, client):
        """
        GIVEN a non-existent entry ID
        WHEN attempting to delete it
        THEN it should return 404
        """
        fake_id = uuid4()
        response = await client.delete(f"/journal-entries/{fake_id}")
        assert response.status_code == 404
