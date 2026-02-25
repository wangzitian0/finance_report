from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import BankStatement, BankStatementStatus, BankStatementTransaction
from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.services.anomaly import detect_anomalies

TRANSFER_TOLERANCE = Decimal("0.001")
TRANSFER_DATE_TOLERANCE_DAYS = 3


async def detect_duplicates(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID | None = None,
) -> list[ConsistencyCheck]:
    query = (
        select(BankStatementTransaction)
        .join(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.status == BankStatementStatus.APPROVED)
    )
    if statement_id:
        query = query.where(BankStatementTransaction.statement_id == statement_id)

    result = await db.execute(query)
    transactions = list(result.scalars().all())

    groups: dict[str, list[BankStatementTransaction]] = {}
    for txn in transactions:
        key = f"{txn.amount}_{txn.direction}_{txn.description[:50] if txn.description else ''}"
        if key not in groups:
            groups[key] = []
        groups[key].append(txn)

    checks: list[ConsistencyCheck] = []
    for key, group in groups.items():
        if len(group) > 1:
            dates = sorted([t.txn_date for t in group])
            if (dates[-1] - dates[0]).days <= 1:
                check = ConsistencyCheck(
                    user_id=user_id,
                    check_type=CheckType.DUPLICATE,
                    status=CheckStatus.PENDING,
                    related_txn_ids=[str(t.id) for t in group],
                    details={
                        "count": len(group),
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
) -> list[ConsistencyCheck]:
    query = (
        select(BankStatementTransaction)
        .join(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.status == BankStatementStatus.APPROVED)
        .options(selectinload(BankStatementTransaction.statement).selectinload(BankStatement.account))
    )
    if statement_id:
        query = query.where(BankStatementTransaction.statement_id == statement_id)

    result = await db.execute(query)
    transactions = list(result.scalars().all())

    out_txns = [t for t in transactions if t.direction == "OUT"]
    in_txns_by_amount: dict[Decimal, list[BankStatementTransaction]] = {}
    for t in transactions:
        if t.direction == "IN":
            if t.amount not in in_txns_by_amount:
                in_txns_by_amount[t.amount] = []
            in_txns_by_amount[t.amount].append(t)

    checks: list[ConsistencyCheck] = []
    matched_in: set[str] = set()

    for out_txn in out_txns:
        # Since TRANSFER_TOLERANCE is 0.001 and amounts are Numeric(18,2),
        # they must be exactly equal for the delta to be <= 0.001.
        candidates = in_txns_by_amount.get(out_txn.amount, [])
        for in_txn in candidates:
            if str(in_txn.id) in matched_in:
                continue

            date_diff = abs((out_txn.txn_date - in_txn.txn_date).days)
            if date_diff <= TRANSFER_DATE_TOLERANCE_DAYS:
                check = ConsistencyCheck(
                    user_id=user_id,
                    check_type=CheckType.TRANSFER_PAIR,
                    status=CheckStatus.PENDING,
                    related_txn_ids=[str(out_txn.id), str(in_txn.id)],
                    details={
                        "amount": str(out_txn.amount),
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
) -> list[ConsistencyCheck]:
    query = (
        select(BankStatementTransaction)
        .join(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.status == BankStatementStatus.APPROVED)
    )
    if statement_id:
        query = query.where(BankStatementTransaction.statement_id == statement_id)

    result = await db.execute(query)
    transactions = list(result.scalars().all())

    checks: list[ConsistencyCheck] = []
    for txn in transactions:
        anomalies = await detect_anomalies(db, txn, user_id=user_id)
        for anomaly in anomalies:
            check = ConsistencyCheck(
                user_id=user_id,
                check_type=CheckType.ANOMALY,
                status=CheckStatus.PENDING,
                related_txn_ids=[str(txn.id)],
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
) -> list[ConsistencyCheck]:
    checks: list[ConsistencyCheck] = []
    checks.extend(await detect_duplicates(db, user_id, statement_id))
    checks.extend(await detect_transfer_pairs(db, user_id, statement_id))
    checks.extend(await detect_anomalies_batch(db, user_id, statement_id))
    return checks


async def resolve_check(
    db: AsyncSession,
    check_id: UUID,
    action: str,
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
        raise ValueError("Check not found or access denied")

    if action == "approve":
        check.status = CheckStatus.APPROVED
    elif action == "reject":
        check.status = CheckStatus.REJECTED
    elif action == "flag":
        check.status = CheckStatus.FLAGGED
    else:
        raise ValueError(f"Invalid action: {action}")

    check.resolved_at = datetime.now(UTC)
    if note:
        check.resolution_note = note

    await db.flush()
    return check


async def get_pending_checks(
    db: AsyncSession,
    user_id: UUID,
    check_type: CheckType | None = None,
    severity: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ConsistencyCheck]:
    query = (
        select(ConsistencyCheck)
        .where(ConsistencyCheck.user_id == user_id)
        .where(ConsistencyCheck.status == CheckStatus.PENDING)
        .order_by(desc(ConsistencyCheck.created_at))
        .limit(limit)
        .offset(offset)
    )
    if check_type:
        query = query.where(ConsistencyCheck.check_type == check_type)
    if severity:
        query = query.where(ConsistencyCheck.severity == severity)

    result = await db.execute(query)
    return list(result.scalars().all())


async def has_unresolved_checks(
    db: AsyncSession,
    user_id: UUID,
) -> bool:
    result = await db.execute(
        select(ConsistencyCheck.id)
        .where(ConsistencyCheck.user_id == user_id)
        .where(ConsistencyCheck.status == CheckStatus.PENDING)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None
