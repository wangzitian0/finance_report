"""Processing account service for transfer detection and pairing.

This module implements the Processing virtual account logic from docs/ssot/processing_account.md.
The Processing account (code "1199") is a system-managed Asset account that tracks in-transit
transfers between user accounts.

Key Concepts:
- Transfer OUT: DEBIT Processing, CREDIT source account
- Transfer IN: DEBIT destination, CREDIT Processing
- Paired transfers result in Processing balance = 0
- Unpaired transfers remain visible in Processing balance for review
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    BankStatementTransaction,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.services.account_service import get_or_create_processing_account

# Transfer detection keywords from SSOT SOP-001
TRANSFER_KEYWORDS = [
    "transfer",
    "payment to",
    "fund transfer",
    "withdrawal",
    "paynow",
    "fast",
    "giro",
]

# Confidence thresholds from reconciliation.md
AUTO_PAIR_THRESHOLD = 85
PENDING_REVIEW_THRESHOLD = 60

# Scoring weights from reconciliation.md
AMOUNT_WEIGHT = Decimal("0.40")
DESCRIPTION_WEIGHT = Decimal("0.30")
DATE_WEIGHT = Decimal("0.20")
HISTORY_WEIGHT = Decimal("0.10")

# Date tolerance for transfer pairing (from processing_account.md)
MAX_DATE_DIFF_DAYS = 7


@dataclass
class TransferPair:
    """Represents a matched pair of transfer transactions."""

    out_entry: JournalEntry
    in_entry: JournalEntry
    confidence: int
    score_breakdown: dict[str, float]


def detect_transfer_pattern(txn: BankStatementTransaction) -> bool:
    """Detect if transaction matches transfer pattern.

    Args:
        txn: Bank statement transaction to check

    Returns:
        True if transaction description contains transfer keywords
    """
    if not txn.description:
        return False

    description_lower = txn.description.lower()
    return any(kw in description_lower for kw in TRANSFER_KEYWORDS)


def _score_amount_match(amount1: Decimal, amount2: Decimal) -> float:
    """Score amount similarity (0-100).

    Args:
        amount1: First amount
        amount2: Second amount

    Returns:
        Score from 0-100 based on amount difference
    """
    diff = abs(amount1 - amount2)

    # Exact match (within 1 cent)
    if diff <= Decimal("0.01"):
        return 100.0

    # Very close match (within 10 cents)
    if diff <= Decimal("0.10"):
        return 95.0

    # Close match (within 1 SGD)
    if diff <= Decimal("1.00"):
        return 85.0

    # Moderate match (within 5 SGD)
    if diff <= Decimal("5.00"):
        return 70.0

    # Calculate proportional score for larger differences
    if amount1 == Decimal("0"):
        return 0.0

    ratio = max(Decimal("0"), Decimal("100") - (diff / amount1) * Decimal("100"))
    return float(round(ratio, 2))


def _score_description_match(desc1: str | None, desc2: str | None) -> float:
    """Score description similarity (0-100).

    Args:
        desc1: First description
        desc2: Second description

    Returns:
        Score from 0-100 based on text similarity
    """
    if not desc1 or not desc2:
        return 0.0

    # Normalize: lowercase and strip whitespace
    norm1 = desc1.lower().strip()
    norm2 = desc2.lower().strip()

    if not norm1 or not norm2:
        return 0.0

    # Use SequenceMatcher for fuzzy matching
    ratio = SequenceMatcher(None, norm1, norm2).ratio()

    # Token overlap score
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())
    token_overlap = len(tokens1 & tokens2) / len(tokens1 | tokens2) if tokens1 | tokens2 else 0

    # Combined score (60% sequence ratio, 40% token overlap)
    return round(100 * (0.6 * ratio + 0.4 * token_overlap), 2)


def _score_date_proximity(date1: date, date2: date) -> float:
    """Score date proximity (0-100).

    Args:
        date1: First date
        date2: Second date

    Returns:
        Score from 0-100 based on date difference
    """
    diff_days = abs((date1 - date2).days)

    # Same day
    if diff_days == 0:
        return 100.0

    # Within 1 day
    if diff_days == 1:
        return 95.0

    # Within 3 days
    if diff_days <= 3:
        return 85.0

    # Within acceptable window (7 days)
    if diff_days <= MAX_DATE_DIFF_DAYS:
        return 70.0

    # Beyond acceptable window - rapidly decreasing score
    return float(max(0, 100 - diff_days * 10))


def _calculate_pair_confidence(
    out_entry: JournalEntry,
    in_entry: JournalEntry,
) -> tuple[int, dict[str, float]]:
    """Calculate confidence score for transfer pair matching.

    Args:
        out_entry: Transfer OUT journal entry
        in_entry: Transfer IN journal entry

    Returns:
        Tuple of (total_score, breakdown_dict)
    """
    # Extract amounts from journal entries
    out_amount = sum(line.amount for line in out_entry.lines if line.direction == Direction.DEBIT)
    in_amount = sum(line.amount for line in in_entry.lines if line.direction == Direction.DEBIT)

    # Score individual components
    amount_score = _score_amount_match(out_amount, in_amount)
    description_score = _score_description_match(out_entry.memo, in_entry.memo)
    date_score = _score_date_proximity(out_entry.entry_date, in_entry.entry_date)

    # History score: 0 for now (can be enhanced with ML)
    history_score = 0.0

    # Calculate weighted total
    total = (
        Decimal(str(amount_score)) * AMOUNT_WEIGHT
        + Decimal(str(description_score)) * DESCRIPTION_WEIGHT
        + Decimal(str(date_score)) * DATE_WEIGHT
        + Decimal(str(history_score)) * HISTORY_WEIGHT
    )

    breakdown = {
        "amount": amount_score,
        "description": description_score,
        "date": date_score,
        "history": history_score,
    }

    return int(round(total, 0)), breakdown


async def find_transfer_pairs(
    db: AsyncSession,
    user_id: UUID,
    threshold: int = AUTO_PAIR_THRESHOLD,
) -> list[TransferPair]:
    """Find matching transfer pairs based on confidence scoring.

    This function searches for unpaired transfer entries in the Processing account
    and attempts to match them based on amount, description, and date proximity.

    Args:
        db: Database session
        user_id: User ID to search transfers for
        threshold: Minimum confidence score (default: 85)

    Returns:
        List of TransferPair objects with confidence >= threshold
    """
    # Get Processing account
    processing_account = await get_or_create_processing_account(db, user_id)

    # Find all journal entries involving Processing account
    result = await db.execute(
        select(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .join(JournalLine, JournalEntry.id == JournalLine.journal_entry_id)

        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(JournalEntry.source_type == JournalEntrySourceType.SYSTEM)
        .where(JournalLine.account_id == processing_account.id)
    )
    entries = result.scalars().unique().all()

    # Separate OUT and IN entries
    out_entries = []
    in_entries = []

    for entry in entries:
        for line in entry.lines:
            if line.account_id == processing_account.id:
                # Transfer OUT: Processing is DEBITED
                if line.direction == Direction.DEBIT:
                    out_entries.append(entry)
                # Transfer IN: Processing is CREDITED
                elif line.direction == Direction.CREDIT:
                    in_entries.append(entry)
                break

    # Find pairs with confidence >= threshold
    pairs: list[TransferPair] = []

    for out_entry in out_entries:
        best_match: TransferPair | None = None

        for in_entry in in_entries:
            confidence, breakdown = _calculate_pair_confidence(out_entry, in_entry)

            if confidence >= threshold:
                pair = TransferPair(
                    out_entry=out_entry,
                    in_entry=in_entry,
                    confidence=confidence,
                    score_breakdown=breakdown,
                )

                # Keep only the best match for this out_entry
                if best_match is None or confidence > best_match.confidence:
                    best_match = pair

        if best_match:
            pairs.append(best_match)

    return pairs


async def create_transfer_out_entry(
    db: AsyncSession,
    user_id: UUID,
    source_account_id: UUID,
    amount: Decimal,
    txn_date: date,
    description: str,
) -> JournalEntry:
    """Create a Transfer OUT journal entry.

    Transfer OUT: DEBIT Processing, CREDIT source account

    Args:
        db: Database session
        user_id: User ID
        source_account_id: Account ID where funds are leaving
        amount: Transfer amount
        txn_date: Transaction date
        description: Transfer description

    Returns:
        Created JournalEntry (not yet committed)
    """
    processing_account = await get_or_create_processing_account(db, user_id)

    entry = JournalEntry(
        user_id=user_id,
        entry_date=txn_date,
        memo=f"Transfer OUT: {description}",
        status=JournalEntryStatus.POSTED,
        source_type=JournalEntrySourceType.SYSTEM,
    )

    lines = [
        JournalLine(
            journal_entry=entry,
            account_id=processing_account.id,
            direction=Direction.DEBIT,
            amount=amount,
        ),
        JournalLine(
            journal_entry=entry,
            account_id=source_account_id,
            direction=Direction.CREDIT,
            amount=amount,
        ),
    ]

    db.add(entry)
    for line in lines:
        db.add(line)

    await db.flush()
    return entry


async def create_transfer_in_entry(
    db: AsyncSession,
    user_id: UUID,
    dest_account_id: UUID,
    amount: Decimal,
    txn_date: date,
    description: str,
) -> JournalEntry:
    """Create a Transfer IN journal entry.

    Transfer IN: DEBIT destination account, CREDIT Processing

    Args:
        db: Database session
        user_id: User ID
        dest_account_id: Account ID where funds are arriving
        amount: Transfer amount
        txn_date: Transaction date
        description: Transfer description

    Returns:
        Created JournalEntry (not yet committed)
    """
    processing_account = await get_or_create_processing_account(db, user_id)

    entry = JournalEntry(
        user_id=user_id,
        entry_date=txn_date,
        memo=f"Transfer IN: {description}",
        status=JournalEntryStatus.POSTED,
        source_type=JournalEntrySourceType.SYSTEM,
    )

    lines = [
        JournalLine(
            journal_entry=entry,
            account_id=dest_account_id,
            direction=Direction.DEBIT,
            amount=amount,
        ),
        JournalLine(
            journal_entry=entry,
            account_id=processing_account.id,
            direction=Direction.CREDIT,
            amount=amount,
        ),
    ]

    db.add(entry)
    for line in lines:
        db.add(line)

    await db.flush()
    return entry


async def get_processing_balance(db: AsyncSession, user_id: UUID) -> Decimal:
    """Get current balance of Processing account.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        Processing account balance (Decimal)
    """
    processing_account = await get_or_create_processing_account(db, user_id)

    # Get all journal lines for Processing account
    result = await db.execute(
        select(JournalLine)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == processing_account.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )
    lines = result.scalars().all()

    # Calculate balance (Asset account: debit - credit)
    balance = sum(line.amount if line.direction == Direction.DEBIT else -line.amount for line in lines)

    return balance


async def get_unpaired_transfers(
    db: AsyncSession,
    user_id: UUID,
    days_threshold: int = MAX_DATE_DIFF_DAYS,
) -> list[dict]:
    """Get unpaired transfer entries (Processing balance != 0).
    
    Returns ALL entries involving Processing account to show user what's unpaired.
    The days_threshold is for alerting purposes only, not filtering.
    
    Args:
        db: Database session
        user_id: User ID
        days_threshold: Alert threshold (unused in current implementation)
    Returns:
        List of dicts with keys: entry_id, direction, amount, date, description
    """
    processing_account = await get_or_create_processing_account(db, user_id)
    # Get all journal lines for Processing account
    result = await db.execute(
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == processing_account.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(JournalEntry.source_type == JournalEntrySourceType.SYSTEM)
        .order_by(JournalEntry.entry_date.desc())
    )
    rows = result.all()
    
    # Build list of unpaired transfers
    unpaired = []
    for line, entry in rows:
        unpaired.append({
            "entry_id": entry.id,
            "direction": "OUT" if line.direction == Direction.DEBIT else "IN",
            "amount": line.amount,
            "date": entry.entry_date,
            "description": entry.memo or "",
        })
    
    return unpaired
