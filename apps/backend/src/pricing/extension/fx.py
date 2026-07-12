"""``get_exchange_rate`` + the ``convert_*`` trio — the FX-specific lookup services.

The single FX lookup implementation (#1610 P2 absorbed ``services/fx.py`` —
that module is retired; every consumer resolves rates through this package's
published surface). Thin: the identity rate (a currency against itself is
always exactly 1, a business rule that doesn't belong in the subject-agnostic
``resolve()``) is handled here, then the general ``PriceableSubject`` +
``resolve()`` path takes over — no FX-specific storage or resolution logic
duplicated. ``convert_amount``/``convert_money``/``convert_to_base`` are thin
lookup+math bridges: the lookup is ``get_exchange_rate``/``get_average_rate``
above, the math is ``audit.money.convert`` (rate passed in, per boundary
ruling 5 — audit never looks up a rate).

Carried over from ``services/fx.py`` for its repointed consumers:

- **``lazy_load`` crawler fallback** — a rate miss with ``lazy_load=True``
  falls back to
  :func:`~src.pricing.extension.market_data.service.resolve_missing_fx_rate`
  (safe inverse/bridge derivation, then an optional provider fetch) — the
  behavior the portfolio read-side queries depend on (#1641/#1643).
- **``fx_warnings`` side-channel** (AC-pricing.fx.1) — the caller learns it
  got the period-end spot fallback instead of a true average; reporting
  surfaces these warnings on the generated report payloads.
- **Average-rate windows on the ``convert_*`` trio** (AC-pricing.fx.3) — the
  income-statement convention converts flows at the period-average rate.
- **``PrefetchedFxRates``** (AC-pricing.fx.2) — the explicit batch-prefetch
  cache the report builders use to avoid per-line lookups.

Deliberately NOT carried over: the in-process TTL ``_FxRateCache`` — a
performance optimization, not a correctness requirement; adding one here is
deferred until this function is actually load-tested in its new home (move
first, improve second). ``PrefetchedFxRates`` covers the hot batch paths.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.audit import ExchangeRate, Money, MoneyError, convert as _money_convert, normalize_currency_code
from src.observability import get_logger
from src.pricing.base.errors import NoObservationError, PricingError
from src.pricing.base.policy import ResolutionPolicy
from src.pricing.base.subject import PriceableSubject
from src.pricing.extension.repository import SqlObservationRepository
from src.pricing.extension.resolve import resolve

# Bound from the bare published root (config publishes no named symbols).
settings = src.config.settings

logger = get_logger(__name__)

#: A structured, JSON-serializable FX degradation notice (e.g. the
#: average-rate period-end fallback) reports surface to their consumers.
FxWarning = dict[str, str]


def _append_fx_warning(fx_warnings: list[FxWarning] | None, warning: FxWarning) -> None:
    if fx_warnings is not None and warning not in fx_warnings:
        fx_warnings.append(warning)


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
    try:
        observation = resolve(subject, rate_date, ResolutionPolicy(), candidates)
    except NoObservationError as exc:
        # Same type, FX-specific message: the ``services/fx.py`` wording the
        # report error surfaces (and their tests) rely on.
        raise NoObservationError(f"No FX rate available for {base}/{quote} on {rate_date}") from exc
    return observation.value


async def get_average_rate(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
    *,
    fx_warnings: list[FxWarning] | None = None,
    lazy_load: bool = False,
) -> Decimal:
    """The mean rate observed in ``[start_date, end_date]``, falling back to
    ``get_exchange_rate(end_date)`` when nothing was observed in the range.

    Computed over the repository's own candidates (not a separate SQL AVG
    query) — the repository's one job stays "what observations exist"; the
    averaging is pricing's own business logic, same as ``resolve()``. The
    period-end fallback is surfaced through ``fx_warnings``
    (AC-pricing.fx.1) so a report can tell its consumer the average was
    unavailable.
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
        logger.warning(
            "No average FX rate data found for period, falling back to period-end spot rate",
            base_currency=base,
            quote_currency=quote,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        _append_fx_warning(
            fx_warnings,
            {
                "type": "average_rate_fallback",
                "base_currency": base,
                "quote_currency": quote,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        return await get_exchange_rate(db, base, quote, end_date, lazy_load=lazy_load)
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
    average_start: date | None = None,
    average_end: date | None = None,
    fx_warnings: list[FxWarning] | None = None,
    lazy_load: bool = False,
) -> Decimal:
    """Convert ``amount`` into ``target_currency`` using the resolved rate.

    With both ``average_start`` and ``average_end`` set, the period-average
    rate is used instead of the ``rate_date`` spot rate (AC-pricing.fx.3 —
    the income-statement convention), with the same period-end fallback +
    ``fx_warnings`` semantics as :func:`get_average_rate`.
    """
    source = normalize_currency_code(currency)
    target = normalize_currency_code(target_currency)
    if source == target:
        return amount
    if average_start and average_end:
        rate = await get_average_rate(
            db,
            source,
            target,
            average_start,
            average_end,
            fx_warnings=fx_warnings,
            lazy_load=lazy_load,
        )
    else:
        rate = await get_exchange_rate(db, source, target, rate_date, lazy_load=lazy_load)
    return _convert_money_amount(amount, source, target, rate)


async def convert_money(
    db: AsyncSession,
    money: Money,
    target_currency: str,
    rate_date: date,
    *,
    average_start: date | None = None,
    average_end: date | None = None,
    fx_warnings: list[FxWarning] | None = None,
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
        average_start=average_start,
        average_end=average_end,
        fx_warnings=fx_warnings,
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


class PrefetchedFxRates:
    """Explicit batch-prefetch cache for report builders (AC-pricing.fx.2).

    The report builders (net worth, cash flow, income statement) resolve the
    same handful of pairs for hundreds of lines; they prefetch once and read
    from this local map instead of hitting the resolver per line. This is the
    deliberate replacement for the retired ``services/fx.py`` global TTL
    cache: scope-local, explicit, and dropped with the report request.
    """

    def __init__(self, fx_warnings: list[FxWarning] | None = None, *, lazy_load: bool = False) -> None:
        self._rates: dict[str, Decimal] = {}
        self._fx_warnings = fx_warnings
        self._lazy_load = lazy_load

    @staticmethod
    def _key(
        base: str,
        quote: str,
        rate_date: date,
        average_start: date | None,
        average_end: date | None,
    ) -> str:
        if average_start and average_end:
            return f"avg:{base}:{quote}:{average_start.isoformat()}:{average_end.isoformat()}"
        return f"spot:{base}:{quote}:{rate_date.isoformat()}"

    def get_rate(
        self,
        base: str,
        quote: str,
        rate_date: date,
        average_start: date | None = None,
        average_end: date | None = None,
    ) -> Decimal | None:
        base = normalize_currency_code(base)
        quote = normalize_currency_code(quote)
        if base == quote:
            return Decimal("1")
        return self._rates.get(self._key(base, quote, rate_date, average_start, average_end))

    def set_rate(
        self,
        base: str,
        quote: str,
        rate_date: date,
        rate: Decimal,
        average_start: date | None = None,
        average_end: date | None = None,
    ) -> None:
        base = normalize_currency_code(base)
        quote = normalize_currency_code(quote)
        self._rates[self._key(base, quote, rate_date, average_start, average_end)] = rate

    async def prefetch(
        self,
        db: AsyncSession,
        pairs: list[tuple[str, str, date, date | None, date | None]],
    ) -> None:
        """Fetch multiple rates into the local prefetch cache.

        Sequential on purpose: all fetches share one ``AsyncSession``, which
        must not be used concurrently. A miss propagates the pricing error
        family — never a silent partial cache.
        """
        unique_pairs = list(set(pairs))
        if not unique_pairs:
            return

        for base, quote, r_date, a_start, a_end in unique_pairs:
            if a_start and a_end:
                rate = await get_average_rate(
                    db,
                    base,
                    quote,
                    a_start,
                    a_end,
                    fx_warnings=self._fx_warnings,
                    lazy_load=self._lazy_load,
                )
            else:
                rate = await get_exchange_rate(db, base, quote, r_date, lazy_load=self._lazy_load)
            self.set_rate(base, quote, r_date, rate, a_start, a_end)
