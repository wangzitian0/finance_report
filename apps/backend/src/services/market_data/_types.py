"""Market-data value objects."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


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


MarketObservation = FxRateObservation | StockPriceObservation


@dataclass(frozen=True)
class _MarketSyncSpec:
    kind: str
    parse_scope: Callable[[str], Any | None]
    scope_name: Callable[[Any], str]
    latest_date: Callable[[AsyncSession, Any], Awaitable[date | None]]
    stored_dates: Callable[[AsyncSession, Any, date, date], Awaitable[set[date]]]
    fetch_series: Callable[[Any, date, date], Awaitable[ValidatedMarketObservationSeries]]
    persist_observation: Callable[[AsyncSession, MarketObservation], Awaitable[Decimal]]
    observation_date: Callable[[MarketObservation], date]
    observation_matches_scope: Callable[[MarketObservation, Any], bool]
