"""``get_exchange_rate`` + the ``convert_*`` trio — the FX-specific lookup services.

Thin: the identity rate (a currency against itself is always exactly 1, a
business rule that doesn't belong in the subject-agnostic ``resolve()``) is
handled here, then the general ``PriceableSubject`` + ``resolve()`` path
takes over — no FX-specific storage or resolution logic duplicated.
``convert_amount``/``convert_money``/``convert_to_base`` are thin lookup+math
bridges: the lookup is ``get_exchange_rate`` above, the math is
``audit.money.convert`` (rate passed in, per boundary ruling 5 — audit never
looks up a rate).

The ``lazy_load`` crawler fallback (``services/fx.py`` parity) lives here now:
the crawler moved into this package (``extension/market_data/``), so a rate
miss with ``lazy_load=True`` falls back to
:func:`~src.pricing.extension.market_data.service.resolve_missing_fx_rate`
(safe inverse/bridge derivation, then an optional provider fetch) — the
behavior the portfolio read-side queries depend on (#1641/#1643).

Deliberately NOT carried over from ``services/fx.py``:

- **Caching** — ``fx.py``'s ``_FxRateCache`` is a performance optimization,
  not a correctness requirement; adding one here is deferred until this
  function is actually load-tested in its new home (move first, improve
  second).
- **``fx_warnings``** — ``fx.py``'s side-channel that lets a caller learn it
  got the period-end fallback instead of a true average. Deferred until a
  real (repointed) caller needs to surface it; adding an unused parameter
  now would be speculative.
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
    *,
    lazy_load: bool = False,
) -> Decimal:
    """The resolved FX rate for ``base_currency``/``quote_currency`` as of ``rate_date``.

    With ``lazy_load=True`` a miss first falls back to the in-package crawler
    (``resolve_missing_fx_rate``: stored inverse/bridge derivation, then an
    optional provider fetch — persisting what it finds), preserving the
    retired ``services/fx.py`` lazy path's behavior. Raises
    :class:`~src.pricing.base.errors.NoObservationError` (propagated from
    ``resolve()``) when no eligible observation exists even after the
    fallback — never returns a silently-wrong rate.
    """
    base = normalize_currency_code(base_currency)
    quote = normalize_currency_code(quote_currency)
    if base == quote:
        return Decimal("1")

    subject = PriceableSubject.currency_pair(base, quote)
    repo = SqlObservationRepository(db)
    candidates = await repo.candidates(subject, rate_date)
    if not candidates and lazy_load:
        # Deferred import: market_data composes this module's siblings, so a
        # module-level import would be a cycle waiting to happen.
        from src.pricing.extension.market_data.service import resolve_missing_fx_rate

        rate = await resolve_missing_fx_rate(db, base, quote, rate_date)
        if rate is not None:
            return rate if isinstance(rate, Decimal) else Decimal(str(rate))
    observation = resolve(subject, rate_date, ResolutionPolicy(), candidates)
    return observation.value


async def get_average_rate(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> Decimal:
    """The mean rate observed in ``[start_date, end_date]``, falling back to
    ``get_exchange_rate(end_date)`` when nothing was observed in the range.

    Computed over the repository's own candidates (not a separate SQL AVG
    query) — the repository's one job stays "what observations exist"; the
    averaging is pricing's own business logic, same as ``resolve()``.
    """
    base = normalize_currency_code(base_currency)
    quote = normalize_currency_code(quote_currency)
    if base == quote:
        return Decimal("1")
    if start_date > end_date:
        raise PricingError("start_date must be on or before end_date")

    subject = PriceableSubject.currency_pair(base, quote)
    repo = SqlObservationRepository(db)
    candidates = await repo.candidates(subject, end_date)
    in_range = [c.value for c in candidates if c.as_of >= start_date]
    if not in_range:
        return await get_exchange_rate(db, base, quote, end_date)
    return sum(in_range) / len(in_range)


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
    *,
    lazy_load: bool = False,
) -> Decimal:
    """Convert ``amount`` into ``target_currency`` using the resolved rate as of ``rate_date``."""
    source = normalize_currency_code(currency)
    target = normalize_currency_code(target_currency)
    if source == target:
        return amount
    rate = await get_exchange_rate(db, source, target, rate_date, lazy_load=lazy_load)
    return _convert_money_amount(amount, source, target, rate)


async def convert_money(
    db: AsyncSession,
    money: Money,
    target_currency: str,
    rate_date: date,
    *,
    lazy_load: bool = False,
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
        lazy_load=lazy_load,
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
