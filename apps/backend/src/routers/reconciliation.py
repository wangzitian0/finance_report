"""Reconciliation API router."""

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.models import (
    BankStatementTransaction,
    BankStatementTransactionStatus,
    Direction,
    JournalEntry,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.schemas.reconciliation import (
    AnomalyResponse,
    BatchAcceptRequest,
    JournalEntrySummary,
    ReconciliationMatchListResponse,
    ReconciliationMatchResponse,
    ReconciliationRunRequest,
    ReconciliationRunResponse,
    ReconciliationStatsResponse,
    ReconciliationStatusEnum,
    UnmatchedTransactionsResponse,
)
from src.services.anomaly import detect_anomalies
from src.services.reconciliation import execute_matching
from src.services.review_queue import (
    accept_match as accept_match_service,
)
from src.services.review_queue import (
    batch_accept as batch_accept_service,
)
from src.services.review_queue import (
    create_entry_from_txn,
    get_pending_items,
)
from src.services.review_queue import (
    reject_match as reject_match_service,
)

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])


def _entry_total_amount(entry: JournalEntry) -> Decimal:
    return sum(line.amount for line in entry.lines if line.direction == Direction.DEBIT)


def _build_entry_summary(entry: JournalEntry) -> JournalEntrySummary:
    return JournalEntrySummary(
        id=entry.id,
        entry_date=entry.entry_date,
        memo=entry.memo,
        status=entry.status.value,
        total_amount=_entry_total_amount(entry),
    )


async def _build_match_response(
    db: AsyncSession,
    match: ReconciliationMatch,
) -> ReconciliationMatchResponse:
    transaction_result = await db.execute(
        select(BankStatementTransaction).where(BankStatementTransaction.id == match.bank_txn_id)
    )
    transaction = transaction_result.scalar_one_or_none()
    entries: list[JournalEntrySummary] = []
    if match.journal_entry_ids:
        entry_ids = [UUID(entry_id) for entry_id in match.journal_entry_ids]
        result = await db.execute(
            select(JournalEntry)
            .where(JournalEntry.id.in_(entry_ids))
            .options(selectinload(JournalEntry.lines))
        )
        for entry in result.scalars():
            entries.append(_build_entry_summary(entry))

    return ReconciliationMatchResponse(
        id=match.id,
        bank_txn_id=match.bank_txn_id,
        journal_entry_ids=match.journal_entry_ids,
        match_score=match.match_score,
        score_breakdown=match.score_breakdown,
        status=ReconciliationStatusEnum(match.status.value),
        version=match.version,
        superseded_by_id=match.superseded_by_id,
        created_at=match.created_at,
        updated_at=match.updated_at,
        transaction=transaction,
        entries=entries,
    )


@router.post("/run", response_model=ReconciliationRunResponse)
async def run_reconciliation(
    payload: ReconciliationRunRequest,
    db: AsyncSession = Depends(get_db),
) -> ReconciliationRunResponse:
    matches = await execute_matching(
        db,
        statement_id=payload.statement_id,
        limit=payload.limit,
    )
    auto_accepted = sum(1 for match in matches if match.status.value == "auto_accepted")
    pending_review = sum(1 for match in matches if match.status.value == "pending_review")

    unmatched_query = select(func.count(BankStatementTransaction.id)).where(
        BankStatementTransaction.status == BankStatementTransactionStatus.UNMATCHED
    )
    if payload.statement_id:
        unmatched_query = unmatched_query.where(
            BankStatementTransaction.statement_id == payload.statement_id
        )
    unmatched_result = await db.execute(unmatched_query)
    unmatched_count = unmatched_result.scalar_one()

    return ReconciliationRunResponse(
        matches_created=len(matches),
        auto_accepted=auto_accepted,
        pending_review=pending_review,
        unmatched=unmatched_count,
    )


