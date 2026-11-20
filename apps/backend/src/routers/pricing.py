"""Unified pricing, market data sync, and manual valuation API router."""

from datetime import date

from fastapi import APIRouter, Query, status

from src.composition import active_stock_symbols, known_user_asset_identifiers, observed_fx_pairs
from src.deps import Ctx, ReadCtx
from src.observability import get_logger
from src.platform import InternalServiceError, ValidationFailedError
from src.pricing import (
    ManualValuationComponentType,
    MarketDataScopeStatus,
    MarketDataSyncResult,
    ValuationService,
    get_market_data_status,
    record_override,
    sync_fx_rates,
    sync_stock_prices,
)
from src.schemas.pricing import (
    ManualValuationSnapshotCreate,
    ManualValuationSnapshotListResponse,
    ManualValuationSnapshotResponse,
    MarketDataStatusResponse,
    MarketDataSyncRequest,
    MarketDataSyncResponse,
    PriceUpdateBatchRequest,
    PriceUpdateBatchResponse,
    PriceUpdateResponse,
    ValuationComponentResponse,
    ValuationComponentsResponse,
)

router = APIRouter(prefix="/pricing", tags=["pricing"])
logger = get_logger(__name__)

_valuations = ValuationService()


def _response_from_result(result: MarketDataSyncResult) -> MarketDataSyncResponse:
    return MarketDataSyncResponse.model_validate(result.to_dict())


def _status_response(status_result: MarketDataScopeStatus) -> MarketDataStatusResponse:
    return MarketDataStatusResponse.model_validate(status_result.to_dict())


def _parse_component_type(component_type: str | None) -> ManualValuationComponentType | None:
    if not component_type:
        return None
    try:
        return ManualValuationComponentType(component_type)
    except ValueError as exc:
        raise ValidationFailedError(f"Unsupported component_type: {component_type}") from exc


@router.get("/market-data/status", response_model=list[MarketDataStatusResponse], status_code=status.HTTP_200_OK)
async def market_data_status_endpoint(
    ctx: ReadCtx,
    pairs: list[str] | None = Query(default=None, description="FX pairs in BASE/QUOTE format"),
    symbols: list[str] | None = Query(default=None, description="Stock symbols"),
    include_default_fx: bool = Query(default=False),
) -> list[MarketDataStatusResponse]:
    """Return read-only market data freshness status for observed or explicit scopes."""
    db, user_id = ctx.db, ctx.user_id
    sync_pairs = (
        pairs if pairs is not None else await observed_fx_pairs(db, user_id, include_default=include_default_fx)
    )
    sync_symbols = symbols if symbols is not None else await active_stock_symbols(db, user_id)
    statuses = await get_market_data_status(db, pairs=sync_pairs, symbols=sync_symbols)
    return [_status_response(item) for item in statuses]


@router.post("/fx/syncs", response_model=MarketDataSyncResponse, status_code=status.HTTP_200_OK)
async def sync_fx_endpoint(
    request: MarketDataSyncRequest,
    ctx: Ctx,
) -> MarketDataSyncResponse:
    """Incrementally fill FX rows for explicit or observed pairs."""
    db, user_id = ctx.db, ctx.user_id
    sync_pairs = request.pairs if request.pairs is not None else await observed_fx_pairs(db, user_id)
    result = await sync_fx_rates(
        db,
        pairs=sync_pairs,
        start_date=request.start_date,
        end_date=request.end_date,
    )
    return _response_from_result(result)


@router.post("/stocks/syncs", response_model=MarketDataSyncResponse, status_code=status.HTTP_200_OK)
async def sync_stocks_endpoint(
    request: MarketDataSyncRequest,
    ctx: Ctx,
) -> MarketDataSyncResponse:
    """Incrementally fill stock prices for explicit symbols or active holdings."""
    db, user_id = ctx.db, ctx.user_id
    sync_symbols = request.symbols if request.symbols is not None else await active_stock_symbols(db, user_id)
    result = await sync_stock_prices(
        db,
        symbols=sync_symbols,
        start_date=request.start_date,
        end_date=request.end_date,
    )
    return _response_from_result(result)


