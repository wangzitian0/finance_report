"""North-Star confidence metric endpoint (EPIC-018 AC18.12).

Surfaces the single measurable expression of the axioms — the low-confidence-data
proportion — as a live value plus its recorded trend.
"""

from fastapi import APIRouter

from src.deps import CurrentUserId, DbSession
from src.extraction import CorrectionLoopService
from src.schemas.metrics import CorrectionLoopReplayResponse

router = APIRouter(prefix="/metrics", tags=["metrics"])
_correction_loop = CorrectionLoopService()


@router.get("/correction-loop/replay", response_model=CorrectionLoopReplayResponse)
async def get_correction_loop_replay(user_id: CurrentUserId, db: DbSession) -> CorrectionLoopReplayResponse:
    """Surface the held-out replay of the live correction corpus (read-only).

    Makes the feedback loop's effect on the North-Star proportion auditable: how
    much recurring-correction priors lower the held-out low-confidence proportion.
    Records nothing and grounds no live generation — the corpus stays a projection
    of `CorrectionLog`.
    """
    result = await _correction_loop.replay(db, user_id)
    return CorrectionLoopReplayResponse(
        holdout_size=result.holdout_size,
        grounded=result.grounded,
        proportion_before=result.proportion_before,
        proportion_after=result.proportion_after,
        reduced=result.reduced,
    )
