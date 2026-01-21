import pytest
from decimal import Decimal
from uuid import uuid4
from src.schemas.journal import JournalLineCreate
from src.models.journal import Direction

# Tests for Data Integrity (Float vs Decimal)
# Ref: docs/ssot/accounting.md (Anti-pattern A)


def test_decimal_parsing_from_string():
    """
    Golden Path: Parsing money from string should be exact.
    """
    data = {
        "account_id": uuid4(),
        "direction": Direction.DEBIT,
        "amount": "123.45",
        "currency": "SGD",
    }
    obj = JournalLineCreate(**data)
    assert obj.amount == Decimal("123.45")
    assert isinstance(obj.amount, Decimal)


def test_float_injection_safety():
    """
    Guardrail: If a float is passed (e.g. from AI or bad client),
    it must NOT result in precision artifacts.

    The system should either:
    1. Reject the float (Strict)
    2. Round it intelligently

    It must NEVER just do Decimal(float_val) which preserves garbage.
    """
    # The classic float precision error: 0.1 + 0.2 = 0.30000000000000004
    bad_float = 0.1 + 0.2

    data = {
        "account_id": uuid4(),
        "direction": Direction.DEBIT,
        "amount": bad_float,
        "currency": "SGD",
    }

    try:
        obj = JournalLineCreate(**data)
    except Exception:
        # If it raises an error (e.g. strict type check), that is also ACCEPTABLE (and preferred).
        return

    # If it accepted it, it better match "0.30" exactly
    # If it captured the artifact 0.3000000000000000444..., this assertion will fail.
    # This acts as a tripwire for the "Float" pitfall.
    assert obj.amount == Decimal("0.30") or obj.amount == Decimal("0.3"), (
        f"DANGEROUS: Float {bad_float} was converted to {obj.amount} with precision artifacts! "
        "Update Pydantic models to use strict=True or a rounding validator."
    )


def test_scientific_notation_rejection():
    """
    Guardrail: Scientific notation (1E-10) often implies float logic.
    Ensure we handle it safely (either reject or parse correctly).
    """
    data = {
        "account_id": uuid4(),
        "direction": Direction.DEBIT,
        "amount": "1.50E+2",  # 150.00
        "currency": "SGD",
    }
    obj = JournalLineCreate(**data)
    assert obj.amount == Decimal("150.00")
