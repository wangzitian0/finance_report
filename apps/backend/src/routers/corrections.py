"""EPIC-018 Phase 2: Corrections API router for feedback learning."""

from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from src.composition import compose_correction_callbacks
from src.deps import CurrentUserId, DbSession
from src.extraction import record_correction
from src.observability import get_logger

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


@router.post("", response_model=CorrectionResponse, status_code=status.HTTP_201_CREATED)
async def create_correction(
    body: CorrectionRequest,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> CorrectionResponse:
    """Record a user correction to an AI-suggested category.

    AC18.2.2: Corrections API records corrections.
    """
    correction = await record_correction(
        db,
        user_id=user_id,
        transaction_id=body.transaction_id,
        corrected_category=body.corrected_category,
        corrected_account_id=body.corrected_account_id,
        **compose_correction_callbacks(),
    )
    await db.commit()
    return CorrectionResponse(
        id=correction.id,
        transaction_id=correction.transaction_id,
        original_category=correction.original_category,
        corrected_category=correction.corrected_category,
    )
