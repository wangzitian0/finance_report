"""Reconciliation scoring functions (split from reconciliation.py)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import AccountType, JournalEntry
from src.reconciliation.base.config import ReconciliationConfig
from src.reconciliation.base.scoring_engine import (
    ReconciliationConfidenceTier,
    derive_reconciliation_score_tier,
    extract_merchant_tokens,
    is_cross_period,
    normalize_text,
    score_amount,
    score_date,
    score_description,
    weighted_total,
)
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus

__all__ = [
    "ReconciliationConfidenceTier",
    "derive_reconciliation_score_tier",
    "extract_merchant_tokens",
    "is_cross_period",
    "normalize_text",
    "score_amount",
    "score_date",
    "score_description",
    "score_business_logic",
    "score_pattern",
    "weighted_total",
]


def score_business_logic(transaction: AtomicTransaction, entry: JournalEntry) -> float:
    """Score business logic fit based on account types."""
    account_types = {line.account.type for line in entry.lines if line.account}
    has_asset = AccountType.ASSET in account_types
    has_income = AccountType.INCOME in account_types
    has_expense = AccountType.EXPENSE in account_types
    has_liability = AccountType.LIABILITY in account_types
    has_equity = AccountType.EQUITY in account_types

    if transaction.direction == "IN":
        if has_asset and has_income:
            return 100.0
        if has_asset and has_liability:
            return 85.0
        if has_asset and has_equity:
            return 75.0
        if has_asset and account_types == {AccountType.ASSET}:
            return 70.0
        return 40.0

    if transaction.direction == "OUT":
        if has_asset and has_expense:
            return 100.0
        if has_asset and has_liability:
            return 90.0
        if has_asset and account_types == {AccountType.ASSET}:
            return 70.0
        return 40.0

    return 50.0


async def score_pattern(
    db: AsyncSession,
    transaction: AtomicTransaction,
    config: ReconciliationConfig,
    user_id: UUID,
) -> float:
    """Score based on historical matching patterns.

    Uses improved merchant extraction that considers multiple significant words.
    """
    merchant_tokens = extract_merchant_tokens(transaction.description)
    if not merchant_tokens:
        return 0.0

    # Use first meaningful token for pattern matching
    token = merchant_tokens[0]
    safe_token = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{safe_token}%"

    result = await db.execute(
        select(AtomicTransaction)
        .join(
            ReconciliationMatch,
            ReconciliationMatch.atomic_txn_id == AtomicTransaction.id,
        )
        .where(AtomicTransaction.user_id == user_id)
        .where(ReconciliationMatch.status.in_([ReconciliationStatus.AUTO_ACCEPTED, ReconciliationStatus.ACCEPTED]))
        .where(AtomicTransaction.description.ilike(pattern, escape="\\"))
        .order_by(AtomicTransaction.txn_date.desc())
        .limit(10)
    )
    history = result.scalars().all()
    if not history:
        return 0.0

    tolerance = max(transaction.amount * config.amount_percent, config.amount_absolute)
    for past in history:
        if abs(past.amount - transaction.amount) <= tolerance:
            return 80.0
    return 40.0
