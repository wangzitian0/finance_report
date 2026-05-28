"""Market data sync API router."""

from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.deps import CurrentUserId, DbSession
from src.services.market_data import MarketDataSyncResult, sync_fx_rates, sync_stock_prices

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


def _response_from_result(result: MarketDataSyncResult) -> MarketDataSyncResponse:
    return MarketDataSyncResponse.model_validate(result.to_dict())


@router.post("/sync/fx", response_model=MarketDataSyncResponse, status_code=status.HTTP_200_OK)
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
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _response_from_result(result)


@router.post("/sync/stocks", response_model=MarketDataSyncResponse, status_code=status.HTTP_200_OK)
async def sync_stocks_endpoint(
    request: MarketDataSyncRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> MarketDataSyncResponse:
    """Incrementally fill stock prices for explicit symbols or active holdings."""
    result = await sync_stock_prices(
        db,
        symbols=request.symbols,
        start_date=request.start_date,
        end_date=request.end_date,
        user_id=user_id,
    )
    return _response_from_result(result)