@router.post("/price-overrides", response_model=PriceUpdateBatchResponse, status_code=status.HTTP_200_OK)
async def create_price_overrides(
    ctx: Ctx,
    request: PriceUpdateBatchRequest,
) -> PriceUpdateBatchResponse:
    """Record manual security price overrides through pricing's observation SSOT."""
    db, user_id = ctx.db, ctx.user_id
    requested_assets = {u.asset_identifier for u in request.updates}
    known_assets = await known_user_asset_identifiers(db, user_id, requested_assets)

    results: list[PriceUpdateResponse] = []
    for update in request.updates:
        if update.asset_identifier not in known_assets:
            results.append(
                PriceUpdateResponse(
                    success=False,
                    message=f"Asset {update.asset_identifier} not found for user",
                    asset_identifier=update.asset_identifier,
                    price_date=update.price_date,
                    price=update.price,
                    currency=update.currency,
                    source="",
                    created_at=None,
                )
            )
            continue
        obs = await record_override(
            db,
            user_id,
            asset_identifier=update.asset_identifier,
            as_of=update.price_date,
            price=update.price,
            currency=update.currency,
        )
        results.append(
            PriceUpdateResponse(
                success=True,
                message="Price updated successfully",
                asset_identifier=update.asset_identifier,
                price_date=update.price_date,
                price=update.price,
                currency=update.currency,
                source="manual",
                created_at=obs.observed_at,
            )
        )
    await db.flush()
    return PriceUpdateBatchResponse(updated_count=len(results), results=results)


@router.post(
    "/manual-valuations",
    response_model=ManualValuationSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_valuation(
    payload: ManualValuationSnapshotCreate,
    ctx: Ctx,
) -> ManualValuationSnapshotResponse:
    """Create or append a versioned manual valuation snapshot."""
    db, user_id = ctx.db, ctx.user_id
    try:
        snapshot = await _valuations.create_valuation_snapshot(
            db,
            user_id,
            component_type=payload.component_type,
            as_of_date=payload.as_of_date,
            value=payload.value,
            currency=payload.currency,
            source=payload.source,
            valuation_basis=payload.valuation_basis,
            notes=payload.notes,
            liquidity_class=payload.liquidity_class,
            recurrence_days=payload.recurrence_days,
            reminder_date=payload.reminder_date,
        )
        await db.flush()
        await db.refresh(snapshot)
    except Exception as e:
        logger.error("Manual valuation snapshot create failed", error=str(e), user_id=str(user_id))
        raise InternalServiceError("Manual valuation snapshot create failed") from e

    return ManualValuationSnapshotResponse.model_validate(snapshot)


@router.get("/manual-valuations", response_model=ManualValuationSnapshotListResponse)
async def list_manual_valuations(
    ctx: ReadCtx,
    as_of_date: date | None = Query(default=None),
    component_type: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ManualValuationSnapshotListResponse:
    """List current manual valuation snapshots."""
    parsed_component_type = _parse_component_type(component_type)

    snapshots, total = await _valuations.list_valuation_snapshots(
        ctx.db,
        ctx.user_id,
        as_of_date=as_of_date,
        component_type=parsed_component_type,
        limit=limit,
        offset=offset,
    )
    return ManualValuationSnapshotListResponse(
        items=[ManualValuationSnapshotResponse.model_validate(snapshot) for snapshot in snapshots],
        total=total,
    )


@router.get("/valuation-components", response_model=ValuationComponentsResponse)
async def list_valuation_components(
    ctx: ReadCtx,
    as_of_date: date | None = Query(default=None),
    include_restricted: bool = Query(default=True),
) -> ValuationComponentsResponse:
    """List latest manual valuation components as of a date."""
    result = await _valuations.get_latest_valuation_components(
        ctx.db,
        ctx.user_id,
        as_of_date=as_of_date or date.today(),
        include_restricted=include_restricted,
    )
    return ValuationComponentsResponse(
        items=[ValuationComponentResponse.model_validate(item.__dict__) for item in result.items],
        total_assets=result.total_assets,
        total_liabilities=result.total_liabilities,
        net_worth_delta=result.net_worth_delta,
        warnings=result.warnings,
    )
