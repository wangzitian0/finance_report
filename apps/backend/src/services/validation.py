"""Validation helpers for statement extraction."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from src.models.statement_enums import BankStatementStatus

BALANCE_TOLERANCE = Decimal("0.10")
IN_DIRECTION_ALIASES = {"IN", "CREDIT", "CR", "DEPOSIT", "INFLOW"}
OUT_DIRECTION_ALIASES = {"OUT", "DEBIT", "DR", "WITHDRAWAL", "WITHDRAW", "OUTFLOW", "PAYMENT"}

# Under-extraction guard (issue #967). A brokerage statement that yields at most
# one transaction is a strong under-capture signal — comparable brokerage
# statements extract ~10 rows — so its confidence must not present as high.
BROKERAGE_MIN_PLAUSIBLE_TXNS = 2
UNDER_EXTRACTION_SCORE_CAP = 60


def normalize_amount_direction(amount: Decimal, direction_value: Any = None) -> tuple[Decimal, str]:
    """Return absolute amount plus canonical IN/OUT direction."""
    direction = str(direction_value or "").strip().upper()
    if direction in IN_DIRECTION_ALIASES:
        canonical_direction = "IN"
    elif direction in OUT_DIRECTION_ALIASES:
        canonical_direction = "OUT"
    else:
        canonical_direction = "OUT" if amount < 0 else "IN"
    return abs(amount), canonical_direction


def validate_balance(extracted: dict[str, Any]) -> dict[str, Any]:
    """Validate that opening + transactions ~= closing within tolerance.

    Dict-based entry point used by extraction; ``validate_balance_explicit``
    is the Decimal-based variant.
    """
    try:
        opening = Decimal(str(extracted.get("opening_balance") or "0"))
        closing = Decimal(str(extracted.get("closing_balance") or "0"))

        net = Decimal("0")
        for txn in extracted.get("transactions", []):
            amount = Decimal(str(txn["amount"]))
            amount, direction = normalize_amount_direction(amount, txn.get("direction"))
            if direction == "IN":
                net += amount
            else:
                net -= amount

        return validate_balance_explicit(opening, closing, net)
    except (ValueError, KeyError, InvalidOperation) as exc:
        # ``balance_computable=False`` flags that the difference could not be
        # derived (structurally-broken payload), so callers can branch on an
        # explicit flag instead of parsing the human-readable ``notes`` string.
        return {
            "balance_valid": False,
            "balance_computable": False,
            "expected_closing": "0",
            "actual_closing": "0",
            "difference": "0",
            "notes": f"Validation error: {exc}",
        }


def _currency_buckets(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve the per-currency opening/closing buckets for a statement.

    #1123 AC1. Prefers an explicit ``balances`` array
    (``[{currency, opening, closing}, ...]``). When absent — today's
    single-currency payloads — it falls back to the scalar
    ``opening_balance`` / ``closing_balance`` under the header ``currency`` (or a
    synthetic ``"*"`` bucket when no currency is stated), so the per-currency
    path degenerates to the existing scalar check without a cross-currency sum.
    """
    raw_balances = extracted.get("balances")
    if raw_balances:
        buckets: list[dict[str, Any]] = []
        for entry in raw_balances:
            currency = (entry.get("currency") or "*").strip().upper() or "*"
            buckets.append(
                {
                    "currency": currency,
                    "opening": Decimal(str(entry.get("opening") or "0")),
                    "closing": Decimal(str(entry.get("closing") or "0")),
                }
            )
        return buckets

    header_currency = (extracted.get("currency") or "*").strip().upper() or "*"
    return [
        {
            "currency": header_currency,
            "opening": Decimal(str(extracted.get("opening_balance") or "0")),
            "closing": Decimal(str(extracted.get("closing_balance") or "0")),
        }
    ]


