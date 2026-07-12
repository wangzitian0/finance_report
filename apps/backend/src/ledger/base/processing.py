"""``processing`` — the in-transit (Processing) account's pure core (base layer).

The Processing virtual account (code ``"1199"``) is part of the ledger bounded
context: a system-managed ASSET account that holds funds *in transit* between a
user's own accounts (Bank A debits on day 1, Bank B credits on day 3 — the money
is "in" Processing on day 2 so the accounting equation holds throughout). See
``common/ledger/readme.md`` (the Processing Virtual Account SSOT).

This module is the **pure** half (no I/O): the :class:`ProcessingAccount` identity
value object (its fixed code/name/type), the :class:`TransferPair` value object, and
the transfer detection + confidence-scoring policy (keyword match, amount/description/
date scoring, the weighted pair confidence). The impure verbs that read/write the
database (acquire the account, post transfer entries, project the balance, find
pairs over persisted entries) live in ``extension/processing.py``.

The crown invariant the value object encodes: a Transfer OUT *debits* Processing /
credits the source; a Transfer IN *debits* the destination / credits Processing —
so a fully-paired transfer nets Processing to zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from uuid import UUID

from src.ledger.orm.account import AccountType
from src.ledger.orm.journal import Direction, JournalEntry

# The fixed identity of the Processing virtual account (SSOT P3 in
# common/ledger/readme.md). A per-user instance is a regular ``Account`` row that
# carries exactly these system-managed attributes — no separate ORM table.
PROCESSING_ACCOUNT_CODE = "1199"
PROCESSING_ACCOUNT_NAME = "Processing"
PROCESSING_ACCOUNT_TYPE = AccountType.ASSET
PROCESSING_ACCOUNT_DESCRIPTION = "System-managed virtual account for tracking in-transit transfers"

# Transfer detection keywords from SSOT SOP-001.
TRANSFER_KEYWORDS = [
    "transfer",
    "payment to",
    "fund transfer",
    "withdrawal",
    "paynow",
    "fast",
    "giro",
]

# Confidence thresholds from reconciliation.md.
AUTO_PAIR_THRESHOLD = 85
PENDING_REVIEW_THRESHOLD = 60

# Scoring weights from reconciliation.md.
AMOUNT_WEIGHT = Decimal("0.40")
DESCRIPTION_WEIGHT = Decimal("0.30")
DATE_WEIGHT = Decimal("0.20")
HISTORY_WEIGHT = Decimal("0.10")

# Date tolerance for transfer pairing (from common/ledger/readme.md).
MAX_DATE_DIFF_DAYS = 7


@dataclass(frozen=True)
class ProcessingAccount:
    """The Processing virtual account's fixed identity (a value object).

    The package's aggregate noun for the in-transit clearing account: it pins the
    system-managed attributes every per-user Processing ``Account`` row must carry
    (code ``"1199"``, name ``"Processing"``, type ASSET, ``is_system``). The live
    per-user ORM row is acquired by ``get_or_create_processing_account`` in the
    extension layer; this type is the pure description of *what* that row is.
    """

    code: str = PROCESSING_ACCOUNT_CODE
    name: str = PROCESSING_ACCOUNT_NAME
    type: AccountType = PROCESSING_ACCOUNT_TYPE
    description: str = PROCESSING_ACCOUNT_DESCRIPTION
    is_system: bool = True


@dataclass
class TransferPair:
    """Represents a matched pair of transfer transactions."""

    out_entry: JournalEntry
    in_entry: JournalEntry
    confidence: int
    score_breakdown: dict[str, float]


def _validate_transfer_params(amount: Decimal, description: str) -> None:
    """Validate shared inputs for Transfer IN/OUT journal entries."""
    if amount <= Decimal("0"):
        raise ValueError("Transfer amount must be positive")
    if not description or not description.strip():
        raise ValueError("Transfer description must not be empty")


def detect_transfer_pattern(description: str | None) -> bool:
    """Detect if a transaction description matches a transfer pattern.

    Args:
        description: Transaction description to check.

    Returns:
        True if the description contains a transfer keyword.
    """
    if not description:
        return False

    description_lower = description.lower()
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
    processing_account_id: UUID | None = None,
) -> tuple[int, dict[str, float]]:
    """Calculate confidence score for transfer pair matching.
    Args:
        out_entry: Transfer OUT journal entry
        in_entry: Transfer IN journal entry
        processing_account_id: Processing account ID for precise amount extraction.
            If None, falls back to finding the first DEBIT line (legacy behavior).
    Returns:
        Tuple of (total_score, breakdown_dict)
    """
    # Extract amounts from the Processing account line in each entry.
    # Use explicit processing_account_id when available for precision;
    # fallback to first DEBIT line for backward compatibility.
    if processing_account_id is None:
        for line in out_entry.lines:
            if line.direction == Direction.DEBIT:
                processing_account_id = line.account_id
                break
    out_amount = Decimal("0")
    in_amount = Decimal("0")
    for line in out_entry.lines:
        if line.account_id == processing_account_id and line.direction == Direction.DEBIT:
            out_amount = line.amount
            break
    for line in in_entry.lines:
        if line.account_id == processing_account_id and line.direction == Direction.CREDIT:
            in_amount = line.amount
            break

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
