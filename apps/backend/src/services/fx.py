"""FX rate service for reporting conversions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy.orm import selectinload\nfrom sqlalchemy.orm import selectinload

from src.config import settings
from src.models import FxRate


class FxRateError(Exception):
    """Raised when FX rates are unavailable for conversion."""

    pass


@dataclass
class _CacheEntry:
    value: Decimal
    expires_at: datetime


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

    def set(self, key: str, value: Decimal) -> None:
        if len(self._store) >= self._max_size:
            now = datetime.now(UTC)
            self._store = {k: v for k, v in self._store.items() if v.expires_at > now}

            if len(self._store) >= self._max_size:
                num_to_remove = int(self._max_size * 0.2)
                keys = list(self._store.keys())
                for k in keys[:num_to_remove]:
                    self._store.pop(k, None)

        self._store[key] = _CacheEntry(value=value, expires_at=datetime.now(UTC) + self._ttl)


_cache = _FxRateCache()


def clear_fx_cache() -> None:
    """Clear the global FX rate cache (primarily for tests)."""
    _cache._store.clear()


def _normalize_currency(code: str) -> str:
    return code.strip().upper()


async def get_exchange_rate(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    rate_date: date,
) -> Decimal:
    """Get FX rate for a given date, falling back to the most recent prior rate."""
    base = _normalize_currency(base_currency)
    quote = _normalize_currency(quote_currency)

    if base == quote:
        return Decimal("1")

    cache_key = f"fx:{base}:{quote}:{rate_date.isoformat()}"
    cached = _cache.get(cache_key)
    if cached:
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
) -> Decimal:
    """Get average FX rate over a period, falling back to period-end rate."""
    base = _normalize_currency(base_currency)
    quote = _normalize_currency(quote_currency)

    if base == quote:
        return Decimal("1")

    if start_date > end_date:
        raise FxRateError("start_date must be before end_date")

    cache_key = f"fx:{base}:{quote}:{start_date.isoformat()}:{end_date.isoformat()}"
    cached = _cache.get(cache_key)
    if cached:
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
        avg_rate = await get_exchange_rate(db, base, quote, end_date)
    elif not isinstance(avg_rate, Decimal):
        avg_rate = Decimal(str(avg_rate))

    _cache.set(cache_key, avg_rate)
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
) -> Decimal:
    """Convert an amount into the target currency using FX rates."""
    source = _normalize_currency(currency)
    target = _normalize_currency(target_currency)

    if source == target:
        return amount

    if average_start and average_end:
        rate = await get_average_rate(db, source, target, average_start, average_end)
    else:
        rate = await get_exchange_rate(db, source, target, rate_date)

    return amount * rate


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

    def __init__(self) -> None:
        self._rates: dict[str, Decimal] = {}

    def get_rate(
        self,
        base: str,
        quote: str,
        rate_date: date,
        average_start: date | None = None,
        average_end: date | None = None,
    ) -> Decimal | None:
        base = _normalize_currency(base)
        quote = _normalize_currency(quote)
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
        base = _normalize_currency(base)
        quote = _normalize_currency(quote)
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
        """Fetch multiple rates in parallel or batch if possible."""
        import asyncio

        async def _fetch_one(p: tuple[str, str, date, date | None, date | None]) -> None:
            base, quote, r_date, a_start, a_end = p
            if a_start and a_end:
                rate = await get_average_rate(db, base, quote, a_start, a_end)
            else:
                rate = await get_exchange_rate(db, base, quote, r_date)
            self.set_rate(base, quote, r_date, rate, a_start, a_end)

        unique_pairs = list(set(pairs))
        if not unique_pairs:
            return

        try:
            async with asyncio.TaskGroup() as tg:
                for p in unique_pairs:
                    tg.create_task(_fetch_one(p))
        except ExceptionGroup as eg:
            # Propagate the first FxRateError if present
            for exc in eg.exceptions:
                if isinstance(exc, FxRateError):
                    raise exc
            raise
