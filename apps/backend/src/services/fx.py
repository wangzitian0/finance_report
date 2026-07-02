"""FX rate service for reporting conversions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import ExchangeRate, Money, MoneyError, convert as _money_convert
from src.audit.money.currency import normalize_currency_code
from src.config import settings
from src.models.market_data import FxRate
from src.observability import get_logger

logger = get_logger(__name__)

FxWarning = dict[str, str]


class FxRateError(Exception):
    """Raised when FX rates are unavailable for conversion."""

    pass


@dataclass
class _CacheEntry:
    value: Decimal
    expires_at: datetime
    warning: FxWarning | None = None


class _FxRateCache:
    def __init__(self, ttl_seconds: int = 86_400, max_size: int = 10_000) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_size = max_size
        self._store: dict[str, _CacheEntry] = {}

    def get(self, key: str) -> Decimal | None:
        entry = self._store.get(key)
        if not entry:
            return None
        if entry.expires_at < datetime.now(UTC):
            self._store.pop(key, None)
            return None
        return entry.value

    def get_warning(self, key: str) -> FxWarning | None:
        entry = self._store.get(key)
        if not entry:
            return None
        if entry.expires_at < datetime.now(UTC):
            self._store.pop(key, None)
            return None
        return entry.warning

    def set(self, key: str, value: Decimal, warning: FxWarning | None = None) -> None:
        if len(self._store) >= self._max_size:
            now = datetime.now(UTC)
            self._store = {k: v for k, v in self._store.items() if v.expires_at > now}

            if len(self._store) >= self._max_size:
                num_to_remove = int(self._max_size * 0.2)
                keys = list(self._store.keys())
                for k in keys[:num_to_remove]:
                    self._store.pop(k, None)

        self._store[key] = _CacheEntry(value=value, expires_at=datetime.now(UTC) + self._ttl, warning=warning)


_cache = _FxRateCache()


def clear_fx_cache() -> None:
    """Clear the global FX rate cache (primarily for tests)."""
    _cache._store.clear()


def _append_fx_warning(fx_warnings: list[FxWarning] | None, warning: FxWarning) -> None:
    if fx_warnings is not None and warning not in fx_warnings:
        fx_warnings.append(warning)


def _convert_money_amount(amount: Decimal, source: str, target: str, rate: Decimal) -> Decimal:
    try:
        return _money_convert(Money(amount, source), ExchangeRate(source, target, rate)).amount
    except MoneyError as exc:
        raise FxRateError(f"Invalid FX conversion boundary for {source}/{target}: {exc}") from exc


async def get_exchange_rate(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    rate_date: date,
    *,
    lazy_load: bool = False,
) -> Decimal:
    """Get FX rate for a given date, falling back to the most recent prior rate."""
    base = normalize_currency_code(base_currency)
    quote = normalize_currency_code(quote_currency)

    if base == quote:
        return Decimal("1")

    cache_key = f"fx:{base}:{quote}:{rate_date.isoformat()}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    stmt = (
        select(FxRate.rate)
        .where(FxRate.base_currency == base)
        .where(FxRate.quote_currency == quote)
        .where(FxRate.rate_date <= rate_date)
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    rate = result.scalar_one_or_none()

    if rate is None and lazy_load:
        from src.services.market_data import resolve_missing_fx_rate

        rate = await resolve_missing_fx_rate(db, base, quote, rate_date)

    if rate is None:
        raise FxRateError(f"No FX rate available for {base}/{quote} on {rate_date}")

    if not isinstance(rate, Decimal):
        rate = Decimal(str(rate))

    _cache.set(cache_key, rate)
    return rate


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
    """Get average FX rate over a period, falling back to period-end rate."""
    base = normalize_currency_code(base_currency)
    quote = normalize_currency_code(quote_currency)

    if base == quote:
        return Decimal("1")

    if start_date > end_date:
        raise FxRateError("start_date must be before end_date")

    cache_key = f"fx:{base}:{quote}:{start_date.isoformat()}:{end_date.isoformat()}"
    cached = _cache.get(cache_key)
    if cached is not None:
        cached_warning = _cache.get_warning(cache_key)
        if cached_warning is not None:
            _append_fx_warning(fx_warnings, cached_warning)
        return cached

    stmt = (
        select(func.avg(FxRate.rate))
        .where(FxRate.base_currency == base)
        .where(FxRate.quote_currency == quote)
        .where(FxRate.rate_date >= start_date)
        .where(FxRate.rate_date <= end_date)
    )
    result = await db.execute(stmt)
    avg_rate = result.scalar_one_or_none()

    if avg_rate is None:
        logger.warning(
            "No average FX rate data found for period, falling back to period-end spot rate",
            base_currency=base,
            quote_currency=quote,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        fallback_warning = {
            "type": "average_rate_fallback",
            "base_currency": base,
            "quote_currency": quote,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        _append_fx_warning(fx_warnings, fallback_warning)
        avg_rate = await get_exchange_rate(db, base, quote, end_date, lazy_load=lazy_load)
    elif not isinstance(avg_rate, Decimal):
        avg_rate = Decimal(str(avg_rate))
        fallback_warning = None
    else:
        fallback_warning = None

    _cache.set(cache_key, avg_rate, warning=fallback_warning)
    return avg_rate


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
    """Convert an amount into the target currency using FX rates."""
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
    same-currency conversion is a no-op (returns ``money`` re-stamped in the target
    code), so callers no longer need an ``if currency != base`` branch.
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
    """Convert an amount into the configured base currency."""
    return await convert_amount(
        db,
        amount=amount,
        currency=currency,
        target_currency=settings.base_currency,
        rate_date=rate_date,
    )


class PrefetchedFxRates:
    """Helper to pre-fetch and store FX rates for batch processing."""

    def __init__(self, fx_warnings: list[FxWarning] | None = None, *, lazy_load: bool = False) -> None:
        self._rates: dict[str, Decimal] = {}
        self._fx_warnings = fx_warnings
        self._lazy_load = lazy_load

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

        if average_start and average_end:
            key = f"avg:{base}:{quote}:{average_start.isoformat()}:{average_end.isoformat()}"
        else:
            key = f"spot:{base}:{quote}:{rate_date.isoformat()}"
        return self._rates.get(key)

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
        if average_start and average_end:
            key = f"avg:{base}:{quote}:{average_start.isoformat()}:{average_end.isoformat()}"
        else:
            key = f"spot:{base}:{quote}:{rate_date.isoformat()}"
        self._rates[key] = rate

    async def prefetch(
        self,
        db: AsyncSession,
        pairs: list[tuple[str, str, date, date | None, date | None]],
    ) -> None:
        """Fetch multiple rates into the local prefetch cache."""

        async def _fetch_one(p: tuple[str, str, date, date | None, date | None]) -> None:
            base, quote, r_date, a_start, a_end = p
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

        unique_pairs = list(set(pairs))
        if not unique_pairs:
            return

        for pair in unique_pairs:
            await _fetch_one(pair)
