"""Entry value-object laws — the double-entry balance invariant (EPIC-012 AC12.34)."""

from decimal import Decimal
from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof

from src.ledger import DegenerateEntryError, Entry, Leg, UnbalancedEntryError
from src.models.journal import Direction
from src.money import Money

pytestmark = pytest.mark.no_db

A, B, C = uuid4(), uuid4(), uuid4()


def _m(x: str, ccy: str = "USD") -> Money:
    return Money(Decimal(x), ccy)


@ac_proof(proof_id="test_entry_balances", ac_ids=["AC12.34.1"], ci_tier="pr_ci")
def test_AC12_34_1_balanced_entry_constructs():
    """AC12.34.1: a balanced transfer / multi-leg entry constructs."""
    e = Entry.transfer(debit=A, credit=B, money=_m("10.00"))
    assert len(e.legs) == 2
    # 3-leg balanced (sell shape: dr cash = cr cost + cr pnl)
    e3 = Entry.of(
        Leg(A, Direction.DEBIT, _m("100.00")),
        Leg(B, Direction.CREDIT, _m("80.00")),
        Leg(C, Direction.CREDIT, _m("20.00")),
    )
    assert len(e3.legs) == 3


@ac_proof(proof_id="test_entry_unbalanced_raises", ac_ids=["AC12.34.1"], ci_tier="pr_ci")
def test_AC12_34_1_unbalanced_entry_is_unconstructable():
    """AC12.34.1: an unbalanced entry cannot be constructed."""
    with pytest.raises(UnbalancedEntryError):
        Entry.of(
            Leg(A, Direction.DEBIT, _m("100.00")),
            Leg(B, Direction.CREDIT, _m("80.00")),
        )
    with pytest.raises(DegenerateEntryError):
        Entry.of()
    # a single-leg entry is degenerate (clear error, not a confusing "unbalanced")
    with pytest.raises(DegenerateEntryError):
        Entry.of(Leg(A, Direction.DEBIT, _m("10.00")))


@ac_proof(proof_id="test_entry_per_currency", ac_ids=["AC12.34.1"], ci_tier="pr_ci")
def test_AC12_34_1_balance_is_checked_per_currency():
    """AC12.34.1: balance is per currency, not a currency-blind sum."""
    # each currency balances on its own
    ok = Entry.of(
        Leg(A, Direction.DEBIT, _m("10.00", "USD")),
        Leg(B, Direction.CREDIT, _m("10.00", "USD")),
        Leg(A, Direction.DEBIT, _m("5.00", "SGD")),
        Leg(B, Direction.CREDIT, _m("5.00", "SGD")),
    )
    assert len(ok.legs) == 4
    # currency-blind sum is zero (10 USD dr vs 10 SGD cr) but per-currency it is NOT
    with pytest.raises(UnbalancedEntryError):
        Entry.of(
            Leg(A, Direction.DEBIT, _m("10.00", "USD")),
            Leg(B, Direction.CREDIT, _m("10.00", "SGD")),
        )


@ac_proof(proof_id="test_entry_leg_positive", ac_ids=["AC12.34.1"], ci_tier="pr_ci")
def test_AC12_34_1_legs_must_be_positive():
    """AC12.34.1: a leg amount must be positive (no zero/negative lines)."""
    with pytest.raises(UnbalancedEntryError):
        Leg(A, Direction.DEBIT, _m("0.00"))
    with pytest.raises(UnbalancedEntryError):
        Leg(A, Direction.DEBIT, _m("-1.00"))


@ac_proof(proof_id="test_entry_leg_direction", ac_ids=["AC12.34.1"], ci_tier="pr_ci")
def test_AC12_34_1_leg_direction_must_be_typed():
    """AC12.34.1: a non-Direction direction is rejected (no silent credit)."""
    with pytest.raises(TypeError):
        Leg(A, "DEBIT", _m("10.00"))  # type: ignore[arg-type]
