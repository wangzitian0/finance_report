"""EPIC-018 Phase 2: Corrections API router for feedback learning."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.services.correction_service import get_correction_stats, record_correction

router = APIRouter(prefix="/corrections", tags=["corrections"])
logger = get_logger(__name__)


class CorrectionRequest(BaseModel):
    """Request to record a user correction."""

    transaction_id: UUID
    corrected_category: str = Field(..., min_length=1, max_length=100)
    corrected_account_id: UUID | None = None


class CorrectionResponse(BaseModel):
    """Response after recording a correction."""

    id: UUID
    transaction_id: UUID
    original_category: str | None
    corrected_category: str


class CorrectionStatsResponse(BaseModel):
    """Correction statistics response."""

    total_corrections: int
    top_corrections: list[dict]
    accuracy_by_category: dict[str, float]


@router.post("", response_model=CorrectionResponse, status_code=201)
async def create_correction(
    body: CorrectionRequest,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> CorrectionResponse:
    """Record a user correction to an AI-suggested category.

    AC18.2.2: Corrections API records corrections.
    """
    try:
        correction = await record_correction(
            db,
            user_id=user_id,
            transaction_id=body.transaction_id,
            corrected_category=body.corrected_category,
            corrected_account_id=body.corrected_account_id,
        )
        await db.commit()
        return CorrectionResponse(
            id=correction.id,
            transaction_id=correction.transaction_id,
            original_category=correction.original_category,
            corrected_category=correction.corrected_category,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/stats", response_model=CorrectionStatsResponse)
async def correction_stats(
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> CorrectionStatsResponse:
    """Get correction statistics for the current user.

    AC18.2.2: Corrections API returns aggregated correction statistics.
    """
    stats = await get_correction_stats(db, user_id=user_id)
    return CorrectionStatsResponse(**stats)
