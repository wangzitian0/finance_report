"""Tests for Pydantic schemas validation."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.models import AccountType, Direction
from src.schemas import (
    AccountCreate,
    AccountUpdate,
    JournalEntryCreate,
    JournalLineCreate,
    VoidJournalEntryRequest,
)


class TestAccountSchemas:
    """Tests for Account schemas."""

    def test_account_create_valid(self):
        """Test valid account creation."""
        account = AccountCreate(
            name="Test Account",
            type=AccountType.ASSET,
            currency="SGD",
        )
        assert account.name == "Test Account"
        assert account.type == AccountType.ASSET
        assert account.currency == "SGD"

    def test_account_create_with_all_fields(self):
        """Test account creation with all optional fields."""
        account = AccountCreate(
            name="Full Account",
            code="1100",
            type=AccountType.LIABILITY,
            currency="USD",
            description="Test description",
        )
        assert account.code == "1100"
        assert account.description == "Test description"

    def test_account_create_empty_name_fails(self):
        """Test that empty name is rejected."""
        with pytest.raises(ValidationError):
            AccountCreate(
                name="",
                type=AccountType.ASSET,
                currency="SGD",
            )

    def test_account_create_invalid_currency_length(self):
        """Test that invalid currency length is rejected."""
        with pytest.raises(ValidationError):
            AccountCreate(
                name="Test",
                type=AccountType.ASSET,
                currency="SGDX",  # Too long
            )

    def test_account_update_partial(self):
        """Test partial account update."""
        update = AccountUpdate(name="New Name")
        assert update.name == "New Name"
        assert update.code is None
        assert update.is_active is None


class TestJournalLineSchemas:
    """Tests for JournalLine schemas."""

    def test_journal_line_create_valid(self):
        """Test valid journal line creation."""
        line = JournalLineCreate(
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.50"),
            currency="SGD",
        )
        assert line.amount == Decimal("100.50")
        assert line.direction == Direction.DEBIT

    def test_journal_line_amount_must_be_positive(self):
        """Test that zero or negative amounts are rejected."""
        with pytest.raises(ValidationError):
            JournalLineCreate(
                account_id=uuid4(),
                direction=Direction.DEBIT,
                amount=Decimal("0"),
                currency="SGD",
            )

        with pytest.raises(ValidationError):
            JournalLineCreate(
                account_id=uuid4(),
                direction=Direction.CREDIT,
                amount=Decimal("-10.00"),
                currency="SGD",
            )

    def test_journal_line_with_fx_rate(self):
        """Test journal line with FX rate."""
        line = JournalLineCreate(
            account_id=uuid4(),
            direction=Direction.CREDIT,
            amount=Decimal("1000.00"),
            currency="USD",
            fx_rate=Decimal("1.35"),
        )
        assert line.fx_rate == Decimal("1.35")


class TestJournalEntrySchemas:
    """Tests for JournalEntry schemas."""

    def test_journal_entry_create_balanced(self):
        """Test balanced journal entry creation."""
        account1 = uuid4()
        account2 = uuid4()
        
        entry = JournalEntryCreate(
            entry_date=date.today(),
            memo="Test entry",
            lines=[
                JournalLineCreate(
                    account_id=account1,
                    direction=Direction.DEBIT,
                    amount=Decimal("100.00"),
                    currency="SGD",
                ),
                JournalLineCreate(
                    account_id=account2,
                    direction=Direction.CREDIT,
                    amount=Decimal("100.00"),
                    currency="SGD",
                ),
            ],
        )
        assert len(entry.lines) == 2

    def test_journal_entry_unbalanced_fails(self):
        """Test that unbalanced entries are rejected."""
        account1 = uuid4()
        account2 = uuid4()
        
        with pytest.raises(ValidationError) as exc_info:
            JournalEntryCreate(
                entry_date=date.today(),
                memo="Unbalanced",
                lines=[
                    JournalLineCreate(
                        account_id=account1,
                        direction=Direction.DEBIT,
                        amount=Decimal("100.00"),
                        currency="SGD",
                    ),
                    JournalLineCreate(
                        account_id=account2,
                        direction=Direction.CREDIT,
                        amount=Decimal("50.00"),
                        currency="SGD",
                    ),
                ],
            )
        assert "not balanced" in str(exc_info.value)

    def test_journal_entry_single_line_fails(self):
        """Test that single-line entries are rejected."""
        with pytest.raises(ValidationError):
            JournalEntryCreate(
                entry_date=date.today(),
                memo="Single line",
                lines=[
                    JournalLineCreate(
                        account_id=uuid4(),
                        direction=Direction.DEBIT,
                        amount=Decimal("100.00"),
                        currency="SGD",
                    ),
                ],
            )

    def test_journal_entry_empty_lines_fails(self):
        """Test that empty lines are rejected."""
        with pytest.raises(ValidationError):
            JournalEntryCreate(
                entry_date=date.today(),
                memo="No lines",
                lines=[],
            )

    def test_journal_entry_with_tolerance(self):
        """Test that entries within tolerance (0.01) are accepted."""
        account1 = uuid4()
        account2 = uuid4()
        
        # Difference of 0.01 should be accepted (exactly at tolerance)
        entry = JournalEntryCreate(
            entry_date=date.today(),
            memo="Near balanced",
            lines=[
                JournalLineCreate(
                    account_id=account1,
                    direction=Direction.DEBIT,
                    amount=Decimal("100.00"),
                    currency="SGD",
                ),
                JournalLineCreate(
                    account_id=account2,
                    direction=Direction.CREDIT,
                    amount=Decimal("100.01"),
                    currency="SGD",
                ),
            ],
        )
        assert entry is not None


class TestVoidRequest:
    """Tests for void request schema."""

    def test_void_request_valid(self):
        """Test valid void request."""
        request = VoidJournalEntryRequest(reason="Test void reason")
        assert request.reason == "Test void reason"

    def test_void_request_empty_reason_fails(self):
        """Test that empty reason is rejected."""
        with pytest.raises(ValidationError):
            VoidJournalEntryRequest(reason="")
