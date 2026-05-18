"""Valuation snapshot API router."""

from datetime import date

from fastapi import APIRouter, Query, status

from src.deps import CurrentUserId, DbSession
from src.schemas.valuation import (
    ValuationComponentListResponse,
    ValuationComponentResponse,
    ValuationSnapshotCreate,
    ValuationSnapshotListResponse,
    ValuationSnapshotResponse,
    derive_freshness,
)
from src.services.valuation import ValuationService

router = APIRouter(prefix="/valuations", tags=["valuations"])
_service = ValuationService()


def _snapshot_response(snapshot, *, reference_date: date) -> ValuationSnapshotResponse:
    data = ValuationSnapshotResponse.model_validate(
        {
            **{column.name: getattr(snapshot, column.name) for column in snapshot.__table__.columns},
            "freshness": derive_freshness(snapshot.as_of_date, snapshot.stale_after_days, reference_date),
        }
    )
    return data


@router.post("/snapshots", response_model=ValuationSnapshotResponse, status_code=status.HTTP_201_CREATED)
async def create_valuation_snapshot(
    request: ValuationSnapshotCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> ValuationSnapshotResponse:
    """Create a new manual/imported/system valuation snapshot."""
    snapshot = await _service.create_snapshot(db, user_id=user_id, payload=request)
    await db.commit()
    return _snapshot_response(snapshot, reference_date=request.as_of_date)


@router.get("/snapshots", response_model=ValuationSnapshotListResponse)
async def list_valuation_snapshots(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ValuationSnapshotListResponse:
    """List valuation snapshots ordered newest first."""
    reference_date = as_of_date or date.today()
    snapshots, total = await _service.list_snapshots(
        db,
        user_id=user_id,
        as_of_date=as_of_date,
        limit=limit,
        offset=offset,
    )
    return ValuationSnapshotListResponse(
        items=[_snapshot_response(snapshot, reference_date=reference_date) for snapshot in snapshots],
        total=total,
    )


@router.get("/components", response_model=ValuationComponentListResponse)
async def list_latest_valuation_components(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(default=None),
) -> ValuationComponentListResponse:
    """Return the latest valuation snapshot per component as of a date."""
    reference_date = as_of_date or date.today()
    snapshots = await _service.latest_components(db, user_id=user_id, as_of_date=reference_date)
    items = [
        ValuationComponentResponse.model_validate(
            _snapshot_response(snapshot, reference_date=reference_date).model_dump()
        )
        for snapshot in snapshots
    ]
    return ValuationComponentListResponse(items=items, total=len(items))
