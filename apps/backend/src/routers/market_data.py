"""Market data sync API router."""

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.deps import CurrentUserId, DbSession
from src.services.market_data import (
    MarketDataScopeStatus,
    MarketDataSyncResult,
    get_market_data_status,
    sync_fx_rates,
    sync_stock_prices,
)

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
        statuses = await get_market_data_status(
            db,
            pairs=pairs,
            symbols=symbols,
            user_id=user_id,
            include_default_fx=include_default_fx,
        )
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
        result = await sync_fx_rates(
            db,
            pairs=request.pairs,
            start_date=request.start_date,
            end_date=request.end_date,
            user_id=user_id,
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
        result = await sync_stock_prices(
            db,
            symbols=request.symbols,
            start_date=request.start_date,
            end_date=request.end_date,
            user_id=user_id,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _response_from_result(result)
