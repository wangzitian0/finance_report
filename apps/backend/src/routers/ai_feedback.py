"""AI suggestion feedback endpoints."""

from typing import Annotated
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
from src.reconciliation import ReconciliationMatch, ReconciliationStatus

router = APIRouter(prefix="/ai", tags=["ai-feedback"])


@router.post("/feedback", response_model=AiFeedbackResponse, status_code=status.HTTP_201_CREATED)
async def create_ai_feedback(
    payload: AiFeedbackRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> AiFeedbackResponse:
    """Persist user feedback for an AI suggestion and apply it to the draft classification.

    A rejected draft is superseded. A corrected draft takes the category of the user. The one-click
    approval reads the draft, so it then honors the decision (#2419).
    """
    try:
        effect = await apply_suggestion_feedback(
            db, user_id, payload.suggestion_id, payload.action, payload.corrected_value
        )
    except SuggestionCorrectionError as exc:
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
    items: list[AiSuggestionResponse] = []

    txn_scope_filter = (
        effective_statement_transaction_filter(user_id, statement_id)
        if statement_id is not None
        else (AtomicTransaction.user_id == user_id)
    )

    classification_filters = (
        TransactionClassification.status == ClassificationStatus.DRAFT,
        TransactionClassification.confidence_score >= 60,
        TransactionClassification.confidence_score < 85,
        # A corrected draft is decided. It is not pending.
        func.coalesce(TransactionClassification.tags["corrected_by_user"].astext, "false") != "true",
    )
    reconciliation_filters = (
        ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
        ReconciliationMatch.match_score >= 60,
        ReconciliationMatch.match_score < 85,
    )

    classification_count_result = await db.execute(
        select(func.count(TransactionClassification.id))
        .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
        .where(txn_scope_filter)
        .where(*classification_filters)
    )
    classification_total = int(classification_count_result.scalar_one() or 0)

    reconciliation_count_result = await db.execute(
        select(func.count(ReconciliationMatch.id))
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(txn_scope_filter)
        .where(*reconciliation_filters)
    )
    reconciliation_total = int(reconciliation_count_result.scalar_one() or 0)

    classification_result = await db.execute(
        select(TransactionClassification, AtomicTransaction)
        .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
        .where(txn_scope_filter)
        .where(*classification_filters)
        .order_by(TransactionClassification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    for classification, txn in classification_result.all():
        category: str | None = None
        if isinstance(classification.tags, dict):
            raw = classification.tags.get("category")
            if isinstance(raw, str) and raw:
                category = raw
        # Ensure suggested_category_or_match is a string (account_id may be UUID)
        suggested = None
        if category:
            suggested = category
        elif classification.account_id:
            suggested = str(classification.account_id)
        else:
            suggested = "AI classification"

        direction_val = txn.direction.value if hasattr(txn.direction, "value") else txn.direction
        items.append(
            AiSuggestionResponse(
                suggestion_id=classification.id,
                transaction=txn.description,
                suggested_category_or_match=suggested,
                ai_score=classification.confidence_score or 60,
                ai_reasoning="Pending AI classification suggestion requires human review.",
                direction=direction_val if direction_val in ("IN", "OUT") else None,
            )
        )

    classification_consumed = offset + len(items)
    reconciliation_offset = max(offset - classification_total, 0)
    remaining = max(limit - len(items), 0)
    if remaining and classification_consumed >= classification_total:
        match_result = await db.execute(
            select(ReconciliationMatch, AtomicTransaction)
            .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
            .where(txn_scope_filter)
            .where(*reconciliation_filters)
            .order_by(ReconciliationMatch.created_at.desc())
            .limit(remaining)
            .offset(reconciliation_offset)
        )
        for match, txn in match_result.all():
            direction_val = txn.direction.value if hasattr(txn.direction, "value") else txn.direction
            items.append(
                AiSuggestionResponse(
                    suggestion_id=match.id,
                    transaction=txn.description,
                    suggested_category_or_match="Reconciliation match",
                    ai_score=match.match_score,
                    ai_reasoning=str(match.score_breakdown.get("ai_reasoning", "Pending AI reconciliation match.")),
                    direction=direction_val if direction_val in ("IN", "OUT") else None,
                )
            )

    return AiSuggestionListResponse(items=items, total=classification_total + reconciliation_total)
