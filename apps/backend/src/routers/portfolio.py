"""Portfolio management API router."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.schemas.portfolio import HoldingResponse
from src.services import allocation, performance, portfolio

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = get_logger(__name__)


class AllocationBreakdownResponse(BaseModel):
    category: str
    value: Decimal = Field(decimal_places=2)
    percentage: Decimal = Field(decimal_places=2)
    count: int


class PerformanceMetricsResponse(BaseModel):
    xirr: Decimal = Field(decimal_places=2)
    time_weighted_return: Decimal = Field(decimal_places=2)
    money_weighted_return: Decimal = Field(decimal_places=2)


class PriceUpdateRequest(BaseModel):
    asset_identifier: str
    price: Decimal = Field(decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    effective_date: date


class PriceUpdateBatchRequest(BaseModel):
    updates: list[PriceUpdateRequest]


@router.get("/holdings", response_model=list[HoldingResponse])
async def get_holdings(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    include_disposed: bool = Query(False, description="Include disposed positions"),
) -> list[HoldingResponse]:
    """Get portfolio holdings with P&L."""
    logger.info(
        "Getting holdings",
        user_id=str(user_id),
        as_of_date=as_of_date,
        include_disposed=include_disposed,
        account_id=str(account_id) if account_id else None,
    )

    holdings = await portfolio.get_holdings(
        db=db,
        user_id=user_id,
        as_of_date=as_of_date or date.today(),
        include_disposed=include_disposed,
    )

    if account_id:
        holdings = [h for h in holdings if h.account_id == account_id]

    logger.info("Retrieved holdings", count=len(holdings))
    return holdings


@router.get("/performance", response_model=PerformanceMetricsResponse)
async def get_performance(
    db: DbSession,
    user_id: CurrentUserId,
    period_start: date | None = Query(None, description="Period start date (for TWR)"),
    period_end: date | None = Query(None, description="Period end date (for TWR, default: today)"),
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
) -> PerformanceMetricsResponse:
    """Calculate portfolio performance metrics (XIRR, TWR, MWR)."""
    logger.info(
        "Calculating performance",
        user_id=str(user_id),
        period_start=period_start,
        period_end=period_end,
        as_of_date=as_of_date,
        account_id=str(account_id) if account_id else None,
    )

    as_of = as_of_date or date.today()
    p_end = period_end or date.today()

    xirr = await performance.calculate_xirr(db=db, user_id=user_id, as_of_date=as_of)

    if period_start:
        twr = await performance.calculate_time_weighted_return(
            db=db,
            user_id=user_id,
            period_start=period_start,
            period_end=p_end,
        )
    else:
        twr = Decimal("0")

    mwr = await performance.calculate_money_weighted_return(
        db=db, user_id=user_id, as_of_date=as_of
    )

    logger.info("Performance calculated", xirr=float(xirr), twr=float(twr), mwr=float(mwr))
    return PerformanceMetricsResponse(xirr=xirr, time_weighted_return=twr, money_weighted_return=mwr)


@router.get("/allocation/sector", response_model=list[AllocationBreakdownResponse])
async def get_sector_allocation(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
) -> list[AllocationBreakdownResponse]:
    """Get sector allocation breakdown."""
    logger.info(
        "Getting sector allocation",
        user_id=str(user_id),
        as_of_date=as_of_date,
        account_id=str(account_id) if account_id else None,
    )

    breakdowns = await allocation.get_sector_allocation(
        db=db,
        user_id=user_id,
        as_of_date=as_of_date or date.today(),
    )

    logger.info("Retrieved sector allocation", count=len(breakdowns))
    return [AllocationBreakdownResponse(**b.to_dict()) for b in breakdowns]


@router.get("/allocation/geography", response_model=list[AllocationBreakdownResponse])
async def get_geography_allocation(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
) -> list[AllocationBreakdownResponse]:
    """Get geography allocation breakdown."""
    logger.info(
        "Getting geography allocation",
        user_id=str(user_id),
        as_of_date=as_of_date,
        account_id=str(account_id) if account_id else None,
    )

    breakdowns = await allocation.get_geography_allocation(
        db=db,
        user_id=user_id,
        as_of_date=as_of_date or date.today(),
    )

    logger.info("Retrieved geography allocation", count=len(breakdowns))
    return [AllocationBreakdownResponse(**b.to_dict()) for b in breakdowns]


@router.get("/allocation/asset-class", response_model=list[AllocationBreakdownResponse])
async def get_asset_class_allocation(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
) -> list[AllocationBreakdownResponse]:
    """Get asset class allocation breakdown."""
    logger.info(
        "Getting asset class allocation",
        user_id=str(user_id),
        as_of_date=as_of_date,
        account_id=str(account_id) if account_id else None,
    )

    breakdowns = await allocation.get_asset_class_allocation(
        db=db,
        user_id=user_id,
        as_of_date=as_of_date or date.today(),
    )

    logger.info("Retrieved asset class allocation", count=len(breakdowns))
    return [AllocationBreakdownResponse(**b.to_dict()) for b in breakdowns]


@router.post("/prices/update", status_code=status.HTTP_200_OK)
async def update_prices(
    db: DbSession,
    user_id: CurrentUserId,
    request: PriceUpdateBatchRequest,
) -> dict:
    """Update market prices manually (batch)."""
    logger.info(
        "Updating market prices",
        user_id=str(user_id),
        count=len(request.updates),
    )

    results = await portfolio.update_market_prices(
        db=db,
        user_id=user_id,
        updates=request.updates,
    )

    await db.commit()

    logger.info("Market prices updated", updated_count=len(results))
    return {"updated_count": len(results), "results": results}
