"""Asset management API router."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models.layer3 import PositionStatus
from src.schemas.assets import (
    DepreciationResponse,
    ManagedPositionListResponse,
    ManagedPositionResponse,
    ReconcilePositionsResponse,
)
from src.services.assets import AssetService, AssetServiceError
from src.utils import raise_bad_request, raise_internal_error, raise_not_found

router = APIRouter(prefix="/assets", tags=["assets"])
logger = get_logger(__name__)

_service = AssetService()


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

    positions, total = await _service.get_positions(
        db, user_id, status_filter=status_filter, limit=limit, offset=offset
    )

    items = []
    for pos in positions:
        response = ManagedPositionResponse.model_validate(pos)
        if pos.account:
            response.account_name = pos.account.name
        items.append(response)

    logger.info("Listed positions", count=len(items), total=total)
    return ManagedPositionListResponse(items=items, total=total)


@router.get("/positions/{position_id}", response_model=ManagedPositionResponse)
async def get_position(
    position_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ManagedPositionResponse:
    """Get a single managed position by ID."""
    logger.info("Getting position", position_id=str(position_id), user_id=str(user_id))

    position = await _service.get_position(db, user_id, position_id)
    if not position:
        raise_not_found("Position")

    response = ManagedPositionResponse.model_validate(position)
    if position.account:
        response.account_name = position.account.name
    return response


@router.post("/reconcile", response_model=ReconcilePositionsResponse, status_code=status.HTTP_200_OK)
async def reconcile_positions(
    db: DbSession,
    user_id: CurrentUserId,
) -> ReconcilePositionsResponse:
    """Reconcile managed positions from atomic snapshots."""
    logger.info("Starting reconciliation", user_id=str(user_id))

    try:
        result = await _service.reconcile_positions(db, user_id)
        await db.commit()
    except AssetServiceError as e:
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
        result = await _service.get_depreciation_schedule(
            db=db,
            user_id=user_id,
            position_id=position_id,
            method=method,
            useful_life_years=useful_life_years,
            salvage_value=salvage_value,
            as_of_date=as_of_date,
        )
    except AssetServiceError as e:
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
