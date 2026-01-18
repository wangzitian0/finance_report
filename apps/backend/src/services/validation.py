"""Validation helpers for statement extraction."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from src.models.statement import BankStatementStatus

BALANCE_TOLERANCE = Decimal("0.10")


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


def validate_balance_explicit(
    opening: Decimal, closing: Decimal, net_transactions: Decimal
) -> dict[str, Any]:
    """Validate balance using explicit Decimal values."""
    expected_closing = opening + net_transactions
    diff = abs(closing - expected_closing)
    balance_valid = diff <= BALANCE_TOLERANCE

    return {
        "balance_valid": balance_valid,
        "expected_closing": str(expected_closing),
        "actual_closing": str(closing),
        "difference": f"{diff:.2f}",
        "notes": None
        if balance_valid
        else f"Balance mismatch: expected {expected_closing}, got {closing}",
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
) -> int:
    """Compute confidence score (0-100) based on SSOT weights.

    Legacy interface for backward compatibility.
    """
    missing_fields = validate_completeness(extracted)
    score = 0

    # Balance validation (40%)
    if balance_result["balance_valid"]:
        score += 40
    else:
        try:
            diff = Decimal(balance_result.get("difference", "0"))
            if diff <= Decimal("1.00"):
                score += 30
            elif diff <= Decimal("10.00"):
                score += 20
        except (ValueError, TypeError):
            pass

    # Field completeness (30%)
    required_fields = 5
    present = required_fields - len(missing_fields)
    score += int((present / required_fields) * 30)

    # Format consistency (20%)
    format_score = 20
    try:
        if extracted.get("period_start"):
            date.fromisoformat(str(extracted["period_start"]))
        if extracted.get("period_end"):
            date.fromisoformat(str(extracted["period_end"]))
        Decimal(str(extracted.get("opening_balance", "0")))
        Decimal(str(extracted.get("closing_balance", "0")))
    except (ValueError, TypeError, InvalidOperation):
        format_score = 0
    score += format_score

    # Transaction count (10%)
    txn_count = len(extracted.get("transactions", []))
    if 1 <= txn_count <= 500:
        score += 10
    elif txn_count > 500:
        score += 5

    return min(100, score)


def route_by_threshold(score: int, balance_valid: bool) -> BankStatementStatus:
    """Route statement by confidence threshold and validation result."""
    if not balance_valid:
        return BankStatementStatus.UPLOADED
    if score >= 85:
        return BankStatementStatus.PARSED
    if score >= 60:
        return BankStatementStatus.PARSED
    return BankStatementStatus.UPLOADED