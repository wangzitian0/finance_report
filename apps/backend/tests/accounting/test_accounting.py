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
    validate_fx_rates,
    validate_journal_balance,
)


@pytest.mark.asyncio
async def test_balanced_entry_passes():
    """AC2.2.1: Balanced debit/credit entries should pass validation.

    Verify that journal entries with equal total debits and credits
    pass the balance validation logic.
    """
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
    """AC2.2.2: Unbalanced entries should be rejected.

    Verify that journal entries with unequal debits and credits
    raise ValidationError with appropriate message.
    """
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
    """AC2.2.3: Single-line entries should be rejected.

    Verify that journal entries with fewer than 2 lines
    raise ValidationError (minimum requirement for double-entry).
    """
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
    """AC2.2.4: Decimal calculations should not lose precision.

    Verify that monetary calculations using Decimal type
    maintain exact precision without floating-point errors.
    """
    amount1 = Decimal("100.50")
    amount2 = Decimal("50.25")
    total = amount1 + amount2

    assert total == Decimal("150.75")
    assert str(total) == "150.75"


@pytest.mark.asyncio
async def test_fx_rate_required_for_non_base_currency():
    """AC2.2.5: Non-base currency lines require fx_rate.

    Verify that journal lines with currency != base currency
    must have a non-null fx_rate value.
    """
    lines = [
        JournalLine(
            id=uuid4(),
            journal_entry_id=uuid4(),
            account_id=uuid4(),
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="USD",
            fx_rate=None,
        ),
    ]

    with pytest.raises(ValidationError, match="fx_rate required"):
        validate_fx_rates(lines)
