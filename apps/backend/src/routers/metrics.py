"""North-Star confidence metric endpoint (EPIC-018 AC18.12).

Surfaces the single measurable expression of the axioms — the low-confidence-data
proportion — as a live value plus its recorded trend.
"""

from fastapi import APIRouter, status

from src.deps import CurrentUserId, DbSession
from src.models.metrics import ConfidenceMetricSnapshot
from src.schemas.metrics import (
    ConfidenceMetricPoint,
    ConfidenceMetricSnapshotResponse,
    ConfidenceNorthStarResponse,
)
from src.services.confidence_metric import ConfidenceMetricService

router = APIRouter(prefix="/metrics", tags=["metrics"])
_service = ConfidenceMetricService()


def _snapshot_response(snapshot: ConfidenceMetricSnapshot) -> ConfidenceMetricSnapshotResponse:
    return ConfidenceMetricSnapshotResponse(
        id=snapshot.id,
        captured_at=snapshot.created_at,
        total_count=snapshot.total_count,
        low_confidence_count=snapshot.low_confidence_count,
        low_confidence_proportion=snapshot.low_confidence_proportion,
        tier_breakdown=snapshot.tier_breakdown,
    )


@router.get("/confidence-north-star", response_model=ConfidenceNorthStarResponse)
async def get_confidence_north_star(user_id: CurrentUserId, db: DbSession) -> ConfidenceNorthStarResponse:
    """Return the current low-confidence proportion and the recorded trend (newest first)."""
    current = await _service.compute(db, user_id)
    series = await _service.list_snapshots(db, user_id)
    return ConfidenceNorthStarResponse(
        current=ConfidenceMetricPoint(
            total_count=current.total_count,
            low_confidence_count=current.low_confidence_count,
            low_confidence_proportion=current.low_confidence_proportion,
            tier_breakdown=current.tier_breakdown,
        ),
        series=[_snapshot_response(snapshot) for snapshot in series],
    )


@router.post(
    "/confidence-north-star/snapshots",
    response_model=ConfidenceMetricSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_confidence_north_star_snapshot(
    user_id: CurrentUserId, db: DbSession
) -> ConfidenceMetricSnapshotResponse:
    """Append the current low-confidence proportion to the North-Star series.

    Lets a scheduler (or an operator) record a point on demand, so the trend
    accumulates even between report-package generations.
    """
    snapshot = await _service.record_snapshot(db, user_id)
    await db.commit()
    return _snapshot_response(snapshot)
