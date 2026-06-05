"""Market data lookup and incremental sync helpers."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from io import StringIO
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.logger import get_logger
from src.models import FxRate, MarketDataSyncState, StockPrice
from src.models.account import Account
from src.models.journal import JournalEntry, JournalLine
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus

logger = get_logger(__name__)

_RATE_QUANT = Decimal("0.000001")
_PRICE_QUANT = Decimal("0.000001")
_DEFAULT_INCREMENTAL_LOOKBACK_DAYS = 7
_PROVIDER_DISAGREEMENT_THRESHOLD = Decimal("0.02")
_FRESHNESS_THRESHOLD = timedelta(hours=24)
_YAHOO_FX_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}=X"
_YAHOO_STOCK_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_YAHOO_CHART_URL = _YAHOO_FX_CHART_URL
_STOOQ_DAILY_URL = "https://stooq.com/q/d/l/"


@dataclass(frozen=True)
class FxRateObservation:
    """Resolved FX rate observation from a provider or derivation path."""

    base_currency: str
    quote_currency: str
    rate: Decimal
    rate_date: date
    source: str


@dataclass(frozen=True)
class StockPriceObservation:
    """Resolved daily close for one stock symbol."""

    symbol: str
    price: Decimal
    currency: str
    price_date: date
    source: str


@dataclass(frozen=True)
class ProviderDisagreement:
    """Cross-provider disagreement that blocks automatic persistence."""

    asset: str
    observed_date: date
    primary_source: str
    secondary_source: str
    primary_value: Decimal
    secondary_value: Decimal
    relative_difference: Decimal
    threshold: Decimal

    def to_dict(self) -> dict[str, str]:
        return {
            "asset": self.asset,
            "observed_date": self.observed_date.isoformat(),
            "primary_source": self.primary_source,
            "secondary_source": self.secondary_source,
            "primary_value": str(self.primary_value),
            "secondary_value": str(self.secondary_value),
            "relative_difference": str(self.relative_difference),
            "threshold": str(self.threshold),
        }


@dataclass(frozen=True)
class ValidatedMarketObservation:
    """Provider observation accepted for persistence, or a disagreement."""

    observation: FxRateObservation | StockPriceObservation | None
    disagreement: ProviderDisagreement | None = None


@dataclass(frozen=True)
class ValidatedMarketObservationSeries:
    """Provider observations accepted for range persistence."""

    observations: list[FxRateObservation | StockPriceObservation] = field(default_factory=list)
    disagreements: list[ProviderDisagreement] = field(default_factory=list)
    provider_success: bool = True


@dataclass(frozen=True)
class MarketDataSyncResult:
    """Scheduler-friendly market data sync counters."""

    kind: str
    requested: int = 0
    inserted: int = 0
    skipped: int = 0
    missing: int = 0
    disagreements: list[ProviderDisagreement] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "requested": self.requested,
            "inserted": self.inserted,
            "skipped": self.skipped,
            "missing": self.missing,
            "disagreements": [item.to_dict() for item in self.disagreements],
        }


@dataclass(frozen=True)
class MarketDataFreshnessResult:
    """Report-time freshness check result."""

    checked_at: datetime
    fx: MarketDataSyncResult
    stock: MarketDataSyncResult

    @property
    def triggered(self) -> bool:
        return self.fx.requested > 0 or self.stock.requested > 0


@dataclass(frozen=True)
class MarketDataScopeStatus:
    """Read-only freshness status for one market data scope."""

    kind: str
    scope: str
    fresh: bool
    last_success_at: datetime | None
    last_success_date: date | None
    last_observation_date: date | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "scope": self.scope,
            "fresh": self.fresh,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_success_date": self.last_success_date.isoformat() if self.last_success_date else None,
            "last_observation_date": self.last_observation_date.isoformat() if self.last_observation_date else None,
        }


@dataclass(frozen=True)
class _StoredFxRate:
    rate: Decimal
    rate_date: date
    source: str


@dataclass(frozen=True)
class _StoredStockPrice:
    price: Decimal
    currency: str
    price_date: date
    source: str


def _normalize_currency(code: str) -> str:
    return code.strip().upper()


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _quantize_rate(rate: Decimal) -> Decimal:
    return rate.quantize(_RATE_QUANT, rounding=ROUND_HALF_UP)


def _quantize_price(price: Decimal) -> Decimal:
    return price.quantize(_PRICE_QUANT, rounding=ROUND_HALF_UP)


def _date_to_epoch(value: date) -> int:
    return int(datetime.combine(value, time.min, tzinfo=UTC).timestamp())


def _iter_dates(start_date: date, end_date: date) -> Sequence[date]:
    days = (end_date - start_date).days
    if days < 0:
        return []
    return [start_date + timedelta(days=offset) for offset in range(days + 1)]


def _parse_fx_pair(pair: str) -> tuple[str, str]:
    parts = [item.strip() for item in pair.split("/", maxsplit=1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid FX pair '{pair}', expected BASE/QUOTE")
    return _normalize_currency(parts[0]), _normalize_currency(parts[1])


def _fx_scope(base_currency: str, quote_currency: str) -> str:
    return f"{_normalize_currency(base_currency)}/{_normalize_currency(quote_currency)}"


def _stock_scope(symbol: str) -> str:
    return _normalize_symbol(symbol)


def _default_start_date(end_date: date) -> date:
    return end_date - timedelta(days=_DEFAULT_INCREMENTAL_LOOKBACK_DAYS - 1)


def _incremental_start(last_stored_date: date | None, start_date: date | None, end_date: date) -> date | None:
    if last_stored_date is not None:
        if start_date is not None and last_stored_date >= end_date:
            start = start_date
        else:
            start = last_stored_date + timedelta(days=1)
    else:
        start = start_date or _default_start_date(end_date)
    if start > end_date:
        return None
    return start


def _relative_difference(primary: Decimal, secondary: Decimal) -> Decimal:
    denominator = max(abs(primary), abs(secondary))
    if denominator == Decimal("0"):
        return Decimal("0")
    return _quantize_rate(abs(primary - secondary) / denominator)


def _observation_date(observation: FxRateObservation | StockPriceObservation) -> date:
    if isinstance(observation, FxRateObservation):
        return observation.rate_date
    return observation.price_date


def _observations_by_date(
    observations: Sequence[FxRateObservation | StockPriceObservation] | None,
) -> dict[date, FxRateObservation | StockPriceObservation]:
    return {_observation_date(observation): observation for observation in observations or []}


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _stooq_stock_symbol(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    if "." in normalized:
        return normalized.lower()
    return f"{normalized.lower()}.us"


def _stooq_fx_symbol(base_currency: str, quote_currency: str) -> str:
    return f"{base_currency.lower()}{quote_currency.lower()}"


def _select_validated_observation(
    *,
    asset: str,
    observed_date: date,
    primary: FxRateObservation | StockPriceObservation | None,
    secondary: FxRateObservation | StockPriceObservation | None,
) -> ValidatedMarketObservation:
    if primary is None:
        return ValidatedMarketObservation(observation=secondary)
    if secondary is None:
        return ValidatedMarketObservation(observation=primary)

    primary_value = primary.rate if isinstance(primary, FxRateObservation) else primary.price
    secondary_value = secondary.rate if isinstance(secondary, FxRateObservation) else secondary.price
    relative_difference = _relative_difference(primary_value, secondary_value)
    if relative_difference > _PROVIDER_DISAGREEMENT_THRESHOLD:
        disagreement = ProviderDisagreement(
            asset=asset,
            observed_date=observed_date,
            primary_source=primary.source,
            secondary_source=secondary.source,
            primary_value=primary_value,
            secondary_value=secondary_value,
            relative_difference=relative_difference,
            threshold=_PROVIDER_DISAGREEMENT_THRESHOLD,
        )
        logger.warning("Market data provider disagreement", **disagreement.to_dict())
        return ValidatedMarketObservation(observation=None, disagreement=disagreement)

    return ValidatedMarketObservation(
        observation=replace(primary, source=f"{primary.source}:validated:{secondary.source}"[:50])
    )


def _select_validated_observation_series(
    *,
    asset: str,
    start_date: date,
    end_date: date,
    primary: Sequence[FxRateObservation | StockPriceObservation] | None,
    secondary: Sequence[FxRateObservation | StockPriceObservation] | None,
    provider_success: bool,
) -> ValidatedMarketObservationSeries:
    primary_by_date = _observations_by_date(primary)
    secondary_by_date = _observations_by_date(secondary)
    observations: list[FxRateObservation | StockPriceObservation] = []
    disagreements: list[ProviderDisagreement] = []

    for observed_date in sorted(set(primary_by_date) | set(secondary_by_date)):
        if observed_date < start_date or observed_date > end_date:
            continue
        selected = _select_validated_observation(
            asset=asset,
            observed_date=observed_date,
            primary=primary_by_date.get(observed_date),
            secondary=secondary_by_date.get(observed_date),
        )
        if selected.disagreement is not None:
            disagreements.append(selected.disagreement)
        elif selected.observation is not None:
            observations.append(selected.observation)

    return ValidatedMarketObservationSeries(
        observations=observations,
        disagreements=disagreements,
        provider_success=provider_success,
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
        .order_by(StockPrice.price_date.desc())
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


async def _active_stock_symbols(db: AsyncSession, user_id: UUID | None) -> list[str]:
    stmt = (
        select(ManagedPosition.asset_identifier)
        .where(ManagedPosition.status == PositionStatus.ACTIVE)
        .where(ManagedPosition.quantity != Decimal("0"))
        .order_by(ManagedPosition.asset_identifier)
    )
    if user_id is not None:
        stmt = stmt.where(ManagedPosition.user_id == user_id)
    result = await db.execute(stmt)
    return sorted({_normalize_symbol(row[0]) for row in result.all() if row[0]})


async def _observed_fx_pairs(
    db: AsyncSession,
    user_id: UUID | None,
    *,
    include_default: bool = True,
) -> list[str]:
    base = _normalize_currency(settings.base_currency)
    default_counterparty = "USD" if base != "USD" else "SGD"
    currencies: set[str] = {base}
    if include_default:
        currencies.add(default_counterparty)

    account_stmt = select(Account.currency)
    if user_id is not None:
        account_stmt = account_stmt.where(Account.user_id == user_id)
    currencies.update(_normalize_currency(row[0]) for row in (await db.execute(account_stmt)).all() if row[0])

    line_stmt = select(JournalLine.currency).join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
    if user_id is not None:
        line_stmt = line_stmt.where(JournalEntry.user_id == user_id)
    currencies.update(_normalize_currency(row[0]) for row in (await db.execute(line_stmt)).all() if row[0])

    position_stmt = select(ManagedPosition.currency)
    if user_id is not None:
        position_stmt = position_stmt.where(ManagedPosition.user_id == user_id)
    currencies.update(_normalize_currency(row[0]) for row in (await db.execute(position_stmt)).all() if row[0])

    snapshot_stmt = select(AtomicPosition.currency)
    if user_id is not None:
        snapshot_stmt = snapshot_stmt.where(AtomicPosition.user_id == user_id)
    currencies.update(_normalize_currency(row[0]) for row in (await db.execute(snapshot_stmt)).all() if row[0])

    return [f"{currency}/{base}" for currency in sorted(currencies) if currency != base]


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
    sync_pairs = list(pairs) if pairs is not None else await _observed_fx_pairs(db, user_id)
    result = MarketDataSyncResult(kind="fx")

    for raw_pair in sync_pairs:
        base, quote_currency = _parse_fx_pair(raw_pair)
        if base == quote_currency:
            continue
        last_date = await _latest_fx_rate_date(db, base, quote_currency)
        sync_start = _incremental_start(last_date, start_date, sync_end)
        if sync_start is None:
            continue

        all_dates = set(_iter_dates(sync_start, sync_end))
        stored_dates = await _stored_fx_rate_dates(db, base, quote_currency, sync_start, sync_end)
        requested_dates = all_dates - stored_dates
        result = replace(result, skipped=result.skipped + len(all_dates & stored_dates))

        if not requested_dates:
            continue

        result = replace(result, requested=result.requested + len(requested_dates))
        validated = await _fetch_validated_fx_rate_series(
            base, quote_currency, min(requested_dates), max(requested_dates)
        )
        result.disagreements.extend(validated.disagreements)

        observed_dates: set[date] = {item.observed_date for item in validated.disagreements}
        persisted_dates: list[date] = []
        for observation in validated.observations:
            if not isinstance(observation, FxRateObservation) or observation.rate_date not in requested_dates:
                continue
            await _persist_fx_rate(db, observation)
            persisted_dates.append(observation.rate_date)
            observed_dates.add(observation.rate_date)
            result = replace(result, inserted=result.inserted + 1)

        result = replace(result, missing=result.missing + len(requested_dates - observed_dates))
        if validated.provider_success:
            await _upsert_sync_state(
                db,
                kind="fx",
                scope=_fx_scope(base, quote_currency),
                last_success_date=sync_end,
                last_observation_date=max(persisted_dates) if persisted_dates else last_date,
            )

    return result


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
        else await _active_stock_symbols(db, user_id)
    )
    result = MarketDataSyncResult(kind="stock")

    for symbol in sync_symbols:
        if not symbol:
            continue
        last_date = await _latest_stock_price_date(db, symbol)
        sync_start = _incremental_start(last_date, start_date, sync_end)
        if sync_start is None:
            continue

        all_dates = set(_iter_dates(sync_start, sync_end))
        stored_dates = await _stored_stock_price_dates(db, symbol, sync_start, sync_end)
        requested_dates = all_dates - stored_dates
        result = replace(result, skipped=result.skipped + len(all_dates & stored_dates))

        if not requested_dates:
            continue

        result = replace(result, requested=result.requested + len(requested_dates))
        validated = await _fetch_validated_stock_price_series(symbol, min(requested_dates), max(requested_dates))
        result.disagreements.extend(validated.disagreements)

        observed_dates: set[date] = {item.observed_date for item in validated.disagreements}
        persisted_dates: list[date] = []
        for observation in validated.observations:
            if not isinstance(observation, StockPriceObservation) or observation.price_date not in requested_dates:
                continue
            await _persist_stock_price(db, observation)
            persisted_dates.append(observation.price_date)
            observed_dates.add(observation.price_date)
            result = replace(result, inserted=result.inserted + 1)

        result = replace(result, missing=result.missing + len(requested_dates - observed_dates))
        if validated.provider_success:
            await _upsert_sync_state(
                db,
                kind="stock",
                scope=_stock_scope(symbol),
                last_success_date=sync_end,
                last_observation_date=max(persisted_dates) if persisted_dates else last_date,
            )

    return result


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
    fx_pairs = set(await _observed_fx_pairs(db, user_id, include_default=include_default_fx))
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

    stock_symbols = await _active_stock_symbols(db, user_id)
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
        list(pairs) if pairs is not None else await _observed_fx_pairs(db, user_id, include_default=include_default_fx)
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
        else await _active_stock_symbols(db, user_id)
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


async def _fetch_validated_fx_rate_series(
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> ValidatedMarketObservationSeries:
    primary = await _fetch_yahoo_or_derived_fx_rate_series(base_currency, quote_currency, start_date, end_date)
    secondary = await _fetch_stooq_fx_rate_series(base_currency, quote_currency, start_date, end_date)
    return _select_validated_observation_series(
        asset=f"{base_currency}/{quote_currency}",
        start_date=start_date,
        end_date=end_date,
        primary=primary,
        secondary=secondary,
        provider_success=primary is not None or secondary is not None,
    )


async def _fetch_validated_stock_price_series(
    symbol: str,
    start_date: date,
    end_date: date,
) -> ValidatedMarketObservationSeries:
    normalized = _normalize_symbol(symbol)
    primary = await _fetch_yahoo_stock_price_series(normalized, start_date, end_date)
    secondary = await _fetch_stooq_stock_price_series(normalized, start_date, end_date)
    return _select_validated_observation_series(
        asset=normalized,
        start_date=start_date,
        end_date=end_date,
        primary=primary,
        secondary=secondary,
        provider_success=primary is not None or secondary is not None,
    )


async def _fetch_validated_fx_rate(
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> ValidatedMarketObservation:
    primary = await _fetch_yahoo_or_derived_fx_rate(base_currency, quote_currency, requested_date)
    secondary = await _fetch_stooq_fx_rate(base_currency, quote_currency, requested_date)
    return _select_validated_observation(
        asset=f"{base_currency}/{quote_currency}",
        observed_date=requested_date,
        primary=primary,
        secondary=secondary,
    )


async def _fetch_validated_stock_price(symbol: str, requested_date: date) -> ValidatedMarketObservation:
    normalized = _normalize_symbol(symbol)
    primary = await _fetch_yahoo_stock_price(normalized, requested_date)
    secondary = await _fetch_stooq_stock_price(normalized, requested_date)
    return _select_validated_observation(
        asset=normalized,
        observed_date=requested_date,
        primary=primary,
        secondary=secondary,
    )


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


async def _fetch_yahoo_or_derived_fx_rate_series(
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> list[FxRateObservation] | None:
    direct = await _fetch_yahoo_fx_rate_series(base_currency, quote_currency, start_date, end_date)
    if direct:
        return direct
    if direct is None:
        direct_failed = True
    else:
        direct_failed = False

    inverse = await _fetch_yahoo_fx_rate_series(quote_currency, base_currency, start_date, end_date)
    if inverse:
        return [
            FxRateObservation(
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate=_quantize_rate(Decimal("1") / observation.rate),
                rate_date=observation.rate_date,
                source="yahoo_finance:inverse",
            )
            for observation in inverse
            if observation.rate != Decimal("0")
        ]

    bridge = _normalize_currency(settings.market_data_fx_bridge_currency)
    if bridge in {base_currency, quote_currency}:
        return None if direct_failed and inverse is None else []

    base_to_bridge = await _fetch_yahoo_fx_rate_series(base_currency, bridge, start_date, end_date)
    bridge_to_quote = await _fetch_yahoo_fx_rate_series(bridge, quote_currency, start_date, end_date)
    if base_to_bridge is None and bridge_to_quote is None and direct_failed and inverse is None:
        return None
    if not base_to_bridge or not bridge_to_quote:
        return []

    bridge_to_quote_by_date = {observation.rate_date: observation for observation in bridge_to_quote}
    observations: list[FxRateObservation] = []
    for base_observation in base_to_bridge:
        quote_observation = bridge_to_quote_by_date.get(base_observation.rate_date)
        if quote_observation is None:
            continue
        observations.append(
            FxRateObservation(
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate=_quantize_rate(base_observation.rate * quote_observation.rate),
                rate_date=base_observation.rate_date,
                source=f"yahoo_finance:bridge:{bridge}",
            )
        )
    return observations


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
    url = _YAHOO_FX_CHART_URL.format(symbol=quote(symbol, safe=""))

    try:
        async with httpx.AsyncClient(
            timeout=settings.market_data_yahoo_timeout_seconds,
            headers={"User-Agent": "finance-report-audit/1.0"},
        ) as client:
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


async def _fetch_yahoo_fx_rate_series(
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> list[FxRateObservation] | None:
    """Fetch Yahoo Finance FX closes for a bounded date range."""
    symbol = f"{base_currency}{quote_currency}"
    params = {
        "period1": str(_date_to_epoch(start_date)),
        "period2": str(_date_to_epoch(end_date + timedelta(days=1))),
        "interval": "1d",
    }
    url = _YAHOO_FX_CHART_URL.format(symbol=quote(symbol, safe=""))

    try:
        async with httpx.AsyncClient(
            timeout=settings.market_data_yahoo_timeout_seconds,
            headers={"User-Agent": "finance-report-audit/1.0"},
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "Yahoo Finance FX range fetch failed",
            base_currency=base_currency,
            quote_currency=quote_currency,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            error=str(exc),
        )
        return None

    return _parse_yahoo_fx_response_series(response.json(), base_currency, quote_currency, start_date, end_date)


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


def _parse_yahoo_fx_response_series(
    payload: dict[str, Any],
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> list[FxRateObservation]:
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return []

    result = results[0]
    timestamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    observations: list[FxRateObservation] = []
    for timestamp, close in zip(timestamps, closes, strict=False):
        if close is None:
            continue
        observed_date = datetime.fromtimestamp(int(timestamp), UTC).date()
        if observed_date < start_date or observed_date > end_date:
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
    return observations


async def _fetch_yahoo_stock_price(symbol: str, requested_date: date) -> StockPriceObservation | None:
    """Fetch the latest Yahoo Finance stock close on or before the requested date."""
    normalized = _normalize_symbol(symbol)
    start = requested_date - timedelta(days=7)
    end = requested_date + timedelta(days=1)
    params = {
        "period1": str(_date_to_epoch(start)),
        "period2": str(_date_to_epoch(end)),
        "interval": "1d",
    }
    url = _YAHOO_STOCK_CHART_URL.format(symbol=quote(normalized, safe=".-"))

    try:
        async with httpx.AsyncClient(
            timeout=settings.market_data_yahoo_timeout_seconds,
            headers={"User-Agent": "finance-report-audit/1.0"},
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "Yahoo Finance stock fetch failed",
            symbol=normalized,
            requested_date=requested_date.isoformat(),
            error=str(exc),
        )
        return None

    return _parse_yahoo_stock_response(response.json(), normalized, requested_date)


async def _fetch_yahoo_stock_price_series(
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[StockPriceObservation] | None:
    """Fetch Yahoo Finance stock closes for a bounded date range."""
    normalized = _normalize_symbol(symbol)
    params = {
        "period1": str(_date_to_epoch(start_date)),
        "period2": str(_date_to_epoch(end_date + timedelta(days=1))),
        "interval": "1d",
    }
    url = _YAHOO_STOCK_CHART_URL.format(symbol=quote(normalized, safe=".-"))

    try:
        async with httpx.AsyncClient(
            timeout=settings.market_data_yahoo_timeout_seconds,
            headers={"User-Agent": "finance-report-audit/1.0"},
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "Yahoo Finance stock range fetch failed",
            symbol=normalized,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            error=str(exc),
        )
        return None

    return _parse_yahoo_stock_response_series(response.json(), normalized, start_date, end_date)


def _parse_yahoo_stock_response(
    payload: dict[str, Any],
    symbol: str,
    requested_date: date,
) -> StockPriceObservation | None:
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return None

    result = results[0]
    currency = _normalize_currency((result.get("meta") or {}).get("currency") or "USD")
    timestamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []

    observations: list[StockPriceObservation] = []
    for timestamp, close in zip(timestamps, closes, strict=False):
        if close is None:
            continue
        observed_date = datetime.fromtimestamp(int(timestamp), UTC).date()
        if observed_date > requested_date:
            continue
        observations.append(
            StockPriceObservation(
                symbol=symbol,
                price=_quantize_price(Decimal(str(close))),
                currency=currency,
                price_date=observed_date,
                source="yahoo_finance",
            )
        )

    if not observations:
        return None
    return max(observations, key=lambda item: item.price_date)


def _parse_yahoo_stock_response_series(
    payload: dict[str, Any],
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[StockPriceObservation]:
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return []

    result = results[0]
    currency = _normalize_currency((result.get("meta") or {}).get("currency") or "USD")
    timestamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []

    observations: list[StockPriceObservation] = []
    for timestamp, close in zip(timestamps, closes, strict=False):
        if close is None:
            continue
        observed_date = datetime.fromtimestamp(int(timestamp), UTC).date()
        if observed_date < start_date or observed_date > end_date:
            continue
        observations.append(
            StockPriceObservation(
                symbol=symbol,
                price=_quantize_price(Decimal(str(close))),
                currency=currency,
                price_date=observed_date,
                source="yahoo_finance",
            )
        )

    return observations


async def _fetch_stooq_fx_rate(
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> FxRateObservation | None:
    params = {
        "s": _stooq_fx_symbol(base_currency, quote_currency),
        "d1": (requested_date - timedelta(days=7)).strftime("%Y%m%d"),
        "d2": requested_date.strftime("%Y%m%d"),
        "i": "d",
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.market_data_yahoo_timeout_seconds,
            headers={"User-Agent": "finance-report-audit/1.0"},
        ) as client:
            response = await client.get(_STOOQ_DAILY_URL, params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "Stooq FX fetch failed",
            base_currency=base_currency,
            quote_currency=quote_currency,
            requested_date=requested_date.isoformat(),
            error=str(exc),
        )
        return None

    return _parse_stooq_fx_csv(response.text, base_currency, quote_currency, requested_date)


async def _fetch_stooq_fx_rate_series(
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> list[FxRateObservation] | None:
    params = {
        "s": _stooq_fx_symbol(base_currency, quote_currency),
        "d1": start_date.strftime("%Y%m%d"),
        "d2": end_date.strftime("%Y%m%d"),
        "i": "d",
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.market_data_yahoo_timeout_seconds,
            headers={"User-Agent": "finance-report-audit/1.0"},
        ) as client:
            response = await client.get(_STOOQ_DAILY_URL, params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "Stooq FX range fetch failed",
            base_currency=base_currency,
            quote_currency=quote_currency,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            error=str(exc),
        )
        return None

    return _parse_stooq_fx_csv_series(response.text, base_currency, quote_currency, start_date, end_date)


def _parse_stooq_fx_csv(
    payload: str,
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> FxRateObservation | None:
    observations: list[FxRateObservation] = []
    for row in csv.DictReader(StringIO(payload)):
        close = row.get("Close")
        row_date = row.get("Date")
        if not close or not row_date or close == "N/D":
            continue
        observed_date = date.fromisoformat(row_date)
        if observed_date > requested_date:
            continue
        observations.append(
            FxRateObservation(
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate=_quantize_rate(Decimal(close)),
                rate_date=observed_date,
                source="stooq",
            )
        )
    if not observations:
        return None
    return max(observations, key=lambda item: item.rate_date)


def _parse_stooq_fx_csv_series(
    payload: str,
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> list[FxRateObservation]:
    observations: list[FxRateObservation] = []
    for row in csv.DictReader(StringIO(payload)):
        close = row.get("Close")
        row_date = row.get("Date")
        if not close or not row_date or close == "N/D":
            continue
        observed_date = date.fromisoformat(row_date)
        if observed_date < start_date or observed_date > end_date:
            continue
        observations.append(
            FxRateObservation(
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate=_quantize_rate(Decimal(close)),
                rate_date=observed_date,
                source="stooq",
            )
        )
    return observations


async def _fetch_stooq_stock_price(symbol: str, requested_date: date) -> StockPriceObservation | None:
    normalized = _normalize_symbol(symbol)
    params = {
        "s": _stooq_stock_symbol(normalized),
        "d1": (requested_date - timedelta(days=7)).strftime("%Y%m%d"),
        "d2": requested_date.strftime("%Y%m%d"),
        "i": "d",
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.market_data_yahoo_timeout_seconds,
            headers={"User-Agent": "finance-report-audit/1.0"},
        ) as client:
            response = await client.get(_STOOQ_DAILY_URL, params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "Stooq stock fetch failed",
            symbol=normalized,
            requested_date=requested_date.isoformat(),
            error=str(exc),
        )
        return None

    return _parse_stooq_stock_csv(response.text, normalized, requested_date)


async def _fetch_stooq_stock_price_series(
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[StockPriceObservation] | None:
    normalized = _normalize_symbol(symbol)
    params = {
        "s": _stooq_stock_symbol(normalized),
        "d1": start_date.strftime("%Y%m%d"),
        "d2": end_date.strftime("%Y%m%d"),
        "i": "d",
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.market_data_yahoo_timeout_seconds,
            headers={"User-Agent": "finance-report-audit/1.0"},
        ) as client:
            response = await client.get(_STOOQ_DAILY_URL, params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "Stooq stock range fetch failed",
            symbol=normalized,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            error=str(exc),
        )
        return None

    return _parse_stooq_stock_csv_series(response.text, normalized, start_date, end_date)


def _parse_stooq_stock_csv(
    payload: str,
    symbol: str,
    requested_date: date,
) -> StockPriceObservation | None:
    observations: list[StockPriceObservation] = []
    for row in csv.DictReader(StringIO(payload)):
        close = row.get("Close")
        row_date = row.get("Date")
        if not close or not row_date or close == "N/D":
            continue
        observed_date = date.fromisoformat(row_date)
        if observed_date > requested_date:
            continue
        observations.append(
            StockPriceObservation(
                symbol=symbol,
                price=_quantize_price(Decimal(close)),
                currency="USD",
                price_date=observed_date,
                source="stooq",
            )
        )
    if not observations:
        return None
    return max(observations, key=lambda item: item.price_date)


def _parse_stooq_stock_csv_series(
    payload: str,
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[StockPriceObservation]:
    observations: list[StockPriceObservation] = []
    for row in csv.DictReader(StringIO(payload)):
        close = row.get("Close")
        row_date = row.get("Date")
        if not close or not row_date or close == "N/D":
            continue
        observed_date = date.fromisoformat(row_date)
        if observed_date < start_date or observed_date > end_date:
            continue
        observations.append(
            StockPriceObservation(
                symbol=symbol,
                price=_quantize_price(Decimal(close)),
                currency="USD",
                price_date=observed_date,
                source="stooq",
            )
        )
    return observations
