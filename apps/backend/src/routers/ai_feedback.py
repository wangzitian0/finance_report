"""AI suggestion feedback endpoints."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from src.deps import CurrentUserId, DbSession
from src.extraction import (
    AtomicTransaction,
    ClassificationStatus,
    SuggestionCorrectionError,
    TransactionClassification,
    apply_suggestion_feedback,
    effective_statement_transaction_filter,
)
from src.identity import (
    AiFeedback,
    AiFeedbackRequest,
    AiFeedbackResponse,
    AiSuggestionListResponse,
    AiSuggestionResponse,
)
from src.platform import raise_bad_request
from src.reconciliation import (
    ReconciliationError,
    ReconciliationMatch,
    ReconciliationStatus,
    apply_reconciliation_feedback,
)

router = APIRouter(prefix="/ai", tags=["ai-feedback"])


def _txn_direction(txn: AtomicTransaction) -> Literal["IN", "OUT"] | None:
    val = txn.direction.value if hasattr(txn.direction, "value") else txn.direction
    if val == "IN":
        return "IN"
    if val == "OUT":
        return "OUT"
    return None


async def _count_suggestions(db: DbSession, model: Any, join_col: Any, scope_filter: Any, filters: tuple[Any, ...]) -> int:
    stmt = select(func.count(model.id)).join(AtomicTransaction, join_col == AtomicTransaction.id).where(scope_filter, *filters)
    return int((await db.execute(stmt)).scalar_one() or 0)


@router.post("/feedback", response_model=AiFeedbackResponse, status_code=status.HTTP_201_CREATED)
async def create_ai_feedback(payload: AiFeedbackRequest, db: DbSession, user_id: CurrentUserId) -> AiFeedbackResponse:
    """Persist user feedback for an AI suggestion and apply it to the draft classification."""
    try:
        effect = await apply_suggestion_feedback(
            db, user_id, payload.suggestion_id, payload.action, payload.corrected_value
        )
        if effect == "recorded":
            effect = await apply_reconciliation_feedback(db, user_id, payload.suggestion_id, payload.action)
    except (SuggestionCorrectionError, ReconciliationError) as exc:
        raise_bad_request(str(exc), cause=exc)
    feedback = AiFeedback(
        suggestion_id=payload.suggestion_id,
        user_id=user_id,
        action=payload.action,
        corrected_value=payload.corrected_value,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    response = AiFeedbackResponse.model_validate(feedback)
    response.effect = effect
    return response


@router.get("/suggestions", response_model=AiSuggestionListResponse)
async def list_ai_suggestions(
    db: DbSession,
    user_id: CurrentUserId,
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum items to return")] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    statement_id: Annotated[UUID | None, Query(description="Optional statement ID filter")] = None,
) -> AiSuggestionListResponse:
    """List pending AI classification and reconciliation suggestions in the 60-84 review band."""
    scope_filter = (
        effective_statement_transaction_filter(user_id, statement_id)
        if statement_id is not None
        else (AtomicTransaction.user_id == user_id)
    )
    cls_filters = (
        TransactionClassification.status == ClassificationStatus.DRAFT,
        TransactionClassification.confidence_score >= 60,
        TransactionClassification.confidence_score < 85,
        func.coalesce(TransactionClassification.tags["corrected_by_user"].astext, "false") != "true",
    )
    rec_filters = (
        ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
        ReconciliationMatch.match_score >= 60,
        ReconciliationMatch.match_score < 85,
    )
    cls_total = await _count_suggestions(
        db, TransactionClassification, TransactionClassification.atomic_txn_id, scope_filter, cls_filters
    )
    rec_total = await _count_suggestions(
        db, ReconciliationMatch, ReconciliationMatch.atomic_txn_id, scope_filter, rec_filters
    )

    items: list[AiSuggestionResponse] = []
    cls_rows = (
        await db.execute(
            select(TransactionClassification, AtomicTransaction)
            .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
            .where(scope_filter, *cls_filters)
            .order_by(TransactionClassification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    for cls, txn in cls_rows:
        raw_cat = cls.tags.get("category") if isinstance(cls.tags, dict) else None
        suggested = (
            raw_cat
            if isinstance(raw_cat, str) and raw_cat
            else (str(cls.account_id) if cls.account_id else "AI classification")
        )
        items.append(
            AiSuggestionResponse(
                suggestion_id=cls.id,
                transaction=txn.description,
                suggested_category_or_match=suggested,
                ai_score=cls.confidence_score or 60,
                ai_reasoning="Pending AI classification suggestion requires human review.",
                direction=_txn_direction(txn),
            )
        )

    remaining = max(limit - len(items), 0)
    if remaining and offset + len(items) >= cls_total:
        match_rows = (
            await db.execute(
                select(ReconciliationMatch, AtomicTransaction)
                .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
                .where(scope_filter, *rec_filters)
                .order_by(ReconciliationMatch.created_at.desc())
                .limit(remaining)
                .offset(max(offset - cls_total, 0))
            )
        ).all()
        for match, txn in match_rows:
            items.append(
                AiSuggestionResponse(
                    suggestion_id=match.id,
                    transaction=txn.description,
                    suggested_category_or_match="Reconciliation match",
                    ai_score=match.match_score,
                    ai_reasoning=str(match.score_breakdown.get("ai_reasoning", "Pending AI reconciliation match.")),
                    direction=_txn_direction(txn),
                )
            )

    return AiSuggestionListResponse(items=items, total=cls_total + rec_total)
