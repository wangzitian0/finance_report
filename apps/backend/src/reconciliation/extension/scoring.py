"""Reconciliation scoring functions (split from reconciliation.py)."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
import os
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import AccountType
from src.models.journal import JournalEntry
from src.models.layer2 import AtomicTransaction
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.observability import get_logger
from src.reconciliation.base.config import ReconciliationConfig

logger = get_logger(__name__)


def normalize_text(value: str) -> str:
    """Normalize text for similarity comparison."""
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def score_description(a: str | None, b: str | None) -> float:
    """Score description similarity (0-100)."""
    if not a or not b:
        return 0.0
    norm_a = normalize_text(a)
    norm_b = normalize_text(b)
    if not norm_a or not norm_b:
        return 0.0
    ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    token_score = len(tokens_a & tokens_b) / len(tokens_a | tokens_b) if tokens_a | tokens_b else 0
    return round(100 * (0.6 * ratio + 0.4 * token_score), 2)


def score_amount(
    txn_amount: Decimal,
    entry_amount: Decimal,
    config: ReconciliationConfig,
    is_multi: bool = False,
) -> float:
    """Score amount match (0-100)."""
    diff = abs(txn_amount - entry_amount)
    if diff <= Decimal("0.01"):
        return 100.0

    tolerance = max(txn_amount * config.amount_percent, config.amount_absolute)
    if diff <= tolerance:
        return 90.0
    if diff <= Decimal("5.00"):
        return 70.0
    if is_multi and diff <= tolerance * 2:
        return 70.0
    if txn_amount == Decimal("0"):
        return 0.0

    ratio = max(Decimal("0"), Decimal("100") - (diff / txn_amount) * Decimal("100"))
    return float(round(ratio, 2))


def is_cross_period(txn_date: date, entry_date: date, max_days: int) -> bool:
    """Detect cross-period matching scenarios."""
    if txn_date.month == entry_date.month:
        return False
    return abs((txn_date - entry_date).days) <= max_days


def score_date(txn_date: date, entry_date: date, config: ReconciliationConfig) -> float:
    """Score date proximity (0-100)."""
    # Scoring tiers:
    # - Same day: 100
    # - Within 3 days: 90
    # - Cross-month but within config.date_days: 75 (bonus for cross-period matching)
    # - Same month within config.date_days: 70
    # - Beyond config.date_days: decreasing score
    #
    diff_days = abs((txn_date - entry_date).days)
    if diff_days == 0:
        return 100.0
    if diff_days <= 3:
        return 90.0

    # Check if within acceptable date window
    if diff_days <= config.date_days:
        # Cross-period matching gets a slight bonus (e.g., Friday txn -> Monday entry)
        if is_cross_period(txn_date, entry_date, max_days=config.date_days):
            return 75.0
        return 70.0

    # Beyond acceptable window - rapidly decreasing score
    return float(max(0, 100 - diff_days * 10))


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


def extract_merchant_tokens(description: str) -> list[str]:
    """Extract meaningful merchant tokens from transaction description.

    Improved extraction that takes up to 3 significant words, skipping
    common prefixes like transaction codes, dates, and generic terms.
    """
    skip_patterns = {
        "ref",
        "txn",
        "trn",
        "pos",
        "atm",
        "eft",
        "ibk",
        "ibt",
        "payment",
        "transfer",
        "debit",
        "credit",
        "card",
        "visa",
        "mastercard",
    }
    words = normalize_text(description).split()
    tokens = []
    for word in words:
        # Skip very short words, numbers, and common prefixes
        if len(word) < 3:
            continue
        if word.isdigit():
            continue
        if word.lower() in skip_patterns:
            continue
        tokens.append(word)
        if len(tokens) >= 3:
            break
    return tokens


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


def weighted_total(scores: dict[str, float], config: ReconciliationConfig) -> int:
    """Compute weighted total score."""
    total = (
        Decimal(str(scores["amount"])) * config.weight_amount
        + Decimal(str(scores["date"])) * config.weight_date
        + Decimal(str(scores["description"])) * config.weight_description
        + Decimal(str(scores["business"])) * config.weight_business
        + Decimal(str(scores["history"])) * config.weight_history
    )
    return int(round(total, 0))


async def ai_semantic_score(
    txn_description: str,
    entry_memo: str,
    date_diff_days: int,
    amount_match_pct: float,
) -> int:
    """EPIC-018 Phase 3: Compute AI semantic similarity score.

    Calls the configured AI provider to assess semantic similarity between a bank transaction
    description and a journal entry memo. Returns 0-100 score.

    Falls back gracefully to 50 (neutral) on any error.
    """
    import json

    from src.prompts.reconciliation import build_reconciliation_prompt
    from src.services.ai_streaming import (
        AIStreamError,
        accumulate_stream,
        stream_ai_json,
    )

    prompt = build_reconciliation_prompt(
        txn_description=txn_description,
        entry_memo=entry_memo,
        date_diff_days=date_diff_days,
        amount_match_pct=amount_match_pct,
    )

    messages = [{"role": "user", "content": prompt}]

    try:
        stream = stream_ai_json(
            messages=messages,
            model=os.getenv("PRIMARY_MODEL", "gemini-2.0-flash"),
            timeout=30.0,
        )
        content = await accumulate_stream(stream)

        if not content or not content.strip():
            logger.warning("AI semantic score returned empty response")
            return 50

        parsed = json.loads(content)
        score = int(parsed.get("similarity_score", 50))

        logger.debug(
            "AI semantic score computed",
            score=score,
            model=os.getenv("PRIMARY_MODEL", "gemini-2.0-flash"),
        )

        return max(0, min(100, score))

    except (AIStreamError, json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
        logger.warning(
            "AI semantic score failed, using fallback",
            error=str(e),
            error_type=type(e).__name__,
        )
        return 50
