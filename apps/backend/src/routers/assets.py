"""Asset management API router."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from src.deps import CurrentUserId, DbSession, ReadDbSession
from src.observability import get_logger
from src.platform import DomainError, InternalServiceError, ResourceNotFoundError, ValidationFailedError
from src.portfolio import PositionService
from src.pricing import (
    ManualValuationComponentType,
    ValuationService,
)
from src.reporting import DEFAULT_INCLUDE_RESTRICTED
from src.schemas.assets import (
    DepreciationResponse,
    ManualValuationSnapshotCreate,
    ManualValuationSnapshotListResponse,
    ManualValuationSnapshotResponse,
    ManualValuationSnapshotUpdate,
    ValuationComponentResponse,
    ValuationComponentsResponse,
)

router = APIRouter(prefix="/assets", tags=["assets"])
logger = get_logger(__name__)

_positions = PositionService()
_valuations = ValuationService()


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
        await db.flush()
        await db.refresh(snapshot)
    except DomainError:
        raise
    except Exception as e:
        logger.error("Manual valuation snapshot create failed", error=str(e), user_id=str(user_id))
        raise InternalServiceError("Manual valuation snapshot create failed") from e

    return ManualValuationSnapshotResponse.model_validate(snapshot)


def _parse_component_type(component_type: str | None) -> ManualValuationComponentType | None:
    if not component_type:
        return None
    try:
        return ManualValuationComponentType(component_type)
    except ValueError as exc:
        raise ValidationFailedError(f"Unsupported component_type: {component_type}") from exc


@router.get("/valuation-snapshots", response_model=ManualValuationSnapshotListResponse)
async def list_valuation_snapshots(
    db: ReadDbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(default=None),
    component_type: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ManualValuationSnapshotListResponse:
    """List manual valuation snapshots."""
    parsed_component_type = _parse_component_type(component_type)

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
    db: ReadDbSession,
    user_id: CurrentUserId,
) -> ManualValuationSnapshotResponse:
    """Get a manual valuation snapshot."""
    snapshot = await _valuations.get_valuation_snapshot(db, user_id, snapshot_id)
    if not snapshot:
        raise ResourceNotFoundError("Manual valuation snapshot not found")
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
        await db.flush()
    except DomainError:
        raise
    except Exception as e:
        logger.error("Manual valuation snapshot update failed", error=str(e), user_id=str(user_id))
        raise InternalServiceError("Manual valuation snapshot update failed") from e
    if not snapshot:
        raise ResourceNotFoundError("Manual valuation snapshot not found")
    await db.refresh(snapshot)
    return ManualValuationSnapshotResponse.model_validate(snapshot)


@router.delete("/valuation-snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_valuation_snapshot(
    snapshot_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Reject destructive deletion of an immutable manual valuation snapshot."""
    deleted = await _valuations.delete_valuation_snapshot(db, user_id, snapshot_id)
    if not deleted:
        raise ResourceNotFoundError("Manual valuation snapshot not found")


@router.get("/valuation-components", response_model=ValuationComponentsResponse)
async def list_valuation_components(
    db: ReadDbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(default=None),
    include_restricted: bool = Query(default=DEFAULT_INCLUDE_RESTRICTED),
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
        warnings=result.warnings,
    )


@router.get("/positions/{position_id}/depreciation", response_model=DepreciationResponse)
async def get_position_depreciation(
    position_id: UUID,
    db: ReadDbSession,
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

    result = await _positions.get_depreciation_schedule(
        db=db,
        user_id=user_id,
        position_id=position_id,
        method=method,
        useful_life_years=useful_life_years,
        salvage_value=salvage_value,
        as_of_date=as_of_date,
    )

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
