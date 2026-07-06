"""``get_exchange_rate`` + the ``convert_*`` trio — the FX-specific lookup services.

Thin: the identity rate (a currency against itself is always exactly 1, a
business rule that doesn't belong in the subject-agnostic ``resolve()``) is
handled here, then the general ``PriceableSubject`` + ``resolve()`` path
takes over — no FX-specific storage or resolution logic duplicated.
``convert_amount``/``convert_money``/``convert_to_base`` are thin lookup+math
bridges: the lookup is ``get_exchange_rate`` above, the math is
``audit.money.convert`` (rate passed in, per boundary ruling 5 — audit never
looks up a rate).

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
- **The average-rate variant** (``fx.py``'s ``average_start``/``average_end``,
  backed by ``get_average_rate``) — that function hasn't been ported to
  pricing yet either. Callers that need it stay on ``services/fx.py`` until
  it is.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.audit import ExchangeRate, Money, MoneyError, convert as _money_convert, normalize_currency_code
from src.pricing.base.errors import PricingError
from src.pricing.base.policy import ResolutionPolicy
from src.pricing.base.subject import PriceableSubject
from src.pricing.extension.repository import SqlObservationRepository
from src.pricing.extension.resolve import resolve

# Bound from the bare published root (config publishes no named symbols).
settings = src.config.settings


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


def _convert_money_amount(amount: Decimal, source: str, target: str, rate: Decimal) -> Decimal:
    try:
        return _money_convert(Money(amount, source), ExchangeRate(source, target, rate)).amount
    except MoneyError as exc:
        raise PricingError(f"invalid FX conversion boundary for {source}/{target}: {exc}") from exc


async def convert_amount(
    db: AsyncSession,
    amount: Decimal,
    currency: str,
    target_currency: str,
    rate_date: date,
) -> Decimal:
    """Convert ``amount`` into ``target_currency`` using the resolved rate as of ``rate_date``."""
    source = normalize_currency_code(currency)
    target = normalize_currency_code(target_currency)
    if source == target:
        return amount
    rate = await get_exchange_rate(db, source, target, rate_date)
    return _convert_money_amount(amount, source, target, rate)


async def convert_money(
    db: AsyncSession,
    money: Money,
    target_currency: str,
    rate_date: date,
) -> Money:
    """Money-native FX conversion: ``Money(source) -> Money(target)``.

    Thin typed wrapper over :func:`convert_amount` so business code stays in
    ``Money`` across the FX boundary instead of unwrapping to ``Decimal``. A
    same-currency conversion is a no-op (returns ``money`` re-stamped in the
    target code), so callers no longer need an ``if currency != base`` branch.
    """
    converted = await convert_amount(
        db,
        amount=money.amount,
        currency=money.currency.code,
        target_currency=target_currency,
        rate_date=rate_date,
    )
    return Money(converted, target_currency)


async def convert_to_base(
    db: AsyncSession,
    amount: Decimal,
    currency: str,
    rate_date: date,
) -> Decimal:
    """Convert ``amount`` into the configured base currency."""
    return await convert_amount(
        db,
        amount=amount,
        currency=currency,
        target_currency=settings.base_currency,
        rate_date=rate_date,
    )
