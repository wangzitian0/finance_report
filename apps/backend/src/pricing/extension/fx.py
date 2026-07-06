"""``get_exchange_rate`` — the FX-specific lookup service.

Thin: the identity rate (a currency against itself is always exactly 1, a
business rule that doesn't belong in the subject-agnostic ``resolve()``) is
handled here, then the general ``PriceableSubject`` + ``resolve()`` path
takes over — no FX-specific storage or resolution logic duplicated.

Deliberately NOT carried over from ``services/fx.py`` yet:

- **Caching** — ``fx.py``'s ``_FxRateCache`` is a performance optimization,
  not a correctness requirement; adding one here is deferred until this
  function is actually load-tested in its new home (move first, improve
  second).
- **``lazy_load`` crawler fallback** — ``fx.py``'s ``lazy_load=True`` calls
  into ``market_data.resolve_missing_fx_rate``, which hasn't moved into
  pricing yet (``sync_market_data`` is still a reserved unit). Adding it here
  would either duplicate the crawler call or reach back into the old
  ``services/market_data`` module, which this package must not depend on.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money.currency import normalize_currency_code
from src.pricing.base.policy import ResolutionPolicy
from src.pricing.base.subject import PriceableSubject
from src.pricing.extension.repository import SqlObservationRepository
from src.pricing.extension.resolve import resolve


async def get_exchange_rate(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    rate_date: date,
) -> Decimal:
    """The resolved FX rate for ``base_currency``/``quote_currency`` as of ``rate_date``.

    Raises :class:`~src.pricing.base.errors.NoObservationError` (propagated
    from ``resolve()``) when no eligible observation exists — never returns
    a silently-wrong rate.
    """
    base = normalize_currency_code(base_currency)
    quote = normalize_currency_code(quote_currency)
    if base == quote:
        return Decimal("1")

    subject = PriceableSubject.currency_pair(base, quote)
    repo = SqlObservationRepository(db)
    candidates = await repo.candidates(subject, rate_date)
    observation = resolve(subject, rate_date, ResolutionPolicy(), candidates)
    return observation.value
