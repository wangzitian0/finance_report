"""Stage 1 statement review on the DWD conform (EPIC-011 Stage 3).

Review state now lives on ``StatementSummary`` (the DWD conform), and the
transactions it validates are Layer-2 ``AtomicTransaction`` rows resolved via the
linked ODS ``UploadedDocument`` (``StatementSummary.uploaded_document_id`` ->
``AtomicTransaction.source_documents[*].doc_id``).
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement_enums import BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary
from src.services.promotion_gate import STATEMENT_BALANCE_TOLERANCE, InvariantResult, evaluate_promotion

# Single-owned by the promotion gate (#930); kept as a local alias for readability.
BALANCE_TOLERANCE = STATEMENT_BALANCE_TOLERANCE


def pending_stage1_review_filter():
    """Return the shared Stage 1 pending-review predicate for PARSED statements."""
    return or_(
        StatementSummary.stage1_status == Stage1Status.PENDING_REVIEW,
        StatementSummary.stage1_status.is_(None),
    )


async def resolve_statement_transactions(
    db: AsyncSession,
    statement: StatementSummary,
) -> list[AtomicTransaction]:
    """Resolve the Layer-2 atomic transactions for a statement envelope.

    Joins ``StatementSummary.uploaded_document_id`` to ``AtomicTransaction`` rows
    whose ``source_documents`` reference that ODS document. Returns transactions
    ordered by ``txn_date`` then ``created_at`` for stable balance chaining.
    """
    if statement.uploaded_document_id is None:
        return []

    doc_marker = [{"doc_id": str(statement.uploaded_document_id)}]
    result = await db.execute(
        select(AtomicTransaction)
        .where(AtomicTransaction.user_id == statement.user_id)
        .where(AtomicTransaction.source_documents.contains(doc_marker))
        .order_by(AtomicTransaction.txn_date, AtomicTransaction.created_at)
    )
    return list(result.scalars().all())


def _direction_is_in(direction: object) -> bool:
    value = direction.value if hasattr(direction, "value") else direction
    return value == TransactionDirection.IN.value


async def validate_balance_chain(
    db: AsyncSession,
    statement_id: UUID,
) -> dict:
    statement = await db.get(StatementSummary, statement_id)
    if not statement:
        raise ValueError("Statement not found")

    transactions = await resolve_statement_transactions(db, statement)

    opening_balance = await _get_opening_balance(db, statement)
    opening_delta = abs((statement.opening_balance or Decimal("0")) - opening_balance)

    txn_sum = Decimal("0")
    for txn in transactions:
        if _direction_is_in(txn.direction):
            txn_sum += txn.amount
        else:
            txn_sum -= txn.amount

    calculated_closing = opening_balance + txn_sum

    closing_delta = abs((statement.closing_balance or Decimal("0")) - calculated_closing)

    return {
        "opening_balance": str(opening_balance),
        "closing_balance": str(statement.closing_balance),
        "calculated_closing": str(calculated_closing),
        "opening_delta": str(opening_delta),
        "closing_delta": str(closing_delta),
        "opening_match": opening_delta <= BALANCE_TOLERANCE,
        "closing_match": closing_delta <= BALANCE_TOLERANCE,
        "validated_at": datetime.now(UTC).isoformat(),
    }


async def _get_opening_balance(db: AsyncSession, statement: StatementSummary) -> Decimal:
    if statement.manual_opening_balance is not None:
        return statement.manual_opening_balance

    filters = [
        StatementSummary.user_id == statement.user_id,
        StatementSummary.status == BankStatementStatus.APPROVED,
    ]
    if statement.account_id is not None:
        filters.append(StatementSummary.account_id == statement.account_id)
    else:
        filters.append(StatementSummary.account_id.is_(None))

    if statement.period_start:
        filters.append(StatementSummary.period_end < statement.period_start)

    prev_result = await db.execute(
        select(StatementSummary).where(and_(*filters)).order_by(desc(StatementSummary.period_end)).limit(1)
    )
    prev_statement = prev_result.scalar_one_or_none()

    if prev_statement and prev_statement.closing_balance is not None:
        return prev_statement.closing_balance

    return statement.opening_balance or Decimal("0")


async def _get_statement_for_update(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
) -> StatementSummary:
    result = await db.execute(
        select(StatementSummary)
        .where(StatementSummary.id == statement_id)
        .where(StatementSummary.user_id == user_id)
        .with_for_update()
    )
    statement = result.scalar_one_or_none()
    if not statement:
        raise ValueError("Statement not found or access denied")
    return statement


def _raise_if_balance_chain_invalid(validation_result: dict, *, after_edits: bool = False) -> None:
    # Route the Stage-1 approval decision through the promotion gate: the
    # balance-chain checks are the deterministic invariants, with no confidence
    # term (min_confidence=0). The gate disposes; a failed invariant blocks
    # approval. Behavior is identical to the prior inline checks.
    verdict = evaluate_promotion(
        [
            InvariantResult(
                name="opening_balance_chain",
                passed=validation_result["opening_match"],
                delta=Decimal(validation_result["opening_delta"]),
                tolerance=BALANCE_TOLERANCE,
            ),
            InvariantResult(
                name="closing_balance_chain",
                passed=validation_result["closing_match"],
                delta=Decimal(validation_result["closing_delta"]),
                tolerance=BALANCE_TOLERANCE,
            ),
        ],
        confidence_rank=0,
        min_confidence=0,
    )
    if verdict.is_authoritative:
        return

    if verdict.failed_invariant == "opening_balance_chain":
        suffix = " after edits" if after_edits else ""
        raise ValueError(
            f"Opening balance mismatch{suffix}: delta={validation_result['opening_delta']} exceeds tolerance "
            f"{BALANCE_TOLERANCE}"
        )

    if after_edits:
        raise ValueError(f"Balance still invalid after edits: delta={validation_result['closing_delta']}")
    raise ValueError(
        f"Balance mismatch: delta={validation_result['closing_delta']} exceeds tolerance {BALANCE_TOLERANCE}"
    )


def _has_unresolved_statement_conflicts(transactions: list[AtomicTransaction]) -> bool:
    seen: dict[tuple, AtomicTransaction] = {}
    by_abs_amount: dict[tuple, AtomicTransaction] = {}

    for txn in transactions:
        direction = txn.direction.value if hasattr(txn.direction, "value") else txn.direction
        # Include the running balance in the duplicate key so the guard stays consistent with the
        # dedup disambiguator (deduplication.calculate_transaction_hash): two rows with different
        # ``balance_after`` are real distinct transactions the dedup layer deliberately kept apart,
        # not duplicates. Equal/absent balances remain ambiguous and are still flagged for review.
        balance_key = None if txn.balance_after is None else txn.balance_after.normalize()
        duplicate_key = (txn.txn_date, txn.description.casefold(), txn.amount.copy_abs(), direction, balance_key)
        if duplicate_key in seen:
            return True
        seen[duplicate_key] = txn

        transfer_key = (txn.txn_date, txn.amount.copy_abs())
        paired = by_abs_amount.get(transfer_key)
        paired_direction = (
            (paired.direction.value if hasattr(paired.direction, "value") else paired.direction)
            if paired is not None
            else None
        )
        if paired is not None and paired_direction != direction:
            return True
        by_abs_amount[transfer_key] = txn

    return False


def _raise_if_statement_conflicts_unresolved(
    statement: StatementSummary, transactions: list[AtomicTransaction]
) -> None:
    # #962: a reviewer can explicitly resolve the duplicate / transfer-pair
    # candidates (confirming they are distinct or a real transfer). Once resolved,
    # the statement is approvable instead of permanently stuck in ``parsed``.
    if statement.stage1_conflicts_resolved_at is not None:
        return
    if _has_unresolved_statement_conflicts(transactions):
        raise ValueError("Cannot approve statement while unresolved duplicate or transfer-pair candidates remain")


def _raise_if_approved_envelope_incomplete(statement: StatementSummary) -> None:
    if statement.account_id is None:
        raise ValueError("Account mapping required before posting. Confirm the statement account before posting.")
    if not (statement.currency or "").strip():
        raise ValueError("Statement currency required before posting. Confirm the source currency before posting.")
    if statement.period_start is None or statement.period_end is None:
        raise ValueError("Statement period required before posting. Confirm the source date range before posting.")
    if statement.period_start > statement.period_end:
        raise ValueError("Statement period is invalid. Confirm the source date range before posting.")
    if statement.opening_balance is None or statement.closing_balance is None:
        raise ValueError(
            "Statement opening and closing balances required before approval. Confirm the source balances first."
        )


async def approve_statement(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
) -> StatementSummary:
    statement = await _get_statement_for_update(db, statement_id, user_id)
    _raise_if_approved_envelope_incomplete(statement)
    validation_result = await validate_balance_chain(db, statement_id)
    transactions = await resolve_statement_transactions(db, statement)

    _raise_if_balance_chain_invalid(validation_result)
    _raise_if_statement_conflicts_unresolved(statement, transactions)

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
) -> StatementSummary:
    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.stage1_status = Stage1Status.REJECTED
    statement.stage1_reviewed_at = datetime.now(UTC)
    statement.status = BankStatementStatus.REJECTED
    # A reject triggers a reparse: the next transaction set must be re-reviewed,
    # so a prior conflict resolution (#962) must not carry over.
    statement.stage1_conflicts_resolved_at = None
    if reason:
        statement.validation_error = reason

    await db.flush()
    return statement


async def resolve_statement_conflicts(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
) -> StatementSummary:
    """Mark a statement's Stage-1 duplicate/transfer-pair candidates as resolved (#962).

    The reviewer has confirmed the flagged rows are genuinely distinct (or a real
    transfer pair), so the approval guard should stop blocking. Idempotent: the
    timestamp simply records that a resolution decision was made.
    """
    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.stage1_conflicts_resolved_at = datetime.now(UTC)
    await db.flush()
    return statement


async def edit_and_approve(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    edits: list[dict],
) -> StatementSummary:
    """Editing parsed transactions is unsupported.

    Layer-2 ``AtomicTransaction`` rows are immutable / write-once: their identity
    (and dedup hash) is fixed at ingestion, so per-transaction corrections cannot
    be applied in place without corrupting deduplication and lineage. Reviewers
    must reject the statement and re-parse the corrected source instead.

    TODO(EPIC-012): introduce an explicit correction / re-parse flow that supersedes
    the original atomic rows rather than mutating them.
    """
    raise ValueError("Editing parsed transactions is unsupported; reject and re-parse the statement instead.")


async def set_opening_balance(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    opening_balance: Decimal,
) -> StatementSummary:
    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.manual_opening_balance = opening_balance

    await db.flush()
    return statement


async def get_pending_stage1_review(
    db: AsyncSession,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[StatementSummary]:
    result = await db.execute(
        select(StatementSummary)
        .where(StatementSummary.user_id == user_id)
        .where(StatementSummary.status == BankStatementStatus.PARSED)
        .where(pending_stage1_review_filter())
        .order_by(StatementSummary.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
