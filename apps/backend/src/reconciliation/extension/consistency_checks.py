from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.extraction import StatementSummary, TransactionDirection, effective_statement_transaction_filter
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import (
    JournalEntry,
    TransferPair,
    find_transfer_pairs,
)
from src.reconciliation.base.errors import (
    CheckResolutionAction,
    ConsistencyCheckNotFoundError,
    InvalidCheckActionError,
)
from src.reconciliation.extension.anomaly import detect_anomalies
from src.reconciliation.extension.scoring import score_description
from src.reconciliation.extension.transfer_pairs import paired_transfer_entry_ids, persist_transfer_pairs
from src.reconciliation.orm.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.reconciliation.orm.reconciliation import (
    DispositionKind,
    ReconciliationMatch,
    ReconciliationMatchJournalEntry,
    ReconciliationStatus,
    ReconciliationTransferPair,
    ReconciliationTransferPairLeg,
    TransferPairDecision,
    TransferPairReviewState,
)

TRANSFER_TOLERANCE = Decimal("0.001")
TRANSFER_DATE_TOLERANCE_DAYS = 3


def _extract_doc_ids(txn: AtomicTransaction) -> set[str]:
    """Extract normalized document IDs from a transaction's source_documents list."""
    doc_ids: set[str] = set()
    for doc in txn.source_documents or []:
        if isinstance(doc, dict) and doc.get("doc_id"):
            doc_ids.add(str(doc["doc_id"]))
    return doc_ids


async def _load_doc_account_map(db: AsyncSession, user_id: UUID) -> dict[str, str]:
    """Map uploaded_document_id strings to their linked StatementSummary account_id or statement_id."""
    rows = (
        await db.execute(
            select(
                StatementSummary.uploaded_document_id,
                StatementSummary.account_id,
                StatementSummary.id,
            ).where(
                StatementSummary.user_id == user_id,
                StatementSummary.uploaded_document_id.is_not(None),
            )
        )
    ).all()
    mapping: dict[str, str] = {}
    for doc_id, account_id, stmt_id in rows:
        if doc_id is not None:
            mapping[str(doc_id)] = str(account_id) if account_id is not None else f"stmt:{stmt_id}"
    return mapping


def _txn_account_scope(txn: AtomicTransaction, doc_account_map: dict[str, str]) -> str:
    """Resolve the statement/account scope for a transaction when linked to a known statement."""
    for doc_id in sorted(_extract_doc_ids(txn)):
        if doc_id in doc_account_map:
            return doc_account_map[doc_id]
    return ""


