"""Transaction classification entry points (#1546, EPIC-018 AC18.17).

The controlled entry point for classifying a user's not-yet-classified
transactions — the seed of the "edit tags → re-extract categories" capability.
Each transaction classifies under the policy in effect on its OWN txn_date, so
this can never restate an already-covered period (the AC18.16.1 invariant). The
pass is append-only and duplicate-free: already-classified transactions are
never touched again; tail transactions (low-confidence / no-proposal) carry no
row and are re-attempted on the next run BY DESIGN (re-extract semantics).
Flag-gated by ``enable_ai_classification`` (+ the per-user override).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.deps import CurrentUserId, DbSession
from src.extraction import backfill_classifications

router = APIRouter(prefix="/classifications", tags=["classifications"])


class BackfillClassificationsResponse(BaseModel):
    classified: int
    candidates: int


@router.post("/backfill", response_model=BackfillClassificationsResponse)
async def backfill_transaction_classifications(
    db: DbSession,
    user_id: CurrentUserId,
) -> BackfillClassificationsResponse:
    """Classify the caller's not-yet-classified transactions (duplicate-free; the tail is re-attempted)."""
    result = await backfill_classifications(db, user_id)
    await db.commit()
    return BackfillClassificationsResponse(classified=result["classified"], candidates=result["candidates"])
