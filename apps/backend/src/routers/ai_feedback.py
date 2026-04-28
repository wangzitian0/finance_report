"""AI suggestion feedback endpoints."""

from fastapi import APIRouter, status
from sqlalchemy import func, select

from src.deps import CurrentUserId, DbSession
from src.models import (
    AiFeedback,
    BankStatement,
    BankStatementTransaction,
    ClassificationStatus,
    ReconciliationMatch,
    ReconciliationStatus,
    TransactionClassification,
)
from src.models.layer2 import AtomicTransaction
from src.schemas.ai_feedback import (
    AiFeedbackRequest,
    AiFeedbackResponse,
    AiSuggestionListResponse,
    AiSuggestionResponse,
)

router = APIRouter(prefix="/ai", tags=["ai-feedback"])


@router.post("/feedback", response_model=AiFeedbackResponse, status_code=status.HTTP_201_CREATED)
async def create_ai_feedback(
    payload: AiFeedbackRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> AiFeedbackResponse:
    """Persist user feedback for an AI suggestion."""
    feedback = AiFeedback(
        suggestion_id=payload.suggestion_id,
        user_id=user_id,
        action=payload.action,
        corrected_value=payload.corrected_value,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return AiFeedbackResponse.model_validate(feedback)


@router.get("/suggestions", response_model=AiSuggestionListResponse)
async def list_ai_suggestions(
    db: DbSession,
    user_id: CurrentUserId,
    limit: int = 50,
    offset: int = 0,
) -> AiSuggestionListResponse:
    """List pending AI classification and reconciliation suggestions in the 60-84 review band."""
    items: list[AiSuggestionResponse] = []

    classification_result = await db.execute(
        select(TransactionClassification, AtomicTransaction)
        .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
        .where(AtomicTransaction.user_id == user_id)
        .where(TransactionClassification.status == ClassificationStatus.DRAFT)
        .where(TransactionClassification.confidence_score >= 60)
        .where(TransactionClassification.confidence_score < 85)
        .order_by(TransactionClassification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    for classification, txn in classification_result.all():
        items.append(
            AiSuggestionResponse(
                suggestion_id=classification.id,
                transaction=txn.description,
                suggested_category_or_match=str(
                    classification.tags or classification.account_id or "AI classification"
                ),
                ai_score=classification.confidence_score or 60,
                ai_reasoning="Pending AI classification suggestion requires human review.",
            )
        )

    remaining = max(limit - len(items), 0)
    if remaining:
        match_result = await db.execute(
            select(ReconciliationMatch, BankStatementTransaction)
            .join(BankStatementTransaction, ReconciliationMatch.bank_txn_id == BankStatementTransaction.id)
            .join(BankStatement, BankStatementTransaction.statement_id == BankStatement.id)
            .where(BankStatement.user_id == user_id)
            .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
            .where(ReconciliationMatch.match_score >= 60)
            .where(ReconciliationMatch.match_score < 85)
            .order_by(ReconciliationMatch.created_at.desc())
            .limit(remaining)
        )
        for match, txn in match_result.all():
            items.append(
                AiSuggestionResponse(
                    suggestion_id=match.id,
                    transaction=txn.description,
                    suggested_category_or_match="Reconciliation match",
                    ai_score=match.match_score,
                    ai_reasoning=str(match.score_breakdown.get("ai_reasoning", "Pending AI reconciliation match.")),
                )
            )

    total_result = await db.execute(
        select(func.count(ReconciliationMatch.id))
        .join(BankStatementTransaction, ReconciliationMatch.bank_txn_id == BankStatementTransaction.id)
        .join(BankStatement, BankStatementTransaction.statement_id == BankStatement.id)
        .where(BankStatement.user_id == user_id)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        .where(ReconciliationMatch.match_score >= 60)
        .where(ReconciliationMatch.match_score < 85)
    )
    total = int(total_result.scalar_one() or 0) + len(items)
    return AiSuggestionListResponse(items=items, total=total)
