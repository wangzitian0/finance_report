"""``PriceableSubject`` — the unified identity for "the thing being priced".

Unifies the 3 key vocabularies the pre-cutover tables used independently:
``FxRate`` keyed on a currency pair, ``StockPrice`` keyed on a symbol,
``ManualValuationSnapshot``/``MarketDataOverride`` keyed on a component or
asset identifier. A ``PriceableSubject`` is one of exactly three kinds; the
mapping from a legacy key to a subject must be injective (no two legacy keys
collide on the same subject) — proven at migration time (AC-pricing.subject.1).

Per boundary ruling 6 (#1610): the dual-listing question (the same equity
under two ticker symbols) is deliberately NOT collapsed here. Each listing is
its own ``SECURITY`` subject; an alias/equivalence mapping is future
package-internal work, not a re-cutover.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.pricing.base.errors import InvalidSubjectError


class SubjectKind(StrEnum):
    """The three subject shapes a pre-cutover key vocabulary mapped to."""

    CURRENCY_PAIR = "currency_pair"
    SECURITY = "security"
    COMPONENT = "component"


@dataclass(frozen=True, slots=True)
class PriceableSubject:
    """An identity for "the thing being priced" — one of the three kinds.

    - ``CURRENCY_PAIR``: ``key`` is ``"{base}/{quote}"`` (e.g. ``"USD/SGD"``),
      both upper-cased ISO-4217 codes (was ``FxRate.base_currency``/``quote_currency``).
    - ``SECURITY``: ``key`` is the provider symbol (was ``StockPrice.symbol``).
    - ``COMPONENT``: ``key`` is the manual-valuation component identifier (was
      ``ManualValuationSnapshot.component_type`` / ``MarketDataOverride.asset_identifier``).
    """

    kind: SubjectKind
    key: str

    def __post_init__(self) -> None:
        if not self.key or not self.key.strip():
            raise InvalidSubjectError(f"{self.kind} subject key must be non-empty")
        if self.kind is SubjectKind.CURRENCY_PAIR:
            parts = self.key.split("/")
            if len(parts) != 2 or not all(len(p) == 3 and p.isalpha() for p in parts):
                raise InvalidSubjectError(
                    f"currency_pair subject key must be '{{3-letter}}/{{3-letter}}', got {self.key!r}"
                )

    @classmethod
    def currency_pair(cls, base: str, quote: str) -> PriceableSubject:
        return cls(SubjectKind.CURRENCY_PAIR, f"{base.upper()}/{quote.upper()}")

    @classmethod
    def security(cls, symbol: str) -> PriceableSubject:
        return cls(SubjectKind.SECURITY, symbol)

    @classmethod
    def component(cls, identifier: str) -> PriceableSubject:
        return cls(SubjectKind.COMPONENT, identifier)
