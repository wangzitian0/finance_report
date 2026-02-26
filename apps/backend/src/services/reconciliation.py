"""Reconciliation matching engine."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy.orm import selectinload\nfrom sqlalchemy.orm import selectinload
from sqlalchemy.orm import selectinload

from src.config import settings
from src.logger import get_logger
from src.models import (
    AccountType,
    AtomicTransaction,
    BankStatement,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    ReconciliationMatch,
    ReconciliationStatus,
    UploadedDocument,
)
from src.services.accounting import ValidationError, validate_journal_balance
from src.services.processing_account import (
    create_transfer_in_entry,
    create_transfer_out_entry,
    detect_transfer_pattern,
    find_transfer_pairs,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReconciliationConfig:
    """Runtime configuration for reconciliation scoring."""

    weight_amount: Decimal
    weight_date: Decimal
    weight_description: Decimal
    weight_business: Decimal
    weight_history: Decimal
    auto_accept: int
    pending_review: int
    amount_percent: Decimal
    amount_absolute: Decimal
    date_days: int


@dataclass
class MatchCandidate:
    """Candidate match result."""

    journal_entry_ids: list[str]
    score: int
    # Score components are 0-100 percentages, not monetary values.
    # Float is acceptable per AGENTS.md which requires Decimal only for money.
    breakdown: dict[str, float]


def entry_total_amount(entry: JournalEntry) -> Decimal:
    """Return total debit amount for matching."""
    return sum(line.amount for line in entry.lines if line.direction == Direction.DEBIT)


def is_entry_balanced(entry: JournalEntry) -> bool:
    """Return True if entry is balanced."""
    try:
        validate_journal_balance(entry.lines)
    except ValidationError:
        return False
    return True


DEFAULT_CONFIG = ReconciliationConfig(
    weight_amount=Decimal("0.40"),
    weight_date=Decimal("0.25"),
    weight_description=Decimal("0.20"),
    weight_business=Decimal("0.10"),
    weight_history=Decimal("0.05"),
    auto_accept=85,
    pending_review=60,
    amount_percent=Decimal("0.005"),
    amount_absolute=Decimal("0.10"),
    date_days=7,
)

MAX_COMBINATION_CANDIDATES = 30

_config_cache: ReconciliationConfig | None = None


def load_reconciliation_config(force_reload: bool = False) -> ReconciliationConfig:
    """Load reconciliation configuration from YAML if available.

    Caches the result to avoid repeated disk I/O.
    """
    global _config_cache
    if _config_cache is not None and not force_reload:
        return _config_cache

    config = DEFAULT_CONFIG
    config_path = Path(__file__).resolve().parents[2] / "config" / "reconciliation.yaml"

    if config_path.exists():
        try:
            import yaml
        except ImportError:
            yaml = None

        if yaml:
            try:
                raw = yaml.safe_load(config_path.read_text()) or {}
                scoring = raw.get("scoring", {})
                weights = scoring.get("weights", {})
                thresholds = scoring.get("thresholds", {})
                tolerances = scoring.get("tolerances", {})

                config = ReconciliationConfig(
                    weight_amount=Decimal(str(weights.get("amount", config.weight_amount))),
                    weight_date=Decimal(str(weights.get("date", config.weight_date))),
                    weight_description=Decimal(str(weights.get("description", config.weight_description))),
                    weight_business=Decimal(str(weights.get("business", config.weight_business))),
                    weight_history=Decimal(str(weights.get("history", config.weight_history))),
                    auto_accept=int(thresholds.get("auto_accept", config.auto_accept)),
                    pending_review=int(thresholds.get("pending_review", config.pending_review)),
                    amount_percent=Decimal(str(tolerances.get("amount_percent", config.amount_percent))),
                    amount_absolute=Decimal(str(tolerances.get("amount_absolute", config.amount_absolute))),
                    date_days=int(tolerances.get("date_days", config.date_days)),
                )
            except Exception as e:
                logger.warning(
                    "Failed to load reconciliation config - using defaults",
                    config_path=str(config_path),
                    error=str(e),
                    error_type=type(e).__name__,
                )

    auto_accept_env = os.getenv("RECONCILIATION_AUTO_ACCEPT_THRESHOLD")
    pending_review_env = os.getenv("RECONCILIATION_REVIEW_THRESHOLD")
    if auto_accept_env:
        config = replace(config, auto_accept=int(auto_accept_env))
    if pending_review_env:
        config = replace(config, pending_review=int(pending_review_env))

    _config_cache = config
    return config


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


def score_business_logic(transaction: BankStatementTransaction, entry: JournalEntry) -> float:
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
    transaction: BankStatementTransaction,
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
        select(BankStatementTransaction)
        .join(BankStatement)
        .join(
            ReconciliationMatch,
            ReconciliationMatch.bank_txn_id == BankStatementTransaction.id,
        )
        .where(BankStatement.user_id == user_id)
        .where(ReconciliationMatch.status.in_([ReconciliationStatus.AUTO_ACCEPTED, ReconciliationStatus.ACCEPTED]))
        .where(BankStatementTransaction.description.ilike(pattern, escape="\\"))
        .order_by(BankStatementTransaction.txn_date.desc())
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


def prune_candidates(
    candidates: list[JournalEntry],
    *,
    txn_date: date,
    target_amount: Decimal,
    limit: int = MAX_COMBINATION_CANDIDATES,
) -> list[JournalEntry]:
    """Reduce candidates before combinational matching to avoid blow-ups.

    Prioritizes:
    1. Exact amount matches (within 1%)
    2. Then by date proximity
    3. Then by absolute amount difference
    """
    if len(candidates) <= limit:
        return candidates

    tolerance = target_amount * Decimal("0.01")  # 1% tolerance for "exact" match

    scored: list[tuple[int, Decimal, int, JournalEntry]] = []
    for entry in candidates:
        amount_diff = abs(entry_total_amount(entry) - target_amount)
        date_diff = abs((txn_date - entry.entry_date).days)
        # Exact match bonus: 0 if within tolerance, 1 otherwise
        exact_match = 0 if amount_diff <= tolerance else 1
        scored.append((exact_match, amount_diff, date_diff, entry))

    # Sort by: exact match first, then amount diff, then date diff
    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    return [entry for _, _, _, entry in scored[:limit]]


async def calculate_match_score(
    db: AsyncSession,
    transaction: BankStatementTransaction,
    entries: list[JournalEntry],
    config: ReconciliationConfig,
    user_id: UUID,
    is_multi: bool = False,
    is_many_to_one: bool = False,
    amount_override: Decimal | None = None,
    history_score_override: float | None = None,
) -> MatchCandidate:
    """Calculate match score for a transaction against entry candidates."""
    entry_amounts = [entry_total_amount(entry) for entry in entries]
    total_amount = sum(entry_amounts, Decimal("0.00"))
    entry_dates = [entry.entry_date for entry in entries]
    entry_memo = " / ".join([entry.memo for entry in entries]).strip()

    txn_amount = amount_override if amount_override is not None else transaction.amount
    amount_score = score_amount(txn_amount, total_amount, config, is_multi=is_multi)
    date_score = max(score_date(transaction.txn_date, d, config) for d in entry_dates)
    description_score = score_description(transaction.description, entry_memo)
    business_score = min(score_business_logic(transaction, entry) for entry in entries) if entries else 0.0

    if history_score_override is not None:
        history_score = history_score_override
    else:
        history_score = await score_pattern(db, transaction, config, user_id=user_id)

    scores = {
        "amount": amount_score,
        "date": date_score,
        "description": description_score,
        "business": business_score,
        "history": history_score,
    }
    if is_many_to_one:
        scores["many_to_one_bonus"] = 10.0
        amount_score = min(100.0, amount_score + 5.0)
        scores["amount"] = amount_score

    total = weighted_total(scores, config)
    return MatchCandidate(
        journal_entry_ids=[str(entry.id) for entry in entries],
        score=total,
        breakdown=scores,
    )


def build_many_to_one_groups(
    transactions: Iterable[BankStatementTransaction],
) -> list[list[BankStatementTransaction]]:
    """Group transactions that look like batch payments."""
    groups: dict[str, list[BankStatementTransaction]] = {}
    keywords = {"batch", "bulk", "settlement", "aggregate"}
    for txn in transactions:
        key = normalize_text(txn.description)
        if not key:
            continue
        if not any(keyword in key for keyword in keywords):
            continue
        group_key = f"{key}:{txn.txn_date.isoformat()}"
        groups.setdefault(group_key, []).append(txn)
    return [group for group in groups.values() if len(group) > 1]


async def find_candidates(
    db: AsyncSession,
    txn_date: date,
    config: ReconciliationConfig,
    user_id: UUID,
) -> list[JournalEntry]:
    """Find journal entry candidates near a transaction date."""
    date_start = txn_date - timedelta(days=config.date_days)
    date_end = txn_date + timedelta(days=config.date_days)

    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.entry_date.between(date_start, date_end))
        .where(JournalEntry.status != JournalEntryStatus.VOID)
        .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
    )
    return result.scalars().all()


async def _validate_layer_consistency(db: AsyncSession, statement_ids: set[UUID]) -> None:
    """Phase 3: Validate consistency between Layer 0 and Layer 2 data.

    Logs warnings if discrepancies are found between legacy BankStatementTransactions
    and new AtomicTransactions. Skipped for statements processed before Phase 2.
    """
    if not statement_ids:
        return

    stmt_query = select(BankStatement).where(BankStatement.id.in_(statement_ids))
    res = await db.execute(stmt_query)
    statements = res.scalars().all()

    for stmt in statements:
        doc_query = select(UploadedDocument).where(
            UploadedDocument.file_hash == stmt.file_hash,
            UploadedDocument.user_id == stmt.user_id,
        )
        res = await db.execute(doc_query)
        doc = res.scalar_one_or_none()

        if not doc:
            continue

        l2_query = select(AtomicTransaction).where(
            AtomicTransaction.user_id == stmt.user_id,
            AtomicTransaction.source_documents.contains([{"doc_id": str(doc.id)}]),
        )
        res = await db.execute(l2_query)
        l2_txns = res.scalars().all()

        l0_query = select(BankStatementTransaction).where(BankStatementTransaction.statement_id == stmt.id)
        res = await db.execute(l0_query)
        l0_txns = res.scalars().all()

        l0_count = len(l0_txns)
        l2_count = len(l2_txns)

        if l0_count != l2_count:
            logger.warning(
                "Layer 0/2 Count Mismatch (EPIC-011 Phase 3)",
                extra={
                    "statement_id": str(stmt.id),
                    "file_hash": stmt.file_hash,
                    "layer0_count": l0_count,
                    "layer2_count": l2_count,
                    "diff": l0_count - l2_count,
                },
            )

        l0_total = sum((t.amount for t in l0_txns), Decimal("0.00"))
        l2_total = sum((t.amount for t in l2_txns), Decimal("0.00"))

        if l0_total != l2_total:
            logger.warning(
                "Layer 0/2 Amount Mismatch (EPIC-011 Phase 3)",
                extra={
                    "statement_id": str(stmt.id),
                    "layer0_total": str(l0_total),
                    "layer2_total": str(l2_total),
                    "diff": str(abs(l0_total - l2_total)),
                },
            )

        if l0_count == l2_count and l0_total == l2_total:
            logger.info(
                "Layer 0/2 Consistency Verified (EPIC-011 Phase 3)",
                extra={
                    "statement_id": str(stmt.id),
                    "count": l0_count,
                    "total": str(l0_total),
                },
            )


async def _get_pending_layer2_transactions(
    db: AsyncSession, user_id: UUID, limit: int | None = None
) -> list[AtomicTransaction]:
    """Fetch pending transactions from Layer 2 (AtomicTransaction).

    Pending means NOT present in reconciliation_matches table.
    """
    # Find IDs that are already matched
    subquery = select(ReconciliationMatch.atomic_txn_id).where(ReconciliationMatch.atomic_txn_id.isnot(None))

    query = (
        select(AtomicTransaction)
        .where(AtomicTransaction.user_id == user_id)
        .where(AtomicTransaction.id.notin_(subquery))
        .order_by(AtomicTransaction.txn_date)
    )

    if limit:
        query = query.limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


async def _get_existing_active_match(
    db: AsyncSession,
    txn_id: UUID,
    is_layer2: bool,
) -> ReconciliationMatch | None:
    """Get existing active (non-superseded) match for a transaction."""
    if is_layer2:
        query = select(ReconciliationMatch).where(
            ReconciliationMatch.atomic_txn_id == txn_id,
            ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
            ReconciliationMatch.superseded_by_id.is_(None),
        )
    else:
        query = select(ReconciliationMatch).where(
            ReconciliationMatch.bank_txn_id == txn_id,
            ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
            ReconciliationMatch.superseded_by_id.is_(None),
        )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def execute_matching(
    db: AsyncSession,
    *,
    user_id: UUID,
    statement_id: UUID | str | None = None,
    limit: int | None = None,
) -> list[ReconciliationMatch]:
    """Execute reconciliation matching for pending transactions."""
    config = load_reconciliation_config()

    if settings.enable_4_layer_read:
        transactions = await _get_pending_layer2_transactions(db, user_id, limit)
    else:
        query = (
            select(BankStatementTransaction)
            .join(BankStatement)
            .where(BankStatementTransaction.status == BankStatementTransactionStatus.PENDING)
            .where(BankStatement.user_id == user_id)
        )

        if statement_id:
            statement_uuid = UUID(statement_id) if isinstance(statement_id, str) else statement_id
            query = query.where(BankStatementTransaction.statement_id == statement_uuid)
        if limit:
            query = query.limit(limit)

        result = await db.execute(query)
        transactions = result.scalars().all()

    if not transactions:
        return []

    # Phase 3: Dual Read Validation (Only runs if NOT in Phase 4 Read mode)
    # If we are in Phase 4, we ARE reading Layer 2.
    # Dual read validation against Layer 0 is tricky because we don't have statement_ids easily.
    # Let's disable Phase 3 validation if Phase 4 read is enabled, as we trust Layer 2.
    if not settings.enable_4_layer_read:
        stmt_ids = {txn.statement_id for txn in transactions if txn.statement_id}
        await _validate_layer_consistency(db, stmt_ids)

    # Optimization: Pre-fetch all candidates for the entire period to avoid N+1 find_candidates
    min_date = min(txn.txn_date for txn in transactions) - timedelta(days=config.date_days)
    max_date = max(txn.txn_date for txn in transactions) + timedelta(days=config.date_days)

    all_candidates_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.entry_date.between(min_date, max_date))
        .where(JournalEntry.status != JournalEntryStatus.VOID)
        .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
    )
    all_candidates = all_candidates_result.scalars().all()

    def get_candidates_for_date(txn_date: date) -> list[JournalEntry]:
        d_start = txn_date - timedelta(days=config.date_days)
        d_end = txn_date + timedelta(days=config.date_days)
        return [c for c in all_candidates if d_start <= c.entry_date <= d_end]

    matches: list[ReconciliationMatch] = []
    matched_txn_ids: set[UUID] = set()

    # Optimization: Cache pattern scores to avoid repeated DB hits for similar merchants
    pattern_score_cache: dict[str, float] = {}

    async def get_cached_pattern_score(txn: BankStatementTransaction) -> float:
        tokens = extract_merchant_tokens(txn.description)
        if not tokens:
            return 0.0
        token = tokens[0]
        if token in pattern_score_cache:
            return pattern_score_cache[token]
        score = await score_pattern(db, txn, config, user_id=user_id)
        pattern_score_cache[token] = score
        return score

    # Phase 1: Transfer Detection (BEFORE normal matching)
    # Detect transfers and create Processing account entries per processing_account.md
    for txn in transactions:
        if txn.id in matched_txn_ids:
            continue

        # Detect transfer pattern (keywords-based detection)
        if detect_transfer_pattern(txn):
            try:
                # Fetch statement to get account_id
                stmt_result = await db.execute(select(BankStatement).where(BankStatement.id == txn.statement_id))
                stmt = stmt_result.scalar_one()

                # Skip transfer detection if statement has no linked account
                if stmt.account_id is None:
                    logger.warning(
                        "Transfer detected but statement has no linked account - skipping Processing entry",
                        txn_id=str(txn.id),
                        statement_id=str(txn.statement_id),
                    )
                    continue
                # Create Processing account entry based on direction
                if txn.direction == "OUT":
                    transfer_entry = await create_transfer_out_entry(
                        db=db,
                        user_id=user_id,
                        source_account_id=stmt.account_id,
                        amount=txn.amount,
                        txn_date=txn.txn_date,
                        description=txn.description,
                    )
                    matched_txn_ids.add(txn.id)

                    # Create reconciliation match for transfer OUT
                    match = ReconciliationMatch(
                        bank_txn_id=txn.id if not settings.enable_4_layer_read else None,
                        atomic_txn_id=txn.id if settings.enable_4_layer_read else None,
                        journal_entry_ids=[str(transfer_entry.id)],
                        match_score=100,  # Transfer detection is exact match
                        score_breakdown={"transfer_out": 100.0},
                        status=ReconciliationStatus.AUTO_ACCEPTED,
                    )
                    db.add(match)
                    matches.append(match)

                    if not settings.enable_4_layer_read:
                        txn.status = BankStatementTransactionStatus.MATCHED
                    if transfer_entry.status != JournalEntryStatus.VOID:
                        transfer_entry.status = JournalEntryStatus.RECONCILED

                    logger.info(
                        "Transfer OUT detected and Processing entry created",
                        txn_id=str(txn.id),
                        entry_id=str(transfer_entry.id),
                        amount=str(txn.amount),
                    )
                elif txn.direction == "IN":
                    transfer_entry = await create_transfer_in_entry(
                        db=db,
                        user_id=user_id,
                        dest_account_id=stmt.account_id,
                        amount=txn.amount,
                        txn_date=txn.txn_date,
                        description=txn.description,
                    )
                    matched_txn_ids.add(txn.id)

                    # Create reconciliation match for transfer IN
                    match = ReconciliationMatch(
                        bank_txn_id=txn.id if not settings.enable_4_layer_read else None,
                        atomic_txn_id=txn.id if settings.enable_4_layer_read else None,
                        journal_entry_ids=[str(transfer_entry.id)],
                        match_score=100,  # Transfer detection is exact match
                        score_breakdown={"transfer_in": 100.0},
                        status=ReconciliationStatus.AUTO_ACCEPTED,
                    )
                    db.add(match)
                    matches.append(match)

                    if not settings.enable_4_layer_read:
                        txn.status = BankStatementTransactionStatus.MATCHED
                    if transfer_entry.status != JournalEntryStatus.VOID:
                        transfer_entry.status = JournalEntryStatus.RECONCILED

                    logger.info(
                        "Transfer IN detected and Processing entry created",
                        txn_id=str(txn.id),
                        entry_id=str(transfer_entry.id),
                        amount=str(txn.amount),
                    )
            except Exception as e:
                logger.error(
                    "Failed to create Processing account entry for transfer",
                    txn_id=str(txn.id),
                    direction=txn.direction,
                    error=str(e),
                )
                # Continue to normal matching if transfer entry creation fails

    # Many-to-one matching
    # Skip transactions already matched in Phase 1 (transfer detection)
    groups = build_many_to_one_groups(transactions)
    for group in groups:
        # Skip groups where all transactions are already matched (e.g., transfers)
        if all(txn.id in matched_txn_ids for txn in group):
            continue
        group_total = sum((txn.amount for txn in group), Decimal("0.00"))
        group_date = max(txn.txn_date for txn in group)
        candidates = get_candidates_for_date(group_date)
        if not candidates:
            continue
        candidates = prune_candidates(
            candidates,
            txn_date=group_date,
            target_amount=group_total,
        )

        best_candidate: MatchCandidate | None = None
        best_entry: JournalEntry | None = None
        # Optimization: pre-calculate pattern score once for the group
        history_score = await get_cached_pattern_score(group[0])

        for entry in candidates:
            if not is_entry_balanced(entry):
                continue

            candidate = await calculate_match_score(
                db,
                group[0],
                [entry],
                config,
                user_id=user_id,
                is_multi=True,
                is_many_to_one=True,
                amount_override=group_total,
                history_score_override=history_score,
            )
            candidate.breakdown["group_total"] = float(group_total)
            if candidate.score >= config.pending_review and (
                best_candidate is None or candidate.score > best_candidate.score
            ):
                best_candidate = candidate
                best_entry = entry

        if best_candidate and best_entry:
            status = (
                ReconciliationStatus.AUTO_ACCEPTED
                if best_candidate.score >= config.auto_accept
                else ReconciliationStatus.PENDING_REVIEW
            )
            for txn in group:
                if txn.id in matched_txn_ids:
                    continue
                existing_match = await _get_existing_active_match(db, txn.id, is_layer2=settings.enable_4_layer_read)
                if existing_match:
                    existing_je_ids = set(existing_match.journal_entry_ids or [])
                    new_je_ids = set(best_candidate.journal_entry_ids or [])
                    if existing_je_ids == new_je_ids:
                        matched_txn_ids.add(txn.id)
                        continue
                    existing_match.status = ReconciliationStatus.SUPERSEDED

                match_kwargs = {
                    "journal_entry_ids": best_candidate.journal_entry_ids,
                    "match_score": best_candidate.score,
                    "score_breakdown": best_candidate.breakdown,
                    "status": status,
                }
                if settings.enable_4_layer_read:
                    match_kwargs["atomic_txn_id"] = txn.id
                else:
                    match_kwargs["bank_txn_id"] = txn.id

                match = ReconciliationMatch(**match_kwargs)
                db.add(match)

                if existing_match:
                    await db.flush()
                    existing_match.superseded_by_id = match.id

                matches.append(match)
                matched_txn_ids.add(txn.id)
                if status == ReconciliationStatus.AUTO_ACCEPTED:
                    if not settings.enable_4_layer_read:
                        txn.status = BankStatementTransactionStatus.MATCHED
                    if best_entry.status != JournalEntryStatus.VOID:
                        best_entry.status = JournalEntryStatus.RECONCILED
                else:
                    if not settings.enable_4_layer_read:
                        txn.status = BankStatementTransactionStatus.PENDING

    # Phase 2: Normal Matching (existing logic)
    # Skip transactions already matched in Phase 1 (transfer detection)
    for txn in transactions:
        if txn.id in matched_txn_ids:
            continue
        candidates = get_candidates_for_date(txn.txn_date)
        if not candidates:
            if not settings.enable_4_layer_read:
                txn.status = BankStatementTransactionStatus.UNMATCHED
            continue
        candidates = prune_candidates(
            candidates,
            txn_date=txn.txn_date,
            target_amount=txn.amount,
        )

        best_match: MatchCandidate | None = None
        # Optimization: use cached history score
        history_score = await get_cached_pattern_score(txn)

        for entry in candidates:
            if not is_entry_balanced(entry):
                continue

            candidate = await calculate_match_score(
                db, txn, [entry], config, user_id=user_id, history_score_override=history_score
            )
            if best_match is None or candidate.score > best_match.score:
                best_match = candidate

        for entry_a, entry_b in combinations(candidates, 2):
            if not (is_entry_balanced(entry_a) and is_entry_balanced(entry_b)):
                continue
            combined = entry_total_amount(entry_a) + entry_total_amount(entry_b)
            tolerance = max(txn.amount * config.amount_percent, config.amount_absolute)
            if abs(combined - txn.amount) > tolerance * 2:
                continue
            candidate = await calculate_match_score(
                db,
                txn,
                [entry_a, entry_b],
                config,
                user_id=user_id,
                is_multi=True,
                history_score_override=history_score,
            )
            candidate.breakdown["multi_entry"] = 1
            if best_match is None or candidate.score > best_match.score:
                best_match = candidate

        for entry_a, entry_b, entry_c in combinations(candidates, 3):
            if not (is_entry_balanced(entry_a) and is_entry_balanced(entry_b) and is_entry_balanced(entry_c)):
                continue
            combined = entry_total_amount(entry_a) + entry_total_amount(entry_b) + entry_total_amount(entry_c)
            tolerance = max(txn.amount * config.amount_percent, config.amount_absolute)
            if abs(combined - txn.amount) > tolerance * 2:
                continue
            candidate = await calculate_match_score(
                db,
                txn,
                [entry_a, entry_b, entry_c],
                config,
                user_id=user_id,
                is_multi=True,
                history_score_override=history_score,
            )
            candidate.breakdown["multi_entry"] = 2
            if best_match is None or candidate.score > best_match.score:
                best_match = candidate

        if not best_match or best_match.score < config.pending_review:
            if not settings.enable_4_layer_read:
                txn.status = BankStatementTransactionStatus.UNMATCHED
            continue

        existing_match = await _get_existing_active_match(db, txn.id, is_layer2=settings.enable_4_layer_read)
        if existing_match:
            existing_je_ids = set(existing_match.journal_entry_ids or [])
            new_je_ids = set(best_match.journal_entry_ids or [])
            if existing_je_ids == new_je_ids:
                continue
            existing_match.status = ReconciliationStatus.SUPERSEDED

        status = (
            ReconciliationStatus.AUTO_ACCEPTED
            if best_match.score >= config.auto_accept
            else ReconciliationStatus.PENDING_REVIEW
        )
        match_kwargs = {
            "journal_entry_ids": best_match.journal_entry_ids,
            "match_score": best_match.score,
            "score_breakdown": best_match.breakdown,
            "status": status,
        }
        if settings.enable_4_layer_read:
            match_kwargs["atomic_txn_id"] = txn.id
        else:
            match_kwargs["bank_txn_id"] = txn.id

        match = ReconciliationMatch(**match_kwargs)
        db.add(match)

        if existing_match:
            await db.flush()
            existing_match.superseded_by_id = match.id

        matches.append(match)

        if status == ReconciliationStatus.AUTO_ACCEPTED:
            if not settings.enable_4_layer_read:
                txn.status = BankStatementTransactionStatus.MATCHED
            if best_match.journal_entry_ids:
                entry_ids = [UUID(entry_id) for entry_id in best_match.journal_entry_ids]
                result = await db.execute(
                    select(JournalEntry).where(JournalEntry.id.in_(entry_ids)).where(JournalEntry.user_id == user_id)
                )
                for entry in result.scalars():
                    if entry.status != JournalEntryStatus.VOID:
                        entry.status = JournalEntryStatus.RECONCILED
        else:
            if not settings.enable_4_layer_read:
                txn.status = BankStatementTransactionStatus.PENDING

    # Phase 3: Auto-Pair Transfers (AFTER all matching complete)
    # Find and pair transfers automatically per processing_account.md
    try:
        transfer_pairs = await find_transfer_pairs(db, user_id, threshold=85)
        if transfer_pairs:
            logger.info(
                "Auto-pairing complete",
                user_id=str(user_id),
                pairs_found=len(transfer_pairs),
            )
    except Exception as e:
        logger.error(
            "Failed to auto-pair transfers",
            user_id=str(user_id),
            error=str(e),
        )
        # Non-fatal error - continue with existing matches

    try:
        await db.flush()
    except Exception as e:
        logger.error(
            "Reconciliation flush failed",
            user_id=str(user_id),
            statement_id=str(statement_id) if statement_id else None,
            matches_attempted=len(matches),
            error=str(e),
            error_type=type(e).__name__,
        )
        raise

    return matches


def auto_accept(match_score: int, config: ReconciliationConfig) -> bool:
    """Return True if match score meets auto-accept threshold."""
    return match_score >= config.auto_accept
