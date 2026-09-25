"""AC-ledger.2.1: Mutation and falsification tests for ledger double-entry accounting invariants.

Verifies that the double-entry accounting engine actively rejects invalid,
tampered, or imbalanced mutations at the domain boundary.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from src.audit.money import Money
from src.ledger import (
    Direction,
    JournalLine,
    Leg,
    UnbalancedEntryError,
    ValidationError,
    validate_fx_rates,
    validate_journal_balance,
)

pytestmark = pytest.mark.no_db


def _make_line(
    *,
    direction: Direction,
    amount: Decimal,
    currency: str = "SGD",
    fx_rate: Decimal | None = None,
) -> JournalLine:
    return JournalLine(
        id=uuid4(),
        journal_entry_id=uuid4(),
        account_id=uuid4(),
        direction=direction,
        amount=amount,
        currency=currency,
        fx_rate=fx_rate,
    )


def test_imbalance_exceeding_tolerance_is_strictly_rejected():
    """Mutation: Tampering debit or credit exceeding the tolerance (0.01) must be rejected."""
    # Balanced baseline
    lines = [
        _make_line(direction=Direction.DEBIT, amount=Decimal("100.00")),
        _make_line(direction=Direction.CREDIT, amount=Decimal("100.00")),
    ]
    validate_journal_balance(lines)

    # Mutate debit +0.02 (exceeds 0.01 balance tolerance)
    imbalanced_debit = [
        _make_line(direction=Direction.DEBIT, amount=Decimal("100.02")),
        _make_line(direction=Direction.CREDIT, amount=Decimal("100.00")),
    ]
    with pytest.raises(ValidationError, match="Journal entry not balanced"):
        validate_journal_balance(imbalanced_debit)

    # Mutate credit -0.02
    imbalanced_credit = [
        _make_line(direction=Direction.DEBIT, amount=Decimal("100.00")),
        _make_line(direction=Direction.CREDIT, amount=Decimal("99.98")),
    ]
    with pytest.raises(ValidationError, match="Journal entry not balanced"):
        validate_journal_balance(imbalanced_credit)


def test_single_sided_entries_are_rejected():
    """Mutation: Entries consisting only of debits or only of credits must be rejected."""
    only_debits = [
        _make_line(direction=Direction.DEBIT, amount=Decimal("50.00")),
        _make_line(direction=Direction.DEBIT, amount=Decimal("50.00")),
    ]
    with pytest.raises(ValidationError, match="Journal entry not balanced"):
        validate_journal_balance(only_debits)

    only_credits = [
        _make_line(direction=Direction.CREDIT, amount=Decimal("100.00")),
    ]
    with pytest.raises(ValidationError, match="Journal entry must have at least 2 lines"):
        validate_journal_balance(only_credits)


def test_zero_and_negative_leg_amounts_are_rejected():
    """Mutation: Pure Leg aggregate rejects zero or negative amounts."""
    account_id = uuid4()
    with pytest.raises(UnbalancedEntryError):
        Leg(account_id, Direction.DEBIT, Money(Decimal("0.00"), "SGD"))

    with pytest.raises(UnbalancedEntryError):
        Leg(account_id, Direction.DEBIT, Money(Decimal("-10.00"), "SGD"))


def test_empty_journal_lines_rejected():
    """Mutation: Validating an empty lines sequence must raise ValidationError."""
    with pytest.raises(ValidationError, match="Journal entry must have at least 2 lines"):
        validate_journal_balance([])


def test_foreign_currency_missing_fx_rate_rejected():
    """Mutation: Foreign currency lines without positive FX rates must be rejected."""
    lines_missing_fx = [
        _make_line(direction=Direction.DEBIT, amount=Decimal("100.00"), currency="USD", fx_rate=None),
        _make_line(direction=Direction.CREDIT, amount=Decimal("130.00"), currency="SGD", fx_rate=Decimal("1.0")),
    ]
    with pytest.raises(ValidationError, match="fx_rate required for currency USD"):
        validate_fx_rates(lines_missing_fx, base_currency="SGD")
