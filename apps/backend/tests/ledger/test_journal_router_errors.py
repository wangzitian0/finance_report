"""AC-ledger.7.2 - AC-ledger.7.2: Journal Router Error Handling Tests

These tests validate journal router error handling for various scenarios including
validation errors, posting restrictions, voiding constraints, and deletion protection.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine, ValidationError
from tests.ledger._ledger_helpers import create_valid_posted_entry


class TestJournalRouterErrors:
    """Test error handling in journal router endpoints."""

    async def test_create_entry_validation_error(self, client, db, test_user):
        """
        GIVEN invalid journal entry data (unbalanced)
        WHEN creating a journal entry
        THEN the ledger service should return 400 with a validation error
        """
        cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
        revenue = Account(user_id=test_user.id, name="Revenue", type=AccountType.INCOME, currency="SGD")
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
                    "currency": "SGD",
                },
                {
                    "account_id": str(revenue.id),
                    "direction": "CREDIT",
                    "amount": "200.00",
                    "currency": "SGD",
                },
            ],
        }

        response = await client.post("/journal-entries", json=entry_data)
        assert response.status_code == 400
        response_data = response.json()
        assert "detail" in response_data
        error_msg = str(response_data).lower()
        assert "balance" in error_msg or "debit" in error_msg or "credit" in error_msg

    async def test_create_entry_service_validation_error_returns_400(self, client, db, test_user):
        """
        GIVEN a schema-valid balanced entry referencing a non-existent account
        WHEN creating the entry
        THEN the service ValidationError surfaces as 400 (router except path)
        """
        entry_data = {
            "entry_date": str(date.today()),
            "memo": "Unknown account",
            "lines": [
                {"account_id": str(uuid4()), "direction": "DEBIT", "amount": "100.00", "currency": "SGD"},
                {"account_id": str(uuid4()), "direction": "CREDIT", "amount": "100.00", "currency": "SGD"},
            ],
        }
        response = await client.post("/journal-entries", json=entry_data)
        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()

    async def test_legacy_unproven_draft_cannot_reach_posting_sink(self, client, db, test_user):
        """
        GIVEN a balanced historical draft without a decision anchor
        WHEN posting the entry through the router
        THEN `post_journal_entry` fails closed and the entry stays a draft
        """
        cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
        revenue = Account(user_id=test_user.id, name="Revenue", type=AccountType.INCOME, currency="SGD")
        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date.today(),
            memo="Test",
            status=JournalEntryStatus.DRAFT,
            lines=[
                JournalLine(account=cash, direction=Direction.DEBIT, amount=Decimal("100.00"), currency="SGD"),
                JournalLine(account=revenue, direction=Direction.CREDIT, amount=Decimal("100.00"), currency="SGD"),
            ],
        )
        db.add(entry)
        await db.commit()

        response = await client.post(f"/journal-entries/{entry.id}/postings")

        assert response.status_code == 400
        assert "legacy-unproven" in response.json()["detail"].lower()
        await db.refresh(entry)
        assert entry.status == JournalEntryStatus.DRAFT

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
                f"/journal-entries/{entry.id}/voidings",
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
        entry = await create_valid_posted_entry(db, test_user.id, memo="Posted entry")

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


async def test_AC_ledger_2576_1_journal_wire_bounds_and_tags_validation(client, db, test_user) -> None:
    """AC-ledger.2576.1: Manual journal line schemas bound amount/fx_rate and reject float or NUL in tags (#2576)."""
    import pytest
    from pydantic import ValidationError as PydanticValidationError

    from src.schemas.journal import JournalLineCreate

    cash = Account(user_id=test_user.id, name="Wire Cash", type=AccountType.ASSET, currency="SGD")
    rev = Account(user_id=test_user.id, name="Wire Revenue", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, rev])
    await db.commit()

    # Over-precision or overflow amount (>= 10^16) rejected at schema boundary (422)
    for bad_amount in ["10000000000000000.00", "1E+20", "10.123"]:
        with pytest.raises(PydanticValidationError):
            JournalLineCreate(
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=bad_amount,
                currency="SGD",
            )

    # Over-precision or overflow fx_rate (>= 10^12) rejected at schema boundary (422)
    for bad_fx in ["1000000000000.000000", "1E+15", "1.1234567"]:
        with pytest.raises(PydanticValidationError):
            JournalLineCreate(
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount="100.00",
                currency="USD",
                fx_rate=bad_fx,
            )

    # Float in tags or NUL character in tags rejected at schema boundary (422)
    for bad_tags in [{"rate": 1.25}, {"nested": [1, 1e16]}, {"bad\x00key": "ok"}, {"key": "bad\x00val"}]:
        resp = await client.post(
            "/journal-entries",
            json={
                "entry_date": str(date.today()),
                "memo": "Bad tags",
                "lines": [
                    {
                        "account_id": str(cash.id),
                        "direction": "DEBIT",
                        "amount": "100.00",
                        "currency": "SGD",
                        "tags": bad_tags,
                    },
                    {
                        "account_id": str(rev.id),
                        "direction": "CREDIT",
                        "amount": "100.00",
                        "currency": "SGD",
                    },
                ],
            },
        )
        assert resp.status_code == 422, f"Expected 422 for tags={bad_tags!r}, got {resp.status_code}: {resp.text}"
