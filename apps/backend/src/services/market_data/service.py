"""Public sync orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.services.market_data import _providers
from src.services.market_data._base import (
    logger,
)
from src.services.market_data._providers import _FX_SYNC_SPEC, _STOCK_SYNC_SPEC
from src.services.market_data._store import (
    _derive_from_bridge_rates,
    _is_sync_scope_fresh,
    _load_stored_direct_or_inverse,
    _persist_fx_rate,
    _sync_scope_status,
    _upsert_sync_state,
)
from src.services.market_data._types import (
    MarketDataFreshnessResult,
    MarketDataScopeStatus,
    MarketDataSyncResult,
    _MarketSyncSpec,
)
from src.services.market_data._util import (
    _default_start_date,
    _fx_scope,
    _incremental_start,
    _iter_dates,
    _normalize_currency,
    _normalize_symbol,
    _normalize_utc,
    _parse_fx_pair,
    _stock_scope,
)
from src.services.market_data_discovery import active_stock_symbols, observed_fx_pairs


async def _sync_market_observation_series(
    db: AsyncSession,
    *,
    raw_scopes: Sequence[str],
    start_date: date | None,
    end_date: date,
    spec: _MarketSyncSpec,
) -> MarketDataSyncResult:
    result = MarketDataSyncResult(kind=spec.kind)

    for raw_scope in raw_scopes:
        scope = spec.parse_scope(raw_scope)
        if scope is None:
            continue

        last_date = await spec.latest_date(db, scope)
        sync_start = _incremental_start(last_date, start_date, end_date)
        if sync_start is None:
            continue

        all_dates = set(_iter_dates(sync_start, end_date))
        stored_dates = await spec.stored_dates(db, scope, sync_start, end_date)
        requested_dates = all_dates - stored_dates
        result = replace(result, skipped=result.skipped + len(all_dates & stored_dates))
        if not requested_dates:
            continue

        result = replace(result, requested=result.requested + len(requested_dates))
        validated = await spec.fetch_series(scope, min(requested_dates), max(requested_dates))
        result.disagreements.extend(validated.disagreements)

        observed_dates: set[date] = {item.observed_date for item in validated.disagreements}
        persisted_dates: list[date] = []
        for observation in validated.observations:
            observation_date = spec.observation_date(observation)
            if not spec.observation_matches_scope(observation, scope) or observation_date not in requested_dates:
                continue
            await spec.persist_observation(db, observation)
            persisted_dates.append(observation_date)
            observed_dates.add(observation_date)
            result = replace(result, inserted=result.inserted + 1)

        result = replace(result, missing=result.missing + len(requested_dates - observed_dates))
        if validated.provider_success:
            await _upsert_sync_state(
                db,
                kind=spec.kind,
                scope=spec.scope_name(scope),
                last_success_date=end_date,
                last_observation_date=max(persisted_dates) if persisted_dates else last_date,
            )

    return result


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

    provider_observation = await _providers._fetch_yahoo_or_derived_fx_rate(base, quote, requested_date)
    if provider_observation is not None:
        return await _persist_fx_rate(db, provider_observation)

    return None


async def sync_fx_rates(
    db: AsyncSession,
    *,
    pairs: Sequence[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    user_id: UUID | None = None,
) -> MarketDataSyncResult:
    """Incrementally fill FX rows for explicit or observed business pairs."""
    sync_end = end_date or date.today()
    sync_pairs = list(pairs) if pairs is not None else await observed_fx_pairs(db, user_id)
    return await _sync_market_observation_series(
        db,
        raw_scopes=sync_pairs,
        start_date=start_date,
        end_date=sync_end,
        spec=_FX_SYNC_SPEC,
    )


async def sync_stock_prices(
    db: AsyncSession,
    *,
    symbols: Sequence[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    user_id: UUID | None = None,
) -> MarketDataSyncResult:
    """Incrementally fill stock prices for explicit symbols or active holdings."""
    sync_end = end_date or date.today()
    sync_symbols = (
        sorted({_normalize_symbol(symbol) for symbol in symbols})
        if symbols is not None
        else await active_stock_symbols(db, user_id)
    )
    return await _sync_market_observation_series(
        db,
        raw_scopes=sync_symbols,
        start_date=start_date,
        end_date=sync_end,
        spec=_STOCK_SYNC_SPEC,
    )


async def ensure_market_data_fresh(
    db: AsyncSession,
    *,
    user_id: UUID | None = None,
    end_date: date | None = None,
    now: datetime | None = None,
    include_default_fx: bool = False,
    extra_fx_pairs: Sequence[str] | None = None,
) -> MarketDataFreshnessResult:
    """Refresh observed market data once when the last successful sync is older than 24h."""
    checked_at = _normalize_utc(now or datetime.now(UTC))
    sync_end = end_date or date.today()
    fx_pairs = set(await observed_fx_pairs(db, user_id, include_default=include_default_fx))
    fx_pairs.update(extra_fx_pairs or [])
    stale_pairs: list[str] = []
    for raw_pair in fx_pairs:
        base, quote_currency = _parse_fx_pair(raw_pair)
        if base == quote_currency:
            continue
        scope = _fx_scope(base, quote_currency)
        if not await _is_sync_scope_fresh(
            db,
            "fx",
            scope,
            checked_at,
            required_observation_date=sync_end,
        ):
            stale_pairs.append(scope)

    stock_symbols = await active_stock_symbols(db, user_id)
    stale_symbols: list[str] = []
    for symbol in stock_symbols:
        scope = _stock_scope(symbol)
        if not await _is_sync_scope_fresh(
            db,
            "stock",
            scope,
            checked_at,
            required_observation_date=sync_end,
        ):
            stale_symbols.append(scope)

    fx_result = (
        await sync_fx_rates(
            db,
            pairs=stale_pairs,
            start_date=_default_start_date(sync_end),
            end_date=sync_end,
            user_id=user_id,
        )
        if stale_pairs
        else MarketDataSyncResult(kind="fx")
    )
    stock_result = (
        await sync_stock_prices(
            db,
            symbols=stale_symbols,
            start_date=_default_start_date(sync_end),
            end_date=sync_end,
            user_id=user_id,
        )
        if stale_symbols
        else MarketDataSyncResult(kind="stock")
    )
    if fx_result.requested or stock_result.requested:
        logger.info(
            "Report-time market data freshness sync completed",
            fx_requested=fx_result.requested,
            stock_requested=stock_result.requested,
            fx_inserted=fx_result.inserted,
            stock_inserted=stock_result.inserted,
        )
    return MarketDataFreshnessResult(checked_at=checked_at, fx=fx_result, stock=stock_result)


async def get_market_data_status(
    db: AsyncSession,
    *,
    pairs: Sequence[str] | None = None,
    symbols: Sequence[str] | None = None,
    user_id: UUID | None = None,
    include_default_fx: bool = False,
    now: datetime | None = None,
) -> list[MarketDataScopeStatus]:
    """Return read-only sync freshness status for explicit or observed scopes."""
    checked_at = _normalize_utc(now or datetime.now(UTC))
    statuses: list[MarketDataScopeStatus] = []

    sync_pairs = (
        list(pairs) if pairs is not None else await observed_fx_pairs(db, user_id, include_default=include_default_fx)
    )
    for raw_pair in sorted(set(sync_pairs)):
        base, quote_currency = _parse_fx_pair(raw_pair)
        if base == quote_currency:
            continue
        statuses.append(
            await _sync_scope_status(
                db,
                kind="fx",
                scope=_fx_scope(base, quote_currency),
                now=checked_at,
            )
        )

    sync_symbols = (
        sorted({_normalize_symbol(symbol) for symbol in symbols})
        if symbols is not None
        else await active_stock_symbols(db, user_id)
    )
    for symbol in sync_symbols:
        if not symbol:
            continue
        statuses.append(
            await _sync_scope_status(
                db,
                kind="stock",
                scope=_stock_scope(symbol),
                now=checked_at,
            )
        )

    return statuses
