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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    AccountType,
    BankStatement,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.services.accounting import ValidationError, validate_journal_balance


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


def load_reconciliation_config() -> ReconciliationConfig:
    """Load reconciliation configuration from YAML if available."""
    config = DEFAULT_CONFIG
    config_path = Path(__file__).resolve().parents[2] / "config" / "reconciliation.yaml"

    if config_path.exists():
        try:
            import yaml
        except ImportError:
            yaml = None

        if yaml:
            raw = yaml.safe_load(config_path.read_text()) or {}
            scoring = raw.get("scoring", {})
            weights = scoring.get("weights", {})
            thresholds = scoring.get("thresholds", {})
            tolerances = scoring.get("tolerances", {})

            config = ReconciliationConfig(
                weight_amount=Decimal(str(weights.get("amount", config.weight_amount))),
                weight_date=Decimal(str(weights.get("date", config.weight_date))),
                weight_description=Decimal(
                    str(weights.get("description", config.weight_description))
                ),
                weight_business=Decimal(str(weights.get("business", config.weight_business))),
                weight_history=Decimal(str(weights.get("history", config.weight_history))),
                auto_accept=int(thresholds.get("auto_accept", config.auto_accept)),
                pending_review=int(thresholds.get("pending_review", config.pending_review)),
                amount_percent=Decimal(
                    str(tolerances.get("amount_percent", config.amount_percent))
                ),
                amount_absolute=Decimal(
                    str(tolerances.get("amount_absolute", config.amount_absolute))
                ),
                date_days=int(tolerances.get("date_days", config.date_days)),
            )

    auto_accept_env = os.getenv("RECONCILIATION_AUTO_ACCEPT_THRESHOLD")
    pending_review_env = os.getenv("RECONCILIATION_REVIEW_THRESHOLD")
    if auto_accept_env:
        config = replace(config, auto_accept=int(auto_accept_env))
    if pending_review_env:
        config = replace(config, pending_review=int(pending_review_env))

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
    diff_days = abs((txn_date - entry_date).days)
    if diff_days == 0:
        return 100.0
    if diff_days <= 3:
        return 90.0

    if is_cross_period(txn_date, entry_date, max_days=config.date_days):
        return 70.0

    if diff_days <= config.date_days:
        return 70.0
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


async def score_pattern(
    db: AsyncSession,
    transaction: BankStatementTransaction,
    config: ReconciliationConfig,
    user_id: UUID,
) -> float:
    """Score based on historical matching patterns."""
    merchant_key = normalize_text(transaction.description).split()[:1]
    if not merchant_key:
        return 0.0
    token = merchant_key[0]
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
        .where(
            ReconciliationMatch.status.in_(
                [ReconciliationStatus.AUTO_ACCEPTED, ReconciliationStatus.ACCEPTED]
            )
        )
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
    """Reduce candidates before combinational matching to avoid blow-ups."""
    if len(candidates) <= limit:
        return candidates

    scored: list[tuple[int, Decimal, JournalEntry]] = []
    for entry in candidates:
        amount_diff = abs(entry_total_amount(entry) - target_amount)
        date_diff = abs((txn_date - entry.entry_date).days)
        scored.append((date_diff, amount_diff, entry))

    scored.sort(key=lambda item: (item[0], item[1]))
    return [entry for _, _, entry in scored[:limit]]


