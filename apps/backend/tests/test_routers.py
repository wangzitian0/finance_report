"""Integration tests for API routers."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.services.accounting import (
    ValidationError,
    calculate_account_balance,
    post_journal_entry,
    void_journal_entry,
)


class TestAccountBalanceErrors:
    """Test error handling in account balance calculation."""

    async def test_calculate_balance_account_not_found(
        self, db: AsyncSession, test_user
    ):
        """Test error when account doesn't exist."""
        non_existent_id = uuid4()
        with pytest.raises(ValidationError, match="not found"):
            await calculate_account_balance(db, non_existent_id, test_user.id)

    async def test_calculate_balance_wrong_user(self, db: AsyncSession, test_user):
        """Test error when account belongs to different user."""
        # Create account for a different user
        other_user_id = uuid4()
        account = Account(
            user_id=other_user_id,
            name="Other User Account",
            type=AccountType.ASSET,
            currency="SGD",
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)

        # Try to access with a different user ID
        with pytest.raises(ValidationError, match="does not belong"):
            await calculate_account_balance(db, account.id, test_user.id)


class TestPostJournalEntryErrors:
    """Test error handling in posting journal entries."""

    async def test_post_entry_not_found(self, db: AsyncSession, test_user):
        """Test error when journal entry doesn't exist."""
        non_existent_id = uuid4()
        with pytest.raises(ValidationError, match="not found"):
            await post_journal_entry(db, non_existent_id, test_user.id)

    async def test_post_entry_wrong_user(self, db: AsyncSession, test_user):
        """Test error when entry belongs to different user."""
        other_user_id = uuid4()
        entry = JournalEntry(
            user_id=other_user_id,
            entry_date=date.today(),
            memo="Other user entry",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.DRAFT,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

        with pytest.raises(ValidationError, match="does not belong"):
            await post_journal_entry(db, entry.id, test_user.id)

    async def test_post_entry_inactive_account(self, db: AsyncSession, test_user):
        """Test error when posting with inactive account."""
        # Create inactive account
        inactive_account = Account(
            user_id=test_user.id,
            name="Inactive Account",
            type=AccountType.ASSET,
            currency="SGD",
            is_active=False,
        )
        active_account = Account(
            user_id=test_user.id,
            name="Active Account",
            type=AccountType.EXPENSE,
            currency="SGD",
            is_active=True,
        )
        db.add_all([inactive_account, active_account])
        await db.commit()
        await db.refresh(inactive_account)
        await db.refresh(active_account)

        # Create entry with inactive account
        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date.today(),
            memo="Test inactive",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.DRAFT,
        )
        db.add(entry)
        await db.flush()

        # Add lines - one uses inactive account
        line1 = JournalLine(
            journal_entry_id=entry.id,
            account_id=inactive_account.id,
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="SGD",
        )
        line2 = JournalLine(
            journal_entry_id=entry.id,
            account_id=active_account.id,
            direction=Direction.CREDIT,
            amount=Decimal("100.00"),
            currency="SGD",
        )
        db.add_all([line1, line2])
        await db.commit()
        await db.refresh(entry)

        with pytest.raises(ValidationError, match="not active"):
            await post_journal_entry(db, entry.id, test_user.id)


class TestVoidJournalEntryErrors:
    """Test error handling in voiding journal entries."""

    async def test_void_entry_not_found(self, db: AsyncSession, test_user):
        """Test error when journal entry doesn't exist."""
        non_existent_id = uuid4()
        with pytest.raises(ValidationError, match="not found"):
            await void_journal_entry(db, non_existent_id, "Test reason", test_user.id)

    async def test_void_entry_wrong_user(self, db: AsyncSession, test_user):
        """Test error when entry belongs to different user."""
        other_user_id = uuid4()
        entry = JournalEntry(
            user_id=other_user_id,
            entry_date=date.today(),
            memo="Other user entry",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

        with pytest.raises(ValidationError, match="does not belong"):
            await void_journal_entry(db, entry.id, "Test reason", test_user.id)

    async def test_void_draft_entry_fails(self, db: AsyncSession, test_user):
        """Test that voiding draft entry fails."""
        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date.today(),
            memo="Draft entry for void test",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.DRAFT,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

        # Note: void_journal_entry(db, entry_id, reason, user_id)
        with pytest.raises(ValidationError, match="only void posted"):
            await void_journal_entry(db, entry.id, "Test reason", test_user.id)


class TestModelRepr:
    """Test model __repr__ methods for coverage."""

    def test_account_repr(self):
        """Test Account __repr__."""
        account = Account(
            id=uuid4(),
            user_id=uuid4(),
            name="Test Account",
            type=AccountType.ASSET,
            currency="SGD",
        )
        repr_str = repr(account)
        assert "Test Account" in repr_str
        assert "ASSET" in repr_str

    def test_journal_entry_repr(self):
        """Test JournalEntry __repr__."""
        entry = JournalEntry(
            id=uuid4(),
            user_id=uuid4(),
            entry_date=date(2026, 1, 1),
            memo="Test memo for repr",
            source_type=JournalEntrySourceType.MANUAL,
        )
        repr_str = repr(entry)
        assert "2026-01-01" in repr_str
        assert "Test memo" in repr_str

    def test_journal_line_repr(self):
        """Test JournalLine __repr__."""
        line = JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.50"),
            currency="SGD",
        )
        repr_str = repr(line)
        assert "DEBIT" in repr_str
        assert "100.50" in repr_str
        assert "SGD" in repr_str
