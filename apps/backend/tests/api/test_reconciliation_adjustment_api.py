"""Tests for Flow 18: Reconciliation Immaterial Adjustment & Penny Rounding Write-Off API.

AC-reconciliation.adjustment.1: POST /reconciliation/adjustment with valid minor difference
creates a POSTED journal entry with 2 lines (Bank account and BankRoundingDifference account).

Verifies:
- POST /reconciliation/adjustment with valid minor difference creates a POSTED journal entry
  with 2 lines (Bank account and BankRoundingDifference account).
- POST /reconciliation/adjustment exceeding immaterial threshold returns 400 Bad Request.
- POST /reconciliation/adjustment with diff == 0 returns 200 and creates no journal entry.
- POST /reconciliation/adjustment with unowned account returns 404 Not Found.
"""

from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.identity import User
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)


async def create_test_bank_account(db, user: User, currency: str = "SGD") -> Account:
    account = Account(
        user_id=user.id,
        name=f"Bank Account {uuid4().hex[:8]}",
        type=AccountType.ASSET,
        currency=currency,
    )
    db.add(account)
    await db.flush()
    return account


class TestReconciliationAdjustmentApi:
    """Test suite for POST /reconciliation/adjustment (Flow 18)."""

    async def test_adjustment_gain_success(self, client: AsyncClient, db, test_user: User):
        """Flow 18: Positive difference (bank > book) posts BankRoundingDifference income."""
        # GIVEN a bank account owned by the test user
        bank_account = await create_test_bank_account(db, test_user, currency="SGD")
        await db.commit()

        # WHEN calling POST /reconciliation/adjustment with bank=500.03, book=500.00
        payload = {
            "account_id": str(bank_account.id),
            "bank_balance": "500.03",
            "book_balance": "500.00",
        }
        response = await client.post("/reconciliation/adjustment", json=payload)

        # THEN returns 200 OK
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["account_id"] == str(bank_account.id)
        assert data["difference"] == "0.03"
        assert data["is_gain"] is True
        assert data["journal_entry_id"] is not None

        # AND a POSTED JournalEntry is created with 2 lines (bank account and BankRoundingDifference)
        entry_id = UUID(data["journal_entry_id"])
        result = await db.execute(
            select(JournalEntry)
            .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
            .where(JournalEntry.id == entry_id)
        )
        entry = result.scalar_one()
        assert entry.status == JournalEntryStatus.POSTED
        assert len(entry.lines) == 2

        line_accounts = {line.account_id: line for line in entry.lines}
        assert bank_account.id in line_accounts

        bank_line = line_accounts[bank_account.id]
        assert bank_line.direction == Direction.DEBIT
        assert bank_line.amount == Decimal("0.03")

        # BankRoundingDifference line
        rounding_line = next(line for line in entry.lines if line.account_id != bank_account.id)
        assert rounding_line.account.name == "BankRoundingDifference"
        assert rounding_line.account.currency == "SGD"
        assert rounding_line.account.type in (AccountType.INCOME, AccountType.EXPENSE)
        assert rounding_line.direction == Direction.CREDIT
        assert rounding_line.amount == Decimal("0.03")

    async def test_adjustment_loss_success(self, client: AsyncClient, db, test_user: User):
        """Flow 18: Negative difference (bank < book) posts BankRoundingDifference expense."""
        # GIVEN a bank account
        bank_account = await create_test_bank_account(db, test_user, currency="SGD")
        await db.commit()

        # WHEN calling POST /reconciliation/adjustment with bank=499.97, book=500.00
        payload = {
            "account_id": str(bank_account.id),
            "bank_balance": "499.97",
            "book_balance": "500.00",
        }
        response = await client.post("/reconciliation/adjustment", json=payload)

        # THEN returns 200 OK
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["difference"] == "-0.03"
        assert data["is_gain"] is False
        assert data["journal_entry_id"] is not None

        # AND a POSTED JournalEntry is created with 2 lines
        entry_id = UUID(data["journal_entry_id"])
        result = await db.execute(
            select(JournalEntry)
            .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
            .where(JournalEntry.id == entry_id)
        )
        entry = result.scalar_one()
        assert entry.status == JournalEntryStatus.POSTED
        assert len(entry.lines) == 2

        bank_line = next(line for line in entry.lines if line.account_id == bank_account.id)
        assert bank_line.direction == Direction.CREDIT
        assert bank_line.amount == Decimal("0.03")

        rounding_line = next(line for line in entry.lines if line.account_id != bank_account.id)
        assert rounding_line.account.name == "BankRoundingDifference"
        assert rounding_line.direction == Direction.DEBIT
        assert rounding_line.amount == Decimal("0.03")

    async def test_adjustment_exceeds_threshold(self, client: AsyncClient, db, test_user: User):
        """Flow 18: Discrepancy exceeding immaterial threshold returns 400."""
        # GIVEN a bank account
        bank_account = await create_test_bank_account(db, test_user)
        await db.commit()

        # WHEN calling POST /reconciliation/adjustment with difference 1.00 > threshold 0.05
        payload = {
            "account_id": str(bank_account.id),
            "bank_balance": "501.00",
            "book_balance": "500.00",
        }
        response = await client.post("/reconciliation/adjustment", json=payload)

        # THEN returns 400 Bad Request with "exceeds immaterial threshold"
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error_detail = response.json()["detail"]
        assert "exceeds immaterial threshold" in error_detail

    async def test_adjustment_zero_diff_no_entry(self, client: AsyncClient, db, test_user: User):
        """Flow 18: diff == 0 returns 200 and creates no journal entry."""
        # GIVEN a bank account
        bank_account = await create_test_bank_account(db, test_user)
        await db.commit()

        # WHEN calling POST /reconciliation/adjustment with bank == book
        payload = {
            "account_id": str(bank_account.id),
            "bank_balance": "500.00",
            "book_balance": "500.00",
        }
        response = await client.post("/reconciliation/adjustment", json=payload)

        # THEN returns 200 OK without creating an entry
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["difference"] == "0.00"
        assert data["journal_entry_id"] is None
        assert data.get("entry") is None

    async def test_adjustment_account_not_found(self, client: AsyncClient, test_user: User):
        """Flow 18: Non-existent or unowned account returns 404."""
        payload = {
            "account_id": str(uuid4()),
            "bank_balance": "500.03",
            "book_balance": "500.00",
        }
        response = await client.post("/reconciliation/adjustment", json=payload)
        assert response.status_code == status.HTTP_404_NOT_FOUND
