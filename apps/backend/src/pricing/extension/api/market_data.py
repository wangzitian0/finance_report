"""Market data sync API router."""

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.deps import CurrentUserId, DbSession
from src.pricing import (
    MarketDataScopeStatus,
    MarketDataSyncResult,
    get_market_data_status,
    sync_fx_rates,
    sync_stock_prices,
)

_ACTIVE_STOCK_SYMBOLS_PROVIDER: Callable[[Any, Any], Awaitable[Any]] | None = None


def register_active_stock_symbols_provider(provider: Callable[[Any, Any], Awaitable[Any]]) -> None:
    global _ACTIVE_STOCK_SYMBOLS_PROVIDER
    _ACTIVE_STOCK_SYMBOLS_PROVIDER = provider


router = APIRouter(prefix="/market-data", tags=["market-data"])


class MarketDataSyncRequest(BaseModel):
    """Market data sync request for scheduler or E2E callers."""

    start_date: date | None = None
    end_date: date | None = None
    pairs: list[str] | None = Field(default=None, description="FX pairs in BASE/QUOTE format")
    symbols: list[str] | None = Field(default=None, description="Stock symbols")


class ProviderDisagreementResponse(BaseModel):
    """Provider disagreement payload."""

    asset: str
    observed_date: date
    primary_source: str
    secondary_source: str
    primary_value: str
    secondary_value: str
    relative_difference: str
    threshold: str


class MarketDataSyncResponse(BaseModel):
    """Scheduler-friendly market data sync counters."""

    kind: str
    requested: int
    inserted: int
    skipped: int
    missing: int
    disagreements: list[ProviderDisagreementResponse]


class MarketDataStatusResponse(BaseModel):
    """Read-only market data freshness status for authenticated users."""

    kind: str
    scope: str
    fresh: bool
    last_success_at: str | None
    last_success_date: str | None
    last_observation_date: str | None


def _response_from_result(result: MarketDataSyncResult) -> MarketDataSyncResponse:
    return MarketDataSyncResponse.model_validate(result.to_dict())


def _status_response(status_result: MarketDataScopeStatus) -> MarketDataStatusResponse:
    return MarketDataStatusResponse.model_validate(status_result.to_dict())


@router.get("/status", response_model=list[MarketDataStatusResponse], status_code=status.HTTP_200_OK)
async def market_data_status_endpoint(
    db: DbSession,
    user_id: CurrentUserId,
    pairs: list[str] | None = Query(default=None, description="FX pairs in BASE/QUOTE format"),
    symbols: list[str] | None = Query(default=None, description="Stock symbols"),
    include_default_fx: bool = Query(default=False),
) -> list[MarketDataStatusResponse]:
    """Return read-only market data freshness status for observed or explicit scopes."""
    try:
        from src.composition import observed_fx_pairs

        sync_pairs = (
            pairs if pairs is not None else await observed_fx_pairs(db, user_id, include_default=include_default_fx)
        )
        if symbols is None:
            if _ACTIVE_STOCK_SYMBOLS_PROVIDER is None:
                raise RuntimeError("Active stock symbols provider not registered")
            sync_symbols = await _ACTIVE_STOCK_SYMBOLS_PROVIDER(db, user_id)
        else:
            sync_symbols = symbols
        statuses = await get_market_data_status(db, pairs=sync_pairs, symbols=sync_symbols)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return [_status_response(item) for item in statuses]


@router.post("/fx/syncs", response_model=MarketDataSyncResponse, status_code=status.HTTP_200_OK)
async def sync_fx_endpoint(
    request: MarketDataSyncRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> MarketDataSyncResponse:
    """Incrementally fill FX rows for explicit or observed pairs."""
    try:
        from src.composition import observed_fx_pairs

        sync_pairs = request.pairs if request.pairs is not None else await observed_fx_pairs(db, user_id)
        result = await sync_fx_rates(
            db,
            pairs=sync_pairs,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _response_from_result(result)


@router.post("/stocks/syncs", response_model=MarketDataSyncResponse, status_code=status.HTTP_200_OK)
async def sync_stocks_endpoint(
    request: MarketDataSyncRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> MarketDataSyncResponse:
    """Incrementally fill stock prices for explicit symbols or active holdings."""
    try:
        if request.symbols is None:
            if _ACTIVE_STOCK_SYMBOLS_PROVIDER is None:
                raise RuntimeError("Active stock symbols provider not registered")
            sync_symbols = await _ACTIVE_STOCK_SYMBOLS_PROVIDER(db, user_id)
        else:
            sync_symbols = request.symbols
        result = await sync_stock_prices(
            db,
            symbols=sync_symbols,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _response_from_result(result)