async def detect_duplicates(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID | None = None,
    run_id: str | None = None,
) -> list[ConsistencyCheck]:
    _ = statement_id
    base_query = select(AtomicTransaction).where(effective_statement_transaction_filter(user_id))

    all_result = await db.execute(base_query)
    all_txns = list(all_result.scalars().all())
    anchor_txns = all_txns
    doc_account_map = await _load_doc_account_map(db, user_id)

    groups: dict[str, list[AtomicTransaction]] = {}
    for txn in all_txns:
        currency_code = txn.currency.upper() if txn.currency else ""
        account_scope = _txn_account_scope(txn, doc_account_map)
        desc_prefix = txn.description[:50] if txn.description else ""
        key = f"{currency_code}_{txn.txn_date}_{txn.amount}_{txn.direction.value}_{desc_prefix}_{account_scope}"
        if key not in groups:
            groups[key] = []
        groups[key].append(txn)

    checks: list[ConsistencyCheck] = []
    anchor_ids = {str(t.id) for t in anchor_txns}

    for key, group in groups.items():
        if len(group) > 1:
            # Only process if at least one transaction in the group is an anchor
            if not any(str(t.id) in anchor_ids for t in group):
                continue

            dates = sorted([t.txn_date for t in group])
            if (dates[-1] - dates[0]).days == 0:
                txn_ids = sorted([str(t.id) for t in group])
                group_currency = group[0].currency.upper() if group[0].currency else ""

                # Idempotency: check if pending check already exists
                existing = await db.execute(
                    select(ConsistencyCheck).where(
                        ConsistencyCheck.user_id == user_id,
                        ConsistencyCheck.check_type == CheckType.DUPLICATE,
                        ConsistencyCheck.status == CheckStatus.PENDING,
                        ConsistencyCheck.related_txn_ids == txn_ids,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                check = ConsistencyCheck(
                    user_id=user_id,
                    run_id=run_id,
                    check_type=CheckType.DUPLICATE,
                    status=CheckStatus.PENDING,
                    related_txn_ids=txn_ids,
                    details={
                        "count": len(group),
                        "currency": group_currency,
                        "amount": str(group[0].amount),
                        "description": group[0].description,
                        "date_range": f"{dates[0]} to {dates[-1]}",
                    },
                    severity="high",
                )
                checks.append(check)
                db.add(check)

    if checks:
        await db.flush()
    return checks


async def detect_transfer_pairs(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID | None = None,
    run_id: str | None = None,
) -> list[ConsistencyCheck]:
    _ = statement_id
    paired_txn_subquery = (
        select(ReconciliationMatch.atomic_txn_id)
        .join(
            ReconciliationTransferPairLeg,
            ReconciliationTransferPairLeg.disposition_id == ReconciliationMatch.id,
        )
        .join(
            ReconciliationTransferPair,
            ReconciliationTransferPair.id == ReconciliationTransferPairLeg.pair_id,
        )
        .where(
            ReconciliationMatch.disposition_kind == DispositionKind.TRANSFER_LEG,
            ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
            ReconciliationMatch.superseded_by_id.is_(None),
            ReconciliationTransferPair.review_state == TransferPairReviewState.PAIRED,
        )
    )
    base_query = select(AtomicTransaction).where(
        effective_statement_transaction_filter(user_id),
        AtomicTransaction.id.notin_(paired_txn_subquery),
    )

    all_result = await db.execute(base_query)
    all_txns = list(all_result.scalars().all())
    doc_account_map = await _load_doc_account_map(db, user_id)
    out_txns = [t for t in all_txns if t.direction == TransactionDirection.OUT]

    in_txns_by_key: dict[tuple[str, Decimal], list[AtomicTransaction]] = {}
    for t in all_txns:
        if t.direction == TransactionDirection.IN:
            curr = t.currency.upper() if t.currency else ""
            if (curr, t.amount) not in in_txns_by_key:
                in_txns_by_key[(curr, t.amount)] = []
            in_txns_by_key[(curr, t.amount)].append(t)

    checks: list[ConsistencyCheck] = []
    matched_in: set[str] = set()

    for out_txn in out_txns:
        out_curr = out_txn.currency.upper() if out_txn.currency else ""
        out_docs = _extract_doc_ids(out_txn)
        out_scope = _txn_account_scope(out_txn, doc_account_map)
        candidates = in_txns_by_key.get((out_curr, out_txn.amount), [])
        for in_txn in candidates:
            if str(in_txn.id) in matched_in:
                continue
            in_docs = _extract_doc_ids(in_txn)
            in_scope = _txn_account_scope(in_txn, doc_account_map)
            if (out_docs and in_docs and (out_docs & in_docs)) or (out_scope and in_scope and out_scope == in_scope):
                continue

            date_diff = abs((out_txn.txn_date - in_txn.txn_date).days)
            if date_diff <= TRANSFER_DATE_TOLERANCE_DAYS:
                txn_ids = sorted([str(out_txn.id), str(in_txn.id)])

                # Idempotency
                existing = await db.execute(
                    select(ConsistencyCheck).where(
                        ConsistencyCheck.user_id == user_id,
                        ConsistencyCheck.check_type == CheckType.TRANSFER_PAIR,
                        ConsistencyCheck.status == CheckStatus.PENDING,
                        ConsistencyCheck.related_txn_ids == txn_ids,
                    )
                )
                if existing.scalar_one_or_none():
                    matched_in.add(str(in_txn.id))
                    continue

                check = ConsistencyCheck(
                    user_id=user_id,
                    run_id=run_id,
                    check_type=CheckType.TRANSFER_PAIR,
                    status=CheckStatus.PENDING,
                    related_txn_ids=txn_ids,
                    details={
                        "amount": str(out_txn.amount),
                        "currency": out_curr,
                        "out_date": str(out_txn.txn_date),
                        "in_date": str(in_txn.txn_date),
                        "amount_delta": "0.00",
                        "date_diff_days": date_diff,
                    },
                    severity="medium",
                )
                checks.append(check)
                db.add(check)
                matched_in.add(str(in_txn.id))
                break

    if checks:
        await db.flush()
    return checks


async def detect_anomalies_batch(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID | None = None,
    run_id: str | None = None,
) -> list[ConsistencyCheck]:
    _ = statement_id
    query = select(AtomicTransaction).where(effective_statement_transaction_filter(user_id))

    result = await db.execute(query)
    transactions = list(result.scalars().all())

    checks: list[ConsistencyCheck] = []
    for txn in transactions:
        anomalies = await detect_anomalies(db, txn, user_id=user_id)
        for anomaly in anomalies:
            txn_ids = [str(txn.id)]

            # Idempotency
            existing = await db.execute(
                select(ConsistencyCheck).where(
                    ConsistencyCheck.user_id == user_id,
                    ConsistencyCheck.check_type == CheckType.ANOMALY,
                    ConsistencyCheck.status == CheckStatus.PENDING,
                    ConsistencyCheck.related_txn_ids == txn_ids,
                )
            )
            found = False
            for existing_check in existing.scalars().all():
                if existing_check.details.get("anomaly_type") == anomaly.anomaly_type:
                    found = True
                    break
            if found:
                continue

            check = ConsistencyCheck(
                user_id=user_id,
                run_id=run_id,
                check_type=CheckType.ANOMALY,
                status=CheckStatus.PENDING,
                related_txn_ids=txn_ids,
                details={
                    "anomaly_type": anomaly.anomaly_type,
                    "message": anomaly.message,
                    "amount": str(txn.amount),
                    "date": str(txn.txn_date),
                },
                severity=anomaly.severity,
            )
            checks.append(check)
            db.add(check)

    if checks:
        await db.flush()
    return checks


async def run_all_consistency_checks(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID,
    run_id: str | None = None,
) -> list[ConsistencyCheck]:
    checks: list[ConsistencyCheck] = []
    checks.extend(await detect_duplicates(db, user_id, statement_id, run_id=run_id))
    checks.extend(await detect_transfer_pairs(db, user_id, statement_id, run_id=run_id))
    checks.extend(await detect_anomalies_batch(db, user_id, statement_id, run_id=run_id))
    return checks


async def _persist_approved_transfer_pair_check(
    db: AsyncSession,
    check: ConsistencyCheck,
    user_id: UUID,
) -> None:
    if not check.related_txn_ids or len(check.related_txn_ids) != 2:
        return

    try:
        txn_ids = [UUID(tid) for tid in check.related_txn_ids]
    except (ValueError, TypeError):
        return

    rows = (
        await db.execute(
            select(
                ReconciliationMatchJournalEntry.journal_entry_id,
                AtomicTransaction.direction,
                AtomicTransaction.currency,
            )
            .join(
                ReconciliationMatch,
                ReconciliationMatch.id == ReconciliationMatchJournalEntry.match_id,
            )
            .join(
                AtomicTransaction,
                AtomicTransaction.id == ReconciliationMatch.atomic_txn_id,
            )
            .where(
                AtomicTransaction.user_id == user_id,
                AtomicTransaction.id.in_(txn_ids),
                ReconciliationMatch.disposition_kind == DispositionKind.TRANSFER_LEG,
                ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
                ReconciliationMatch.superseded_by_id.is_(None),
            )
        )
    ).all()

    out_entry_id: UUID | None = None
    in_entry_id: UUID | None = None
    currency: str | None = None

    for entry_id, direction, curr in rows:
        if direction == TransactionDirection.OUT:
            out_entry_id = entry_id
            currency = curr
        elif direction == TransactionDirection.IN:
            in_entry_id = entry_id
            if currency is None:
                currency = curr

    if out_entry_id is None or in_entry_id is None or currency is None:
        return

    entries_result = await db.execute(
        select(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .where(
            JournalEntry.user_id == user_id,
            JournalEntry.id.in_([out_entry_id, in_entry_id]),
        )
    )
    entries = {entry.id: entry for entry in entries_result.scalars().all()}
    out_entry = entries.get(out_entry_id)
    in_entry = entries.get(in_entry_id)
    if out_entry is None or in_entry is None:
        return

    paired_ids = await paired_transfer_entry_ids(db, user_id=user_id) - {out_entry.id, in_entry.id}
    candidate_pairs = await find_transfer_pairs(
        db,
        user_id,
        currency=currency,
        description_scorer=score_description,
        threshold=0,
        exclude_entry_ids=paired_ids,
    )
    matched_pair = next(
        (p for p in candidate_pairs if p.out_entry.id == out_entry.id and p.in_entry.id == in_entry.id),
        None,
    )
    if matched_pair is None:
        matched_pair = TransferPair(
            out_entry=out_entry,
            in_entry=in_entry,
            confidence=100,
            score_breakdown={"reviewer_approved": 100.0},
        )

    await persist_transfer_pairs(db, [matched_pair], decision=TransferPairDecision.REVIEWER_PAIRED)


async def resolve_check(
    db: AsyncSession,
    check_id: UUID,
    action: CheckResolutionAction,
    user_id: UUID,
    note: str | None = None,
) -> ConsistencyCheck:
    result = await db.execute(
        select(ConsistencyCheck)
        .where(ConsistencyCheck.id == check_id)
        .where(ConsistencyCheck.user_id == user_id)
        .with_for_update()
    )
    check = result.scalar_one_or_none()
    if not check:
        raise ConsistencyCheckNotFoundError("Check not found or access denied")

    if action == CheckResolutionAction.APPROVE:
        check.status = CheckStatus.APPROVED
        if check.check_type == CheckType.TRANSFER_PAIR:
            await _persist_approved_transfer_pair_check(db, check, user_id)
    elif action == CheckResolutionAction.REJECT:
        check.status = CheckStatus.REJECTED
    elif action == CheckResolutionAction.FLAG:
        check.status = CheckStatus.FLAGGED
    else:
        raise InvalidCheckActionError(f"Invalid action: {action}")

    check.resolved_at = datetime.now(UTC)
    if note:
        check.resolution_note = note

    await db.flush()
    return check


async def has_unresolved_checks(
    db: AsyncSession,
    user_id: UUID,
    run_id: str | None = None,
) -> bool:
    query = (
        select(ConsistencyCheck.id)
        .where(ConsistencyCheck.user_id == user_id)
        .where(ConsistencyCheck.status == CheckStatus.PENDING)
        .where(
            or_(
                ConsistencyCheck.severity.is_(None),
                ConsistencyCheck.severity != "low",
            )
        )
        .limit(1)
    )
    if run_id:
        query = query.where(
            or_(
                ConsistencyCheck.run_id == run_id,
                ConsistencyCheck.run_id.is_(None),
            )
        )

    result = await db.execute(query)
    return result.scalar_one_or_none() is not None


async def list_checks(
    db: AsyncSession,
    user_id: UUID,
    *,
    status: CheckStatus | None = None,
    check_type: CheckType | None = None,
    severity: str | None = None,
    run_id: str | None = None,
    limit: int | None = 50,
    offset: int = 0,
) -> tuple[list[ConsistencyCheck], int]:
    """Return filtered consistency checks with total count."""
    query = (
        select(ConsistencyCheck)
        .where(ConsistencyCheck.user_id == user_id)
        .order_by(desc(ConsistencyCheck.created_at))
        .offset(offset)
    )
    if limit is not None:
        query = query.limit(limit)

    count_query = select(func.count()).select_from(ConsistencyCheck).where(ConsistencyCheck.user_id == user_id)

    if status:
        query = query.where(ConsistencyCheck.status == status)
        count_query = count_query.where(ConsistencyCheck.status == status)
    if check_type:
        query = query.where(ConsistencyCheck.check_type == check_type)
        count_query = count_query.where(ConsistencyCheck.check_type == check_type)
    if severity:
        query = query.where(ConsistencyCheck.severity == severity)
        count_query = count_query.where(ConsistencyCheck.severity == severity)
    if run_id:
        run_filter = or_(ConsistencyCheck.run_id == run_id, ConsistencyCheck.run_id.is_(None))
        query = query.where(run_filter)
        count_query = count_query.where(run_filter)

    result = await db.execute(query)
    checks = list(result.scalars().all())

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    return checks, total
