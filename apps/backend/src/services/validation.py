"""Validation helpers for statement extraction."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from src.models.statement import BankStatementStatus

BALANCE_TOLERANCE = Decimal("0.01")


def validate_balance(extracted: dict[str, Any]) -> dict[str, Any]:
    """Validate that opening + transactions ~= closing within tolerance.

    Legacy interface for backward compatibility.
    """
    try:
        opening = Decimal(str(extracted.get("opening_balance") or "0"))
        closing = Decimal(str(extracted.get("closing_balance") or "0"))

        net = Decimal("0")
        for txn in extracted.get("transactions", []):
            amount = Decimal(str(txn["amount"]))
            if txn.get("direction") == "IN":
                net += amount
            else:
                net -= amount

        return validate_balance_explicit(opening, closing, net)
    except (ValueError, KeyError, InvalidOperation) as exc:
        return {
            "balance_valid": False,
            "expected_closing": "0",
            "actual_closing": "0",
            "difference": "0",
            "notes": f"Validation error: {exc}",
        }


def validate_balance_explicit(opening: Decimal, closing: Decimal, net_transactions: Decimal) -> dict[str, Any]:
    """Validate balance using explicit Decimal values."""
    expected_closing = (opening or Decimal("0")) + (net_transactions or Decimal("0"))
    diff = abs((closing or Decimal("0")) - expected_closing)
    balance_valid = diff <= BALANCE_TOLERANCE

    return {
        "balance_valid": balance_valid,
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
) -> int:
    """Compute confidence score (0-100) based on SSOT V2 weights.

    Weights: Balance 35% | Completeness 25% | Format 15% | Txn Count 10%
           | Balance Progression 10% | Currency Consistency 5%
    """
    if missing_fields is None:
        missing_fields = validate_completeness(extracted)

    score = 0
    transactions = extracted.get("transactions", []) or []

    # Balance validation (35%)
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

    return min(100, score)


def _score_balance_progression(transactions: list[dict[str, Any]]) -> int:
    """Score 0-10 based on balance_after chain consistency.

    Checks: balance_after[n] == balance_after[n-1] +/- amount[n] within tolerance.
    """
    balances = []
    for txn in transactions:
        bal = txn.get("balance_after")
        amt = txn.get("amount")
        direction = txn.get("direction", "IN")
        if bal is not None and amt is not None:
            try:
                balances.append((Decimal(str(bal)), Decimal(str(amt)), direction))
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

    currencies = [txn.get("currency") for txn in transactions if txn.get("currency")]
    if not currencies:
        return 0

    if not header_currency:
        from collections import Counter

        most_common = Counter(currencies).most_common(1)[0][0]
        header_currency = most_common

    matching = sum(1 for c in currencies if c == header_currency)
    ratio = matching / len(currencies)
    return int(ratio * 5)


def route_by_threshold(score: int, balance_valid: bool) -> BankStatementStatus:
    """Route statement by confidence threshold and validation result."""
    if not balance_valid:
        return BankStatementStatus.UPLOADED
    if score >= 85:
        return BankStatementStatus.PARSED
    if score >= 60:
        return BankStatementStatus.PARSED
    return BankStatementStatus.UPLOADED
