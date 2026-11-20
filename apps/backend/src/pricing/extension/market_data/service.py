"""Public sync orchestration.

``sync_fx_rates``/``sync_stock_prices``/``ensure_market_data_fresh``/
``get_market_data_status`` all take their scopes as explicit parameters —
they never discover *which* pairs/symbols to look at themselves. Deciding
that requires reading the user's ledger/portfolio/extraction data, so each
of those domains publishes its own read (``ledger.used_currencies``,
``portfolio.active_stock_symbols``/``position_currencies``,
``extraction.snapshot_currencies``) and the delivery layer composes them
(``src/composition.py::observed_fx_pairs`` — #1641/#1610).
Dependency inversion, meta Decision B: pricing must not depend on the domain
flow; the caller (scheduler / router / advisor) discovers the scopes and
passes them in here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.pricing.extension.market_data import _providers
from src.pricing.extension.market_data._base import (
    logger,
)
from src.pricing.extension.market_data._providers import _FX_SYNC_SPEC, _STOCK_SYNC_SPEC
from src.pricing.extension.market_data._store import (
    _derive_from_bridge_rates,
    _is_sync_scope_fresh,
    _load_stored_direct_or_inverse,
    _persist_fx_rate,
    _sync_scope_status,
    _upsert_sync_state,
)
from src.pricing.extension.market_data._types import (
    FetchedFreshnessSync,
    FetchedMarketSync,
    FetchedScopeSync,
    MarketDataFreshnessResult,
    MarketDataScopeStatus,
    MarketDataSyncResult,
    PlannedFreshnessSync,
    PlannedMarketSync,
    PlannedScopeSync,
    ProviderDisagreement,
    _MarketSyncSpec,
)
from src.pricing.extension.market_data._util import (
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

# Bound from the bare published root (config publishes no named symbols).
settings = src.config.settings


async def _plan_market_observation_series(
    db: AsyncSession,
    *,
    raw_scopes: Sequence[str],
    start_date: date | None,
    end_date: date,
    spec: _MarketSyncSpec,
) -> PlannedMarketSync:
    """Inspect stored dates and return the missing market data scope plan."""
    skipped = 0
    items: list[PlannedScopeSync] = []

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
        requested_dates = frozenset(all_dates - stored_dates)
        skipped += len(all_dates & stored_dates)
        if not requested_dates:
            continue

        items.append(
            PlannedScopeSync(
                scope=scope,
                scope_name=spec.scope_name(scope),
                last_date=last_date,
                requested_dates=requested_dates,
            )
        )

    return PlannedMarketSync(
        kind=spec.kind,
        end_date=end_date,
        skipped=skipped,
        items=tuple(items),
    )


async def _fetch_market_observation_series(
    plan: PlannedMarketSync,
    *,
    spec: _MarketSyncSpec,
    max_concurrency: int = 4,
) -> FetchedMarketSync:
    """Fetch provider series concurrently for a planned sync without DB access."""
    if not plan.items:
        return FetchedMarketSync(kind=plan.kind, items=())

    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _fetch_scope(item: PlannedScopeSync) -> FetchedScopeSync:
        async with semaphore:
            validated = await spec.fetch_series(
                item.scope,
                min(item.requested_dates),
                max(item.requested_dates),
            )
        return FetchedScopeSync(item=item, validated=validated)

    fetched_items = await asyncio.gather(*(_fetch_scope(item) for item in plan.items))
    return FetchedMarketSync(kind=plan.kind, items=tuple(fetched_items))


async def _persist_market_observation_series(
    db: AsyncSession,
    plan: PlannedMarketSync,
    fetched: FetchedMarketSync,
    *,
    spec: _MarketSyncSpec,
) -> MarketDataSyncResult:
    """Persist fetched market observations and sync-state watermarks without committing."""
    requested = 0
    inserted = 0
    missing = 0
    disagreements: list[ProviderDisagreement] = []

    for fetched_item in fetched.items:
        item = fetched_item.item
        validated = fetched_item.validated
        requested += len(item.requested_dates)
        disagreements.extend(validated.disagreements)

        observed_dates: set[date] = {dis.observed_date for dis in validated.disagreements}
        persisted_dates: list[date] = []
        for observation in validated.observations:
            observation_date = spec.observation_date(observation)
            if not spec.observation_matches_scope(observation, item.scope) or observation_date not in item.requested_dates:
                continue
            await spec.persist_observation(db, observation)
            persisted_dates.append(observation_date)
            observed_dates.add(observation_date)
            inserted += 1

        missing += len(item.requested_dates - observed_dates)
        if validated.provider_success:
            await _upsert_sync_state(
                db,
                kind=spec.kind,
                scope=item.scope_name,
                last_success_date=plan.end_date,
                last_observation_date=max(persisted_dates) if persisted_dates else item.last_date,
            )

    return MarketDataSyncResult(
        kind=spec.kind,
        requested=requested,
        inserted=inserted,
        skipped=plan.skipped,
        missing=missing,
        disagreements=disagreements,
    )


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


async def plan_fx_sync(
    db: AsyncSession,
    *,
    pairs: Sequence[str],
    start_date: date | None = None,
    end_date: date | None = None,
) -> PlannedMarketSync:
    """Plan incremental FX rate sync ranges from database state."""
    sync_end = end_date or date.today()
    return await _plan_market_observation_series(
        db,
        raw_scopes=list(pairs),
        start_date=start_date,
        end_date=sync_end,
        spec=_FX_SYNC_SPEC,
    )


async def fetch_planned_fx_sync(
    plan: PlannedMarketSync,
    *,
    max_concurrency: int = 4,
) -> FetchedMarketSync:
    """Fetch planned FX rate series from providers without database access."""
    return await _fetch_market_observation_series(
        plan,
        spec=_FX_SYNC_SPEC,
        max_concurrency=max_concurrency,
    )


async def persist_fetched_fx_sync(
    db: AsyncSession,
    plan: PlannedMarketSync,
    fetched: FetchedMarketSync,
) -> MarketDataSyncResult:
    """Persist fetched FX rates without committing."""
    return await _persist_market_observation_series(
        db,
        plan,
        fetched,
        spec=_FX_SYNC_SPEC,
    )


async def sync_fx_rates(
    db: AsyncSession,
    *,
    pairs: Sequence[str],
    start_date: date | None = None,
    end_date: date | None = None,
) -> MarketDataSyncResult:
    """Incrementally fill FX rows for the given ``BASE/QUOTE`` pairs."""
    plan = await plan_fx_sync(db, pairs=pairs, start_date=start_date, end_date=end_date)
    fetched = await fetch_planned_fx_sync(plan)
    return await persist_fetched_fx_sync(db, plan, fetched)


async def plan_stock_sync(
    db: AsyncSession,
    *,
    symbols: Sequence[str],
    start_date: date | None = None,
    end_date: date | None = None,
) -> PlannedMarketSync:
    """Plan incremental stock price sync ranges from database state."""
    sync_end = end_date or date.today()
    sync_symbols = sorted({_normalize_symbol(symbol) for symbol in symbols})
    return await _plan_market_observation_series(
        db,
        raw_scopes=sync_symbols,
        start_date=start_date,
        end_date=sync_end,
        spec=_STOCK_SYNC_SPEC,
    )


async def fetch_planned_stock_sync(
    plan: PlannedMarketSync,
    *,
    max_concurrency: int = 4,
) -> FetchedMarketSync:
    """Fetch planned stock price series from providers without database access."""
    return await _fetch_market_observation_series(
        plan,
        spec=_STOCK_SYNC_SPEC,
        max_concurrency=max_concurrency,
    )


async def persist_fetched_stock_sync(
    db: AsyncSession,
    plan: PlannedMarketSync,
    fetched: FetchedMarketSync,
) -> MarketDataSyncResult:
    """Persist fetched stock prices without committing."""
    return await _persist_market_observation_series(
        db,
        plan,
        fetched,
        spec=_STOCK_SYNC_SPEC,
    )


async def sync_stock_prices(
    db: AsyncSession,
    *,
    symbols: Sequence[str],
    start_date: date | None = None,
    end_date: date | None = None,
) -> MarketDataSyncResult:
    """Incrementally fill stock prices for the given symbols."""
    plan = await plan_stock_sync(db, symbols=symbols, start_date=start_date, end_date=end_date)
    fetched = await fetch_planned_stock_sync(plan)
    return await persist_fetched_stock_sync(db, plan, fetched)


async def plan_market_data_freshness(
    db: AsyncSession,
    *,
    fx_pairs: Sequence[str],
    stock_symbols: Sequence[str],
    end_date: date | None = None,
    now: datetime | None = None,
) -> PlannedFreshnessSync:
    """Inspect freshness state and plan stale FX and stock syncs."""
    checked_at = _normalize_utc(now or datetime.now(UTC))
    sync_end = end_date or date.today()
    stale_pairs: list[str] = []
    for raw_pair in set(fx_pairs):
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

    fx_plan = (
        await plan_fx_sync(
            db,
            pairs=stale_pairs,
            start_date=_default_start_date(sync_end),
            end_date=sync_end,
        )
        if stale_pairs
        else PlannedMarketSync(kind="fx", end_date=sync_end, skipped=0, items=())
    )
    stock_plan = (
        await plan_stock_sync(
            db,
            symbols=stale_symbols,
            start_date=_default_start_date(sync_end),
            end_date=sync_end,
        )
        if stale_symbols
        else PlannedMarketSync(kind="stock", end_date=sync_end, skipped=0, items=())
    )
    return PlannedFreshnessSync(checked_at=checked_at, fx=fx_plan, stock=stock_plan)


async def fetch_planned_freshness(
    plan: PlannedFreshnessSync,
    *,
    max_concurrency: int = 4,
) -> FetchedFreshnessSync:
    """Fetch stale FX and stock scopes concurrently without database access."""
    fx_fetched, stock_fetched = await asyncio.gather(
        fetch_planned_fx_sync(plan.fx, max_concurrency=max_concurrency),
        fetch_planned_stock_sync(plan.stock, max_concurrency=max_concurrency),
    )
    return FetchedFreshnessSync(fx=fx_fetched, stock=stock_fetched)


async def persist_fetched_freshness(
    db: AsyncSession,
    plan: PlannedFreshnessSync,
    fetched: FetchedFreshnessSync,
) -> MarketDataFreshnessResult:
    """Persist fetched freshness series without committing."""
    fx_result = await persist_fetched_fx_sync(db, plan.fx, fetched.fx)
    stock_result = await persist_fetched_stock_sync(db, plan.stock, fetched.stock)
    if fx_result.requested or stock_result.requested:
        logger.info(
            "Report-time market data freshness sync completed",
            fx_requested=fx_result.requested,
            stock_requested=stock_result.requested,
            fx_inserted=fx_result.inserted,
            stock_inserted=stock_result.inserted,
        )
    return MarketDataFreshnessResult(checked_at=plan.checked_at, fx=fx_result, stock=stock_result)


async def ensure_market_data_fresh(
    db: AsyncSession,
    *,
    fx_pairs: Sequence[str],
    stock_symbols: Sequence[str],
    end_date: date | None = None,
    now: datetime | None = None,
) -> MarketDataFreshnessResult:
    """Refresh the given scopes once when the last successful sync is older than 24h."""
    plan = await plan_market_data_freshness(
        db,
        fx_pairs=fx_pairs,
        stock_symbols=stock_symbols,
        end_date=end_date,
        now=now,
    )
    fetched = await fetch_planned_freshness(plan)
    return await persist_fetched_freshness(db, plan, fetched)


async def get_market_data_status(
    db: AsyncSession,
    *,
    pairs: Sequence[str],
    symbols: Sequence[str],
    now: datetime | None = None,
) -> list[MarketDataScopeStatus]:
    """Return read-only sync freshness status for the given scopes."""
    checked_at = _normalize_utc(now or datetime.now(UTC))
    statuses: list[MarketDataScopeStatus] = []

    for raw_pair in sorted(set(pairs)):
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

    sync_symbols = sorted({_normalize_symbol(symbol) for symbol in symbols})
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
