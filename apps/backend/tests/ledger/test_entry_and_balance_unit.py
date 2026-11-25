from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest

from src.audit.money import Money
from src.ledger import (
    DegenerateEntryError,
    Direction,
    Entry,
    Leg,
    UnbalancedEntryError,
    ValidationError,
    validate_fx_rates,
    validate_journal_balance,
)
from tests.ledger._ledger_helpers import make_line

pytestmark = pytest.mark.no_db
A, B, C = uuid4(), uuid4(), uuid4()


def _money(val: str, ccy: str = "USD") -> Money:
    return Money(Decimal(val), ccy)


def test_entry_and_leg_construction_and_invariants() -> None:
    assert len(Entry.transfer(debit=A, credit=B, money=_money("10.00")).legs) == 2
    assert (
        len(
            Entry.of(
                Leg(A, Direction.DEBIT, _money("100.00")),
                Leg(B, Direction.CREDIT, _money("80.00")),
                Leg(C, Direction.CREDIT, _money("20.00")),
            ).legs
        )
        == 3
    )
    assert (
        len(
            Entry.of(
                Leg(A, Direction.DEBIT, _money("10.00", "USD")),
                Leg(B, Direction.CREDIT, _money("10.00", "USD")),
                Leg(A, Direction.DEBIT, _money("5.00", "SGD")),
                Leg(B, Direction.CREDIT, _money("5.00", "SGD")),
            ).legs
        )
        == 4
    )
    for err, fn in (
        (
            UnbalancedEntryError,
            lambda: Entry.of(Leg(A, Direction.DEBIT, _money("100.00")), Leg(B, Direction.CREDIT, _money("80.00"))),
        ),
        (
            UnbalancedEntryError,
            lambda: Entry.of(
                Leg(A, Direction.DEBIT, _money("10.00", "USD")), Leg(B, Direction.CREDIT, _money("10.00", "SGD"))
            ),
        ),
        (DegenerateEntryError, lambda: Entry.of()),
        (DegenerateEntryError, lambda: Entry.of(Leg(A, Direction.DEBIT, _money("10.00")))),
        (UnbalancedEntryError, lambda: Leg(A, Direction.DEBIT, _money("0.00"))),
        (UnbalancedEntryError, lambda: Leg(A, Direction.DEBIT, _money("-1.00"))),
        (TypeError, lambda: Leg(A, "DEBIT", _money("10.00"))),
    ):
        with pytest.raises(err):
            fn()


@pytest.mark.parametrize(
    ("lines", "match"),
    [
        ([make_line(Direction.DEBIT, "100.00"), make_line(Direction.CREDIT, "100.00")], None),
        ([make_line(Direction.DEBIT, "100.00", None), make_line(Direction.CREDIT, "100.00", None)], None),
        ([make_line(Direction.DEBIT, "100.02"), make_line(Direction.CREDIT, "100.00")], "not balanced"),
        ([make_line(Direction.DEBIT, "100.00"), make_line(Direction.CREDIT, "99.98")], "not balanced"),
        ([make_line(Direction.DEBIT, "50.00"), make_line(Direction.DEBIT, "50.00")], "not balanced"),
        ([make_line(Direction.CREDIT, "100.00")], "at least 2 lines"),
        ([], "at least 2 lines"),
        (
            [make_line(Direction.DEBIT, "100.00", "USD"), make_line(Direction.CREDIT, "100.00", "SGD")],
            "fx_rate required for currency USD",
        ),
    ],
)
def test_validate_journal_balance_cases(lines, match) -> None:
    if match is None:
        validate_journal_balance(lines)
    else:
        with pytest.raises(ValidationError, match=match):
            validate_journal_balance(lines)


def test_fx_rates_and_concurrent_validation() -> None:
    validate_fx_rates([make_line(Direction.DEBIT, "100.00", None)])
    with pytest.raises(ValidationError, match="fx_rate required for currency USD"):
        validate_fx_rates(
            [make_line(Direction.DEBIT, "100.00", "USD"), make_line(Direction.CREDIT, "130.00", "SGD", Decimal("1.0"))],
            base_currency="SGD",
        )
    assert Decimal("100.50") + Decimal("50.25") == Decimal("150.75")

    def _worker(worker_id: int) -> bool:
        lines = [
            make_line(Direction.DEBIT, "100.00"),
            make_line(Direction.CREDIT, "100.00" if worker_id % 2 == 0 else "90.00"),
        ]
        try:
            validate_journal_balance(lines)
            return True
        except ValidationError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_worker, range(100)))
    assert results == [idx % 2 == 0 for idx in range(100)]