@router.get("/matches", response_model=ReconciliationMatchListResponse)
async def list_matches(
    status: ReconciliationStatusEnum | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationMatchListResponse:
    query = select(ReconciliationMatch).options(selectinload(ReconciliationMatch.transaction))
    if status:
        query = query.where(ReconciliationMatch.status == ReconciliationStatus(status.value))
    query = query.order_by(ReconciliationMatch.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    matches = result.scalars().all()
    items = [await _build_match_response(db, match) for match in matches]

    total_query = select(func.count(ReconciliationMatch.id))
    if status:
        total_query = total_query.where(
            ReconciliationMatch.status == ReconciliationStatus(status.value)
        )
    total_result = await db.execute(total_query)
    total = total_result.scalar_one()

    return ReconciliationMatchListResponse(items=items, total=total)


@router.get("/pending", response_model=ReconciliationMatchListResponse)
async def pending_review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ReconciliationMatchListResponse:
    matches = await get_pending_items(db, limit=limit, offset=offset)
    items = [await _build_match_response(db, match) for match in matches]
    return ReconciliationMatchListResponse(items=items, total=len(items))


@router.post("/matches/{match_id}/accept", response_model=ReconciliationMatchResponse)
async def accept_match(
    match_id: str,
    db: AsyncSession = Depends(get_db),
) -> ReconciliationMatchResponse:
    try:
        match = await accept_match_service(db, match_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.refresh(match)
    return await _build_match_response(db, match)


@router.post("/matches/{match_id}/reject", response_model=ReconciliationMatchResponse)
async def reject_match(
    match_id: str,
    db: AsyncSession = Depends(get_db),
) -> ReconciliationMatchResponse:
    try:
        match = await reject_match_service(db, match_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.refresh(match)
    return await _build_match_response(db, match)


@router.post("/batch-accept", response_model=ReconciliationMatchListResponse)
async def batch_accept(
    payload: BatchAcceptRequest,
    db: AsyncSession = Depends(get_db),
) -> ReconciliationMatchListResponse:
    matches = await batch_accept_service(db, payload.match_ids)
    items = [await _build_match_response(db, match) for match in matches]
    return ReconciliationMatchListResponse(items=items, total=len(items))


@router.get("/stats", response_model=ReconciliationStatsResponse)
async def reconciliation_stats(db: AsyncSession = Depends(get_db)) -> ReconciliationStatsResponse:
    total_result = await db.execute(select(func.count(BankStatementTransaction.id)))
    matched_result = await db.execute(
        select(func.count(BankStatementTransaction.id)).where(
            BankStatementTransaction.status == BankStatementTransactionStatus.MATCHED
        )
    )
    unmatched_result = await db.execute(
        select(func.count(BankStatementTransaction.id)).where(
            BankStatementTransaction.status == BankStatementTransactionStatus.UNMATCHED
        )
    )
    pending_result = await db.execute(
        select(func.count(ReconciliationMatch.id)).where(
            ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW
        )
    )
    auto_result = await db.execute(
        select(func.count(ReconciliationMatch.id)).where(
            ReconciliationMatch.status == ReconciliationStatus.AUTO_ACCEPTED
        )
    )

    total = total_result.scalar_one()
    matched = matched_result.scalar_one()
    unmatched = unmatched_result.scalar_one()
    pending = pending_result.scalar_one()
    auto = auto_result.scalar_one()

    score_result = await db.execute(select(ReconciliationMatch.match_score))
    scores = [row[0] for row in score_result.all()]
    buckets = {"0-59": 0, "60-79": 0, "80-89": 0, "90-100": 0}
    for score in scores:
        if score < 60:
            buckets["0-59"] += 1
        elif score < 80:
            buckets["60-79"] += 1
        elif score < 90:
            buckets["80-89"] += 1
        else:
            buckets["90-100"] += 1

    match_rate = float(round((matched / total) * 100, 2)) if total else 0.0

    return ReconciliationStatsResponse(
        total_transactions=total,
        matched_transactions=matched,
        unmatched_transactions=unmatched,
        pending_review=pending,
        auto_accepted=auto,
        match_rate=match_rate,
        score_distribution=buckets,
    )


@router.get("/unmatched", response_model=UnmatchedTransactionsResponse)
async def list_unmatched(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> UnmatchedTransactionsResponse:
    result = await db.execute(
        select(BankStatementTransaction)
        .where(BankStatementTransaction.status == BankStatementTransactionStatus.UNMATCHED)
        .order_by(BankStatementTransaction.txn_date.desc())
        .limit(limit)
        .offset(offset)
    )
    items = result.scalars().all()

    total_result = await db.execute(
        select(func.count(BankStatementTransaction.id)).where(
            BankStatementTransaction.status == BankStatementTransactionStatus.UNMATCHED
        )
    )
    total = total_result.scalar_one()

    return UnmatchedTransactionsResponse(items=items, total=total)


@router.post("/unmatched/{txn_id}/create-entry", response_model=JournalEntrySummary)
async def create_entry(
    txn_id: str,
    db: AsyncSession = Depends(get_db),
) -> JournalEntrySummary:
    result = await db.execute(
        select(BankStatementTransaction).where(BankStatementTransaction.id == txn_id)
    )
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    entry = await create_entry_from_txn(db, txn)
    return _build_entry_summary(entry)


@router.get("/transactions/{txn_id}/anomalies", response_model=list[AnomalyResponse])
async def list_anomalies(
    txn_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[AnomalyResponse]:
    result = await db.execute(
        select(BankStatementTransaction).where(BankStatementTransaction.id == txn_id)
    )
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    anomalies = await detect_anomalies(db, txn)
    return [AnomalyResponse(**anomaly.__dict__) for anomaly in anomalies]
