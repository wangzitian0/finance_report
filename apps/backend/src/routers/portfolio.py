"""Portfolio management API router."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.audit.money import to_money
from src.audit.ratio import Ratio
from src.deps import CurrentUserId, DbSession
from src.extraction import BrokeragePositionImportService
from src.models.layer3 import ManagedPosition, PositionStatus
from src.models.portfolio import (
    DividendIncome,
    InvestmentTransaction,
    InvestmentTransactionType,
)
from src.observability import get_logger
from src.schemas.portfolio import (
    BrokerageImportRequest,
    BrokerageImportResponse,
    CostBasisMethodUpdateRequest,
    CostBasisMethodUpdateResponse,
    DividendEventResponse,
    HoldingResponse,
    InvestmentPerformanceReportScheduleResponse,
    PortfolioSummaryDashboardResponse,
    PriceUpdateBatchResponse,
    PriceUpdateRequest as SchemaPriceUpdateRequest,
    RealizedLotResponse,
)
from src.services import allocation, performance
from src.services.fx import FxRateError
from src.services.performance import InsufficientDataError, PerformanceError
from src.services.performance_report import build_investment_performance_report_schedule
from src.services.portfolio import AssetNotFoundError, PortfolioNotFoundError, portfolio_service

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = get_logger(__name__)

# Default cap + bounds for portfolio list endpoints (issue #1007, AC17.30).
# Matches the accounts module convention (limit default 100, ge=1, le=500).
_DEFAULT_LIST_LIMIT = 100
_MAX_LIST_LIMIT = 500

_portfolio_service = portfolio_service
_brokerage_import_service = BrokeragePositionImportService()


def _canonical_percent(value: Decimal) -> Decimal:
    percent_ratio = Ratio.from_percent(value)
    return percent_ratio.to_percent()


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
    price_date: date


class PriceUpdateBatchRequest(BaseModel):
    updates: list[PriceUpdateRequest]


class DividendCreateRequest(BaseModel):
    payment_date: date
    amount: Decimal = Field(decimal_places=2, gt=0)
    currency: str = Field(min_length=3, max_length=3)


@router.post("/brokerage/import", response_model=BrokerageImportResponse, status_code=status.HTTP_200_OK)
async def import_brokerage_positions(
    request: BrokerageImportRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BrokerageImportResponse:
    """Import parsed brokerage holdings into AtomicPosition and reconcile ManagedPosition."""
    result = await _brokerage_import_service.import_positions(
        db,
        user_id=user_id,
        payload=request.payload,
        filename=request.filename,
        source_document_id=request.source_document_id,
    )
    await db.commit()
    return BrokerageImportResponse(**result.__dict__)


@router.get("/holdings", response_model=list[HoldingResponse])
async def get_holdings(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    include_disposed: bool = Query(False, description="Include disposed positions"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[HoldingResponse]:
    """Get portfolio holdings with P&L (bounded by limit/offset; see AC17.30)."""
    logger.info(
        "Getting holdings",
        user_id=str(user_id),
        as_of_date=as_of_date,
        include_disposed=include_disposed,
        limit=limit,
        offset=offset,
    )

    try:
        holdings = await _portfolio_service.get_holdings(
            db=db,
            user_id=user_id,
            as_of_date=as_of_date,
            include_disposed=include_disposed,
        )
    except (PortfolioNotFoundError, AssetNotFoundError):
        # No holdings found — return empty list instead of error
        return []

    page = list(holdings)[offset : offset + limit]
    logger.info("Retrieved holdings", count=len(page), total=len(holdings))
    return page


@router.get("/summary", response_model=PortfolioSummaryDashboardResponse)
async def get_portfolio_summary(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
) -> PortfolioSummaryDashboardResponse:
    """Get portfolio summary with YTD realized P&L and dividend income."""
    report_date = as_of_date or date.today()
    try:
        summary = await _portfolio_service.get_portfolio_summary(db=db, user_id=user_id, as_of_date=as_of_date)
    except (PortfolioNotFoundError, AssetNotFoundError):
        return PortfolioSummaryDashboardResponse(
            total_market_value=Decimal("0.00"),
            total_cost_basis=Decimal("0.00"),
            total_unrealized_pnl=Decimal("0.00"),
            total_unrealized_pnl_percent=Decimal("0.00"),
            total_realized_pnl=Decimal("0.00"),
            total_realized_pnl_percent=Decimal("0.00"),
            net_pnl=Decimal("0.00"),
            net_pnl_percent=Decimal("0.00"),
            holdings_count=0,
            active_positions_count=0,
            disposed_positions_count=0,
            currency="SGD",
            realized_pnl_ytd=Decimal("0.00"),
            dividend_income_ytd=Decimal("0.00"),
        )

    year_start = date(report_date.year, 1, 1)
    summary_currency = summary.currency.upper()
    try:
        realized_by_asset, _ = await _portfolio_service.get_realized_pnl_by_asset(
            db, user_id, start_date=year_start, end_date=report_date, target_currency=summary_currency
        )
        dividend_by_asset = await _portfolio_service.get_dividend_income_by_asset(
            db, user_id, start_date=year_start, end_date=report_date, target_currency=summary_currency
        )
    except FxRateError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    data = summary.model_dump()
    data["realized_pnl_ytd"] = to_money(sum(realized_by_asset.values(), Decimal("0.00")))
    data["dividend_income_ytd"] = to_money(sum(dividend_by_asset.values(), Decimal("0.00")))
    return PortfolioSummaryDashboardResponse(**data)


@router.get("/{ticker}/dividends", response_model=list[DividendEventResponse])
async def get_holding_dividends(
    ticker: str,
    db: DbSession,
    user_id: CurrentUserId,
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[DividendEventResponse]:
    """List dividend events for a holding ticker (bounded by limit/offset; see AC17.30)."""
    result = await db.execute(
        select(DividendIncome)
        .join(ManagedPosition, DividendIncome.position_id == ManagedPosition.id)
        .where(DividendIncome.user_id == user_id)
        .where(ManagedPosition.user_id == user_id)
        .where(ManagedPosition.asset_identifier == ticker)
        .order_by(DividendIncome.payment_date.desc(), DividendIncome.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        DividendEventResponse(
            id=dividend.id,
            ex_date=dividend.payment_date,
            pay_date=dividend.payment_date,
            amount=dividend.amount,
            currency=dividend.currency,
            reinvested=False,
        )
        for dividend in result.scalars().all()
    ]


@router.post("/{ticker}/dividends", response_model=DividendEventResponse, status_code=status.HTTP_201_CREATED)
async def create_holding_dividend(
    ticker: str,
    request: DividendCreateRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> DividendEventResponse:
    """Record dividend income for an existing current-user holding."""
    position = await db.scalar(
        select(ManagedPosition)
        .where(ManagedPosition.user_id == user_id)
        .where(ManagedPosition.asset_identifier == ticker)
        .where(ManagedPosition.status == PositionStatus.ACTIVE)
        .order_by(ManagedPosition.created_at.desc())
    )
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")

    dividend = DividendIncome(
        user_id=user_id,
        position_id=position.id,
        payment_date=request.payment_date,
        amount=request.amount,
        currency=request.currency.upper(),
    )
    db.add(dividend)
    await db.commit()
    await db.refresh(dividend)
    return DividendEventResponse(
        id=dividend.id,
        ex_date=dividend.payment_date,
        pay_date=dividend.payment_date,
        amount=dividend.amount,
        currency=dividend.currency,
        reinvested=False,
    )


@router.get("/{ticker}/realized", response_model=list[RealizedLotResponse])
async def get_holding_realized_lots(
    ticker: str,
    db: DbSession,
    user_id: CurrentUserId,
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[RealizedLotResponse]:
    """List lot-level realized P&L rows for a holding ticker (bounded by limit/offset; see AC17.30)."""
    result = await db.execute(
        select(InvestmentTransaction, ManagedPosition)
        .outerjoin(ManagedPosition, InvestmentTransaction.position_id == ManagedPosition.id)
        .where(InvestmentTransaction.user_id == user_id)
        .where(InvestmentTransaction.transaction_type == InvestmentTransactionType.SELL)
        .where(InvestmentTransaction.asset_identifier == ticker)
        .order_by(InvestmentTransaction.transaction_date.desc(), InvestmentTransaction.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = []
    for txn, position in result.all():
        acquired_date = position.acquisition_date if position else None
        holding_period = (txn.transaction_date - acquired_date).days if acquired_date else None
        rows.append(
            RealizedLotResponse(
                lot_id=txn.id,
                acquired_date=acquired_date,
                sold_date=txn.transaction_date,
                quantity=txn.quantity or Decimal("0.000000"),
                basis=to_money(txn.cost_basis or Decimal("0.00")),
                proceeds=to_money(txn.gross_amount - txn.fees),
                gain_loss=to_money(txn.realized_pnl or Decimal("0.00")),
                holding_period=holding_period,
                currency=txn.currency,
            )
        )
    return rows


@router.patch("/{ticker}", response_model=CostBasisMethodUpdateResponse)
async def update_holding_cost_basis_method(
    ticker: str,
    request: CostBasisMethodUpdateRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> CostBasisMethodUpdateResponse:
    """Persist cost-basis method for all active positions matching a holding ticker."""
    result = await db.execute(
        select(ManagedPosition)
        .where(ManagedPosition.user_id == user_id)
        .where(ManagedPosition.asset_identifier == ticker)
        .where(ManagedPosition.status == PositionStatus.ACTIVE)
    )
    positions = list(result.scalars().all())
    if not positions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    for position in positions:
        position.cost_basis_method = request.cost_basis_method
    await db.commit()
    return CostBasisMethodUpdateResponse(
        updated_count=len(positions),
        cost_basis_method=request.cost_basis_method,
    )


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
    )

    as_of = as_of_date or date.today()
    p_end = period_end or date.today()

    try:
        xirr = await performance.calculate_xirr(db=db, user_id=user_id, as_of_date=as_of)
    except InsufficientDataError:
        xirr = Decimal("0")
    except PerformanceError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    if period_start:
        try:
            twr = await performance.calculate_time_weighted_return(
                db=db,
                user_id=user_id,
                period_start=period_start,
                period_end=p_end,
            )
        except InsufficientDataError:
            twr = Decimal("0")
    else:
        twr = Decimal("0")

    try:
        mwr = await performance.calculate_money_weighted_return(db=db, user_id=user_id, as_of_date=as_of)
    except InsufficientDataError:
        mwr = Decimal("0")
    except PerformanceError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    xirr = _canonical_percent(xirr)
    twr = _canonical_percent(twr)
    mwr = _canonical_percent(mwr)
    logger.info("Performance calculated", xirr=float(xirr), twr=float(twr), mwr=float(mwr))
    return PerformanceMetricsResponse(xirr=xirr, time_weighted_return=twr, money_weighted_return=mwr)


@router.get("/performance/report-schedule", response_model=InvestmentPerformanceReportScheduleResponse)
async def get_investment_performance_report_schedule(
    db: DbSession,
    user_id: CurrentUserId,
    period_start: date | None = Query(None, description="Report period start date (default: Jan 1 of period end year)"),
    period_end: date | None = Query(None, description="Report period end date (default: today)"),
    as_of_date: date | None = Query(None, description="Valuation date (default: period_end)"),
    currency: str = Query(default="SGD", min_length=3, max_length=3),
) -> InvestmentPerformanceReportScheduleResponse:
    """Build the report-ready investment performance schedule consumed by EPIC-005."""
    period_end = period_end or date.today()
    period_start = period_start or date(period_end.year, 1, 1)
    as_of_date = as_of_date or period_end

    if period_start > period_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="period_start must be <= period_end"
        )
    if as_of_date < period_end:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="as_of_date must be >= period_end")

    currency = currency.strip().upper()
    if currency != "SGD":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Investment performance report schedule currently supports SGD presentation currency",
        )

    try:
        return await build_investment_performance_report_schedule(
            db,
            user_id,
            period_start=period_start,
            period_end=period_end,
            as_of_date=as_of_date,
            currency=currency,
        )
    except FxRateError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/allocation/sector", response_model=list[AllocationBreakdownResponse])
async def get_sector_allocation(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[AllocationBreakdownResponse]:
    """Get sector allocation breakdown (bounded by limit/offset; see AC17.30)."""
    logger.info(
        "Getting sector allocation",
        user_id=str(user_id),
        as_of_date=as_of_date,
        limit=limit,
        offset=offset,
    )

    breakdowns = await allocation.get_sector_allocation(
        db=db,
        user_id=user_id,
        as_of_date=as_of_date or date.today(),
    )

    page = list(breakdowns)[offset : offset + limit]
    logger.info("Retrieved sector allocation", count=len(page), total=len(breakdowns))
    return [AllocationBreakdownResponse(**b.to_dict()) for b in page]


@router.get("/allocation/geography", response_model=list[AllocationBreakdownResponse])
async def get_geography_allocation(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[AllocationBreakdownResponse]:
    """Get geography allocation breakdown (bounded by limit/offset; see AC17.30)."""
    logger.info(
        "Getting geography allocation",
        user_id=str(user_id),
        as_of_date=as_of_date,
        limit=limit,
        offset=offset,
    )

    breakdowns = await allocation.get_geography_allocation(
        db=db,
        user_id=user_id,
        as_of_date=as_of_date or date.today(),
    )

    page = list(breakdowns)[offset : offset + limit]
    logger.info("Retrieved geography allocation", count=len(page), total=len(breakdowns))
    return [AllocationBreakdownResponse(**b.to_dict()) for b in page]


@router.get("/allocation/asset-class", response_model=list[AllocationBreakdownResponse])
async def get_asset_class_allocation(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[AllocationBreakdownResponse]:
    """Get asset class allocation breakdown (bounded by limit/offset; see AC17.30)."""
    logger.info(
        "Getting asset class allocation",
        user_id=str(user_id),
        as_of_date=as_of_date,
        limit=limit,
        offset=offset,
    )

    breakdowns = await allocation.get_asset_class_allocation(
        db=db,
        user_id=user_id,
        as_of_date=as_of_date or date.today(),
    )

    page = list(breakdowns)[offset : offset + limit]
    logger.info("Retrieved asset class allocation", count=len(page), total=len(breakdowns))
    return [AllocationBreakdownResponse(**b.to_dict()) for b in page]


@router.post("/prices/update", response_model=PriceUpdateBatchResponse, status_code=status.HTTP_200_OK)
async def update_prices(
    db: DbSession,
    user_id: CurrentUserId,
    request: PriceUpdateBatchRequest,
) -> PriceUpdateBatchResponse:
    """Update market prices manually (batch)."""
    logger.info(
        "Updating market prices",
        user_id=str(user_id),
        count=len(request.updates),
    )

    # Map router request models to service schema models
    schema_updates = [
        SchemaPriceUpdateRequest(
            asset_identifier=u.asset_identifier,
            price_date=u.price_date,
            price=u.price,
            currency=u.currency,
        )
        for u in request.updates
    ]

    results = await _portfolio_service.update_market_prices(
        db=db,
        user_id=user_id,
        updates=schema_updates,
    )

    await db.commit()

    logger.info("Market prices updated", updated_count=len(results))
    return PriceUpdateBatchResponse(updated_count=len(results), results=results)
