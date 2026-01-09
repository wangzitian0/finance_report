"""Unit tests for accounting service."""

from decimal import Decimal
from uuid import uuid4

import pytest

from src.models import (
    Direction,
    JournalLine,
)
from src.services.accounting import (
    ValidationError,
    validate_journal_balance,
)


@pytest.mark.asyncio
async def test_balanced_entry_passes():
    """Balanced debit/credit entries should pass validation."""
    lines = [
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="SGD",
        ),
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.CREDIT,
            amount=Decimal("100.00"),
            currency="SGD",
        ),
    ]
    
    validate_journal_balance(lines)  # Should not raise


@pytest.mark.asyncio
async def test_unbalanced_entry_fails():
    """Unbalanced entries should be rejected."""
    lines = [
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="SGD",
        ),
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.CREDIT,
            amount=Decimal("90.00"),
            currency="SGD",
        ),
    ]
    
    with pytest.raises(ValidationError, match="not balanced"):
        validate_journal_balance(lines)


@pytest.mark.asyncio
async def test_single_line_entry_fails():
    """Single-line entries should be rejected."""
    lines = [
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="SGD",
        ),
    ]
    
    with pytest.raises(ValidationError, match="at least 2 lines"):
        validate_journal_balance(lines)


@pytest.mark.asyncio
async def test_decimal_precision():
    """Decimal calculations should not lose precision."""
    amount1 = Decimal("100.50")
    amount2 = Decimal("50.25")
    total = amount1 + amount2
    
    assert total == Decimal("150.75")
    assert str(total) == "150.75"
