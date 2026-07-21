"""Reconciliation API router."""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from src.audit import STATEMENT_SOURCE_TYPES
from src.composition import compose_reviewed_disposition_dependencies
from src.config_app import get_effective_base_currency
from src.deps import CurrentUserId, DbSession, Pagination
from src.extraction import BankStatementStatus
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    Direction,
    JournalEntry,
    JournalEntryStatus,
    ValidationError,
    current_anchored_journal_entries,
)
from src.observability import ensure_request_id, get_logger, log_financial_mutation, safe_error_message
from src.platform import get_owned_or_404, raise_bad_request, raise_not_found
from src.reconciliation import (
    MatchNotFoundError,
    ReconciliationError,
    ReconciliationMatch,
    ReconciliationStatus,
    ReviewedDispositionCommand,
    ReviewedDispositionError,
    accept_match as accept_match_service,
    batch_accept as batch_accept_service,
    detect_anomalies,
    execute_matching,
    get_pending_items,
    get_reconciliation_stats,
    reject_match as reject_match_service,
    submit_reviewed_disposition,
)
from src.schemas.reconciliation import (
    AnomalyResponse,
    BankTransactionSummary,
    BatchAcceptRequest,
    JournalEntrySummary,
    ReconciliationMatchListResponse,
    ReconciliationMatchResponse,
    ReconciliationRunRequest,
    ReconciliationRunResponse,
    ReconciliationStatsResponse,
    ReconciliationStatusEnum,
    ReviewedDispositionRequest,
    UnmatchedTransactionsResponse,
)

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])
logger = get_logger(__name__)


def _unmatched_atomic_txn_query(user_id: UUID):
    """Select Layer-2 atomic transactions that still require economic review.

    A source entry created from a reviewed disposition is already resolved; it
    must not keep reappearing in the unmatched queue merely because it has no
    separate reconciliation-match row.
    """
    matched_transaction = aliased(AtomicTransaction)
    matched_subquery = (
        select(ReconciliationMatch.atomic_txn_id)
        .join(matched_transaction, matched_transaction.id == ReconciliationMatch.atomic_txn_id)
        .where(matched_transaction.user_id == user_id)
        .where(ReconciliationMatch.atomic_txn_id.is_not(None))
    )
    posted_source_subquery = (
        current_anchored_journal_entries(
            user_id=user_id,
            target_kind="journal_command",
            target_id=func.concat("statement-transaction:", JournalEntry.source_id),
        )
        .with_only_columns(JournalEntry.source_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.status != JournalEntryStatus.VOID)
    )
    return select(AtomicTransaction).where(
        AtomicTransaction.user_id == user_id,
        AtomicTransaction.id.notin_(matched_subquery),
        AtomicTransaction.id.notin_(posted_source_subquery),
    )


async def _statement_atomic_txn_ids(db: AsyncSession, statement: StatementSummary) -> list[UUID]:
    """Resolve the atomic transaction ids for a statement via its ODS document link."""
    if statement.uploaded_document_id is None:
        return []
    doc_marker = [{"doc_id": str(statement.uploaded_document_id)}]
    result = await db.execute(
        select(AtomicTransaction.id)
        .where(AtomicTransaction.user_id == statement.user_id)
        .where(AtomicTransaction.source_documents.contains(doc_marker))
    )
    return list(result.scalars().all())


def _entry_total_amount(entry: JournalEntry) -> Decimal:
    return sum((line.amount for line in entry.lines if line.direction == Direction.DEBIT), Decimal("0"))


def _build_entry_summary(entry: JournalEntry) -> JournalEntrySummary:
    return JournalEntrySummary(
        id=entry.id,
        entry_date=entry.entry_date,
        memo=entry.memo,
        status=entry.status.value,
        total_amount=_entry_total_amount(entry),
    )


def _build_match_response(
    match: ReconciliationMatch,
    *,
    transaction: AtomicTransaction | None,
    entry_summaries: dict[str, JournalEntrySummary],
) -> ReconciliationMatchResponse:
    entries: list[JournalEntrySummary] = []
    for entry_id in match.journal_entry_ids or []:
        summary = entry_summaries.get(entry_id)
        if summary:
            entries.append(summary)
    return ReconciliationMatchResponse(
        id=match.id,
        atomic_txn_id=match.atomic_txn_id,
        journal_entry_ids=match.journal_entry_ids,
        match_score=match.match_score,
        score_breakdown=match.score_breakdown,
        status=ReconciliationStatusEnum(match.status.value),
        version=match.version,
        superseded_by_id=match.superseded_by_id,
        created_at=match.created_at,
        updated_at=match.updated_at,
        transaction=BankTransactionSummary.model_validate(transaction) if transaction else None,
        entries=entries,
    )


