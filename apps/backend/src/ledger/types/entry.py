"""``Entry`` — the balanced double-entry value object (the ledger's core noun).

The crown-jewel invariant of a double-entry system is *debits == credits*. Today
that invariant lives as a scattered runtime check (``abs(debit - credit) < 0.01``
re-implemented in several services). ``Entry`` makes it a **type**: an entry that
does not balance *per currency* cannot be constructed — :class:`UnbalancedEntryError`
is raised at construction, exactly like :class:`~src.money.Money` rejects ``float``.

This is the *invariant* (a value object), not the *policy*: which account is
debited/credited for a buy/sell/dividend stays in the domain ``ops`` (and the
persistence stays in ``store``). ``Entry`` only guarantees the result balances.

Balance is checked **per currency** (stronger than the legacy currency-blind sum):
for every currency, the sum of debit amounts must equal the sum of credit amounts.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.ledger.types.errors import EmptyEntryError, UnbalancedEntryError
from src.models.journal import Direction
from src.money import Money


@dataclass(frozen=True)
class Leg:
    """One debit or credit line: a positive :class:`Money` amount on an account."""

    account_id: UUID
    direction: Direction
    money: Money
    fx_rate: Decimal | None = None
    event_type: str | None = None
    tags: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.money, Money):
            raise TypeError(f"leg amount must be Money, got {type(self.money).__name__}")
        if not self.money.is_positive():
            raise UnbalancedEntryError(f"leg amount must be positive, got {self.money}")


@dataclass(frozen=True)
class Entry:
    """An immutable, balanced set of legs. Cannot be constructed unbalanced."""

    legs: tuple[Leg, ...] = field(default=())

    def __post_init__(self) -> None:
        if not self.legs:
            raise EmptyEntryError("an entry needs at least two legs")
        net_by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for leg in self.legs:
            code = leg.money.currency.code
            if leg.direction == Direction.DEBIT:
                net_by_currency[code] += leg.money.amount
            else:
                net_by_currency[code] -= leg.money.amount
        unbalanced = {c: n for c, n in net_by_currency.items() if n != 0}
        if unbalanced:
            raise UnbalancedEntryError(f"entry does not balance per currency: {unbalanced}")

    @classmethod
    def of(cls, *legs: Leg) -> Entry:
        """Build an entry from explicit legs (validates balance)."""
        return cls(tuple(legs))

    @classmethod
    def transfer(
        cls,
        *,
        debit: UUID,
        credit: UUID,
        money: Money,
        fx_rate: Decimal | None = None,
        event_type: str | None = None,
        tags: dict[str, Any] | None = None,
    ) -> Entry:
        """The common two-leg case: move ``money`` from ``credit`` to ``debit``."""
        return cls.of(
            Leg(debit, Direction.DEBIT, money, fx_rate, event_type, tags),
            Leg(credit, Direction.CREDIT, money, fx_rate, event_type, tags),
        )
