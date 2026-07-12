"""Asset management API router."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from src.audit.money import Money, to_money
from src.config import settings
from src.deps import CurrentUserId, DbSession, Pagination
from src.ledger import Account
from src.models.layer3 import (
    ManagedPosition,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
    PositionStatus,
)
from src.observability import get_logger
from src.platform import raise_bad_request, raise_internal_error, raise_not_found
from src.portfolio import PositionService, PositionServiceError
from src.pricing import PricingError, ValuationService, ValuationServiceError, convert_money
from src.schemas.assets import (
    DepreciationResponse,
    ManagedPositionListResponse,
    ManagedPositionResponse,
    ManualValuationSnapshotCreate,
    ManualValuationSnapshotListResponse,
    ManualValuationSnapshotResponse,
    ManualValuationSnapshotUpdate,
    ReconcilePositionsResponse,
    RestrictedHoldingResponse,
    ValuationComponentResponse,
    ValuationComponentsResponse,
)

router = APIRouter(prefix="/assets", tags=["assets"])
logger = get_logger(__name__)

_positions = PositionService()
_valuations = ValuationService()


async def _apply_reporting_valuation(
    db: DbSession,
    position: ManagedPosition,
    response: ManagedPositionResponse,
) -> None:
    """#1098: attach the base/reporting-currency cost basis to a position response.

    Mirrors how services/portfolio.py converts cost via the single convert_money
    authority (converted once, at the position's acquisition-date FX boundary).
    On any FX failure the reporting view degrades to null rather than raising —
    an FX error must never 500 a read (the #1388 lesson).
    """
    try:
        converted = await convert_money(
            db,
            Money(position.cost_basis, position.currency),
            settings.base_currency,
            rate_date=position.acquisition_date,
            lazy_load=True,
        )
    except PricingError as exc:
        logger.warning(
            "Reporting-currency conversion unavailable for position; returning native only",
            position_id=str(position.id),
            native_currency=position.currency,
            base_currency=settings.base_currency,
            error=str(exc),
        )
        response.reporting_cost_basis = None
        response.reporting_currency = None
        return

    response.reporting_cost_basis = converted.amount
    response.reporting_currency = converted.currency.code


@router.get("/positions", response_model=ManagedPositionListResponse)
async def list_positions(
    db: DbSession,
    user_id: CurrentUserId,
    status_filter: PositionStatus | None = None,
    limit: int = Query(50, ge=1, le=100, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> ManagedPositionListResponse:
    """List all managed positions for the current user with pagination."""
    logger.info(
        "Listing positions",
        user_id=str(user_id),
        status_filter=status_filter.value if status_filter else None,
        limit=limit,
        offset=offset,
    )

    positions, total = await _positions.get_positions(
        db, user_id, status_filter=status_filter, limit=limit, offset=offset
    )

    # ManagedPosition carries only the bare account_id FK (#1675 D4): resolve
    # display names with one explicit user-scoped query, no ORM navigation.
    account_names: dict[UUID, str] = {}
    if positions:
        rows = await db.execute(
            select(Account.id, Account.name)
            .where(Account.user_id == user_id)
            .where(Account.id.in_({pos.account_id for pos in positions}))
        )
        account_names = dict(rows.all())

    items = []
    for pos in positions:
        response = ManagedPositionResponse.model_validate(pos)
        response.account_name = account_names.get(pos.account_id)
        await _apply_reporting_valuation(db, pos, response)
        items.append(response)

    logger.info("Listed positions", count=len(items), total=total)
    return ManagedPositionListResponse(items=items, total=total)


@router.post(
    "/valuation-snapshots",
    response_model=ManualValuationSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_valuation_snapshot(
    payload: ManualValuationSnapshotCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> ManualValuationSnapshotResponse:
    """Create a manual valuation snapshot."""
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
        await db.commit()
        await db.refresh(snapshot)
    except Exception as e:
        logger.error("Manual valuation snapshot create failed", error=str(e), user_id=str(user_id))
        await db.rollback()
        raise_internal_error("Manual valuation snapshot create failed", cause=e)

    return ManualValuationSnapshotResponse.model_validate(snapshot)


@router.get("/valuation-snapshots", response_model=ManualValuationSnapshotListResponse)
async def list_valuation_snapshots(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(default=None),
    component_type: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ManualValuationSnapshotListResponse:
    """List manual valuation snapshots."""
    from src.models.layer3 import ManualValuationComponentType

    parsed_component_type = None
    if component_type:
        try:
            parsed_component_type = ManualValuationComponentType(component_type)
        except ValueError as exc:
            raise_bad_request(f"Unsupported component_type: {component_type}", cause=exc)

    snapshots, total = await _valuations.list_valuation_snapshots(
        db,
        user_id,
        as_of_date=as_of_date,
        component_type=parsed_component_type,
        limit=limit,
        offset=offset,
    )
    return ManualValuationSnapshotListResponse(
        items=[ManualValuationSnapshotResponse.model_validate(snapshot) for snapshot in snapshots],
        total=total,
    )


@router.get("/valuation-snapshots/{snapshot_id}", response_model=ManualValuationSnapshotResponse)
async def get_valuation_snapshot(
    snapshot_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ManualValuationSnapshotResponse:
    """Get a manual valuation snapshot."""
    snapshot = await _valuations.get_valuation_snapshot(db, user_id, snapshot_id)
    if not snapshot:
        raise_not_found("Manual valuation snapshot")
    return ManualValuationSnapshotResponse.model_validate(snapshot)


@router.patch("/valuation-snapshots/{snapshot_id}", response_model=ManualValuationSnapshotResponse)
async def update_valuation_snapshot(
    snapshot_id: UUID,
    payload: ManualValuationSnapshotUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> ManualValuationSnapshotResponse:
    """Update a manual valuation snapshot."""
    try:
        snapshot = await _valuations.update_valuation_snapshot(
            db,
            user_id,
            snapshot_id,
            values=payload.model_dump(exclude_unset=True),
        )
        await db.commit()
    except (PositionServiceError, ValuationServiceError) as e:
        await db.rollback()
        raise_bad_request(str(e), cause=e)
    except Exception as e:
        logger.error("Manual valuation snapshot update failed", error=str(e), user_id=str(user_id))
        await db.rollback()
        raise_internal_error("Manual valuation snapshot update failed", cause=e)
    if not snapshot:
        raise_not_found("Manual valuation snapshot")
    await db.refresh(snapshot)
    return ManualValuationSnapshotResponse.model_validate(snapshot)


@router.delete("/valuation-snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_valuation_snapshot(
    snapshot_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete a manual valuation snapshot."""
    deleted = await _valuations.delete_valuation_snapshot(db, user_id, snapshot_id)
    if not deleted:
        raise_not_found("Manual valuation snapshot")
    await db.commit()


@router.get("/valuation-components", response_model=ValuationComponentsResponse)
async def list_valuation_components(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(default=None),
    include_restricted: bool = Query(default=True),
) -> ValuationComponentsResponse:
    """List latest manual valuation components as of a date."""
    result = await _valuations.get_latest_valuation_components(
        db,
        user_id,
        as_of_date=as_of_date or date.today(),
        include_restricted=include_restricted,
    )
    return ValuationComponentsResponse(
        items=[ValuationComponentResponse.model_validate(item.__dict__) for item in result.items],
        total_assets=result.total_assets,
        total_liabilities=result.total_liabilities,
        net_worth_delta=result.net_worth_delta,
    )


@router.get("/restricted", response_model=list[RestrictedHoldingResponse])
async def list_restricted_holdings(
    db: DbSession,
    user_id: CurrentUserId,
    pagination: Pagination,
    as_of_date: date | None = Query(default=None),
) -> list[RestrictedHoldingResponse]:
    """List latest ESOP/RSU/locked manual valuations as restricted holdings."""
    report_date = as_of_date or date.today()
    restricted_types = (
        ManualValuationComponentType.ESOP,
        ManualValuationComponentType.RSU,
        ManualValuationComponentType.STOCK_OPTIONS,
    )
    result = await db.execute(
        select(ManualValuationSnapshot)
        .where(ManualValuationSnapshot.user_id == user_id)
        .where(ManualValuationSnapshot.as_of_date <= report_date)
        .where(ManualValuationSnapshot.component_type.in_(restricted_types))
        .where(ManualValuationSnapshot.liquidity_class == ManualValuationLiquidityClass.RESTRICTED)
        # Current heads only; superseded corrections must not surface as phantom holdings.
        .where(ManualValuationSnapshot.superseded_by_id.is_(None))
        .order_by(ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc())
    )

    holdings: dict[tuple[ManualValuationComponentType, str, str], ManualValuationSnapshot] = {}
    for snapshot in result.scalars().all():
        key = (snapshot.component_type, snapshot.source, snapshot.currency)
        holdings.setdefault(key, snapshot)

    # Paginate the deduplicated current-head holdings (dedup must run over the full
    # result set before slicing, so the bound is applied here rather than in SQL).
    # Sort explicitly with a stable tiebreaker (id) instead of relying on dict
    # insertion order, so offset pagination is deterministic when as_of_date /
    # created_at tie — otherwise pages could drop or duplicate rows.
    ordered = sorted(
        holdings.values(),
        key=lambda s: (s.as_of_date, s.created_at, s.id),
        reverse=True,
    )
    page = ordered[pagination.offset : pagination.offset + pagination.limit]
    return [
        RestrictedHoldingResponse(
            ticker=snapshot.source,
            quantity=Decimal("1.000000"),
            vesting_schedule=snapshot.notes,
            unlock_date=snapshot.reminder_date,
            fair_value=to_money(snapshot.value),
            currency=snapshot.currency,
        )
        for snapshot in page
    ]


@router.get("/positions/{position_id}", response_model=ManagedPositionResponse)
async def get_position(
    position_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ManagedPositionResponse:
    """Get a single managed position by ID."""
    logger.info("Getting position", position_id=str(position_id), user_id=str(user_id))

    position = await _positions.get_position(db, user_id, position_id)
    if not position:
        raise_not_found("Position")

    response = ManagedPositionResponse.model_validate(position)
    # Bare FK id column, resolved explicitly (#1675 D4) — no ORM navigation.
    response.account_name = await db.scalar(
        select(Account.name).where(Account.user_id == user_id).where(Account.id == position.account_id)
    )
    await _apply_reporting_valuation(db, position, response)
    return response


@router.post("/reconcile", response_model=ReconcilePositionsResponse, status_code=status.HTTP_200_OK)
async def reconcile_positions(
    db: DbSession,
    user_id: CurrentUserId,
) -> ReconcilePositionsResponse:
    """Reconcile managed positions from atomic snapshots."""
    logger.info("Starting reconciliation", user_id=str(user_id))

    try:
        result = await _positions.reconcile_positions(db, user_id)
        await db.commit()
    except (PositionServiceError, ValuationServiceError) as e:
        logger.error("Reconciliation failed", error=str(e), user_id=str(user_id))
        await db.rollback()
        raise_internal_error(str(e), cause=e)
    except Exception as e:
        logger.error("Unexpected error during reconciliation", error=str(e), user_id=str(user_id))
        await db.rollback()
        raise_internal_error("Reconciliation failed unexpectedly", cause=e)

    logger.info(
        "Reconciliation completed",
        created=result.created,
        updated=result.updated,
        disposed=result.disposed,
        skipped=result.skipped,
    )
    return ReconcilePositionsResponse(
        message="Positions reconciled successfully",
        created=result.created,
        updated=result.updated,
        disposed=result.disposed,
        skipped=result.skipped,
        skipped_assets=result.skipped_assets,
    )


@router.get("/positions/{position_id}/depreciation", response_model=DepreciationResponse)
async def get_position_depreciation(
    position_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
    method: Literal["straight-line", "declining-balance"] = Query(
        default="straight-line", description="Depreciation method"
    ),
    useful_life_years: int = Query(default=5, ge=1, le=50, description="Useful life in years"),
    salvage_value: Decimal = Query(default=Decimal("0"), ge=0, description="Salvage value at end of life"),
    as_of_date: date | None = Query(default=None, description="Calculate depreciation as of this date"),
) -> DepreciationResponse:
    """Calculate depreciation for a position."""
    logger.info(
        "Calculating depreciation",
        position_id=str(position_id),
        method=method,
        useful_life_years=useful_life_years,
    )

    try:
        result = await _positions.get_depreciation_schedule(
            db=db,
            user_id=user_id,
            position_id=position_id,
            method=method,
            useful_life_years=useful_life_years,
            salvage_value=salvage_value,
            as_of_date=as_of_date,
        )
    except (PositionServiceError, ValuationServiceError) as e:
        logger.warning("Depreciation calculation failed", error=str(e))
        raise_bad_request(str(e))

    return DepreciationResponse(
        position_id=result.position_id,
        asset_identifier=result.asset_identifier,
        period_depreciation=result.period_depreciation,
        accumulated_depreciation=result.accumulated_depreciation,
        book_value=result.book_value,
        method=result.method,
        useful_life_years=result.useful_life_years,
        salvage_value=result.salvage_value,
    )
