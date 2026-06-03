"""Portfolio management API router."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus
from src.models.market_data import StockPrice
from src.models.portfolio import (
    DividendIncome,
    InvestmentTransaction,
    InvestmentTransactionType,
    MarketDataOverride,
    PriceSource,
)
from src.schemas.portfolio import (
    BrokerageImportRequest,
    BrokerageImportResponse,
    CostBasisMethodUpdateRequest,
    DividendEventResponse,
    HoldingResponse,
    InvestmentPerformanceAllocationRow,
    InvestmentPerformanceDataFreshness,
    InvestmentPerformanceHoldingRow,
    InvestmentPerformanceReportScheduleResponse,
    PortfolioSummaryDashboardResponse,
    PriceUpdateRequest as SchemaPriceUpdateRequest,
    RealizedLotResponse,
)
from src.services import allocation, performance
from src.services.brokerage_positions import BrokeragePositionImportService
from src.services.fx import FxRateError, convert_amount
from src.services.performance import InsufficientDataError, PerformanceError
from src.services.portfolio import AssetNotFoundError, PortfolioNotFoundError, PortfolioService

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = get_logger(__name__)

_portfolio_service = PortfolioService()
_brokerage_import_service = BrokeragePositionImportService()


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


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _percent(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _source_document_links(source_documents: object) -> list[str]:
    if isinstance(source_documents, list):
        docs = source_documents
    elif isinstance(source_documents, dict):
        docs = source_documents.get("documents") or source_documents.get("source_documents") or [source_documents]
    else:
        docs = []

    links: list[str] = []
    for doc in docs:
        if isinstance(doc, dict):
            doc_type = doc.get("doc_type") or doc.get("type") or "source"
            doc_id = doc.get("doc_id") or doc.get("id") or doc.get("source_id")
            if doc_id:
                links.append(f"{doc_type}:{doc_id}")
    return links


def _freshness_link(asset_identifier: str, source_kind: str, source_id: object, evidence_date: date) -> str:
    return f"price_source:{source_kind}:{asset_identifier}:{source_id}:{evidence_date.isoformat()}"


async def _report_preparation_holdings(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date,
) -> list[HoldingResponse]:
    """Load current holdings only when post-period manual prices evidence report preparation."""
    override_result = await db.execute(
        select(MarketDataOverride)
        .where(MarketDataOverride.user_id == user_id)
        .where(MarketDataOverride.source == PriceSource.MANUAL)
        .where(MarketDataOverride.price_date > as_of_date)
        .order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
    )
    override_assets = {override.asset_identifier for override in override_result.scalars().all()}
    if not override_assets:
        return []

    try:
        current_holdings = await _portfolio_service.get_holdings(
            db=db,
            user_id=user_id,
            include_disposed=True,
        )
    except (PortfolioNotFoundError, AssetNotFoundError):
        return []

    return [
        holding
        for holding in current_holdings
        if holding.asset_identifier in override_assets and holding.status == PositionStatus.ACTIVE
    ]


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
) -> list[HoldingResponse]:
    """Get portfolio holdings with P&L."""
    logger.info(
        "Getting holdings",
        user_id=str(user_id),
        as_of_date=as_of_date,
        include_disposed=include_disposed,
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

    logger.info("Retrieved holdings", count=len(holdings))
    return holdings


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
    realized_result = await db.execute(
        select(InvestmentTransaction)
        .where(InvestmentTransaction.user_id == user_id)
        .where(InvestmentTransaction.transaction_type == InvestmentTransactionType.SELL)
        .where(InvestmentTransaction.transaction_date >= year_start)
        .where(InvestmentTransaction.transaction_date <= report_date)
    )
    summary_currency = summary.currency.upper()
    realized_pnl_ytd = Decimal("0.00")
    for txn in realized_result.scalars().all():
        realized_amount = txn.realized_pnl or Decimal("0.00")
        try:
            realized_pnl_ytd += await convert_amount(
                db,
                realized_amount,
                txn.currency,
                summary_currency,
                txn.transaction_date,
                lazy_load=True,
            )
        except FxRateError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    dividend_result = await db.execute(
        select(DividendIncome)
        .where(DividendIncome.user_id == user_id)
        .where(DividendIncome.payment_date >= year_start)
        .where(DividendIncome.payment_date <= report_date)
    )
    dividend_income_ytd = Decimal("0.00")
    for dividend in dividend_result.scalars().all():
        try:
            dividend_income_ytd += await convert_amount(
                db,
                dividend.amount,
                dividend.currency,
                summary_currency,
                dividend.payment_date,
                lazy_load=True,
            )
        except FxRateError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    data = summary.model_dump()
    data["realized_pnl_ytd"] = Decimal(realized_pnl_ytd).quantize(Decimal("0.01"))
    data["dividend_income_ytd"] = Decimal(dividend_income_ytd).quantize(Decimal("0.01"))
    return PortfolioSummaryDashboardResponse(**data)


@router.get("/{ticker}/dividends", response_model=list[DividendEventResponse])
async def get_holding_dividends(
    ticker: str,
    db: DbSession,
    user_id: CurrentUserId,
) -> list[DividendEventResponse]:
    """List dividend events for a holding ticker."""
    result = await db.execute(
        select(DividendIncome)
        .join(ManagedPosition, DividendIncome.position_id == ManagedPosition.id)
        .where(DividendIncome.user_id == user_id)
        .where(ManagedPosition.user_id == user_id)
        .where(ManagedPosition.asset_identifier == ticker)
        .order_by(DividendIncome.payment_date.desc())
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
) -> list[RealizedLotResponse]:
    """List lot-level realized P&L rows for a holding ticker."""
    result = await db.execute(
        select(InvestmentTransaction, ManagedPosition)
        .outerjoin(ManagedPosition, InvestmentTransaction.position_id == ManagedPosition.id)
        .where(InvestmentTransaction.user_id == user_id)
        .where(InvestmentTransaction.transaction_type == InvestmentTransactionType.SELL)
        .where(InvestmentTransaction.asset_identifier == ticker)
        .order_by(InvestmentTransaction.transaction_date.desc())
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
                basis=(txn.cost_basis or Decimal("0.00")).quantize(Decimal("0.01")),
                proceeds=(txn.gross_amount - txn.fees).quantize(Decimal("0.01")),
                gain_loss=(txn.realized_pnl or Decimal("0.00")).quantize(Decimal("0.01")),
                holding_period=holding_period,
                currency=txn.currency,
            )
        )
    return rows


@router.patch("/{ticker}", response_model=dict)
async def update_holding_cost_basis_method(
    ticker: str,
    request: CostBasisMethodUpdateRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> dict:
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
    return {"updated_count": len(positions), "cost_basis_method": request.cost_basis_method.value}


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

    _two_dp = Decimal("0.01")
    xirr = xirr.quantize(_two_dp, rounding=ROUND_HALF_UP)
    twr = twr.quantize(_two_dp, rounding=ROUND_HALF_UP)
    mwr = mwr.quantize(_two_dp, rounding=ROUND_HALF_UP)
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

    notes: list[str] = [
        "Cost basis uses the holding-level cost-basis method where available.",
        (
            "Market values use the latest available brokerage or market-data snapshot on or before the as-of date; "
            "report-preparation overrides after the as-of date are disclosed when they evidence active holdings."
        ),
    ]

    used_report_preparation_evidence = False
    try:
        holdings = list(
            await _portfolio_service.get_holdings(
                db=db,
                user_id=user_id,
                as_of_date=as_of_date,
                include_disposed=True,
            )
        )
    except (PortfolioNotFoundError, AssetNotFoundError):
        holdings = []

    if not holdings:
        holdings = await _report_preparation_holdings(db=db, user_id=user_id, as_of_date=as_of_date)
        used_report_preparation_evidence = bool(holdings)
        if used_report_preparation_evidence:
            notes.append(
                "No holdings snapshot existed on or before the as-of date; the schedule used active holdings "
                "with post-period manual market-data overrides as report-preparation evidence."
            )
        else:
            notes.append("No portfolio holdings were available for the requested as-of date.")

    asset_identifiers = [holding.asset_identifier for holding in holdings]
    position_by_asset: dict[str, ManagedPosition] = {}
    if asset_identifiers:
        position_result = await db.execute(
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .where(ManagedPosition.asset_identifier.in_(asset_identifiers))
        )
        position_by_asset = {position.asset_identifier: position for position in position_result.scalars().all()}

    async def _schedule_amount(amount: Decimal, source_currency: str, rate_date: date) -> Decimal:
        try:
            return await convert_amount(
                db,
                amount,
                source_currency,
                currency,
                rate_date,
                lazy_load=True,
            )
        except FxRateError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    async def _metric_or_note(metric_name: str, calculation):
        try:
            return await calculation()
        except InsufficientDataError as exc:
            notes.append(f"{metric_name} unavailable: {exc}")
            return None
        except PerformanceError as exc:
            notes.append(f"{metric_name} unavailable: {exc}")
            return None

    xirr = await _metric_or_note(
        "XIRR", lambda: performance.calculate_xirr(db=db, user_id=user_id, as_of_date=as_of_date)
    )
    twr = await _metric_or_note(
        "TWR",
        lambda: performance.calculate_time_weighted_return(
            db=db,
            user_id=user_id,
            period_start=period_start,
            period_end=period_end,
        ),
    )
    mwr = await _metric_or_note(
        "MWR",
        lambda: performance.calculate_money_weighted_return(db=db, user_id=user_id, as_of_date=as_of_date),
    )
    dividend_yield = await _metric_or_note(
        "Dividend yield",
        lambda: performance.calculate_dividend_yield(db=db, user_id=user_id, as_of_date=as_of_date),
    )

    realized_result = await db.execute(
        select(InvestmentTransaction)
        .where(InvestmentTransaction.user_id == user_id)
        .where(InvestmentTransaction.transaction_type == InvestmentTransactionType.SELL)
        .where(InvestmentTransaction.transaction_date >= period_start)
        .where(InvestmentTransaction.transaction_date <= period_end)
    )
    realized_by_asset: dict[str, Decimal] = {}
    source_links: set[str] = {"report_section:investment_performance"}
    for txn in realized_result.scalars().all():
        realized_pnl = await _schedule_amount(
            txn.realized_pnl or Decimal("0.00"),
            txn.currency,
            txn.transaction_date,
        )
        realized_by_asset[txn.asset_identifier] = (
            realized_by_asset.get(txn.asset_identifier, Decimal("0.00")) + realized_pnl
        )
        if txn.journal_entry_id:
            source_links.add(f"journal_entry:{txn.journal_entry_id}")
        if txn.source_id:
            source_links.add(f"investment_transaction_source:{txn.source_id}")

    dividend_result = await db.execute(
        select(DividendIncome, ManagedPosition)
        .join(ManagedPosition, DividendIncome.position_id == ManagedPosition.id)
        .where(DividendIncome.user_id == user_id)
        .where(ManagedPosition.user_id == user_id)
        .where(DividendIncome.payment_date >= period_start)
        .where(DividendIncome.payment_date <= period_end)
    )
    dividend_by_asset: dict[str, Decimal] = {}
    for dividend, position in dividend_result.all():
        dividend_amount = await _schedule_amount(dividend.amount, dividend.currency, dividend.payment_date)
        dividend_by_asset[position.asset_identifier] = (
            dividend_by_asset.get(
                position.asset_identifier,
                Decimal("0.00"),
            )
            + dividend_amount
        )

    holding_rows: list[InvestmentPerformanceHoldingRow] = []
    for holding in holdings:
        position = position_by_asset.get(holding.asset_identifier)
        if position is None:
            cost_basis = _money(holding.cost_basis)
        else:
            cost_basis = _money(
                await _schedule_amount(position.cost_basis, position.currency, position.acquisition_date)
            )
        market_value = _money(holding.market_value)
        holding_rows.append(
            InvestmentPerformanceHoldingRow(
                asset_identifier=holding.asset_identifier,
                quantity=holding.quantity,
                cost_basis=cost_basis,
                market_value=market_value,
                unrealized_pnl=_money(market_value - cost_basis),
                realized_pnl=_money(realized_by_asset.get(holding.asset_identifier, Decimal("0.00"))),
                dividend_income=_money(dividend_by_asset.get(holding.asset_identifier, Decimal("0.00"))),
                currency=holding.currency,
            )
        )

    allocation_rows: list[InvestmentPerformanceAllocationRow] = []
    for dimension, loader in [
        ("sector", allocation.get_sector_allocation),
        ("geography", allocation.get_geography_allocation),
        ("asset_class", allocation.get_asset_class_allocation),
    ]:
        for row in await loader(db=db, user_id=user_id, as_of_date=as_of_date):
            allocation_rows.append(
                InvestmentPerformanceAllocationRow(
                    dimension=dimension,
                    category=row.category,
                    value=_money(row.value),
                    percentage=_money(row.percentage),
                    count=row.count,
                )
            )
    if used_report_preparation_evidence and not allocation_rows and holding_rows:
        total_market_value = sum((row.market_value for row in holding_rows), Decimal("0.00"))
        for dimension, attribute, fallback_category in [
            ("sector", "sector", "Unclassified"),
            ("geography", "geography", "Unclassified"),
            ("asset_class", "asset_type", "Unclassified"),
        ]:
            grouped: dict[str, tuple[Decimal, int]] = {}
            for holding, row in zip(holdings, holding_rows, strict=True):
                category = getattr(holding, attribute) or fallback_category
                current_value, current_count = grouped.get(category, (Decimal("0.00"), 0))
                grouped[category] = (current_value + row.market_value, current_count + 1)
            for category, (value, count) in grouped.items():
                percentage = Decimal("0.00")
                if total_market_value:
                    percentage = (value / total_market_value * Decimal("100")).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                allocation_rows.append(
                    InvestmentPerformanceAllocationRow(
                        dimension=dimension,
                        category=category,
                        value=_money(value),
                        percentage=percentage,
                        count=count,
                    )
                )
        notes.append("Allocation rows use report-preparation holdings when as-of allocation snapshots are unavailable.")

    latest_atomic_query = select(AtomicPosition).where(AtomicPosition.user_id == user_id)
    if used_report_preparation_evidence and asset_identifiers:
        latest_atomic_query = latest_atomic_query.where(AtomicPosition.asset_identifier.in_(asset_identifiers))
    else:
        latest_atomic_query = latest_atomic_query.where(AtomicPosition.snapshot_date <= as_of_date)
    latest_atomic_result = await db.execute(
        latest_atomic_query.order_by(AtomicPosition.snapshot_date.desc(), AtomicPosition.created_at.desc())
    )
    atomics = list(latest_atomic_result.scalars().all())
    latest_atomic_by_asset: dict[str, AtomicPosition] = {}
    for atomic in atomics:
        latest_atomic_by_asset.setdefault(atomic.asset_identifier, atomic)
        for link in _source_document_links(atomic.source_documents):
            source_links.add(link)

    latest_override_query = (
        select(MarketDataOverride)
        .where(MarketDataOverride.user_id == user_id)
        .where(MarketDataOverride.price_date <= as_of_date)
    )
    latest_override_result = await db.execute(
        latest_override_query.order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
    )
    overrides = list(latest_override_result.scalars().all())
    if asset_identifiers:
        report_preparation_override_result = await db.execute(
            select(MarketDataOverride)
            .where(MarketDataOverride.user_id == user_id)
            .where(MarketDataOverride.asset_identifier.in_(asset_identifiers))
            .where(MarketDataOverride.source == PriceSource.MANUAL)
            .where(MarketDataOverride.price_date > as_of_date)
            .order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
        )
        overrides.extend(report_preparation_override_result.scalars().all())
        overrides.sort(key=lambda override: override.price_date, reverse=True)
    latest_override = overrides[0] if overrides else None
    latest_override_by_asset: dict[str, MarketDataOverride] = {}
    for override in overrides:
        latest_override_by_asset.setdefault(override.asset_identifier, override)

    stock_prices: list[StockPrice] = []
    if asset_identifiers:
        stock_price_result = await db.execute(
            select(StockPrice)
            .where(StockPrice.symbol.in_(asset_identifiers))
            .where(StockPrice.price_date <= as_of_date)
            .order_by(StockPrice.price_date.desc(), StockPrice.created_at.desc())
        )
        stock_prices = list(stock_price_result.scalars().all())
    latest_stock_price_by_asset: dict[str, StockPrice] = {}
    for stock_price in stock_prices:
        latest_stock_price_by_asset.setdefault(stock_price.symbol, stock_price)

    price_dates: list[date] = []
    providers: set[str] = set()
    stale_holdings: list[str] = []
    for asset_identifier in asset_identifiers:
        override = latest_override_by_asset.get(asset_identifier)
        stock_price = latest_stock_price_by_asset.get(asset_identifier)
        atomic = latest_atomic_by_asset.get(asset_identifier)

        candidates: list[tuple[date, str, object, str | None]] = []
        if override is not None:
            candidates.append((override.price_date, "market_data_override", override.id, override.source.value))
        if stock_price is not None:
            candidates.append((stock_price.price_date, "stock_price", stock_price.id, stock_price.source))
        if atomic is not None:
            candidates.append((atomic.snapshot_date, "atomic_position", atomic.id, atomic.broker))

        if not candidates:
            stale_holdings.append(asset_identifier)
            continue

        evidence_date, source_kind, source_id, provider = max(candidates, key=lambda candidate: candidate[0])
        price_dates.append(evidence_date)
        source_links.add(_freshness_link(asset_identifier, source_kind, source_id, evidence_date))
        if provider:
            providers.add(provider)
        if evidence_date < as_of_date:
            stale_holdings.append(asset_identifier)

    latest_price_date = max(price_dates) if price_dates else None
    market_data_provider = ", ".join(sorted(providers)) if providers else None

    data_freshness = InvestmentPerformanceDataFreshness(
        latest_price_date=latest_price_date,
        market_data_provider=market_data_provider,
        stale=bool(stale_holdings),
        stale_holdings=sorted(stale_holdings),
        manual_override_basis=(
            f"{latest_override.asset_identifier}:{latest_override.price_date.isoformat()}"
            if latest_override is not None
            else None
        ),
    )
    if data_freshness.stale:
        notes.append("One or more market values use stale data relative to the requested as-of date.")

    return InvestmentPerformanceReportScheduleResponse(
        period_start=period_start,
        period_end=period_end,
        as_of_date=as_of_date,
        currency=currency,
        xirr=_percent(xirr),
        time_weighted_return=_percent(twr),
        money_weighted_return=_percent(mwr),
        realized_pnl=_money(sum(realized_by_asset.values(), Decimal("0.00"))),
        unrealized_pnl=_money(sum((row.unrealized_pnl for row in holding_rows), Decimal("0.00"))),
        dividend_income=_money(sum(dividend_by_asset.values(), Decimal("0.00"))),
        dividend_yield=_percent(dividend_yield),
        holdings=holding_rows,
        allocation=allocation_rows,
        data_freshness=data_freshness,
        source_links=sorted(source_links),
        notes=notes,
    )


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
    return {"updated_count": len(results), "results": results}
