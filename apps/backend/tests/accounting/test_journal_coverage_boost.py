"""AC2.3 - AC2.7: Journal router coverage boost tests.

These tests target specific uncovered lines from EPIC-002:
- AC2.3.7: create_entry ValidationError catch (unbalanced, single-line)
- AC2.7.5: DELETE /{entry_id} endpoint (success, not-found, non-draft)
"""

from datetime import date
from uuid import uuid4

import pytest

from src.models.account import Account, AccountType
from src.models.journal import (
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
)


@pytest.mark.asyncio
class TestJournalDeleteEndpoint:
    """Tests for DELETE /journal-entries/{entry_id}."""

    async def test_delete_draft_entry_success(self, client, db, test_user):
        """
        GIVEN a draft journal entry exists
        WHEN DELETE /journal-entries/{entry_id}
        THEN it should return 204 and the entry is removed.
        """
        cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="USD")
        db.add(cash)
        await db.flush()

        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date.today(),
            memo="Draft to delete",
            status=JournalEntryStatus.DRAFT,
            source_type=JournalEntrySourceType.MANUAL,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        entry_id = entry.id

        response = await client.delete(f"/journal-entries/{entry_id}")
        assert response.status_code == 204

        get_response = await client.get(f"/journal-entries/{entry_id}")
        assert get_response.status_code == 404

    async def test_delete_nonexistent_entry_returns_404(self, client, test_user):
        """
        GIVEN a non-existent entry ID
        WHEN DELETE /journal-entries/{entry_id}
        THEN it should return 404.
        """
        fake_id = uuid4()
        response = await client.delete(f"/journal-entries/{fake_id}")
        assert response.status_code == 404

    async def test_delete_posted_entry_returns_400(self, client, db, test_user):
        """
        GIVEN a POSTED journal entry
        WHEN DELETE /journal-entries/{entry_id}
        THEN it should return 400 because only draft entries can be deleted.
        """
        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date.today(),
            memo="Posted - cannot delete",
            status=JournalEntryStatus.POSTED,
            source_type=JournalEntrySourceType.MANUAL,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

        response = await client.delete(f"/journal-entries/{entry.id}")
        assert response.status_code == 400
        assert "draft" in response.json()["detail"].lower()

    async def test_delete_voided_entry_returns_400(self, client, db, test_user):
        """
        GIVEN a VOID journal entry
        WHEN DELETE /journal-entries/{entry_id}
        THEN it should return 400 because only draft entries can be deleted.
        """
        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date.today(),
            memo="Voided - cannot delete",
            status=JournalEntryStatus.VOID,
            source_type=JournalEntrySourceType.MANUAL,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

        response = await client.delete(f"/journal-entries/{entry.id}")
        assert response.status_code == 400


class TestJournalCreateValidationError:
    """Tests for create_entry ValidationError path (journal.py lines 47-48)."""

    @pytest.mark.asyncio
    async def test_create_unbalanced_entry_returns_error(self, client, db, test_user):
        """
        GIVEN unbalanced debit/credit amounts
        WHEN POST /journal-entries
        THEN it should return an error (400 or 422).
        """
        cash = Account(user_id=test_user.id, name="Cash CB", type=AccountType.ASSET, currency="USD")
        expense = Account(user_id=test_user.id, name="Food CB", type=AccountType.EXPENSE, currency="USD")
        db.add_all([cash, expense])
        await db.commit()
        await db.refresh(cash)
        await db.refresh(expense)

        payload = {
            "entry_date": str(date.today()),
            "memo": "Unbalanced",
            "lines": [
                {"account_id": str(cash.id), "direction": "DEBIT", "amount": "100.00", "currency": "USD"},
                {"account_id": str(expense.id), "direction": "CREDIT", "amount": "50.00", "currency": "USD"},
            ],
        }

        response = await client.post("/journal-entries", json=payload)
        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_create_single_line_entry_returns_error(self, client, db, test_user):
        """
        GIVEN a journal entry with only one line (must have >= 2)
        WHEN POST /journal-entries
        THEN it should return an error.
        """
        cash = Account(user_id=test_user.id, name="Cash SL", type=AccountType.ASSET, currency="USD")
        db.add(cash)
        await db.commit()
        await db.refresh(cash)

        payload = {
            "entry_date": str(date.today()),
            "memo": "Single line",
            "lines": [
                {"account_id": str(cash.id), "direction": "DEBIT", "amount": "100.00", "currency": "USD"},
            ],
        }

        response = await client.post("/journal-entries", json=payload)
        assert response.status_code in (400, 422)