def validate_balance_per_currency(extracted: dict[str, Any]) -> dict[str, Any]:
    """Validate ``open + ΣIN − ΣOUT ≈ close`` independently for each currency.

    #1123 AC1. Transactions are grouped by their own ``currency`` and each
    currency's running balance is checked against that currency's opening/closing
    pair. Currencies are NEVER summed together — a multi-currency statement is a
    set of independent single-currency closed loops. The legacy scalar check
    (:func:`validate_balance`) is the degenerate one-currency case of this rule.

    Returns a dict with an overall ``balance_valid`` (AND across currencies) plus
    a ``per_currency`` list, one :func:`validate_balance_explicit`-shaped result
    per currency tagged with its ``currency`` code. No cross-currency aggregate
    ``expected_closing`` is produced.
    """
    try:
        buckets = _currency_buckets(extracted)

        # Net IN/OUT per currency. A transaction without an explicit currency
        # falls back to the single bucket when there is exactly one (the
        # degenerate case); with multiple buckets an untagged txn lands in "*".
        single_bucket_ccy = buckets[0]["currency"] if len(buckets) == 1 else None
        nets: dict[str, Decimal] = {b["currency"]: Decimal("0") for b in buckets}
        for txn in extracted.get("transactions", []):
            amount = Decimal(str(txn["amount"]))
            amount, direction = normalize_amount_direction(amount, txn.get("direction"))
            ccy = (txn.get("currency") or single_bucket_ccy or "*").strip().upper() or "*"
            nets.setdefault(ccy, Decimal("0"))
            nets[ccy] += amount if direction == "IN" else -amount
    except (ValueError, KeyError, InvalidOperation) as exc:
        return {
            "balance_valid": False,
            "balance_computable": False,
            "per_currency": [],
            "notes": f"Validation error: {exc}",
        }

    per_currency: list[dict[str, Any]] = []
    for bucket in buckets:
        ccy = bucket["currency"]
        result = validate_balance_explicit(bucket["opening"], bucket["closing"], nets.get(ccy, Decimal("0")))
        result["currency"] = ccy
        per_currency.append(result)

    return {
        "balance_valid": all(r["balance_valid"] for r in per_currency),
        "balance_computable": True,
        "per_currency": per_currency,
    }


def validate_balance_explicit(opening: Decimal, closing: Decimal, net_transactions: Decimal) -> dict[str, Any]:
    """Validate balance using explicit Decimal values."""
    expected_closing = (opening or Decimal("0")) + (net_transactions or Decimal("0"))
    diff = abs((closing or Decimal("0")) - expected_closing)
    balance_valid = diff <= BALANCE_TOLERANCE

    return {
        "balance_valid": balance_valid,
        "balance_computable": True,
        "expected_closing": str(expected_closing),
        "actual_closing": str(closing),
        "difference": f"{diff:.2f}",
        "notes": None if balance_valid else f"Balance mismatch: expected {expected_closing}, got {closing}",
    }


def validate_completeness(extracted: dict[str, Any]) -> list[str]:
    """Return missing required fields for a statement."""
    required_fields = [
        "institution",
        "period_start",
        "period_end",
        "opening_balance",
        "closing_balance",
    ]
    return [field for field in required_fields if not extracted.get(field)]


