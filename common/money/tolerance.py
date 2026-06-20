"""``MoneyTolerance`` — a typed absolute+relative tolerance for money matching.

The recurring reconciliation/balance pattern is ``abs(a - b) <= max(absolute,
amount * percent)``. ``MoneyTolerance`` owns that comparison as one value so call
sites stop hand-rolling ``max(...)`` and ``abs(...) < Decimal("0.01")``.

It is a *comparison primitive*, not a policy: which absolute/percent to use stays
with the caller (e.g. reconciliation config); ``MoneyTolerance`` only decides
whether two amounts are within the given band.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from common.money.money import Money
from common.ratio import Ratio

_ScaleInput = Decimal | int


@dataclass(frozen=True)
class MoneyTolerance:
    """An absolute floor plus an optional relative band, both currency-aware."""

    absolute: Money
    relative: Ratio = field(default=Ratio.zero())

    def threshold_for(self, expected: Money) -> Money:
        """The allowed deviation around ``expected``: ``max(absolute, relative*|expected|)``."""
        relative_band = abs(expected) * self.relative.value
        return max(self.absolute, relative_band)

    def holds(self, actual: Money, expected: Money) -> bool:
        """True when ``actual`` is within tolerance of ``expected``."""
        return abs(actual - expected) <= self.threshold_for(expected)

    def scaled(self, factor: _ScaleInput) -> MoneyTolerance:
        """Widen (or narrow) the whole band by a dimensionless factor."""
        return MoneyTolerance(self.absolute * factor, self.relative * factor)