async def _load_entry_summaries(
    db: AsyncSession,
    matches: Sequence[ReconciliationMatch],
    user_id: UUID,
) -> dict[str, JournalEntrySummary]:
    entry_ids: set[UUID] = set()
    for match in matches:
        for entry_id in match.journal_entry_ids or []:
            try:
                entry_ids.add(UUID(entry_id))
            except ValueError:
                logger.warning(
                    "Invalid UUID in journal_entry_ids",
                    match_id=str(match.id),
                    invalid_entry_id=entry_id,
                )
                continue

    if not entry_ids:
        return {}

    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id.in_(entry_ids))
        .where(JournalEntry.user_id == user_id)
        .options(selectinload(JournalEntry.lines))
    )
    return {str(entry.id): _build_entry_summary(entry) for entry in result.scalars().all()}


async def _load_transactions(
    db: AsyncSession,
    matches: Sequence[ReconciliationMatch],
) -> dict[UUID, AtomicTransaction]:
    """Batch-fetch each match's ``AtomicTransaction`` by id (#1675 D4: no
    relationship() eager-load across the reconciliation -> extraction
    boundary)."""
    txn_ids = {match.atomic_txn_id for match in matches}
    if not txn_ids:
        return {}
    result = await db.execute(select(AtomicTransaction).where(AtomicTransaction.id.in_(txn_ids)))
    return {txn.id: txn for txn in result.scalars().all()}