async def calculate_match_score(
    db: AsyncSession,
    transaction: BankStatementTransaction,
    entries: list[JournalEntry],
    config: ReconciliationConfig,
    user_id: UUID,
    is_multi: bool = False,
    is_many_to_one: bool = False,
    amount_override: Decimal | None = None,
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
    business_score = (
        min(score_business_logic(transaction, entry) for entry in entries) if entries else 0.0
    )
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


async def execute_matching(
    db: AsyncSession,
    *,
    user_id: UUID,
    statement_id: UUID | str | None = None,
    limit: int | None = None,
) -> list[ReconciliationMatch]:
    """Execute reconciliation matching for pending transactions."""
    config = load_reconciliation_config()

    query = select(BankStatementTransaction).join(BankStatement).where(
        BankStatementTransaction.status == BankStatementTransactionStatus.PENDING
    ).where(BankStatement.user_id == user_id)

    if statement_id:
        statement_uuid = UUID(statement_id) if isinstance(statement_id, str) else statement_id
        query = query.where(BankStatementTransaction.statement_id == statement_uuid)
    if limit:
        query = query.limit(limit)

    result = await db.execute(query)
    transactions = result.scalars().all()
    matches: list[ReconciliationMatch] = []
    matched_txn_ids: set[UUID] = set()

    groups = build_many_to_one_groups(transactions)
    for group in groups:
        group_total = sum((txn.amount for txn in group), Decimal("0.00"))
        group_date = max(txn.txn_date for txn in group)
        candidates = await find_candidates(db, group_date, config, user_id=user_id)
        if not candidates:
            continue
        candidates = prune_candidates(
            candidates,
            txn_date=group_date,
            target_amount=group_total,
        )

        best_candidate: MatchCandidate | None = None
        best_entry: JournalEntry | None = None
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
                match = ReconciliationMatch(
                    bank_txn_id=txn.id,
                    journal_entry_ids=best_candidate.journal_entry_ids,
                    match_score=best_candidate.score,
                    score_breakdown=best_candidate.breakdown,
                    status=status,
                )
                db.add(match)
                matches.append(match)
                matched_txn_ids.add(txn.id)
                if status == ReconciliationStatus.AUTO_ACCEPTED:
                    txn.status = BankStatementTransactionStatus.MATCHED
                    if best_entry.status != JournalEntryStatus.VOID:
                        best_entry.status = JournalEntryStatus.RECONCILED
                else:
                    txn.status = BankStatementTransactionStatus.PENDING

    for txn in transactions:
        if txn.id in matched_txn_ids:
            continue
        candidates = await find_candidates(db, txn.txn_date, config, user_id=user_id)
        if not candidates:
            txn.status = BankStatementTransactionStatus.UNMATCHED
            continue
        candidates = prune_candidates(
            candidates,
            txn_date=txn.txn_date,
            target_amount=txn.amount,
        )

        best_match: MatchCandidate | None = None
        for entry in candidates:
            if not is_entry_balanced(entry):
                continue
            candidate = await calculate_match_score(db, txn, [entry], config, user_id=user_id)
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
            )
            candidate.breakdown["multi_entry"] = 1
            if best_match is None or candidate.score > best_match.score:
                best_match = candidate

        for entry_a, entry_b, entry_c in combinations(candidates, 3):
            if not (
                is_entry_balanced(entry_a)
                and is_entry_balanced(entry_b)
                and is_entry_balanced(entry_c)
            ):
                continue
            combined = (
                entry_total_amount(entry_a)
                + entry_total_amount(entry_b)
                + entry_total_amount(entry_c)
            )
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
            )
            candidate.breakdown["multi_entry"] = 2
            if best_match is None or candidate.score > best_match.score:
                best_match = candidate

        if not best_match or best_match.score < config.pending_review:
            txn.status = BankStatementTransactionStatus.UNMATCHED
            continue

        status = (
            ReconciliationStatus.AUTO_ACCEPTED
            if best_match.score >= config.auto_accept
            else ReconciliationStatus.PENDING_REVIEW
        )
        match = ReconciliationMatch(
            bank_txn_id=txn.id,
            journal_entry_ids=best_match.journal_entry_ids,
            match_score=best_match.score,
            score_breakdown=best_match.breakdown,
            status=status,
        )
        db.add(match)
        matches.append(match)

        if status == ReconciliationStatus.AUTO_ACCEPTED:
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
            txn.status = BankStatementTransactionStatus.PENDING

    await db.commit()
    return matches


def auto_accept(match_score: int, config: ReconciliationConfig) -> bool:
    """Return True if match score meets auto-accept threshold."""
    return match_score >= config.auto_accept
