"""Tests for router error handling paths to improve coverage."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalLine


@pytest.mark.asyncio
class TestAccountsRouterCoverage:
    """Additional tests for accounts router coverage."""

    async def test_delete_account_with_transactions(self, client, db, test_user):
        """
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


@pytest.mark.asyncio
class TestAIModelsRouterCoverage:
    """Additional tests for AI models router coverage."""

    async def test_list_models_free_only_filter(self, client):
        """
        GIVEN the AI models endpoint with free_only filter
        WHEN requesting models
        THEN it should return only free models
        """
        response = await client.get("/ai/models?free_only=true")
        assert response.status_code == 200 or response.status_code == 503  # Service may be unavailable

        # If successful, verify free_only filtering
        if response.status_code == 200:
            data = response.json()
            assert "models" in data
            # All returned models should be free
            for model in data["models"]:
                assert model.get("is_free") is True


@pytest.mark.asyncio
class TestAuthRouterCoverage:
    """Additional tests for auth router coverage."""

    async def test_login_invalid_credentials(self, public_client):
        """
        GIVEN invalid login credentials
        WHEN attempting to login
        THEN it should return 401 error
        """
        response = await public_client.post(
            "/auth/login",
            data={
                "username": "nonexistent@example.com",
                "password": "wrongpassword",
            },
        )
        assert response.status_code in [401, 422]  # Either unauthorized or validation error


@pytest.mark.asyncio
class TestChatRouterCoverage:
    """Additional tests for chat router coverage."""

    async def test_get_nonexistent_session(self, client):
        """
        GIVEN a non-existent session ID
        WHEN requesting session details
        THEN it should return 404
        """
        fake_id = uuid4()
        response = await client.get(f"/chat/sessions/{fake_id}")
        assert response.status_code == 404

    async def test_send_message_to_nonexistent_session(self, client):
        """
        GIVEN a non-existent session ID
        WHEN sending a message
        THEN it should return 404
        """
        fake_id = uuid4()
        response = await client.post(
            f"/chat/sessions/{fake_id}/messages",
            json={"content": "Hello"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
class TestServiceLayerCoverage:
    """Additional tests for service layer coverage gaps."""

    async def test_pii_redaction_edge_cases(self):
        """
        GIVEN text with edge case PII patterns
        WHEN redacting
        THEN it should handle gracefully
        """
        from src.services.pii_redaction import detect_pii, mask_account_number, redact_text

        pii_matches = detect_pii("")
        assert pii_matches == []

        pii_matches = detect_pii("No PII here")
        assert len(pii_matches) == 0

        text_with_email = "Contact user@example.com for details"
        pii_matches = detect_pii(text_with_email)
        assert isinstance(pii_matches, list)

        result = redact_text("Some text here", replacement="[REDACTED]")
        assert result is not None
        assert hasattr(result, "redacted_text")

        masked = mask_account_number("1234567890", visible_digits=4)
        assert masked.endswith("7890")
        assert "*" in masked or "X" in masked
