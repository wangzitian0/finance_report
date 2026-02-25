from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import BankStatement, BankStatementStatus
from src.models.statement import Stage1Status

BALANCE_TOLERANCE = Decimal("0.001")


async def validate_balance_chain(
    db: AsyncSession,
    statement_id: UUID,
) -> dict:
    result = await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id).options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()
    if not statement:
        raise ValueError("Statement not found")

    opening_balance = await _get_opening_balance(db, statement)

    txn_sum = Decimal("0")
    for txn in statement.transactions:
        if txn.direction == "IN":
            txn_sum += txn.amount
        else:
            txn_sum -= txn.amount

    calculated_closing = opening_balance + txn_sum

    closing_delta = abs((statement.closing_balance or Decimal("0")) - calculated_closing)

    return {
        "opening_balance": str(opening_balance),
        "closing_balance": str(statement.closing_balance),
        "calculated_closing": str(calculated_closing),
        "opening_delta": "0.000",
        "closing_delta": str(closing_delta),
        "opening_match": True,
        "closing_match": closing_delta <= BALANCE_TOLERANCE,
        "validated_at": datetime.now(UTC).isoformat(),
    }


async def _get_opening_balance(db: AsyncSession, statement: BankStatement) -> Decimal:
    if statement.manual_opening_balance is not None:
        return statement.manual_opening_balance

    prev_result = await db.execute(
        select(BankStatement)
        .where(
            and_(
                BankStatement.user_id == statement.user_id,
                BankStatement.account_id == statement.account_id,
                BankStatement.period_end < statement.period_start,
                BankStatement.status == BankStatementStatus.APPROVED,
            )
        )
        .order_by(desc(BankStatement.period_end))
        .limit(1)
    )
    prev_statement = prev_result.scalar_one_or_none()

    if prev_statement and prev_statement.closing_balance is not None:
        return prev_statement.closing_balance

    return statement.opening_balance or Decimal("0")


async def _get_statement_for_update(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
) -> BankStatement:
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
        .with_for_update()
    )
    statement = result.scalar_one_or_none()
    if not statement:
        raise ValueError("Statement not found or access denied")
    return statement


async def approve_statement(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
) -> BankStatement:
    validation_result = await validate_balance_chain(db, statement_id)

    if not validation_result["closing_match"]:
        raise ValueError(
            f"Balance mismatch: delta={validation_result['closing_delta']} exceeds tolerance {BALANCE_TOLERANCE}"
        )

    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.stage1_status = Stage1Status.APPROVED
    statement.stage1_reviewed_at = datetime.now(UTC)
    statement.balance_validation_result = validation_result
    statement.status = BankStatementStatus.APPROVED

    await db.flush()
    return statement


async def reject_statement(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    reason: str | None = None,
) -> BankStatement:
    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.stage1_status = Stage1Status.REJECTED
    statement.stage1_reviewed_at = datetime.now(UTC)
    statement.status = BankStatementStatus.REJECTED
    if reason:
        statement.validation_error = reason

    await db.flush()
    return statement


async def edit_and_approve(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    edits: list[dict],
) -> BankStatement:
    statement = await _get_statement_for_update(db, statement_id, user_id)

    for edit in edits:
        txn = next((t for t in statement.transactions if str(t.id) == edit.get("txn_id")), None)
        if txn:
            if "amount" in edit:
                txn.amount = Decimal(str(edit["amount"]))
            if "description" in edit:
                txn.description = edit["description"]
            if "txn_date" in edit:
                txn.txn_date = edit["txn_date"]

    validation_result = await validate_balance_chain(db, statement_id)

    if not validation_result["closing_match"]:
        raise ValueError(f"Balance still invalid after edits: delta={validation_result['closing_delta']}")

    statement.stage1_status = Stage1Status.EDITED
    statement.stage1_reviewed_at = datetime.now(UTC)
    statement.balance_validation_result = validation_result
    statement.status = BankStatementStatus.APPROVED

    await db.flush()
    return statement


async def set_opening_balance(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    opening_balance: Decimal,
) -> BankStatement:
    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.manual_opening_balance = opening_balance

    await db.flush()
    return statement


async def get_pending_stage1_review(
    db: AsyncSession,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[BankStatement]:
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.status == BankStatementStatus.PARSED)
        .where(or_(BankStatement.stage1_status.is_(None), BankStatement.stage1_status == Stage1Status.PENDING_REVIEW))
        .order_by(BankStatement.created_at.desc())
        .limit(limit)
        .offset(offset)
        .options(selectinload(BankStatement.transactions))
    )
    return list(result.scalars().all())
