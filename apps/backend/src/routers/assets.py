"""Asset management API router."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models.layer3 import PositionStatus
from src.schemas.assets import (
    ManagedPositionListResponse,
    ManagedPositionResponse,
    ReconcilePositionsResponse,
)
from src.services.assets import AssetService, AssetServiceError
from src.utils import raise_not_found

router = APIRouter(prefix="/api/assets", tags=["assets"])
logger = get_logger(__name__)

_service = AssetService()


@router.get("/positions", response_model=ManagedPositionListResponse)
async def list_positions(
    db: DbSession,
    user_id: CurrentUserId,
    status_filter: PositionStatus | None = None,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
) -> ManagedPositionListResponse:
    """List all managed positions for the current user with pagination."""
    logger.info(
        "Listing positions",
        user_id=str(user_id),
        status_filter=status_filter.value if status_filter else None,
        page=page,
        page_size=page_size,
    )

    offset = (page - 1) * page_size
    positions, total = await _service.get_positions(
        db, user_id, status_filter=status_filter, limit=page_size, offset=offset
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e
    except Exception as e:
        logger.error("Unexpected error during reconciliation", error=str(e), user_id=str(user_id))
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Reconciliation failed unexpectedly",
        ) from e

    logger.info(
        "Reconciliation completed",
        created=result.created,
        updated=result.updated,
        disposed=result.disposed,
    )
    return ReconcilePositionsResponse(
        message="Positions reconciled successfully",
        created=result.created,
        updated=result.updated,
        disposed=result.disposed,
    )