# Synchronous 200: matching runs inline and the response carries the completed run
# result (matches_created/auto_accepted/pending_review/unmatched), so this is a
# finished operation, not a 202 background job (cf. #1099 AC-platform.29.1).
@router.post("/runs", response_model=ReconciliationRunResponse, status_code=status.HTTP_200_OK)
async def run_reconciliation(
    payload: ReconciliationRunRequest,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReconciliationRunResponse:
    statement: StatementSummary | None = None
    if payload.statement_id:
        stmt_result = await db.execute(
            select(StatementSummary)
            .where(StatementSummary.id == payload.statement_id)
            .where(StatementSummary.user_id == user_id)
            .where(StatementSummary.status != BankStatementStatus.RETIRED)
        )
        statement = stmt_result.scalar_one_or_none()
        if statement is None:
            raise_not_found("Statement")

    request_id = ensure_request_id()
    statement_id = str(payload.statement_id) if payload.statement_id else None
    logger.info(
        "reconciliation.run.started",
        audit_event="reconciliation.run.started",
        request_id=request_id,
        statement_id=statement_id,
        phase="matching_started",
        progress=None,
        model_to_use=None,
        limit=payload.limit,
    )

    try:
        currency = await get_effective_base_currency(db)
        matches = await execute_matching(
            db,
            limit=payload.limit,
            user_id=user_id,
            currency=currency,
        )
        await db.commit()
    except ValidationError as exc:
        await db.rollback()
        raise_bad_request(str(exc), cause=exc)
    except Exception as exc:
        logger.exception(
            "reconciliation.run.failed",
            audit_event="reconciliation.run.failed",
            request_id=request_id,
            statement_id=statement_id,
            phase="matching_failed",
            progress=None,
            model_to_use=None,
            limit=payload.limit,
            error_type=type(exc).__name__,
            safe_error_message=safe_error_message(str(exc)),
        )
        await db.rollback()
        raise

    auto_accepted = sum(1 for match in matches if match.status.value == "auto_accepted")
    pending_review = sum(1 for match in matches if match.status.value == "pending_review")

    unmatched_query = _unmatched_atomic_txn_query(user_id)
    if statement is not None:
        statement_txn_ids = await _statement_atomic_txn_ids(db, statement)
        if not statement_txn_ids:
            unmatched_count = 0
        else:
            unmatched_query = unmatched_query.where(AtomicTransaction.id.in_(statement_txn_ids))
            unmatched_result = await db.execute(select(func.count()).select_from(unmatched_query.subquery()))
            unmatched_count = unmatched_result.scalar_one()
    else:
        unmatched_result = await db.execute(select(func.count()).select_from(unmatched_query.subquery()))
        unmatched_count = unmatched_result.scalar_one()

    logger.info(
        "reconciliation.run.completed",
        audit_event="reconciliation.run.completed",
        request_id=request_id,
        statement_id=statement_id,
        phase="matching_completed",
        progress=None,
        model_to_use=None,
        limit=payload.limit,
        matches_created=len(matches),
        auto_accepted=auto_accepted,
        pending_review=pending_review,
        unmatched=unmatched_count,
    )

    return ReconciliationRunResponse(
        matches_created=len(matches),
        auto_accepted=auto_accepted,
        pending_review=pending_review,
        unmatched=unmatched_count,
    )


@router.get("/matches", response_model=ReconciliationMatchListResponse)
async def list_matches(
    status_filter: ReconciliationStatusEnum | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReconciliationMatchListResponse:
    query = (
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(AtomicTransaction.user_id == user_id)
    )
    if status_filter:
        query = query.where(ReconciliationMatch.status == ReconciliationStatus(status_filter.value))
    query = query.order_by(ReconciliationMatch.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    matches = result.scalars().all()
    entry_summaries = await _load_entry_summaries(db, matches, user_id)
    txn_map = await _load_transactions(db, matches)
    items = [
        _build_match_response(
            match,
            transaction=txn_map.get(match.atomic_txn_id),
            entry_summaries=entry_summaries,
        )
        for match in matches
    ]

    total_query = (
        select(func.count(ReconciliationMatch.id))
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(AtomicTransaction.user_id == user_id)
    )
    if status_filter:
        total_query = total_query.where(ReconciliationMatch.status == ReconciliationStatus(status_filter.value))
    total_result = await db.execute(total_query)
    total = total_result.scalar_one()

    return ReconciliationMatchListResponse(items=items, total=total)


@router.get("/pending", response_model=ReconciliationMatchListResponse)
async def pending_review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReconciliationMatchListResponse:
    matches = await get_pending_items(db, limit=limit, offset=offset, user_id=user_id)
    entry_summaries = await _load_entry_summaries(db, matches, user_id)
    txn_map = await _load_transactions(db, matches)
    items = [
        _build_match_response(
            match,
            transaction=txn_map.get(match.atomic_txn_id),
            entry_summaries=entry_summaries,
        )
        for match in matches
    ]

    total_query = (
        select(func.count(ReconciliationMatch.id))
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(AtomicTransaction.user_id == user_id)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
    )
    total_result = await db.execute(total_query)
    total = total_result.scalar_one()

    return ReconciliationMatchListResponse(items=items, total=total)


@router.post("/matches/{match_id}/accept", response_model=ReconciliationMatchResponse)
async def accept_match(
    match_id: UUID,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReconciliationMatchResponse:
    try:
        match = await accept_match_service(
            db,
            match_id,
            user_id=user_id,
        )
        await db.commit()
    except MatchNotFoundError as exc:
        raise_not_found("Match", cause=exc)
    except ReconciliationError as exc:
        raise_bad_request(str(exc), cause=exc)
    log_financial_mutation(
        logger,
        "reconciliation.match.accepted",
        user_id=user_id,
        action="accept",
        resource_type="reconciliation_match",
        resource_id=match.id,
        status=match.status.value,
    )
    entry_summaries = await _load_entry_summaries(db, [match], user_id)
    txn = await db.get(AtomicTransaction, match.atomic_txn_id)
    return _build_match_response(
        match,
        transaction=txn,
        entry_summaries=entry_summaries,
    )


@router.post("/matches/{match_id}/reject", response_model=ReconciliationMatchResponse)
async def reject_match(
    match_id: UUID,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReconciliationMatchResponse:
    try:
        match = await reject_match_service(db, str(match_id), user_id=user_id)
        await db.commit()
    except MatchNotFoundError as exc:
        raise_not_found("Match", cause=exc)
    except ReconciliationError as exc:
        raise_bad_request(str(exc), cause=exc)
    entry_summaries = await _load_entry_summaries(db, [match], user_id)
    txn = await db.get(AtomicTransaction, match.atomic_txn_id)
    return _build_match_response(
        match,
        transaction=txn,
        entry_summaries=entry_summaries,
    )


@router.post("/batch-accept", response_model=ReconciliationMatchListResponse)
async def batch_accept(
    payload: BatchAcceptRequest,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReconciliationMatchListResponse:
    try:
        matches = await batch_accept_service(
            db,
            payload.match_ids,
            user_id=user_id,
        )
        await db.commit()
    except ReconciliationError as exc:
        raise_bad_request(str(exc), cause=exc)
    log_financial_mutation(
        logger,
        "reconciliation.match.batch_accepted",
        user_id=user_id,
        action="batch_accept",
        resource_type="reconciliation_match",
        resource_id="batch",
        requested_count=len(payload.match_ids),
        accepted_count=len(matches),
    )
    if not matches:
        return ReconciliationMatchListResponse(items=[], total=0)

    match_ids = [match.id for match in matches]
    result = await db.execute(select(ReconciliationMatch).where(ReconciliationMatch.id.in_(match_ids)))
    loaded_matches = result.scalars().all()
    entry_summaries = await _load_entry_summaries(db, loaded_matches, user_id)
    txn_map = await _load_transactions(db, loaded_matches)
    items = [
        _build_match_response(
            match,
            transaction=txn_map.get(match.atomic_txn_id),
            entry_summaries=entry_summaries,
        )
        for match in loaded_matches
    ]
    return ReconciliationMatchListResponse(items=items, total=len(items))


@router.get("/stats", response_model=ReconciliationStatsResponse)
async def reconciliation_stats(
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReconciliationStatsResponse:
    stats = await get_reconciliation_stats(db, user_id, include_distribution=True)
    return ReconciliationStatsResponse(
        total_transactions=stats.total_transactions,
        matched_transactions=stats.matched_transactions,
        unmatched_transactions=stats.unmatched_transactions,
        pending_review=stats.pending_review,
        auto_accepted=stats.auto_accepted,
        match_rate=stats.match_rate,
        score_distribution=stats.score_distribution or {},
    )


@router.get("/unmatched", response_model=UnmatchedTransactionsResponse)
async def list_unmatched(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> UnmatchedTransactionsResponse:
    result = await db.execute(
        _unmatched_atomic_txn_query(user_id).order_by(AtomicTransaction.txn_date.desc()).limit(limit).offset(offset)
    )
    items = [BankTransactionSummary.model_validate(item) for item in result.scalars().all()]

    total_result = await db.execute(select(func.count()).select_from(_unmatched_atomic_txn_query(user_id).subquery()))
    total = total_result.scalar_one()

    return UnmatchedTransactionsResponse(items=items, total=total)


@router.post("/unmatched/{txn_id}/reviewed-disposition", response_model=JournalEntrySummary)
async def submit_unmatched_reviewed_disposition(
    txn_id: UUID,
    payload: ReviewedDispositionRequest,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> JournalEntrySummary:
    """Post one unmatched source transaction from explicit reviewed economic meaning."""
    try:
        entry = await submit_reviewed_disposition(
            db,
            transaction_id=txn_id,
            user_id=user_id,
            command=ReviewedDispositionCommand(
                intent=payload.intent,
                counter_account_id=payload.counter_account_id,
                category=payload.category,
                rationale=payload.rationale,
            ),
            dependencies=compose_reviewed_disposition_dependencies(db),
        )
        entry_with_lines = (
            await db.execute(
                select(JournalEntry).options(selectinload(JournalEntry.lines)).where(JournalEntry.id == entry.id)
            )
        ).scalar_one()
        response = _build_entry_summary(entry_with_lines)
        await db.commit()
    except LookupError as exc:
        await db.rollback()
        raise_not_found("Transaction", cause=exc)
    except ReviewedDispositionError as exc:
        await db.rollback()
        raise_bad_request(str(exc), cause=exc)
    except Exception:
        # The TraceRecord causal set and source entry are one caller-owned UoW.
        await db.rollback()
        raise
    return response


@router.get("/transactions/{txn_id}/anomalies", response_model=list[AnomalyResponse])
async def list_anomalies(
    txn_id: UUID,
    *,
    db: DbSession,
    user_id: CurrentUserId,
    pagination: Pagination,
) -> list[AnomalyResponse]:
    txn = await get_owned_or_404(db, AtomicTransaction, txn_id, user_id, name="Transaction")
    anomalies = await detect_anomalies(db, txn, user_id=user_id)
    page = anomalies[pagination.offset : pagination.offset + pagination.limit]
    return [AnomalyResponse(**anomaly.__dict__) for anomaly in page]
