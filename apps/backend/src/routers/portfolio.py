"""Portfolio management API router."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.audit import Ratio, to_money
from src.deps import CurrentUserId, DbSession
from src.extraction import BrokeragePositionImportService, ManagedPosition, PositionStatus
from src.observability import get_logger
from src.portfolio import (
    AssetNotFoundError,
    InsufficientDataError,
    InvestmentAccountingService,
    InvestmentAccountingValidationError,
    InvestmentTransaction,
    InvestmentTransactionType,
    PerformanceError,
    PortfolioNotFoundError,
    PositionServiceError,
    build_investment_performance_report_schedule,
    calculate_money_weighted_return,
    calculate_time_weighted_return,
    calculate_xirr,
    get_asset_class_allocation as asset_class_allocation_breakdowns,
    get_geography_allocation as geography_allocation_breakdowns,
    get_sector_allocation as sector_allocation_breakdowns,
    portfolio_service,
)
from src.pricing import PricingError
from src.schemas.portfolio import (
    BrokerageImportRequest,
    BrokerageImportResponse,
    CostBasisMethodUpdateRequest,
    CostBasisMethodUpdateResponse,
    DividendEventResponse,
    HoldingsListResponse,
    InvestmentPerformanceReportScheduleResponse,
    PerformanceMetricsResponse,
    PortfolioSummaryDashboardResponse,
    PriceUpdateBatchResponse,
    PriceUpdateRequest,
    RealizedLotResponse,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = get_logger(__name__)

_DEFAULT_LIST_LIMIT = 100
_MAX_LIST_LIMIT = 500

_portfolio_service = portfolio_service
_brokerage_import_service = BrokeragePositionImportService()
_investment_accounting_service = InvestmentAccountingService()


def _canonical_percent(value: Decimal) -> Decimal:
    percent_ratio = Ratio.from_percent(value)
    return percent_ratio.to_percent()


class AllocationBreakdownResponse(BaseModel):
    category: str
    value: Decimal = Field(decimal_places=2)
    percentage: Decimal = Field(decimal_places=2)
    count: int


class PriceUpdateBatchRequest(BaseModel):
    updates: list[PriceUpdateRequest]


class DividendCreateRequest(BaseModel):
    payment_date: date
    amount: Decimal = Field(decimal_places=2, gt=0)
    currency: str = Field(min_length=3, max_length=3)
    dividend_type: str = "ordinary"
    notes: str | None = None
    cash_account_id: UUID | None = None
    dividend_income_account_id: UUID | None = None
    withholding_tax: Decimal = Field(default=Decimal("0.00"), decimal_places=2, ge=0)
    withholding_tax_account_id: UUID | None = None


@router.post("/brokerage/import", response_model=BrokerageImportResponse, status_code=status.HTTP_200_OK)
async def import_brokerage_positions(
    request: BrokerageImportRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BrokerageImportResponse:
    """Import parsed brokerage holdings into AtomicPosition and reconcile ManagedPosition."""
    try:
        result = await _brokerage_import_service.import_positions(
            db,
            user_id=user_id,
            payload=request.payload,
            filename=request.filename,
            source_document_id=request.source_document_id,
        )
        await db.commit()
    except PositionServiceError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return BrokerageImportResponse(**result.__dict__)


@router.get("/holdings", response_model=HoldingsListResponse)
async def get_holdings(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    include_disposed: bool = Query(False, description="Include disposed positions"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> HoldingsListResponse:
    """Get portfolio holdings with P&L (bounded by limit/offset; see AC17.30).

    AC-portfolio.holdings.6 (#1796): responds in the repo-standard items+total
    wrapper plus ``warnings`` — a snapshot excluded from the page (no reconciled
    managed position as of the date) is disclosed to the caller, not just logged.
    """
    warnings: list[dict[str, str]] = []
    try:
        holdings = list(
            await _portfolio_service.get_holdings(
                db=db,
                user_id=user_id,
                as_of_date=as_of_date,
                include_disposed=include_disposed,
                warnings=warnings,
            )
        )
    except (PortfolioNotFoundError, AssetNotFoundError):
        return HoldingsListResponse(items=[], total=0, warnings=warnings)

    page = holdings[offset : offset + limit]
    return HoldingsListResponse(items=page, total=len(holdings), warnings=warnings)


@router.get("/summary", response_model=PortfolioSummaryDashboardResponse)
async def get_portfolio_summary(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
) -> PortfolioSummaryDashboardResponse:
    """Get portfolio summary with YTD realized P&L and dividend income."""
    try:
        return await _portfolio_service.get_portfolio_summary_dashboard(db=db, user_id=user_id, as_of_date=as_of_date)
    except PricingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{ticker}/dividends", response_model=list[DividendEventResponse])
async def get_holding_dividends(
    ticker: str,
    db: DbSession,
    user_id: CurrentUserId,
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[DividendEventResponse]:
    """List dividend events for a holding ticker (bounded by limit/offset; see AC17.30)."""
    dividends = await _investment_accounting_service.list_holding_dividends(
        db, user_id=user_id, ticker=ticker, limit=limit, offset=offset
    )
    return [
        DividendEventResponse(
            id=dividend.id,
            ex_date=dividend.payment_date,
            pay_date=dividend.payment_date,
            amount=dividend.amount,
            currency=dividend.currency,
            reinvested=False,
            journal_entry_id=getattr(dividend, "journal_entry_id", None),
        )
        for dividend in dividends
    ]


@router.post("/{ticker}/dividends", response_model=DividendEventResponse, status_code=status.HTTP_201_CREATED)
async def create_holding_dividend(
    ticker: str,
    request: DividendCreateRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> DividendEventResponse:
    """Record dividend income for an existing current-user holding via InvestmentAccountingService."""
    try:
        dividend = await _investment_accounting_service.record_holding_dividend(
            db,
            user_id=user_id,
            ticker=ticker,
            payment_date=request.payment_date,
            amount=request.amount,
            currency=request.currency,
            dividend_type=request.dividend_type,
            withholding_tax=request.withholding_tax,
            cash_account_id=request.cash_account_id,
            dividend_income_account_id=request.dividend_income_account_id,
            withholding_tax_account_id=request.withholding_tax_account_id,
        )
    except PortfolioNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (InvestmentAccountingValidationError, PricingError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    journal_entry_id = getattr(dividend, "journal_entry_id", None)
    await db.commit()
    await db.refresh(dividend)
    return DividendEventResponse(
        id=dividend.id,
        ex_date=dividend.payment_date,
        pay_date=dividend.payment_date,
        amount=dividend.amount,
        currency=dividend.currency,
        reinvested=False,
        journal_entry_id=journal_entry_id,
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
    as_of = as_of_date or date.today()
    p_end = period_end or date.today()
    unavailable_reasons: dict[str, str] = {}

    try:
        xirr: Decimal | None = _canonical_percent(await calculate_xirr(db=db, user_id=user_id, as_of_date=as_of))
    except InsufficientDataError as e:
        xirr = None
        unavailable_reasons["xirr"] = str(e)
    except (PerformanceError, PricingError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    if period_start:
        has_position = await db.scalar(select(ManagedPosition.id).where(ManagedPosition.user_id == user_id).limit(1))
        if has_position is None:
            twr: Decimal | None = None
            unavailable_reasons["time_weighted_return"] = "No positions found for time-weighted return calculation"
        else:
            try:
                twr = _canonical_percent(
                    await calculate_time_weighted_return(
                        db=db,
                        user_id=user_id,
                        period_start=period_start,
                        period_end=p_end,
                    )
                )
            except InsufficientDataError as e:
                twr = None
                unavailable_reasons["time_weighted_return"] = str(e)
            except PricingError as e:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    else:
        twr = None
        unavailable_reasons["time_weighted_return"] = "period_start is required for time-weighted return calculation"

    try:
        mwr: Decimal | None = _canonical_percent(
            await calculate_money_weighted_return(db=db, user_id=user_id, as_of_date=as_of)
        )
    except InsufficientDataError as e:
        mwr = None
        unavailable_reasons["money_weighted_return"] = str(e)
    except (PerformanceError, PricingError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    return PerformanceMetricsResponse(
        xirr=xirr,
        time_weighted_return=twr,
        money_weighted_return=mwr,
        unavailable_reasons=unavailable_reasons,
    )


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
    except PricingError as exc:
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
    breakdowns = await sector_allocation_breakdowns(db=db, user_id=user_id, as_of_date=as_of_date or date.today())
    page = list(breakdowns)[offset : offset + limit]
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
    breakdowns = await geography_allocation_breakdowns(db=db, user_id=user_id, as_of_date=as_of_date or date.today())
    page = list(breakdowns)[offset : offset + limit]
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
    breakdowns = await asset_class_allocation_breakdowns(db=db, user_id=user_id, as_of_date=as_of_date or date.today())
    page = list(breakdowns)[offset : offset + limit]
    return [AllocationBreakdownResponse(**b.to_dict()) for b in page]


@router.post("/prices/update", response_model=PriceUpdateBatchResponse, status_code=status.HTTP_200_OK)
async def update_prices(
    db: DbSession,
    user_id: CurrentUserId,
    request: PriceUpdateBatchRequest,
) -> PriceUpdateBatchResponse:
    """Update market prices manually (batch)."""
    results = await _portfolio_service.update_market_prices(db=db, user_id=user_id, updates=request.updates)
    await db.commit()
    return PriceUpdateBatchResponse(updated_count=len(results), results=results)
