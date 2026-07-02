"""Transaction classification entry points (#1546, EPIC-018 AC18.17).

The controlled entry point for classifying a user's not-yet-classified
transactions — the seed of the "edit tags → re-extract categories" capability.
Each transaction classifies under the policy in effect on its OWN txn_date, so
this can never restate an already-covered period (the AC18.16.1 invariant), and
the pass is idempotent + append-only by construction (a re-run is a no-op).
Flag-gated by ``enable_ai_classification`` (+ the per-user override).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.deps import CurrentUserId, DbSession
from src.services.transaction_classification import backfill_classifications

router = APIRouter(prefix="/classifications", tags=["classifications"])


class BackfillClassificationsResponse(BaseModel):
    classified: int
    candidates: int


@router.post("/backfill", response_model=BackfillClassificationsResponse)
async def backfill_transaction_classifications(
    db: DbSession,
    user_id: CurrentUserId,
) -> BackfillClassificationsResponse:
    """Classify the caller's not-yet-classified transactions (idempotent)."""
    result = await backfill_classifications(db, user_id)
    await db.commit()
    return BackfillClassificationsResponse(classified=result["classified"], candidates=result["candidates"])
