import asyncio
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models import BankStatement
from src.models.consistency_check import ConsistencyCheck
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.schemas import BankStatementResponse, StatementDecisionRequest
from src.schemas.review import (
    BalanceValidationResult,
    EditAndApproveRequest,
    SetOpeningBalanceRequest,
    StatementReviewResponse,
)
from src.services import StorageError, StorageService
from src.services.consistency_checks import (
    get_pending_checks,
    has_unresolved_checks,
    resolve_check,
    run_all_consistency_checks,
)
from src.services.statement_validation import (
    approve_statement,
    edit_and_approve,
    reject_statement,
    set_opening_balance,
    validate_balance_chain,
)
from src.utils import raise_not_found

router = APIRouter(prefix="/statements", tags=["statements", "review"])
logger = get_logger(__name__)


class ConsistencyCheckResponse(BaseModel):
    id: UUID
    check_type: str
    status: str
    related_txn_ids: list[str]
    details: dict
    severity: str
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConsistencyCheckListResponse(BaseModel):
    items: list[ConsistencyCheckResponse]
    total: int


class ResolveCheckRequest(BaseModel):
    action: str = Field(..., description="approve, reject, or flag")
    note: str | None = None


class BatchApproveRequest(BaseModel):
    match_ids: list[str] = Field(default_factory=list)


class BatchRejectRequest(BaseModel):
    match_ids: list[str] = Field(default_factory=list)


class Stage2ReviewQueueResponse(BaseModel):
    pending_matches: list[dict]
    consistency_checks: list[ConsistencyCheckResponse]
    has_unresolved_checks: bool


