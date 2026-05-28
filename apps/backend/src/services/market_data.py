"""Market data lookup helpers for report-side FX resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.logger import get_logger
from src.models import FxRate

logger = get_logger(__name__)

_RATE_QUANT = Decimal("0.000001")
_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}=X"


@dataclass(frozen=True)
class FxRateObservation:
    """Resolved FX rate observation from a provider or derivation path."""

    base_currency: str
    quote_currency: str
    rate: Decimal
    rate_date: date
    source: str


@dataclass(frozen=True)
class _StoredFxRate:
    rate: Decimal
    rate_date: date
    source: str


def _normalize_currency(code: str) -> str:
    return code.strip().upper()


def _quantize_rate(rate: Decimal) -> Decimal:
    return rate.quantize(_RATE_QUANT, rounding=ROUND_HALF_UP)


def _date_to_epoch(value: date) -> int:
    return int(datetime.combine(value, time.min, tzinfo=UTC).timestamp())


async def _load_stored_rate(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> _StoredFxRate | None:
    stmt = (
        select(FxRate.rate, FxRate.rate_date, FxRate.source)
        .where(FxRate.base_currency == base_currency)
        .where(FxRate.quote_currency == quote_currency)
        .where(FxRate.rate_date <= requested_date)
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        return None
    rate = row.rate if isinstance(row.rate, Decimal) else Decimal(str(row.rate))
    return _StoredFxRate(rate=_quantize_rate(rate), rate_date=row.rate_date, source=row.source)


async def _load_stored_direct_or_inverse(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> FxRateObservation | None:
    direct = await _load_stored_rate(db, base_currency, quote_currency, requested_date)
    if direct is not None:
        return FxRateObservation(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=direct.rate,
            rate_date=direct.rate_date,
            source=direct.source,
        )

    inverse = await _load_stored_rate(db, quote_currency, base_currency, requested_date)
    if inverse is None:
        return None

    return FxRateObservation(
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate=_quantize_rate(Decimal("1") / inverse.rate),
        rate_date=inverse.rate_date,
        source=f"derived:inverse:{quote_currency}/{base_currency}",
    )


async def _derive_from_bridge_rates(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    requested_date: date,
    bridge_currency: str,
) -> FxRateObservation | None:
    bridge = _normalize_currency(bridge_currency)
    if bridge in {base_currency, quote_currency}:
        return None

    base_to_bridge = await _load_stored_direct_or_inverse(db, base_currency, bridge, requested_date)
    bridge_to_quote = await _load_stored_direct_or_inverse(db, bridge, quote_currency, requested_date)
    if base_to_bridge is None or bridge_to_quote is None:
        return None

    return FxRateObservation(
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate=_quantize_rate(base_to_bridge.rate * bridge_to_quote.rate),
        rate_date=max(base_to_bridge.rate_date, bridge_to_quote.rate_date),
        source=f"derived:bridge:{bridge}",
    )


async def _persist_fx_rate(db: AsyncSession, observation: FxRateObservation) -> Decimal:
    base = _normalize_currency(observation.base_currency)
    quote = _normalize_currency(observation.quote_currency)
    rate = _quantize_rate(observation.rate)

    existing = await _load_stored_rate(db, base, quote, observation.rate_date)
    if existing is not None and existing.rate_date == observation.rate_date:
        return existing.rate

    db.add(
        FxRate(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            rate_date=observation.rate_date,
            source=observation.source[:50],
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        concurrent = await _load_stored_rate(db, base, quote, observation.rate_date)
        if concurrent is not None and concurrent.rate_date == observation.rate_date:
            return concurrent.rate
        raise
    logger.info(
        "Persisted lazy FX rate",
        base_currency=base,
        quote_currency=quote,
        rate_date=observation.rate_date.isoformat(),
        source=observation.source[:50],
    )
    return rate


async def resolve_missing_fx_rate(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> Decimal | None:
    """Resolve a missing report FX rate through safe derivation or provider fetch."""
    base = _normalize_currency(base_currency)
    quote = _normalize_currency(quote_currency)
    if base == quote:
        return Decimal("1")

    direct_or_inverse = await _load_stored_direct_or_inverse(db, base, quote, requested_date)
    if direct_or_inverse is not None:
        if direct_or_inverse.source.startswith("derived:inverse:"):
            return await _persist_fx_rate(db, direct_or_inverse)
        return direct_or_inverse.rate

    bridge = await _derive_from_bridge_rates(
        db,
        base,
        quote,
        requested_date,
        settings.market_data_fx_bridge_currency,
    )
    if bridge is not None:
        return await _persist_fx_rate(db, bridge)

    if not settings.market_data_lazy_fetch_enabled:
        return None

    provider_observation = await _fetch_yahoo_or_derived_fx_rate(base, quote, requested_date)
    if provider_observation is not None:
        return await _persist_fx_rate(db, provider_observation)

    return None


async def _fetch_yahoo_or_derived_fx_rate(
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> FxRateObservation | None:
    direct = await _fetch_yahoo_fx_rate(base_currency, quote_currency, requested_date)
    if direct is not None:
        return direct

    inverse = await _fetch_yahoo_fx_rate(quote_currency, base_currency, requested_date)
    if inverse is not None:
        return FxRateObservation(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=_quantize_rate(Decimal("1") / inverse.rate),
            rate_date=inverse.rate_date,
            source="yahoo_finance:inverse",
        )

    bridge = _normalize_currency(settings.market_data_fx_bridge_currency)
    if bridge in {base_currency, quote_currency}:
        return None
    base_to_bridge = await _fetch_yahoo_fx_rate(base_currency, bridge, requested_date)
    bridge_to_quote = await _fetch_yahoo_fx_rate(bridge, quote_currency, requested_date)
    if base_to_bridge is None or bridge_to_quote is None:
        return None

    return FxRateObservation(
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate=_quantize_rate(base_to_bridge.rate * bridge_to_quote.rate),
        rate_date=max(base_to_bridge.rate_date, bridge_to_quote.rate_date),
        source=f"yahoo_finance:bridge:{bridge}",
    )


async def _fetch_yahoo_fx_rate(
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> FxRateObservation | None:
    """Fetch the latest Yahoo Finance FX close on or before the requested date."""
    symbol = f"{base_currency}{quote_currency}"
    start = requested_date - timedelta(days=7)
    end = requested_date + timedelta(days=1)
    params = {
        "period1": str(_date_to_epoch(start)),
        "period2": str(_date_to_epoch(end)),
        "interval": "1d",
    }
    headers = {"User-Agent": "finance-report-audit/1.0"}
    url = _YAHOO_CHART_URL.format(symbol=symbol)

    try:
        async with httpx.AsyncClient(timeout=settings.market_data_yahoo_timeout_seconds, headers=headers) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "Yahoo Finance FX fetch failed",
            base_currency=base_currency,
            quote_currency=quote_currency,
            requested_date=requested_date.isoformat(),
            error=str(exc),
        )
        return None

    return _parse_yahoo_fx_response(response.json(), base_currency, quote_currency, requested_date)


def _parse_yahoo_fx_response(
    payload: dict[str, Any],
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> FxRateObservation | None:
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return None

    result = results[0]
    timestamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []

    observations: list[FxRateObservation] = []
    for timestamp, close in zip(timestamps, closes, strict=False):
        if close is None:
            continue
        observed_date = datetime.fromtimestamp(int(timestamp), UTC).date()
        if observed_date > requested_date:
            continue
        observations.append(
            FxRateObservation(
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate=_quantize_rate(Decimal(str(close))),
                rate_date=observed_date,
                source="yahoo_finance",
            )
        )

    if not observations:
        return None
    return max(observations, key=lambda item: item.rate_date)
