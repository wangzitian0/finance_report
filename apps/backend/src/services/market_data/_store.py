"""DB load/persist."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.market_data import FxRate, MarketDataSyncState, StockPrice
from src.services.market_data._base import (
    _FRESHNESS_THRESHOLD,
    logger,
)
from src.services.market_data._types import (
    FxRateObservation,
    MarketDataScopeStatus,
    StockPriceObservation,
    _StoredFxRate,
    _StoredStockPrice,
)
from src.services.market_data._util import (
    _normalize_currency,
    _normalize_symbol,
    _normalize_utc,
    _parse_fx_pair,
    _quantize_price,
    _quantize_rate,
)


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


async def _load_stored_rate_on_date(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> _StoredFxRate | None:
    stored = await _load_stored_rate(db, base_currency, quote_currency, requested_date)
    if stored is None or stored.rate_date != requested_date:
        return None
    return stored


async def _latest_fx_rate_date(db: AsyncSession, base_currency: str, quote_currency: str) -> date | None:
    return await db.scalar(
        select(func.max(FxRate.rate_date))
        .where(FxRate.base_currency == base_currency)
        .where(FxRate.quote_currency == quote_currency)
    )


async def _stored_fx_rate_dates(
    db: AsyncSession,
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> set[date]:
    result = await db.execute(
        select(FxRate.rate_date)
        .where(FxRate.base_currency == base_currency)
        .where(FxRate.quote_currency == quote_currency)
        .where(FxRate.rate_date >= start_date)
        .where(FxRate.rate_date <= end_date)
    )
    return {row[0] for row in result.all()}


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

    existing = await _load_stored_rate_on_date(db, base, quote, observation.rate_date)
    if existing is not None:
        return existing.rate

    try:
        async with db.begin_nested():
            db.add(
                FxRate(
                    base_currency=base,
                    quote_currency=quote,
                    rate=rate,
                    rate_date=observation.rate_date,
                    source=observation.source[:50],
                )
            )
            await db.flush()
    except IntegrityError:
        concurrent = await _load_stored_rate_on_date(db, base, quote, observation.rate_date)
        if concurrent is not None:
            return concurrent.rate
        raise
    logger.info(
        "Persisted FX rate",
        base_currency=base,
        quote_currency=quote,
        rate_date=observation.rate_date.isoformat(),
        source=observation.source[:50],
    )
    return rate


async def _load_stored_stock_price(
    db: AsyncSession,
    symbol: str,
    requested_date: date,
) -> _StoredStockPrice | None:
    normalized = _normalize_symbol(symbol)
    stmt = (
        select(StockPrice.price, StockPrice.currency, StockPrice.price_date, StockPrice.source)
        .where(StockPrice.symbol == normalized)
        .where(StockPrice.price_date <= requested_date)
        .order_by(
            StockPrice.price_date.desc(),
            StockPrice.created_at.desc(),
            StockPrice.source.asc(),
            StockPrice.currency.asc(),
            StockPrice.id.asc(),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        return None
    price = row.price if isinstance(row.price, Decimal) else Decimal(str(row.price))
    return _StoredStockPrice(
        price=_quantize_price(price),
        currency=_normalize_currency(row.currency),
        price_date=row.price_date,
        source=row.source,
    )


async def _load_stored_stock_price_on_date(
    db: AsyncSession,
    symbol: str,
    requested_date: date,
) -> _StoredStockPrice | None:
    stored = await _load_stored_stock_price(db, symbol, requested_date)
    if stored is None or stored.price_date != requested_date:
        return None
    return stored


async def _latest_stock_price_date(db: AsyncSession, symbol: str) -> date | None:
    return await db.scalar(
        select(func.max(StockPrice.price_date)).where(StockPrice.symbol == _normalize_symbol(symbol))
    )


async def _stored_stock_price_dates(
    db: AsyncSession,
    symbol: str,
    start_date: date,
    end_date: date,
) -> set[date]:
    result = await db.execute(
        select(StockPrice.price_date)
        .where(StockPrice.symbol == _normalize_symbol(symbol))
        .where(StockPrice.price_date >= start_date)
        .where(StockPrice.price_date <= end_date)
    )
    return {row[0] for row in result.all()}


async def _load_sync_state(db: AsyncSession, kind: str, scope: str) -> MarketDataSyncState | None:
    return await db.scalar(
        select(MarketDataSyncState)
        .where(MarketDataSyncState.kind == kind)
        .where(MarketDataSyncState.scope == scope)
        .limit(1)
    )


async def _fallback_last_success_at(db: AsyncSession, kind: str, scope: str) -> datetime | None:
    if kind == "fx":
        base, quote_currency = _parse_fx_pair(scope)
        value = await db.scalar(
            select(func.max(FxRate.created_at))
            .where(FxRate.base_currency == base)
            .where(FxRate.quote_currency == quote_currency)
        )
    else:
        value = await db.scalar(
            select(func.max(StockPrice.created_at)).where(StockPrice.symbol == _normalize_symbol(scope))
        )
    return _normalize_utc(value) if value is not None else None


async def _latest_observation_date_on_or_before(
    db: AsyncSession,
    kind: str,
    scope: str,
    observed_date: date,
) -> date | None:
    if kind == "fx":
        base, quote_currency = _parse_fx_pair(scope)
        return await db.scalar(
            select(func.max(FxRate.rate_date))
            .where(FxRate.base_currency == base)
            .where(FxRate.quote_currency == quote_currency)
            .where(FxRate.rate_date <= observed_date)
        )
    return await db.scalar(
        select(func.max(StockPrice.price_date))
        .where(StockPrice.symbol == _normalize_symbol(scope))
        .where(StockPrice.price_date <= observed_date)
    )


async def _is_sync_scope_fresh(
    db: AsyncSession,
    kind: str,
    scope: str,
    now: datetime,
    *,
    required_observation_date: date | None = None,
) -> bool:
    state = await _load_sync_state(db, kind, scope)
    if state is not None:
        fresh = _normalize_utc(state.last_success_at) >= now - _FRESHNESS_THRESHOLD
    else:
        fallback = await _fallback_last_success_at(db, kind, scope)
        fresh = fallback is not None and fallback >= now - _FRESHNESS_THRESHOLD

    if not fresh or required_observation_date is None:
        return fresh

    return await _latest_observation_date_on_or_before(db, kind, scope, required_observation_date) is not None


async def _latest_observation_date(db: AsyncSession, kind: str, scope: str) -> date | None:
    if kind == "fx":
        base, quote_currency = _parse_fx_pair(scope)
        return await _latest_fx_rate_date(db, base, quote_currency)
    return await _latest_stock_price_date(db, scope)


async def _sync_scope_status(
    db: AsyncSession,
    *,
    kind: str,
    scope: str,
    now: datetime,
) -> MarketDataScopeStatus:
    state = await _load_sync_state(db, kind, scope)
    fallback_success_at = await _fallback_last_success_at(db, kind, scope) if state is None else None
    last_success_at = _normalize_utc(state.last_success_at) if state is not None else fallback_success_at
    latest_observation_date = await _latest_observation_date(db, kind, scope)
    last_success_date = state.last_success_date if state is not None else latest_observation_date
    last_observation_date = (
        state.last_observation_date
        if state is not None and state.last_observation_date is not None
        else latest_observation_date
    )
    return MarketDataScopeStatus(
        kind=kind,
        scope=scope,
        fresh=(
            last_success_at is not None
            and last_success_at >= now - _FRESHNESS_THRESHOLD
            and last_observation_date is not None
        ),
        last_success_at=last_success_at,
        last_success_date=last_success_date,
        last_observation_date=last_observation_date,
    )


async def _upsert_sync_state(
    db: AsyncSession,
    *,
    kind: str,
    scope: str,
    last_success_date: date,
    last_observation_date: date | None,
    now: datetime | None = None,
) -> None:
    observed_now = now or datetime.now(UTC)
    state = await _load_sync_state(db, kind, scope)
    try:
        async with db.begin_nested():
            if state is None:
                db.add(
                    MarketDataSyncState(
                        kind=kind,
                        scope=scope,
                        last_success_at=observed_now,
                        last_success_date=last_success_date,
                        last_observation_date=last_observation_date,
                        created_at=observed_now,
                        updated_at=observed_now,
                    )
                )
            else:
                state.last_success_at = observed_now
                state.last_success_date = last_success_date
                state.last_observation_date = last_observation_date
                state.updated_at = observed_now
            await db.flush()
    except IntegrityError:
        concurrent = await _load_sync_state(db, kind, scope)
        if concurrent is None:
            raise
        async with db.begin_nested():
            concurrent.last_success_at = observed_now
            concurrent.last_success_date = last_success_date
            concurrent.last_observation_date = last_observation_date
            concurrent.updated_at = observed_now
            await db.flush()


async def _persist_stock_price(db: AsyncSession, observation: StockPriceObservation) -> Decimal:
    symbol = _normalize_symbol(observation.symbol)
    currency = _normalize_currency(observation.currency)
    price = _quantize_price(observation.price)

    existing = await _load_stored_stock_price_on_date(db, symbol, observation.price_date)
    if existing is not None:
        return existing.price

    try:
        async with db.begin_nested():
            db.add(
                StockPrice(
                    symbol=symbol,
                    price=price,
                    currency=currency,
                    price_date=observation.price_date,
                    source=observation.source[:50],
                )
            )
            await db.flush()
    except IntegrityError:
        concurrent = await _load_stored_stock_price_on_date(db, symbol, observation.price_date)
        if concurrent is not None:
            return concurrent.price
        raise
    logger.info(
        "Persisted stock price",
        symbol=symbol,
        price_date=observation.price_date.isoformat(),
        source=observation.source[:50],
    )
    return price


async def _latest_fx_rate_date_for_scope(db: AsyncSession, scope: tuple[str, str]) -> date | None:
    base, quote_currency = scope
    return await _latest_fx_rate_date(db, base, quote_currency)


async def _stored_fx_rate_dates_for_scope(
    db: AsyncSession,
    scope: tuple[str, str],
    start_date: date,
    end_date: date,
) -> set[date]:
    base, quote_currency = scope
    return await _stored_fx_rate_dates(db, base, quote_currency, start_date, end_date)