@router.get("/{statement_id}/review", response_model=StatementReviewResponse)
async def get_statement_for_review(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> StatementReviewResponse:
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()

    if not statement:
        raise_not_found("Statement")

    pdf_url = None
    try:
        storage = StorageService()
        pdf_url = await asyncio.to_thread(storage.generate_presigned_url, key=statement.file_path, expires_in=3600)
    except StorageError as exc:
        logger.warning(
            "Could not generate presigned URL for review",
            error=str(exc),
            statement_id=str(statement_id),
        )

    validation_result = await validate_balance_chain(db, statement_id)

    response_data = {
        **{c.name: getattr(statement, c.name) for c in statement.__table__.columns},
        "transactions": statement.transactions,
        "pdf_url": pdf_url,
        "balance_validation_result": BalanceValidationResult(
            opening_balance=validation_result["opening_balance"],
            closing_balance=validation_result["closing_balance"],
            calculated_closing=validation_result["calculated_closing"],
            opening_delta=validation_result["opening_delta"],
            closing_delta=validation_result["closing_delta"],
            opening_match=validation_result["opening_match"],
            closing_match=validation_result["closing_match"],
            validated_at=validation_result["validated_at"],
        ),
    }
    return StatementReviewResponse.model_validate(response_data)


@router.post("/{statement_id}/review/approve", response_model=BankStatementResponse)
async def approve_statement_stage1(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    statement = await approve_statement(db, statement_id, user_id)
    await db.commit()

    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.post("/{statement_id}/review/reject", response_model=BankStatementResponse)
async def reject_statement_stage1(
    statement_id: UUID,
    decision: StatementDecisionRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    statement = await reject_statement(db, statement_id, user_id, reason=decision.notes)
    await db.commit()

    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.post("/{statement_id}/review/edit", response_model=BankStatementResponse)
async def edit_and_approve_statement(
    statement_id: UUID,
    request: EditAndApproveRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    edits_data = [{"txn_id": e.txn_id, **e.model_dump(exclude={"txn_id"})} for e in request.edits]
    statement = await edit_and_approve(db, statement_id, user_id, edits_data)
    await db.commit()

    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.post("/{statement_id}/review/opening-balance", response_model=BankStatementResponse)
async def set_statement_opening_balance(
    statement_id: UUID,
    request: SetOpeningBalanceRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> BankStatementResponse:
    statement = await set_opening_balance(db, statement_id, user_id, request.opening_balance)
    await db.commit()

    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one()
    return BankStatementResponse.model_validate(statement)


@router.get("/stage2", response_model=Stage2ReviewQueueResponse)
async def get_stage2_review_queue(
    db: DbSession,
    user_id: CurrentUserId,
) -> Stage2ReviewQueueResponse:
    matches_result = await db.execute(
        select(ReconciliationMatch)
        .where(
            ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
            ReconciliationMatch.user_id == user_id,
        )
        .limit(50)
    )
    pending_matches = []
    for match in matches_result.scalars().all():
        pending_matches.append(
            {
                "id": str(match.id),
                "match_score": match.match_score,
                "status": match.status.value,
                "created_at": match.created_at.isoformat() if match.created_at else None,
            }
        )

    checks = await get_pending_checks(db, user_id)

    return Stage2ReviewQueueResponse(
        pending_matches=pending_matches,
        consistency_checks=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        has_unresolved_checks=await has_unresolved_checks(db, user_id),
    )


@router.post("/{statement_id}/stage2/run-checks", response_model=ConsistencyCheckListResponse)
async def run_stage2_checks(
    statement_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ConsistencyCheckListResponse:
    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id).where(BankStatement.user_id == user_id)
    )
    statement = result.scalar_one_or_none()
    if not statement:
        raise_not_found("Statement")

    checks = await run_all_consistency_checks(db, user_id, statement_id)
    await db.commit()

    return ConsistencyCheckListResponse(
        items=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        total=len(checks),
    )


@router.post("/consistency-checks/{check_id}/resolve", response_model=ConsistencyCheckResponse)
async def resolve_consistency_check(
    check_id: UUID,
    request: ResolveCheckRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> ConsistencyCheckResponse:
    check = await resolve_check(db, check_id, request.action, user_id, request.note)
    await db.commit()

    return ConsistencyCheckResponse.model_validate(check)


@router.get("/consistency-checks", response_model=ConsistencyCheckListResponse)
async def list_consistency_checks(
    db: DbSession,
    user_id: CurrentUserId,
    status: str | None = None,
    check_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ConsistencyCheckListResponse:
    query = (
        select(ConsistencyCheck)
        .where(ConsistencyCheck.user_id == user_id)
        .order_by(ConsistencyCheck.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    count_query = select(func.count()).select_from(ConsistencyCheck).where(ConsistencyCheck.user_id == user_id)

    if status:
        query = query.where(ConsistencyCheck.status == status)
        count_query = count_query.where(ConsistencyCheck.status == status)
    if check_type:
        query = query.where(ConsistencyCheck.check_type == check_type)
        count_query = count_query.where(ConsistencyCheck.check_type == check_type)

    result = await db.execute(query)
    checks = list(result.scalars().all())

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    return ConsistencyCheckListResponse(
        items=[ConsistencyCheckResponse.model_validate(c) for c in checks],
        total=total,
    )


@router.post("/batch-approve", response_model=dict)
async def batch_approve_matches(
    request: BatchApproveRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> dict:
    if await has_unresolved_checks(db, user_id):
        return {
            "success": False,
            "error": "Cannot batch approve while there are unresolved consistency checks",
            "approved_count": 0,
        }

    if not request.match_ids:
        return {"success": True, "approved_count": 0}

    result = await db.execute(
        select(ReconciliationMatch)
        .where(ReconciliationMatch.id.in_(request.match_ids))
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
    )
    matches = list(result.scalars().all())

    approved_count = 0
    for match in matches:
        match.status = ReconciliationStatus.ACCEPTED
        match.version += 1
        approved_count += 1

    await db.commit()

    return {
        "success": True,
        "approved_count": approved_count,
    }


@router.post("/batch-reject", response_model=dict)
async def batch_reject_matches(
    request: BatchRejectRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> dict:
    if not request.match_ids:
        return {"success": True, "rejected_count": 0}

    result = await db.execute(
        select(ReconciliationMatch)
        .where(ReconciliationMatch.id.in_(request.match_ids))
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
    )
    matches = list(result.scalars().all())

    rejected_count = 0
    for match in matches:
        match.status = ReconciliationStatus.REJECTED
        match.version += 1
        rejected_count += 1

    await db.commit()

    return {
        "success": True,
        "rejected_count": rejected_count,
    }