def compute_confidence_score(
    extracted: dict[str, Any],
    balance_result: dict[str, Any],
    missing_fields: list[str] | None = None,
    *,
    is_brokerage: bool = False,
    effective_txn_count: int | None = None,
) -> int:
    """Compute confidence score (0-100) based on SSOT V2 weights.

    Weights: Balance 35% | Completeness 25% | Format 15% | Txn Count 10%
           | Balance Progression 10% | Currency Consistency 5%

    The Balance Progression component (10%) is only awarded when transactions
    carry a per-line running ``balance_after`` chain. Statements without that
    chain therefore top out near 90 even when otherwise clean — this is the
    documented ceiling, not a bug (issue #967).

    When ``is_brokerage`` is set and the parse yields an implausibly low
    transaction count (``< BROKERAGE_MIN_PLAUSIBLE_TXNS``), the score is capped
    at ``UNDER_EXTRACTION_SCORE_CAP`` so under-capture does not present as high
    confidence. The under-extraction check uses ``effective_txn_count`` when
    provided — the count of *persisted* transactions after skipped/invalid rows
    — falling back to the raw extracted-payload count otherwise.
    """
    if missing_fields is None:
        missing_fields = validate_completeness(extracted)

    score = 0
    transactions = extracted.get("transactions", []) or []

    # Balance validation (35%)
    if balance_result.get("balance_proof_available", True):
        if balance_result["balance_valid"]:
            score += 35
        else:
            try:
                diff = Decimal(str(balance_result.get("difference", "0") or "0"))
                if diff <= Decimal("1.00"):
                    score += 25
                elif diff <= Decimal("10.00"):
                    score += 17
            except (ValueError, TypeError, InvalidOperation):
                pass

    # Field completeness (25%)
    required_fields_count = 5
    present = required_fields_count - len(missing_fields)
    score += int((present / required_fields_count) * 25)

    # Format consistency (15%)
    format_score = 15
    try:
        if extracted.get("period_start"):
            date.fromisoformat(str(extracted["period_start"]))
        if extracted.get("period_end"):
            date.fromisoformat(str(extracted["period_end"]))
        Decimal(str(extracted.get("opening_balance", "0") or "0"))
        Decimal(str(extracted.get("closing_balance", "0") or "0"))
    except (ValueError, TypeError, InvalidOperation):
        format_score = 0
    score += format_score

    # Transaction count (10%)
    txn_count = len(transactions)
    if 1 <= txn_count <= 500:
        score += 10
    elif txn_count > 500:
        score += 5

    # Balance progression (10%)
    score += _score_balance_progression(transactions)

    # Currency consistency (5%)
    header_currency = extracted.get("currency")
    score += _score_currency_consistency(transactions, header_currency)

    score = min(100, score)

    # Under-extraction penalty (issue #967): a brokerage statement with an
    # implausibly low transaction count is likely an under-capture, so cap the
    # score below the auto-approve band regardless of how clean the captured
    # rows look. Prefer the persisted count (after skipped/invalid rows) so a
    # payload that extracts 2 rows but persists only 1 still trips the cap.
    txn_count = effective_txn_count if effective_txn_count is not None else len(transactions)
    if is_brokerage and txn_count < BROKERAGE_MIN_PLAUSIBLE_TXNS:
        score = min(score, UNDER_EXTRACTION_SCORE_CAP)

    return score


def _score_balance_progression(transactions: list[dict[str, Any]]) -> int:
    """Score 0-10 based on balance_after chain consistency.

    Checks: balance_after[n] == balance_after[n-1] +/- amount[n] within tolerance.
    """
    balances = []
    for txn in transactions:
        bal = txn.get("balance_after")
        amt = txn.get("amount")
        direction = str(txn.get("direction", "IN")).upper()
        if bal is not None and amt is not None:
            try:
                amount = Decimal(str(amt))
                amount, direction = normalize_amount_direction(amount, direction)
                balances.append((Decimal(str(bal)), amount, direction))
            except (ValueError, TypeError, InvalidOperation):
                continue

    if len(balances) < 2:
        return 0

    consistent = 0
    total = len(balances) - 1
    tolerance = Decimal("0.10")
    for i in range(1, len(balances)):
        prev_bal = balances[i - 1][0]
        cur_bal, cur_amt, cur_dir = balances[i]
        if cur_dir == "IN":
            expected = prev_bal + cur_amt
        else:
            expected = prev_bal - cur_amt
        if abs(cur_bal - expected) <= tolerance:
            consistent += 1

    if total == 0:
        return 0
    ratio = consistent / total
    return int(ratio * 10)


def _score_currency_consistency(transactions: list[dict[str, Any]], header_currency: str | None) -> int:
    """Score 0-5 based on per-transaction currency matching header currency."""
    if not transactions:
        return 0

    all_currencies = [txn.get("currency") for txn in transactions]
    non_empty_currencies = [c for c in all_currencies if c]

    if not non_empty_currencies:
        return 0

    if not header_currency:
        from collections import Counter

        most_common = Counter(non_empty_currencies).most_common(1)[0][0]
        header_currency = most_common

    matching = sum(1 for c in all_currencies if c == header_currency)
    ratio = matching / len(transactions)
    return int(ratio * 5)


def route_by_threshold(score: int, balance_valid: bool) -> BankStatementStatus:
    """Route statement by confidence threshold and validation result."""
    if not balance_valid:
        return BankStatementStatus.UPLOADED
    if score >= 85:
        return BankStatementStatus.APPROVED
    if score >= 60:
        return BankStatementStatus.PARSED
    return BankStatementStatus.UPLOADED
